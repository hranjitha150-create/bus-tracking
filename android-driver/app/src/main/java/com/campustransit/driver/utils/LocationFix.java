package com.campustransit.driver.utils;
import android.location.Location;
import com.campustransit.driver.models.Models.LocationPayload;

/** Extract a real Android fix; separate clocks allow deterministic mock tests. */
public final class LocationFix {
    private LocationFix() {}
    public static LocationPayload extract(Location location, long now, long elapsedNanos) {
        if (location == null || !location.hasAccuracy()) return null;
        long elapsedAge = (elapsedNanos - location.getElapsedRealtimeNanos()) / 1000000L;
        LocationPayload fix = new LocationPayload(location.getLatitude(), location.getLongitude(),
            location.hasSpeed() ? Math.max(0, location.getSpeed()) : 0, location.getAccuracy(), location.getTime());
        return elapsedAge >= 0 && elapsedAge <= FixPolicy.MAX_AGE_MS && FixPolicy.valid(fix, now) ? fix : null;
    }
}
