package com.campustransit.driver.services;

import android.app.*;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.location.*;
import android.net.*;
import android.os.*;
import androidx.annotation.NonNull;
import androidx.core.app.NotificationCompat;
import androidx.core.app.ServiceCompat;
import androidx.core.content.ContextCompat;
import com.campustransit.driver.BuildConfig;
import com.campustransit.driver.R;
import com.campustransit.driver.activities.ActiveTripActivity;
import com.campustransit.driver.api.*;
import com.campustransit.driver.models.Models.*;
import com.campustransit.driver.utils.*;
import org.json.JSONObject;
import retrofit2.*;

public final class TrackingService extends Service implements LocationListener {
    public static final String STOP = "com.campustransit.driver.STOP_SHARING";
    private static final String CHANNEL = "active_trip_location";
    private static final int NOTIFICATION = 401;
    private static volatile boolean running;
    private static volatile long runningTrip;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final LatestFixQueue queue = new LatestFixQueue();
    private DriverApi api;
    private TokenStore tokens;
    private TripState state;
    private LocationManager locations;
    private ConnectivityManager network;
    private Call<?> inFlight;
    private boolean listening, networkRegistered, destroyed;
    private int failures;
    private long lastFixElapsed, lastAttemptElapsed;
    private final Runnable uploader = this::upload;
    private final Runnable watchdog = new Runnable() {
        @Override public void run() {
            if (destroyed) return;
            if (tokens.token().isEmpty()) { tokens.clear(); shutdown("Session expired. Sign in again; sharing stopped."); return; }
            if (!Permissions.location(TrackingService.this) || !Permissions.notifications(TrackingService.this)) { shutdown("Location or notification permission was removed. Sharing stopped."); return; }
            if (!locations.isProviderEnabled(LocationManager.GPS_PROVIDER)) status("GPS is disabled. Turn on device location to continue.");
            else if (lastFixElapsed > 0 && SystemClock.elapsedRealtime() - lastFixElapsed > 60000) status("Waiting for a recent GPS fix. Move to an open area.");
            handler.postDelayed(this, 10000);
        }
    };
    private final ConnectivityManager.NetworkCallback networkCallback = new ConnectivityManager.NetworkCallback() {
        @Override public void onAvailable(@NonNull Network ignored) { handler.post(() -> { failures = 0; schedule(0); }); }
        @Override public void onLost(@NonNull Network ignored) { handler.post(() -> { if (!online()) status("No internet. Keeping only the newest GPS fix."); }); }
    };

