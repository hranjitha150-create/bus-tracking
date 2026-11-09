package com.campustransit.driver.utils;
public final class RetryPolicy {
    public static final int MAX_ATTEMPTS = 5;
    public static long delayMillis(int failures) { return Math.min(30000L, 2000L << Math.min(Math.max(failures - 1, 0), 4)); }
    private RetryPolicy() {}
}
