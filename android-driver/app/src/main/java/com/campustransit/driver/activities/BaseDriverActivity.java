package com.campustransit.driver.activities;

import android.Manifest;
import android.content.Intent;
import android.location.LocationManager;
import android.net.Uri;
import android.os.*;
import android.provider.Settings;
import android.view.View;
import android.widget.*;
import androidx.annotation.NonNull;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import com.campustransit.driver.BuildConfig;
import com.campustransit.driver.R;
import com.campustransit.driver.api.*;
import com.campustransit.driver.models.Models.*;
import com.campustransit.driver.services.TrackingService;
import com.campustransit.driver.utils.*;
import java.util.Locale;
import retrofit2.*;

public abstract class BaseDriverActivity extends AppCompatActivity {
    protected abstract int layout();
    protected abstract String title();
    protected boolean routeScreen() { return false; }
    protected boolean tripControls() { return true; }
    protected Assignment assignment;
    private TokenStore tokens;
    private TripState state;
    private DriverApi api;
    private boolean visible, busy;
    private Call<Assignment> fetch;
    private final Handler timer = new Handler(Looper.getMainLooper());
    private final Runnable tick = new Runnable() { @Override public void run() { if (visible) { text(R.id.gpsStatus, gpsLabel()); buttons(); timer.postDelayed(this, 2000); } } };
    private String gpsLabel() { return TrackingService.isRunning(state.tripId()) ? state.status() : "Sharing is off. " + state.status(); }

