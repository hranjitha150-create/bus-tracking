# Phase 5 verification — 2026-11-06

## Passed locally

- **133 automated tests passed on PostgreSQL 17**: the previous 112 tests plus 21 Phase 5 integration/GIS tests. These use disposable databases, not SQLite or production data.
- The additive `tracking/0003_buslocation_is_simulated_and_more.py` migration applied successfully to the local validation database, reversed to 0002, and reapplied successfully. `makemigrations --check --dry-run` reports no changes.
- Django system checks, Python compilation and syntax checks for all three modified JavaScript modules passed.
- **Full HTTP/browser integration passed**: an authenticated test driver starts a trip and publishes GPS through the real REST endpoints; PostgreSQL updates latest location/history/progress; a separately signed-in student polls automatically and sees a moving retained marker, a decreasing ETA, the next stop and 21 ordered stops; a separately signed-in administrator sees the same bus/next stop and can inspect it. Ending the trip changes both portals to completed and suppresses ETA/live status. An admin HTTP 503 response removes live labels and is recoverable.
- Existing student browser regression checks passed for assignment changes/revocation, session expiry, missing/stale/completed GPS, network failure/recovery, missing map library, marker/map retention and mobile layout.
- Reviewed [student integration screenshot](screenshots/phase5-student-tracking.png) and [admin integration screenshot](screenshots/phase5-admin-tracking.png). They contain **synthetic fixtures in a disposable test database**. They are not real R001 geometry or actual production GPS.

## New test coverage

Tests cover driver → database → student/admin → completion; decreasing route-distance ETA; stop progression; confidence-aware monotone progress through jitter; loop/crossing disambiguation; explicitly configured DROP direction; rejection of implicit reverse geometry; off-route/rejoin behavior; stationary/fallback speed; fresh/stale GPS; implausible jumps and poor-accuracy rollback; passed pickups; invalid/missing/changed geometry; history sampling/disable/retention; source-mode separation and production replay guards; single-request/cached optional OSRM generation; routing failure rollback and active-trip geometry protection. Existing role, assignment, token, concurrency and Android-facing API tests remain passing.

OSRM HTTP responses were mocked in tests. No geometry request was sent for invented coordinates. The browser fixture constructs an explicitly synthetic test LineString to exercise the full ETA path; it is not offered as real road data.

## External verification blocked

The configured Supabase pooler hostname failed DNS resolution on two read-only attempts (`getaddrinfo failed`). Therefore:

- Supabase migration 0003 was **not applied** in this phase. Run `python backend/manage.py migrate` once the configured database host resolves.
- The live database's current R001 content could not be inspected. The actual mentor CSV is absent from the checkout, so its real coordinates and an actual OSRM-generated R001 path remain unverified.
- No Supabase accounts, locations, geometry or simulation data were created/changed by the tests. Normal `.env` credentials were not printed or modified.

See [deployment and operator commands](phase5.md) for migration, actual CSV import, optional one-time geometry generation and history maintenance. Tests establish the integrated local software path; no real Android satellite GPS or physical travel/ETA accuracy was tested in this phase. The existing Java Android app's normal driver endpoint contract is preserved; Phase 4 build/device verification is documented separately.

The browser harness stops its own HTTP server and drops its test database. The isolated PostgreSQL test server is stopped after verification.
