package com.campustransit.driver;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import com.campustransit.driver.utils.TokenStore;
import com.campustransit.driver.services.TrackingService;
import com.campustransit.driver.utils.LocationFix;
import com.campustransit.driver.models.Models.LocationPayload;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Instrumented checks: these require an emulator/device and are not JVM tests. */
@RunWith(AndroidJUnit4.class)
public class DeviceSafetyTest {
    @Test public void tokenRoundTripsEncryptedAndClears() throws Exception {
        android.content.Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        TokenStore store = new TokenStore(context);
        store.save("test-only-secret", "2099-01-01T00:00:00Z");
        assertEquals("test-only-secret", store.token());
        String raw = context.getSharedPreferences("secure_session", 0).getString("ciphertext", "");
        assertFalse(raw.contains("test-only-secret")); store.clear(); assertEquals("", store.token());
    }
    @Test public void processDoesNotAutoStartSharing() { assertFalse(TrackingService.isRunning(0)); }
    @Test public void loginScreenShowsValidationWithoutRequestingGPS() {
        android.content.Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        new TokenStore(context).clear();
        try (androidx.test.core.app.ActivityScenario<com.campustransit.driver.activities.LoginActivity> scenario = androidx.test.core.app.ActivityScenario.launch(com.campustransit.driver.activities.LoginActivity.class)) {
            scenario.onActivity(activity -> {
                activity.findViewById(com.campustransit.driver.R.id.login).performClick();
                assertTrue(((android.widget.TextView) activity.findViewById(com.campustransit.driver.R.id.loginStatus)).getText().toString().contains("email and password"));
                assertFalse(TrackingService.isRunning(0));
            });
        }
    }
    @Test public void mockAndroidLocationExtractsFieldsAndRejectsOldFix() {
        long now = 1800000000000L, elapsed = 200000000000L;
        android.location.Location mock = new android.location.Location("gps");
        mock.setLatitude(12.123); mock.setLongitude(77.456); mock.setSpeed(4); mock.setAccuracy(5);
        mock.setTime(now); mock.setElapsedRealtimeNanos(elapsed);
        LocationPayload payload = LocationFix.extract(mock, now, elapsed);
        assertNotNull(payload); assertEquals(12.123, payload.latitude, .000001); assertEquals(4, payload.speed, .001);
        assertEquals(5, payload.accuracy, .001); assertEquals(now, payload.timestamp());
        assertNull(LocationFix.extract(mock, now + 180000, elapsed + 180000000000L));
        mock.removeAccuracy(); assertNull(LocationFix.extract(mock, now, elapsed));
    }
    @Test public void manifestKeepsServicePrivateAndAvoidsBackgroundLocation() throws Exception {
        android.content.Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        android.content.pm.PackageInfo info = context.getPackageManager().getPackageInfo(context.getPackageName(), android.content.pm.PackageManager.GET_PERMISSIONS | android.content.pm.PackageManager.GET_SERVICES);
        for (String permission : info.requestedPermissions) assertNotEquals("android.permission.ACCESS_BACKGROUND_LOCATION", permission);
        boolean found = false;
        for (android.content.pm.ServiceInfo service : info.services) if (service.name.endsWith("TrackingService")) { found = true; assertFalse(service.exported); }
        assertTrue(found);
    }
}
