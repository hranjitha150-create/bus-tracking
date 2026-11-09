# Phase 2 verification — 2026-11-06

## Completed

- **64 automated tests passed** against PostgreSQL 17: the original 31 Phase 1 tests and 33 admin portal tests.
- Real Chromium browser smoke checks passed for session login, bus creation through the form, dynamic pickup selection, successful reassignment, Leaflet map initialization, authenticated fleet refresh, mobile menu open/close and absence of horizontal document overflow at 390 px. No JavaScript page errors were observed.
- Desktop and mobile screenshots were reviewed. Screenshots use synthetic records in a disposable test database, not Supabase college records: [desktop](screenshots/admin-desktop.png), [mobile](screenshots/admin-mobile.png), [map](screenshots/admin-map.png).
- Django system checks passed. No model/migration changes were detected. Python compilation and both JavaScript syntax checks passed.
- Read-only `manage.py migrate --check` succeeded against the configured Supabase database. Phase 2 adds no schema migrations and required no production database writes.

## Test scope

Admin tests exercise bus creation/search/updates/deactivation, capacity and identifier validation, account/profile registration and atomic rollback, password hashing and token revocation, one-active student assignments, driver conflicts and replacement history, invalid pickups, route-change protections, active-trip protections, route code stability, stop insertion/edit/reorder/removal, source imports/idempotency/rollback, GPS freshness and previous-trip handling, real dashboard counts, all admin page rendering, API pagination/search, assignment ending, session CSRF and cross-role HTML/API denial.

## Outstanding input

The mentor's `backend/data/bus_route_stops.csv` is still absent. The actual 21-stop R001 route could not be imported. Tests use explicitly synthetic fixtures only. Upload the real file through `/portal/routes/import/` when available.

Bootstrap/Leaflet CDN access and OpenStreetMap tiles need network connectivity. The Android app, location publishing and student map remain outside Phase 2. The existing student authentication and assigned-bus APIs remain covered by the passing regression suite.
