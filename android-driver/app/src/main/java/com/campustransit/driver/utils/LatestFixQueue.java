package com.campustransit.driver.utils;
import com.campustransit.driver.models.Models.LocationPayload;

/** One memory-only pending sample; acknowledgements cannot clear a newer fix. */
public final class LatestFixQueue {
    private LocationPayload pending;
    private long highestTimestamp = Long.MIN_VALUE;
    public synchronized boolean offer(LocationPayload fix) {
        if (fix.timestamp() <= highestTimestamp) return false;
        highestTimestamp = fix.timestamp(); pending = fix; return true;
    }
    public synchronized LocationPayload peek() { return pending; }
    public synchronized void acknowledge(LocationPayload fix) { if (pending == fix) pending = null; }
    public synchronized void clear() { pending = null; }
}
