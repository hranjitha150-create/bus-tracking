package com.campustransit.driver.api;
import com.campustransit.driver.models.Models.*;
import okhttp3.mockwebserver.*;
import org.junit.*;
import static org.junit.Assert.*;

public class DriverApiTest {
    private MockWebServer server;
    private DriverApi api;
    @Before public void before() throws Exception { server = new MockWebServer(); server.start(); api = ApiClient.create(server.url("/").toString(), () -> "test-token"); }
    @After public void after() throws Exception { server.shutdown(); }
    @Test public void loginDoesNotSendOldTokenAndParsesRole() throws Exception {
        server.enqueue(new MockResponse().setBody("{\"token\":\"issued-token\",\"expires_at\":\"2030-01-01T00:00:00Z\",\"user\":{\"role\":\"DRIVER\",\"full_name\":\"Test Driver\"}}"));
        LoginResponse result = api.login(new LoginRequest("driver@example.test", "test-only-password")).execute().body();
        assertEquals("DRIVER", result.user.role);
        RecordedRequest request = server.takeRequest();
        assertEquals("/api/auth/login/", request.getPath());
        assertNull(request.getHeader("Authorization"));
        assertTrue(request.getBody().readUtf8().contains("driver@example.test"));
    }
    @Test public void assignmentStartLocationEndUseBearerAndTripPaths() throws Exception {
        server.enqueue(new MockResponse().setBody("{\"status\":\"unassigned\"}"));
        assertFalse(api.assignment().execute().body().assigned());
        assertEquals("Bearer test-token", server.takeRequest().getHeader("Authorization"));
        server.enqueue(new MockResponse().setResponseCode(201).setBody("{\"trip\":{\"id\":42,\"status\":\"ACTIVE\"}}"));
        assertEquals(42, api.start().execute().body().trip.id);
        assertEquals("/api/driver/trips/start/", server.takeRequest().getPath());
        server.enqueue(new MockResponse().setResponseCode(201).setBody("{\"status\":\"accepted\"}"));
        api.location(42, new LocationPayload(12, 77, 2, 5, 1800000000000L)).execute();
        RecordedRequest gps = server.takeRequest();
        assertEquals("/api/driver/trips/42/location/", gps.getPath()); assertTrue(gps.getBody().readUtf8().contains("recorded_at"));
        server.enqueue(new MockResponse().setBody("{\"trip\":{\"id\":42,\"status\":\"COMPLETED\"}}"));
        assertEquals("COMPLETED", api.end(42).execute().body().trip.status);
        assertEquals("/api/driver/trips/42/end/", server.takeRequest().getPath());
    }
    @Test public void authenticationFailuresAndRedirectsAreNotSilentlyRetried() throws Exception {
        server.enqueue(new MockResponse().setResponseCode(401).setBody("{\"detail\":\"expired\"}"));
        assertEquals(401, api.assignment().execute().code()); server.takeRequest();
        server.enqueue(new MockResponse().setResponseCode(302).setHeader("Location", server.url("/other/")));
        assertEquals(302, api.assignment().execute().code()); server.takeRequest();
        assertEquals(2, server.getRequestCount());
    }
}
