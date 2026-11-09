# Phase 3 verification — 2026-11-06

## Executed checks

- **91 automated tests passed** on PostgreSQL 17: the 64 existing Phase 1/2 tests plus 23 student portal tests and 4 reusable geometry tests.
- Real Chromium browser checks passed for login/redirect, all 21 ordered stops, start/destination/pickup markers, a pickup that is also the route start, automatic two-second test polling, marker movement without map or marker replacement, stale samples and client clock aging, missing GPS, completed trips, HTTP 503 handling, network disconnection/recovery, invalid geometry fallback, reassignment, assignment revocation, map-library failure, session expiry and mobile navigation/overflow checks.
- No JavaScript page errors were observed during the browser checks.
- Desktop and mobile screenshots were reviewed. These contain **synthetic CSV/GPS fixtures in a disposable local test database**, not production route coordinates or real Supabase tracking: [dashboard](screenshots/student-dashboard.png), [tracking](screenshots/student-tracking.png), [mobile route/stops](screenshots/student-mobile.png).
- Django system checks passed. `makemigrations --check --dry-run` reported no changes. Python compilation and both new JavaScript syntax checks passed.
- Read-only `manage.py migrate --check` succeeded against the configured Supabase database. No schema migrations were needed and no Supabase records were created or changed during Phase 3 validation.

## Backend coverage

Student tests verify active assignment-derived bus access, ignored malicious bus/route/student selectors, denial of other buses through legacy APIs, current pickup membership, all 21 parsed fixture stops in order, safe missing-profile/no-assignment/inactive-bus states, assignment replacement, missing route, current active trips, absent/fresh/stale/future GPS timestamps, completed-trip historical positions, rejection of old-trip samples as current locations, explicit ETA unavailability, the Phase 5 ETA provider hook, corrupt geometry fallback, all student pages, configurable polling, no-store responses, session authentication, read-only APIs, anonymous/wrong-role denial and continued admin API denial.

## Remaining external input

The mentor's actual `backend/data/bus_route_stops.csv` is still missing. Real R001 coordinates and the 21 real stops could not be imported or verified. Supply the original file through the existing admin import interface, then configure the bus's driver/route assignment and student's pickup assignment. Phase 3 renders those actual stored records without seeding invented positions.

ETA calculation remains deliberately unavailable until Phase 5; its integration point is `eta/services.py`. Android GPS publishing is outside this phase. Bootstrap/Leaflet CDN resources and OpenStreetMap tiles require network access. Their failure states were verified.

The browser harness starts/stops its own temporary Django server and creates/drops its test database. The isolated PostgreSQL cluster is stopped after final verification. Normal application settings continue to use the configured Supabase database.