    @Override protected void onCreate(Bundle saved) {
        super.onCreate(saved); setContentView(layout()); LoginActivity.applyInsets(this);
        tokens = new TokenStore(this); state = new TripState(this); api = ApiClient.get(this);
        text(R.id.screenTitle, title());
        text(R.id.intervalInfo, "Target GPS interval: " + BuildConfig.GPS_INTERVAL_SECONDS + " seconds. Android and satellite availability can delay updates.");
        findViewById(R.id.refresh).setOnClickListener(view -> refresh());
        findViewById(R.id.startTrip).setOnClickListener(view -> permissionThenTrip());
        findViewById(R.id.resumeSharing).setOnClickListener(view -> permissionThenTrip());
        findViewById(R.id.endTrip).setOnClickListener(view -> new AlertDialog.Builder(this).setTitle("End this college trip?")
            .setMessage("Location sharing will stop immediately. The trip is completed when the server confirms.").setNegativeButton("Cancel", null).setPositiveButton("End trip", (dialog, which) -> end()).show());
        findViewById(R.id.stopSharing).setOnClickListener(view -> { TrackingService.stop(this, "Sharing stopped by driver. Resume explicitly when ready."); buttons(); });
        findViewById(R.id.settings).setOnClickListener(view -> startActivity(new Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS)));
        findViewById(R.id.viewBus).setOnClickListener(view -> startActivity(new Intent(this, AssignedBusActivity.class)));
        findViewById(R.id.viewRoute).setOnClickListener(view -> startActivity(new Intent(this, RouteDetailsActivity.class)));
        findViewById(R.id.viewTrip).setOnClickListener(view -> startActivity(new Intent(this, ActiveTripActivity.class)));
        findViewById(R.id.dashboard).setOnClickListener(view -> { startActivity(new Intent(this, DashboardActivity.class).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP)); finish(); });
        findViewById(R.id.logout).setOnClickListener(view -> new AlertDialog.Builder(this).setTitle("Sign out?").setMessage("Sharing stops immediately. If a server trip is still active, end it first or resume it after signing in again.")
            .setNegativeButton("Cancel", null).setPositiveButton("Stop sharing and sign out", (dialog, which) -> logout()).show());
        findViewById(R.id.dashboard).setVisibility(this instanceof DashboardActivity ? View.GONE : View.VISIBLE);
        buttons();
    }
    @Override protected void onResume() { super.onResume(); visible = true; if (tokens.token().isEmpty()) { expired(); return; } refresh(); timer.post(tick); }
    @Override protected void onPause() { visible = false; timer.removeCallbacks(tick); if (fetch != null) fetch.cancel(); super.onPause(); }
    private void text(int id, String text) { ((TextView) findViewById(id)).setText(text == null ? "Not available" : text); }
    private void message(String text) { text(R.id.message, text); }
    private void busy(boolean value) { busy = value; findViewById(R.id.loading).setVisibility(value ? View.VISIBLE : View.GONE); buttons(); }
    private boolean active() { return assignment != null && assignment.active_trip != null; }
    private void buttons() {
        boolean assigned = assignment != null && assignment.assigned();
        boolean active = active();
        boolean running = TrackingService.isRunning(state.tripId());
        show(R.id.startTrip, tripControls() && assigned && !active);
        show(R.id.resumeSharing, tripControls() && active && !running && !assignment.active_trip.is_simulated);
        show(R.id.endTrip, tripControls() && active);
        show(R.id.stopSharing, tripControls() && running);
        for (int id : new int[]{R.id.startTrip, R.id.resumeSharing, R.id.endTrip, R.id.refresh}) findViewById(id).setEnabled(!busy);
        findViewById(R.id.busCard).setVisibility(assigned ? View.VISIBLE : View.GONE);
    }
    private void show(int id, boolean show) { findViewById(id).setVisibility(show ? View.VISIBLE : View.GONE); }
    protected void refresh() {
        if (!visible) return;
        if (fetch != null) fetch.cancel();
        busy(true); message("Checking your driver assignment…");
        fetch = api.assignment();
        fetch.enqueue(new Callback<Assignment>() {
            @Override public void onResponse(Call<Assignment> call, Response<Assignment> response) {
                if (!visible || call.isCanceled()) return;
                busy(false);
                if (response.code() == 401 || response.code() == 403) { expired(); return; }
                if (!response.isSuccessful() || response.body() == null) { assignment = null; buttons(); message("Cannot load assignment. Retry when the server is available."); return; }
                assignment = response.body();
                long previous = state.tripId(), current = active() ? assignment.active_trip.id : 0;
                if (previous != current && TrackingService.isRunning(previous)) TrackingService.stop(BaseDriverActivity.this, "Server trip changed or completed. Sharing stopped.");
                state.trip(current); display();
            }
            @Override public void onFailure(Call<Assignment> call, Throwable error) { if (visible && !call.isCanceled()) { assignment = null; busy(false); message("No connection to the college server. Check internet and retry. Existing foreground sharing, if running, reports its own status below."); } }
        });
    }
    private void display() {
        text(R.id.driverName, assignment.driver != null ? assignment.driver.full_name : "Driver account");
        message(assignment.assigned() ? "Your current college assignment is connected." : assignment.message);
        if (active() && assignment.active_trip.is_simulated) message("A development replay is active. Real GPS sharing is disabled; end the simulated trip before starting a real journey.");
        if (assignment.assigned()) {
            text(R.id.busNumber, assignment.bus.bus_number); text(R.id.registration, assignment.bus.registration_number);
            text(R.id.routeName, assignment.route.route_code + " · " + assignment.route.route_name);
            text(R.id.journey, "Start: " + assignment.route.start_location + "\nDestination: " + assignment.route.destination + "\nDirection: " + assignment.route.direction.replace('_', ' '));
            text(R.id.busDescription, "Capacity: " + assignment.bus.capacity + "\n" + (assignment.bus.description == null ? "" : assignment.bus.description));
        }
        Trip trip = assignment.active_trip != null ? assignment.active_trip : assignment.trip;
        text(R.id.tripStatus, trip == null ? "Not started" : trip.status + " · " + trip.trip_type + " · #" + trip.id);
        text(R.id.gpsStatus, gpsLabel());
        LinearLayout stops = findViewById(R.id.stopsContainer); stops.removeAllViews();
        if (routeScreen() && assignment.assigned()) {
            if (assignment.route.stops == null || assignment.route.stops.isEmpty()) {
                TextView empty = new TextView(this); empty.setText(R.string.no_route_stops); stops.addView(empty);
            } else for (int i = 0; i < assignment.route.stops.size(); i++) {
                Stop stop = assignment.route.stops.get(i);
                View row = getLayoutInflater().inflate(R.layout.item_stop, stops, false);
                ((TextView) row.findViewById(R.id.stopName)).setText(getString(R.string.stop_title, stop.order, stop.name, i == 0 ? " · Start" : i == assignment.route.stops.size() - 1 ? " · Destination" : ""));
                ((TextView) row.findViewById(R.id.stopCoordinates)).setText(String.format(Locale.US, "%.7f, %.7f", stop.latitude, stop.longitude)); stops.addView(row);
            }
        }
        buttons();
    }
    private void permissionThenTrip() {
        if (!Permissions.location(this)) { ActivityCompat.requestPermissions(this, new String[]{Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION}, 101); return; }
        if (!Permissions.notificationPermission(this)) { ActivityCompat.requestPermissions(this, new String[]{Manifest.permission.POST_NOTIFICATIONS}, 102); return; }
        if (!Permissions.notifications(this)) { message("Enable trip notifications and the active-trip channel before sharing location."); startActivity(new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName())); return; }
        LocationManager manager = (LocationManager) getSystemService(LOCATION_SERVICE);
        if (!manager.isProviderEnabled(LocationManager.GPS_PROVIDER)) { message("Turn on device location, then tap Start or Resume sharing again."); startActivity(new Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS)); return; }
        if (active()) { startSharing(assignment.active_trip.id); return; }
        if (assignment == null || !assignment.assigned()) { message("Refresh and confirm an active assignment first."); return; }
        busy(true); message("Starting your trip securely…");
        api.start().enqueue(new Callback<TripResponse>() {
            @Override public void onResponse(Call<TripResponse> call, Response<TripResponse> response) {
                if (isDestroyed()) return;
                busy(false);
                if (response.code() == 401 || response.code() == 403) { expired(); return; }
                if (!response.isSuccessful() || response.body() == null || response.body().trip == null) { message("Trip could not start. Refresh to check assignments and conflicts."); return; }
                state.trip(response.body().trip.id);
                if (visible) { startSharing(response.body().trip.id); refresh(); }
                else state.status("Trip started. Reopen the app and tap Resume sharing; GPS has not started.");
            }
            @Override public void onFailure(Call<TripResponse> call, Throwable error) { if (!isDestroyed()) { busy(false); message("Start request was not confirmed. Refresh before retrying; the server safely reuses an active trip."); } }
        });
    }
    private void startSharing(long id) {
        if (!visible) { state.status("Reopen the app and tap Resume sharing."); return; }
        try { TrackingService.begin(this, id); message("Starting visible foreground GPS sharing…"); }
        catch (RuntimeException denied) { state.status("Android blocked the service. Keep the app open and retry Resume sharing."); message(state.status()); }
    }
    private void end() {
        if (!active()) return;
        long id = assignment.active_trip.id;
        TrackingService.stop(this, "Sharing stopped while ending the trip."); busy(true);
        api.end(id).enqueue(new Callback<TripResponse>() {
            @Override public void onResponse(Call<TripResponse> call, Response<TripResponse> response) {
                if (isDestroyed()) return;
                busy(false);
                if (response.code() == 401 || response.code() == 403) { expired(); return; }
                if (response.isSuccessful()) { state.trip(0); state.status("Trip completed. Location sharing is off."); refresh(); }
                else message("Sharing is off, but the server did not confirm completion. Refresh and retry End trip.");
            }
            @Override public void onFailure(Call<TripResponse> call, Throwable error) { if (!isDestroyed()) { busy(false); message("Sharing is off. Completion was not confirmed; reconnect and retry End trip."); } }
        });
    }
    @Override public void onRequestPermissionsResult(int requestCode, @NonNull String[] permissions, @NonNull int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (requestCode != 101 && requestCode != 102) return;
        if ((requestCode == 101 && Permissions.location(this)) || (requestCode == 102 && Permissions.notifications(this))) permissionThenTrip();
        else new AlertDialog.Builder(this).setTitle("Permission needed for a visible trip")
            .setMessage("Precise location and notifications are required before sharing. No GPS transmission has started. You can enable permissions in app settings.")
            .setNegativeButton("Not now", null).setPositiveButton("App settings", (dialog, which) -> startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + getPackageName())))).show();
    }
    private void logout() {
        TrackingService.stop(this, "Signed out. Location sharing is off.");
        String token = tokens.token();
        if (!token.isEmpty()) ApiClient.create(BuildConfig.API_URL, () -> token).logout().enqueue(new Callback<Void>() {
            @Override public void onResponse(Call<Void> call, Response<Void> response) { }
            @Override public void onFailure(Call<Void> call, Throwable error) { }
        });
        tokens.clear(); state.clear(); openLogin();
    }
    private void expired() { TrackingService.stop(this, "Session ended. Location sharing stopped."); tokens.clear(); state.clear(); openLogin(); }
    private void openLogin() { startActivity(new Intent(this, LoginActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK)); finish(); }
}
