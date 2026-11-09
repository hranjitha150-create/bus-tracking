package com.campustransit.driver.models;

import com.google.gson.annotations.SerializedName;
import java.time.Instant;
import java.util.List;

public final class Models {
    private Models() {}
    public static class User { public long id; public String full_name, email, role; }
    public static class LoginRequest {
        public final String email, password;
        public LoginRequest(String email, String password) { this.email = email; this.password = password; }
    }
    public static class LoginResponse { public String token, expires_at; public User user; }
    public static class Bus { public long id; public String bus_number, registration_number, description; public int capacity; }
    public static class Stop { public long id; public int order; public String name, address; public double latitude, longitude; }
    public static class Route { public long id; public String route_code, route_name, start_location, destination, direction; public List<Stop> stops; }
    public static class Trip { public long id; public String status, trip_type, start_time, end_time; public boolean is_simulated; }
    public static class Assignment {
        public String status, message; public User driver; public Bus bus; public Route route;
        public Trip active_trip, trip; public int gps_interval_seconds;
        public boolean assigned() { return "assigned".equals(status) && bus != null && route != null; }
    }
    public static class TripResponse { public Trip trip; public boolean created; }
    public static class LocationPayload {
        public final double latitude, longitude, speed, accuracy;
        public final String recorded_at;
        public LocationPayload(double latitude, double longitude, double speed, double accuracy, long timestamp) {
            this.latitude = latitude; this.longitude = longitude; this.speed = speed; this.accuracy = accuracy;
            this.recorded_at = Instant.ofEpochMilli(timestamp).toString();
        }
        public long timestamp() { return Instant.parse(recorded_at).toEpochMilli(); }
    }
    public static class LocationResponse { public String status, recorded_at, received_at; }
}
