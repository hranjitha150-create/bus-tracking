# Student portal — Phase 3

Phase 5 now implements the ETA integration point and adds next-stop/progress display. See [current live GPS/ETA behavior](phase5.md); the Phase 3 notes below describe the original portal and authentication contract.

Sign in through the existing `/login/` page using a college-provisioned STUDENT account. The existing `/dashboard/student/` destination now serves the full student dashboard. Admin and driver role redirects are unchanged. No schema migration, new database or duplicate profile/route model is introduced.

## Pages

| URL | Purpose |
| --- | --- |
| `/dashboard/student/`, `/student/` | Name, enrollment, assigned bus and route, pickup, current trip, last GPS and ETA availability |
| `/student/bus/` | Assigned bus registration, capacity and description |
| `/student/tracking/` | Leaflet map and polling updates for the assigned bus |
| `/student/route/` | Map plus all ordered stops, coordinates, pickup highlighting and endpoints |
| `/student/pickup/` | Pickup address, coordinates and focused map |
| `/student/profile/` | Own account/profile details and CSRF-protected POST logout |

Mobile navigation collapses into an accessible menu. Pages provide clear messages for a missing student profile, no active bus assignment, an inactive bus, missing route, invalid pickup configuration, no active trip, missing or stale GPS, completed trips, API failure and network loss. Personal and tracking pages use no-store response headers. Profile changes and assignment changes remain administrator operations.

## Assignment-only access

`students/queries.py` derives the bus from `StudentBusAssignment` using the authenticated user, `is_active=True` and `bus__is_active=True`. It holds that assignment row stable while materializing a transaction-scoped snapshot. Route lookup uses the assigned bus's current active driver/route assignment. Location lookup additionally requires the matching bus, relevant trip and assigned route.

No student endpoint accepts a bus ID in its path. Query parameters such as `bus`, `bus_id`, `route_id` and `student` are ignored for selection and authorization. The frontend only calls fixed `/api/student/...` URLs and has no bus selector. An assignment change is picked up on the next poll; the old marker and route layers are cleared. An ended assignment returns the no-assignment state. The existing Phase 1 `/api/buses/{id}/location/` and trip APIs remain scoped and reject other buses with 404. All admin APIs remain forbidden to students.

Only active STUDENT accounts may use student APIs (401 anonymous, 403 wrong role). Admins manage records through their separate portal rather than impersonating students through these endpoints.

## REST endpoints

| Endpoint | Response |
| --- | --- |
| `GET /api/student/dashboard/` | Authorized student transport snapshot |
| `GET /api/student/my-bus/` | Same complete snapshot for the assigned bus |
| `GET /api/student/my-route/` | Assignment status, assigned bus, route, ordered stops and pickup |
| `GET /api/student/my-bus/location/` | Complete snapshot including location, trip, route and ETA state; used by polling |
| `GET /api/student/my-bus/eta/` | Explicit ETA availability plus authorized bus/pickup identity |

The complete snapshot contains:

- `status`: `assigned`, `unassigned` or `profile_unavailable`, with a user-facing `message`.
- `student`: own name, email, enrollment, department, semester and phone. No password, other students or driver personal information is returned.
- `assignment`, `bus`, `route`, `pickup_stop`: current authorized details, or null. `route.stops` is ordered by `stop_order` and includes actual stored decimal coordinates converted to JSON numbers. The pickup must belong to the assigned route; invalid legacy configurations return a message instead of exposing an unrelated stop.
- `active_trip`, `trip`, `trip_status`, `trip_label`: the active matching trip, or the latest relevant bus/route trip when inactive.
- `location`: matching current-trip position, or a clearly historical position for a completed trip. Null if missing or if the stored location belongs to an older trip while a different trip is active.
- `gps`: `status`, label, age, device `recorded_at`, server `received_at`, freshness window and `is_fresh`.
- `eta`: availability contract described below.
- `generated_at` and `poll_interval_seconds`: server clock and polling configuration.

Missing data returns 200 with explicit null/unavailable fields, so clients do not need to treat “not started” as a server error. All methods other than GET/HEAD/OPTIONS are rejected. Responses are private and not cached.

## GPS and polling

