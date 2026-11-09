package com.campustransit.driver.api;
import com.campustransit.driver.models.Models.*;
import retrofit2.Call;
import retrofit2.http.*;

public interface DriverApi {
    @POST("api/auth/login/") Call<LoginResponse> login(@Body LoginRequest body);
    @POST("api/auth/logout/") Call<Void> logout();
    @GET("api/driver/assignment/") Call<Assignment> assignment();
    @POST("api/driver/trips/start/") Call<TripResponse> start();
    @POST("api/driver/trips/{id}/end/") Call<TripResponse> end(@Path("id") long tripId);
    @POST("api/driver/trips/{id}/location/") Call<LocationResponse> location(@Path("id") long tripId, @Body LocationPayload location);
}
