package com.campustransit.driver.utils;
import com.campustransit.driver.models.Models.LocationPayload;

public final class FixPolicy {
    public static final long MAX_AGE_MS = 120000;
    private FixPolicy() {}
    public static boolean valid(LocationPayload fix, long now) {
        return Double.isFinite(fix.latitude) && Math.abs(fix.latitude) <= 90
            && Double.isFinite(fix.longitude) && Math.abs(fix.longitude) <= 180
            && Double.isFinite(fix.speed) && fix.speed >= 0 && Double.isFinite(fix.accuracy) && fix.accuracy >= 0
            && fix.timestamp() >= now - MAX_AGE_MS && fix.timestamp() <= now + 30000;
    }
}
