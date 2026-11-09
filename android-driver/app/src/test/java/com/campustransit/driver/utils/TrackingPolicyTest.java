package com.campustransit.driver.utils;
import com.campustransit.driver.models.Models.LocationPayload;
import org.junit.Test;
import static org.junit.Assert.*;

public class TrackingPolicyTest {
    @Test public void rejectsInvalidOldAndFutureFixes() {
        long now = 1800000000000L;
        assertTrue(FixPolicy.valid(new LocationPayload(12, 77, 1, 5, now), now));
        assertFalse(FixPolicy.valid(new LocationPayload(91, 77, 1, 5, now), now));
        assertFalse(FixPolicy.valid(new LocationPayload(12, Double.NaN, 1, 5, now), now));
        assertFalse(FixPolicy.valid(new LocationPayload(12, 77, -1, 5, now), now));
        assertFalse(FixPolicy.valid(new LocationPayload(12, 77, 1, -5, now), now));
        assertFalse(FixPolicy.valid(new LocationPayload(12, 77, 1, 5, now - 120001), now));
        assertFalse(FixPolicy.valid(new LocationPayload(12, 77, 1, 5, now + 30001), now));
    }
    @Test public void newestOnlyQueueDoesNotLoseFixDuringAcknowledgement() {
        LatestFixQueue queue = new LatestFixQueue();
        LocationPayload first = new LocationPayload(12, 77, 0, 5, 1000);
        LocationPayload next = new LocationPayload(12, 77.1, 1, 5, 2000);
        assertTrue(queue.offer(first)); assertTrue(queue.offer(next));
        queue.acknowledge(first); assertSame(next, queue.peek());
        assertFalse(queue.offer(first)); assertFalse(queue.offer(next));
        queue.acknowledge(next); assertNull(queue.peek());
        assertFalse(queue.offer(first));
    }
    @Test public void retryBackoffIsBounded() {
        assertEquals(2000, RetryPolicy.delayMillis(1));
        assertEquals(4000, RetryPolicy.delayMillis(2));
        assertEquals(30000, RetryPolicy.delayMillis(99));
        assertEquals(5, RetryPolicy.MAX_ATTEMPTS);
    }
}
