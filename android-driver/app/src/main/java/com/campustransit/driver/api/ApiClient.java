package com.campustransit.driver.api;

import android.content.Context;
import com.campustransit.driver.BuildConfig;
import com.campustransit.driver.utils.TokenStore;
import java.util.concurrent.TimeUnit;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import retrofit2.Retrofit;
import retrofit2.converter.gson.GsonConverterFactory;

public final class ApiClient {
    public interface TokenSource { String token(); }
    private ApiClient() {}
    public static DriverApi get(Context context) {
        TokenStore tokens = new TokenStore(context.getApplicationContext());
        return create(BuildConfig.API_URL, tokens::token);
    }
    public static DriverApi create(String url, TokenSource tokens) {
        OkHttpClient http = new OkHttpClient.Builder().connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(10, TimeUnit.SECONDS).writeTimeout(10, TimeUnit.SECONDS).callTimeout(20, TimeUnit.SECONDS)
            .followRedirects(false).followSslRedirects(false).retryOnConnectionFailure(false)
            .addInterceptor(chain -> {
                Request.Builder request = chain.request().newBuilder().header("Accept", "application/json");
                if (!chain.request().url().encodedPath().endsWith("/auth/login/")) {
                    String token = tokens.token();
                    if (!token.isEmpty()) request.header("Authorization", "Bearer " + token);
                }
                return chain.proceed(request.build());
            }).build();
        return new Retrofit.Builder().baseUrl(url).client(http).addConverterFactory(GsonConverterFactory.create()).build().create(DriverApi.class);
    }
}