    public static boolean isRunning(long tripId) { return running && runningTrip == tripId; }
    public static void begin(Context context, long tripId) {
        Intent intent = new Intent(context, TrackingService.class).putExtra("trip_id", tripId);
        ContextCompat.startForegroundService(context, intent);
    }
    public static void stop(Context context, String reason) {
        context.stopService(new Intent(context, TrackingService.class));
        new TripState(context).status(reason);
    }
    @Override public void onCreate() {
        super.onCreate();
        tokens = new TokenStore(this); state = new TripState(this); api = ApiClient.get(this);
        locations = (LocationManager) getSystemService(LOCATION_SERVICE);
        network = (ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
        getSystemService(NotificationManager.class).createNotificationChannel(new NotificationChannel(CHANNEL, getString(R.string.channel_name), NotificationManager.IMPORTANCE_LOW));
    }
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null || STOP.equals(intent.getAction())) { shutdown("Location sharing stopped. The server trip remains open until ended."); return START_NOT_STICKY; }
        long requested = intent.getLongExtra("trip_id", 0);
        if (requested <= 0 || tokens.token().isEmpty() || !Permissions.location(this) || !Permissions.notifications(this)) { shutdown("Sign in and grant precise location and notification permission before sharing."); return START_NOT_STICKY; }
        if (running && runningTrip == requested) return START_NOT_STICKY;
        if (running) { shutdown("Another trip was requested. Reopen the dashboard to resume safely."); return START_NOT_STICKY; }
        try {
            int type = Build.VERSION.SDK_INT >= 29 ? ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION : 0;
            ServiceCompat.startForeground(this, NOTIFICATION, notification("Checking your active trip…"), type);
        } catch (RuntimeException startDenied) { shutdown("Android could not start tracking. Open the app and try Resume sharing."); return START_NOT_STICKY; }
        running = true; runningTrip = requested; state.trip(requested);
        state.status("Checking your active trip before accessing GPS…");
        api.assignment().enqueue(new Callback<Assignment>() {
            @Override public void onResponse(Call<Assignment> call, Response<Assignment> response) {
                if (destroyed) return;
                Assignment assignment = response.body();
                if (response.code() == 401) { tokens.clear(); shutdown("Session expired. Sign in again."); return; }
                if (!response.isSuccessful() || assignment == null || assignment.active_trip == null || assignment.active_trip.id != requested || assignment.active_trip.is_simulated || !assignment.assigned()) {
                    shutdown("The active trip could not be verified. Reopen the dashboard before resuming."); return;
                }
                startGPS();
            }
            @Override public void onFailure(Call<Assignment> call, Throwable error) { if (!destroyed) shutdown("Cannot verify your trip. Check the connection and tap Resume sharing."); }
        });
        // Never silently resurrect location sharing after process death or reboot.
        return START_NOT_STICKY;
    }
    @SuppressWarnings("MissingPermission")
    private void startGPS() {
        if (destroyed || !Permissions.location(this)) { shutdown("Precise location permission is required."); return; }
        try {
            locations.requestLocationUpdates(LocationManager.GPS_PROVIDER, BuildConfig.GPS_INTERVAL_SECONDS * 1000L, 0, this, Looper.getMainLooper());
            listening = true;
            network.registerDefaultNetworkCallback(networkCallback); networkRegistered = true;
            lastFixElapsed = SystemClock.elapsedRealtime();
            status(locations.isProviderEnabled(LocationManager.GPS_PROVIDER) ? "Waiting for a GPS fix. No coordinates have been sent yet." : "GPS is disabled. Enable device location.");
            handler.postDelayed(watchdog, 10000);
        } catch (RuntimeException denied) { shutdown("GPS is unavailable or permission was removed. Sharing stopped."); }
    }
    @Override public void onLocationChanged(@NonNull Location location) {
        if (destroyed || !listening) return;
        if (!locations.isProviderEnabled(LocationManager.GPS_PROVIDER)) { queue.clear(); status("GPS is disabled. Waiting for device location."); return; }
        if (!Permissions.location(this) || !Permissions.notifications(this)) { shutdown("Permission was removed. Location sharing stopped."); return; }
        LocationPayload fix = LocationFix.extract(location, System.currentTimeMillis(), SystemClock.elapsedRealtimeNanos());
        if (fix == null) { status("Ignored an invalid, old or incomplete GPS fix. Check device location and clock."); return; }
        if (!queue.offer(fix)) return;
        lastFixElapsed = SystemClock.elapsedRealtime();
        if (inFlight == null && failures == 0) schedule(Math.max(0, BuildConfig.GPS_INTERVAL_SECONDS * 1000L - (SystemClock.elapsedRealtime() - lastAttemptElapsed)));
    }
    private boolean online() { return network.getActiveNetwork() != null; }
    private void schedule(long delay) { if (destroyed) return; handler.removeCallbacks(uploader); handler.postDelayed(uploader, delay); }
    private void upload() {
        if (destroyed || inFlight != null) return;
        if (!locations.isProviderEnabled(LocationManager.GPS_PROVIDER)) { queue.clear(); status("GPS is disabled. No pending fix will be transmitted."); return; }
        if (!Permissions.location(this) || !Permissions.notifications(this)) { shutdown("Permission was removed. Location sharing stopped."); return; }
        if (tokens.token().isEmpty()) { shutdown("Session expired. Sharing stopped."); return; }
        LocationPayload fix = queue.peek();
        if (fix == null) return;
        if (!FixPolicy.valid(fix, System.currentTimeMillis())) { queue.acknowledge(fix); status("Waiting for a fresh GPS sample; old pending sample discarded."); return; }
        if (!online()) { status("No internet. Keeping only the newest GPS fix."); return; }
        lastAttemptElapsed = SystemClock.elapsedRealtime();
        Call<LocationResponse> call = api.location(runningTrip, fix); inFlight = call;
        call.enqueue(new Callback<LocationResponse>() {
            @Override public void onResponse(Call<LocationResponse> call, Response<LocationResponse> response) {
                inFlight = null;
                if (destroyed) return;
                if (response.isSuccessful()) {
                    failures = 0; queue.acknowledge(fix); status("GPS sent at " + java.time.LocalTime.now().withNano(0) + " · accuracy " + Math.round(fix.accuracy) + " m");
                    if (queue.peek() != null) schedule(BuildConfig.GPS_INTERVAL_SECONDS * 1000L);
                } else if (response.code() == 401) { tokens.clear(); shutdown("Session expired. Sign in again; sharing stopped."); }
                else if (response.code() == 400 || isOlderSample(response)) {
                    failures = 0; queue.acknowledge(fix); status("GPS sample rejected as invalid or old. Waiting for the next fix.");
                    if (queue.peek() != null) schedule(BuildConfig.GPS_INTERVAL_SECONDS * 1000L);
                } else if (response.code() == 403 || response.code() == 404 || response.code() == 409 || response.code() == 410) {
                    shutdown("Trip or assignment is no longer authorized. Sharing stopped; refresh the dashboard.");
                } else retry();
            }
            @Override public void onFailure(Call<LocationResponse> call, Throwable error) { inFlight = null; if (!destroyed && queue.peek() != null) retry(); }
        });
    }
    private boolean isOlderSample(Response<?> response) {
        if (response.code() != 409 || response.errorBody() == null) return false;
        try { return "out_of_order".equals(new JSONObject(response.errorBody().string()).optString("code")); }
        catch (Exception ignored) { return false; }
    }
    private void retry() {
        failures++;
        if (failures >= RetryPolicy.MAX_ATTEMPTS) {
            status("Upload retries paused for 60 seconds. Only the newest GPS fix is retained.");
            handler.removeCallbacks(uploader);
            handler.postDelayed(() -> { failures = 0; schedule(0); }, 60000);
        } else { status("Connection problem. Retrying the latest GPS sample (" + failures + "/5). "); schedule(RetryPolicy.delayMillis(failures)); }
    }
    @Override public void onProviderDisabled(@NonNull String provider) {
        queue.clear(); if (inFlight != null) inFlight.cancel(); status("GPS disabled. Location sharing is waiting for device location.");
    }
    @Override public void onProviderEnabled(@NonNull String provider) { status("GPS enabled. Waiting for a new fix."); }
    @Override public void onStatusChanged(String provider, int status, Bundle extras) { }
    private Notification notification(String message) {
        PendingIntent open = PendingIntent.getActivity(this, 1, new Intent(this, ActiveTripActivity.class), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        PendingIntent stop = PendingIntent.getService(this, 2, new Intent(this, TrackingService.class).setAction(STOP), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new NotificationCompat.Builder(this, CHANNEL).setSmallIcon(R.drawable.ic_bus).setContentTitle(getString(R.string.tracking_title))
            .setContentText(message).setStyle(new NotificationCompat.BigTextStyle().bigText(message)).setContentIntent(open)
            .setOngoing(true).setOnlyAlertOnce(true).addAction(R.drawable.ic_bus, getString(R.string.stop_sharing), stop).build();
    }
    private void status(String message) {
        if (destroyed) return;
        state.status(message);
        if (running && Permissions.notifications(this)) {
            try { getSystemService(NotificationManager.class).notify(NOTIFICATION, notification(message)); } catch (SecurityException ignored) { }
        }
    }
    private void shutdown(String reason) { if (state != null) state.status(reason); stopSelf(); cleanup(); }
    private void cleanup() {
        if (destroyed) return;
        destroyed = true; running = false; runningTrip = 0;
        handler.removeCallbacksAndMessages(null); queue.clear();
        if (inFlight != null) inFlight.cancel();
        if (listening) locations.removeUpdates(this);
        if (networkRegistered) { try { network.unregisterNetworkCallback(networkCallback); } catch (RuntimeException ignored) { } }
        stopForeground(STOP_FOREGROUND_REMOVE);
    }
    @Override public void onDestroy() { cleanup(); super.onDestroy(); }
    @Override public IBinder onBind(Intent intent) { return null; }
}
