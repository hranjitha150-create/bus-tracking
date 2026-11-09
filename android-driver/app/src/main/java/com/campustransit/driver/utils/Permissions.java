package com.campustransit.driver.utils;
import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Build;
import androidx.core.content.ContextCompat;
import androidx.core.app.NotificationManagerCompat;
public final class Permissions {
    private Permissions() {}
    public static boolean location(Context context) { return ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED; }
    public static boolean notificationPermission(Context context) { return Build.VERSION.SDK_INT < 33 || ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED; }
    public static boolean notifications(Context context) {
        if (!notificationPermission(context) || !NotificationManagerCompat.from(context).areNotificationsEnabled()) return false;
        android.app.NotificationChannel channel = context.getSystemService(android.app.NotificationManager.class).getNotificationChannel("active_trip_location");
        return channel == null || channel.getImportance() != android.app.NotificationManager.IMPORTANCE_NONE;
    }
}
