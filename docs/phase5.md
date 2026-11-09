# Phase 5 — integrated GPS, route progress and ETA

The normal pipeline is the existing Android foreground service → driver REST API → Supabase PostgreSQL → assigned-student/admin APIs → existing Leaflet markers. Phase 5 adds quality checks, transactional progress, ETA, optional directional routing and explicitly labeled development replay. There is no traffic feed and no generated production GPS.

## Deploy and prepare R001

Apply the additive migration before running the updated app:

```powershell
.\.venv\Scripts\python.exe backend\manage.py migrate
```

`tracking/0003_buslocation_is_simulated_and_more.py` adds simulation flags to trips/locations/history and a one-to-one TripProgress record. Existing trips and GPS rows default to real-driver mode; existing keys, assignments and partial unique constraints are retained.

Import the actual mentor CSV if it is not already in the database, using the admin upload interface or existing command. No CSV was supplied in this checkout during implementation, and live Supabase DNS lookup failed, so its current R001 content could not be verified.

```powershell
.\.venv\Scripts\python.exe backend\manage.py import_bus_route backend/data/bus_route_stops.csv
.\.venv\Scripts\python.exe backend\manage.py generate_route_geometry R001
```

The optional geometry command sends **one operator-initiated OSRM request**, outside the GPS/read APIs. It uses actual ordered stop coordinates, requires all 21 stops for R001, requests a GeoJSON road-following LineString and stores it in PostgreSQL. An existing geometry is skipped unless `--force` is supplied. Active trips block replacement. Network/validation failures retain the previous geometry. Commands serialize across processes, wait at least 1.1 seconds before requesting and do not automatically retry. Use your own routing service for production traffic; public demo routing has usage limits and no uptime/traffic-data guarantee. See the [OSRM route API](https://project-osrm.org/docs/v26.5.0/http) and [demo server policy](https://github.com/Project-OSRM/osrm-backend/wiki/Demo-server).

The returned path must follow the configured stops in order and have endpoints near the configured start/destination. Review it for suitability for your college bus. It does not establish legal bus access, real-time closures or traffic. If unavailable, both maps retain an explicitly labeled approximate stop-connecting polyline, and ETA/next-stop estimates remain unavailable rather than using straight-line travel times.

Set up actual driver/bus/route and student/pickup assignments through the existing portal. The Android APK and its authentication contract remain compatible: additional response fields are additive, and real uploads still use the original driver URL.

## GPS acceptance and latest-location storage

`POST /api/driver/trips/{id}/location/` continues to authenticate an active DRIVER and enforce its current active bus/route assignment. A bus row lock coordinates concurrent uploads, trip start/end and portal assignment changes. The trip is rechecked after locking.

The API validates geographic ranges, finite nonnegative speed/accuracy, timezone-aware device timestamps, sample age, future-clock tolerance and trip start time. New defaults reject accuracy worse than 100 m and speed above 45 m/s. For consecutive samples on the same trip, a position jump is rejected when straight-line displacement exceeds maximum plausible speed × elapsed time + both accuracy radii + a configured noise allowance. Rejected fixes do not update latest location, history or progress.

An accepted sample atomically updates the one BusLocation, optionally appends history and advances TripProgress. Older timestamps never replace newer current positions. Identical latest samples or retained-history retries return `duplicate` without refreshing their received timestamp. A timestamp reused with different values is rejected. If history sampling/retention omits an old sample, its retry can return `out_of_order`; it still cannot overwrite the latest sample.

`LOCATION_HISTORY_ENABLED` and `LOCATION_HISTORY_MIN_INTERVAL_SECONDS` control history collection separately from live position/progress updates. Default behavior saves every accepted fix. To enforce time retention, schedule this maintenance command daily (cron, Task Scheduler or your deployment scheduler):

```powershell
.\.venv\Scripts\python.exe backend\manage.py prune_location_history
```

It deletes history older than `LOCATION_HISTORY_RETENTION_DAYS` in bounded batches and preserves the latest position and progress. No automatic task was registered in the user's account during this implementation.

## Route matching and next stop

`tracking/gis.py` builds a cached metre-based plan from the stored LineString and ordered stops. Stops are projected sequentially onto the route, not chosen by nearest-stop distance. The plan fingerprint includes geometry, stop order/coordinates and direction. It is reused in-process; no routing HTTP requests occur during uploads or polling.

`tracking/processing.py` projects each valid GPS fix onto candidate route segments. Previous matched progress, elapsed time, speed and accuracy constrain candidates at bends, loops and crossings. Confirmed along-route distance is monotone through normal GPS jitter. The next stop is the first ordered stop not confidently passed, using a threshold at least as large as the configured passed-stop tolerance and current accuracy radius. Distances to the next and pickup stops are along the configured path.

Off-route fixes still update the actual GPS marker, but do not advance route progress or produce ETA. The last matched time is retained so legitimate rejoining after a deviation can recover. Geometry changes cannot reuse old progress silently. Stale/missing GPS and unmatched samples suppress reliable progress estimates.

Route direction is explicit. TO_COLLEGE routes support PICKUP trips; FROM_COLLEGE routes support DROP trips. The latter must have its own correctly ordered stops and stored directional geometry. The system never automatically reverses morning road geometry to represent an evening road path; mismatched direction/type returns `direction_mismatch`.

## ETA contract

`eta/services.py::estimate_pickup_eta` now calculates:

```text
seconds = remaining route metres / estimated metres per second
          + remaining intermediate stops × configured dwell seconds
```

Speed is exponentially smoothed over recent accepted fixes. Forward route movement can supplement missing/zero reported speed. A configured nominal speed is an explicit fallback before a stationary condition has been established. Sustained stationary samples make ETA unavailable instead of implying the bus will immediately move. Dwells are assumptions, not measured traffic delays.

Available responses retain the existing `status`, `seconds`, `arrival_at` and `message` fields and add `distance_m`, `speed_kmh`, `speed_source`, `assumed_dwell_seconds` and `is_simulated`. The message identifies the speed assumption and states that live traffic is not used. Arrivals are estimates, not guarantees.

Unavailable reasons include `no_assignment`, `no_active_trip`, `completed`, `gps_unavailable`, `gps_stale`, `poor_accuracy`, `pickup_unavailable`, `pickup_passed`, `off_route`, `geometry_unavailable`, `geometry_invalid`, `geometry_changed`, `direction_mismatch` and `progress_pending`. Duration and arrival are null when unavailable. No fabricated ETA is returned.

## Student and admin interfaces

The existing student URLs derive the active bus from the authenticated student's assignment. They accept no bus-selection path parameter. `GET /api/student/my-bus/location/` now includes `progress` with next stop, route progress, next-stop distance, pickup distance and pickup-passed state, alongside the existing location, trip, GPS and ETA. Old/other-trip samples never become current positions for a new trip.

The student pages show next stop, distances, progress and ETA, updating the existing marker. Polling defaults to 10 seconds and is configurable; production settings of 5–10 seconds are appropriate. Hidden-page polling, network recovery, timeout handling, stale-state aging, logout/expiry and assignment-change protections from Phase 3 remain in place.

`GET /api/admin/live-buses/` still includes registered buses with missing/inactive GPS states as well as currently tracked buses. It adds next stop/progress, simulation flag and polling configuration. The admin map updates marker positions in place; **Inspect bus** selects a vehicle and opens its popup with driver, route, trip, timestamps and next stop. Completed trips leave clearly historical markers. Default admin polling is now 10 seconds. All admin endpoints remain ADMIN-only.

## Configuration

Optional values are documented in `backend/.env.example`; normal real-driver behavior is the default.

| Setting | Default | Meaning |
| --- | --- | --- |
| `GPS_MAX_ACCURACY_METERS` | 100 | Worst accepted reported accuracy |
| `GPS_MAX_SPEED_MPS` | 45 | Maximum accepted speed and jump envelope |
| `GPS_JUMP_ALLOWANCE_METERS` | 50 | Additional displacement noise allowance |
| `ROUTE_CORRIDOR_METERS` | 50 | Off-route threshold before adding accuracy radius |
| `ROUTE_STOP_SNAP_METERS` | 150 | Maximum stop-to-geometry/endpoints gap |
| `STOP_PASSED_METERS` | 25 | Minimum confident passed-stop distance |
| `ETA_FALLBACK_SPEED_KMH` | 20 | Explicit nominal speed assumption |
| `ETA_STATIONARY_SECONDS` | 30 | Stationary duration before suppressing ETA |
| `ETA_STOP_DWELL_SECONDS` | 15 | Assumed dwell per intermediate stop |
| `LOCATION_HISTORY_ENABLED` | True | Persist accepted history samples |
| `LOCATION_HISTORY_MIN_INTERVAL_SECONDS` | 0 | Minimum time between retained samples |
| `LOCATION_HISTORY_RETENTION_DAYS` | 30 | Age removed by the maintenance command |
| `STUDENT_POLL_INTERVAL_SECONDS` | 10 | Existing student polling configuration |
| `ADMIN_POLL_INTERVAL_SECONDS` | 10 | Admin polling interval |
| `OSRM_BASE_URL` | https://router.project-osrm.org | Trusted HTTPS routing server |
| `ENABLE_ROUTE_REPLAY` | False | Separate development-only simulation path |

## Optional development replay

Replay is deliberately unavailable unless **both** `DJANGO_DEBUG=True` and `ENABLE_ROUTE_REPLAY=True`. Use a separate local development database/server with the real R001 import and a development driver assignment. Production should keep replay disabled.

```powershell
.\.venv\Scripts\python.exe backend\manage.py replay_bus_route --driver-email development-driver@example.test --base-url http://127.0.0.1:8000 --interval 10 --speed-kmh 20 --max-updates 30
```

The tool prompts for the development driver's password (not a command-line password), reads actual stored R001 stops, interpolates along stored road geometry or explicitly approximate stop connections, and sends real-time timestamped **SIMULATED** samples through designated development endpoints. It never seeds substitute route coordinates. It ends its simulated trip and revokes its token on normal exit/interruption where the server is reachable.

`POST /api/development/trips/start/` creates/reuses only simulated trips; `POST /api/development/trips/{id}/location/` only accepts those trips. They retain normal DRIVER ownership checks and are unavailable in production mode. Real GPS endpoints cannot write a simulated trip, and replay cannot write a real trip. Switching modes requires ending the old trip. The database and every location/trip API retain simulation flags. Student pages display a simulation banner, GPS labels say SIMULATED and map markers are purple; admin popups/tables/inspection likewise identify replay data.

Development replay is useful without a phone but does not establish physical GPS accuracy, road suitability or real-world ETA performance. Real Android GPS remains the default pipeline.

## Validation

```powershell
.\.venv\Scripts\python.exe backend\manage.py test accounts routes tracking admin_portal students drivers eta --settings=config.test_settings --noinput
.\.venv\Scripts\python.exe backend\manage.py check
.\.venv\Scripts\python.exe backend\manage.py makemigrations --check --dry-run
```

The optional `backend/eta/browser_smoke.py` starts its own local HTTP server and disposable PostgreSQL database. It drives actual login/start/GPS HTTP requests through both browser portals, checking ETA movement, next stops, retained markers and completion. All automated fixture coordinates are synthetic, isolated from Supabase, and are not supplied as real route data. See [Phase 5 verification](phase5-verification.md).
