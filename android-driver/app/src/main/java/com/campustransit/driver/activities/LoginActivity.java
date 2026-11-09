package com.campustransit.driver.activities;

import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.widget.*;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.graphics.Insets;
import androidx.core.view.*;
import com.campustransit.driver.BuildConfig;
import com.campustransit.driver.R;
import com.campustransit.driver.api.*;
import com.campustransit.driver.models.Models.*;
import com.campustransit.driver.utils.TokenStore;
import retrofit2.*;

public final class LoginActivity extends AppCompatActivity {
    private Call<LoginResponse> request;
    private TokenStore tokens;
    private boolean busy;
    @Override protected void onCreate(Bundle saved) {
        super.onCreate(saved); setContentView(R.layout.activity_login); applyInsets(this);
        tokens = new TokenStore(this);
        if (!tokens.token().isEmpty()) { openDashboard(); return; }
        findViewById(R.id.login).setOnClickListener(view -> login());
    }
    public static void applyInsets(AppCompatActivity activity) {
        ViewCompat.setOnApplyWindowInsetsListener(activity.findViewById(R.id.root), (view, insets) -> {
            Insets bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() | WindowInsetsCompat.Type.ime());
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom); return insets;
        });
    }
    private void login() {
        if (busy) return;
        EditText email = findViewById(R.id.email), password = findViewById(R.id.password);
        String address = email.getText().toString().trim(), secret = password.getText().toString();
        if (address.isEmpty() || secret.isEmpty()) { message("Enter your college email and password."); return; }
        password.setText(""); setBusy(true); message("");
        request = ApiClient.get(this).login(new LoginRequest(address, secret));
        request.enqueue(new Callback<LoginResponse>() {
            @Override public void onResponse(Call<LoginResponse> call, Response<LoginResponse> response) {
                if (isDestroyed()) return;
                setBusy(false); LoginResponse body = response.body();
                if (!response.isSuccessful() || body == null || body.user == null || body.token == null) {
                    message(response.code() == 401 ? "Email or password is incorrect." : "Sign-in failed (" + response.code() + "). Check the server URL and try again."); return;
                }
                if (!"DRIVER".equals(body.user.role)) {
                    ApiClient.create(BuildConfig.API_URL, () -> body.token).logout().enqueue(new Callback<Void>() {
                        @Override public void onResponse(Call<Void> call, Response<Void> result) { }
                        @Override public void onFailure(Call<Void> call, Throwable error) { }
                    });
                    message("This app is for college driver accounts. Use the website for student or administrator access."); return;
                }
                try { tokens.save(body.token, body.expires_at); openDashboard(); }
                catch (Exception secureStorageError) { message("Secure token storage is unavailable. Unlock the device and try again."); }
            }
            @Override public void onFailure(Call<LoginResponse> call, Throwable error) { if (!isDestroyed()) { setBusy(false); message("Cannot reach the college server. Check your connection and the app’s API URL."); } }
        });
    }
    private void setBusy(boolean value) { busy = value; findViewById(R.id.login).setEnabled(!value); findViewById(R.id.loginProgress).setVisibility(value ? View.VISIBLE : View.GONE); }
    private void message(String text) { ((TextView) findViewById(R.id.loginStatus)).setText(text); }
    private void openDashboard() { startActivity(new Intent(this, DashboardActivity.class)); finish(); }
    @Override protected void onDestroy() { if (request != null) request.cancel(); super.onDestroy(); }
}
