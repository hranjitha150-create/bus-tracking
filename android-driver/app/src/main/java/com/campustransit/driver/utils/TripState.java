package com.campustransit.driver.utils;
import android.content.Context;
import android.content.SharedPreferences;

/** No GPS points or passwords are persisted. A saved trip ID never auto-starts sharing. */
public final class TripState {
    private final SharedPreferences prefs;
    public TripState(Context context) { prefs = context.getSharedPreferences("trip_state", Context.MODE_PRIVATE); }
    public long tripId() { return prefs.getLong("trip_id", 0); }
    public void trip(long id) { prefs.edit().putLong("trip_id", id).apply(); }
    public String status() { return prefs.getString("status", "Location sharing is off."); }
    public void status(String status) { prefs.edit().putString("status", status).apply(); }
    public void clear() { prefs.edit().clear().apply(); }
}