Fresh GPS requires an ACTIVE matching trip, recorded and received timestamps not in the future, and both timestamps within `GPS_STALE_SECONDS` (120 by default). States include `fresh`, `stale`, `unavailable`, `no_active_trip`, `completed` and `invalid_timestamp`. Coordinates are never generated when none exist.

`student.js` fetches `/api/student/my-bus/location/` every **10 seconds** by default. Configure `STUDENT_POLL_INTERVAL_SECONDS=10` in `backend/.env`; valid values are 2–300. The interval is supplied by the server rather than chosen using a bus ID. Requests do not overlap, use a timeout, skip hidden pages and resume on visibility/network recovery. Page unload aborts requests and clears polling/age intervals; browser back navigation restarts them safely.

`student-map.js` creates one Leaflet map, one route layer group and at most one bus marker. Fresh positions call `setLatLng()` on the existing marker. Route layers rebuild only when the route/pickup/assignment changes. Missing location removes the marker; completed/stale positions remain visibly historical. The client also ages samples using the server clock offset, preventing a once-fresh sample from staying green indefinitely between polls.

Network/API failures retain a clearly labeled last-known position, remove live styling and suppress ETA. Authentication failures clear assignment, route and position data and offer a login link. Leaflet/library/tile failure is reported without breaking the textual route/stop/coordinate data. Popups and stop names use text nodes; initial state uses Django `json_script`.

## R001 source data and geometry

Phase 3 does not create sample stops in Supabase. The mentor's CSV was still absent during implementation. Place the real file at `backend/data/bus_route_stops.csv` and import it through the admin CSV interface or:

```powershell
.\.venv\Scripts\python.exe backend\manage.py import_bus_route backend/data/bus_route_stops.csv
```

The existing importer requires 21 ordered stops from **NIE Golden Jubilee** to **North Campus Last Stop**, validates real coordinates and retains metadata. Assign R001 to the student's bus through an active driver/bus/route assignment, then assign a pickup on that route. The student map renders every imported stop in database order and highlights start, destination and pickup. It never falls back to another bus's R001 when a student has no assigned route.

`Route.geometry` already stores optional GeoJSON LineString road geometry using `[longitude, latitude]`. `routes/geometry.py` validates it before delivery. Valid stored geometry is drawn as a solid line. When missing or invalid, a dashed line connects actual stop coordinates and is explicitly labeled **“Approximate stop connections — not a verified driving route.”** Fewer than two stops yield no polyline. Invalid stored geometry is reported and never crashes the page.

Future OSRM integration can store `routes[0].geometry` from a response requested with `geometries=geojson&overview=full`, validate it with `routes.models.validate_geometry()`, and save it in `Route.geometry`. No public routing-service request is made by student browsers. The storage contract stays independent of a specific routing service. See [OSRM HTTP API](https://project-osrm.org/docs/v26.4.0/http) and [Leaflet reference](https://leafletjs.com/reference).

## Phase 5 ETA integration point

`eta/services.py::estimate_pickup_eta(bus, trip, pickup_stop, location, now)` is the integration point. The Phase 3 implementation always returns:

```json
{"status":"unavailable","reason":"not_implemented","seconds":null,"arrival_at":null,"message":"Arrival estimates are not available yet."}
```

The query service only invokes the estimator for a fresh, matching active-trip location and valid assigned pickup. Other cases return explicit reasons such as `no_assignment`, `route_unavailable`, `pickup_unavailable`, `no_active_trip`, `gps_unavailable` or `gps_stale`. Phase 5 can return `status: available`, nonnegative numeric `seconds`, an aware ISO-8601 `arrival_at`, and a human-readable message. The existing UI then displays the estimate and refreshes it with location polls. No straight-line travel-time estimate or fake countdown is implemented now.

## Verification

Run against a dedicated PostgreSQL test database:

```powershell
.\.venv\Scripts\python.exe backend\manage.py test accounts routes tracking admin_portal students --settings=config.test_settings --noinput
node --check backend/static/js/student.js
node --check backend/static/js/student-map.js
```

Optional real-browser checks are in `backend/students/browser_smoke.py`. They require Playwright/Chromium and the isolated PostgreSQL server on `127.0.0.1:55432`, create/drop a disposable test database, and use synthetic CSV/GPS fixtures only. The browser interval is reduced to two seconds exclusively for this check. No test account, GPS sample or test write endpoint is added to Supabase or the application. See [Phase 3 verification](phase3-verification.md).
