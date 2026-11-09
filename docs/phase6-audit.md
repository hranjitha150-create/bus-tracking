# Phase 6 audit and verification

Audit date: 2026-11-06. The existing project and migrations were preserved. This report supersedes earlier verification summaries for current acceptance status.

## Changes made

- Added a fail-closed production settings profile, secure cookies/HTTPS/HSTS, explicit proxy trust, CSP, no-store API headers, hashed WhiteNoise assets, Waitress requirements and secret-redacted production logging.
- Added shared website/API login attempt budgets, including authenticated requests, without persisting passwords or exposing raw tokens in logs.
- Tightened legacy driver actions to revalidate current assignments, reject simulation mixing and reject trip-type/route-direction mismatches. Active account/role checks cover object permissions.
- Hardened Android notification/channel checks, GPS-disabled handling and prevention of real GPS transmission into simulation trips. Added a separate native QA build/package.
- Removed repeated student ETA/route/progress queries and per-bus fleet queries. Regression tests enforce student snapshot ≤8 SELECTs and fleet ≤6 SELECTs with constant growth behavior as six tracked buses are added.
- Added a scoped database grant audit/revocation command. Applied it to the connected Supabase project: all 22 Django tables were checked; unnecessary PUBLIC/anon/authenticated table and sequence grants were revoked. Existing RLS stayed enabled and Supabase auth/storage tables were untouched.
- Added enumeration/cross-role, throttle, logging, grant and query-budget regression tests, a production smoke tool, configured-secret comparison and emulator integration harness.
- Added current architecture, schema, API, database, Android, route, testing, deployment, recovery and demonstration guides.

## Executed checks

| Check | Observed result |
| --- | --- |
| Python syntax compilation | Passed for backend application/config/tool modules |
| Django system check | No issues |
| Supabase migration drift | No model changes; no pending migrations |
| PostgreSQL backend/API tests | **142 passed**, final full suite after throttle adjustment |
| Supabase application grants | 22 tables; no PUBLIC/anon/authenticated table privileges remain |
| Source secret comparison | 198 source/document files checked; no configured installation secret found; not a general scanner |
| Production profile/static smoke | Passed: forced DEBUG/replay off, HTTPS redirect, no-store, CSP, hashed WhiteNoise asset |
| Invalid production config | Weak secret, wildcard host, HTTP CORS and plaintext DB configuration all rejected |
| Admin Chromium smoke | Login, bus create, dynamic pickup, assignment, Leaflet/fleet refresh, mobile nav; no JS errors |
| Student Chromium smoke | 21 synthetic ordered stops, marker polling, stale/missing/completed states, clock aging, API/offline recovery, reassignment/revocation, missing Leaflet, expiry, mobile layout |
| GPS→browser integration | Real local HTTP login/start/GPS→PostgreSQL→student polling/admin; decreasing ETA, next stop, stable maps and completion passed with synthetic fixtures |
| Android Gradle builds | Debug, unsigned release, integration and instrumentation APK builds passed |
| Android JVM tests | **6 passed**, MockWebServer and tracking policy tests |
| Android lint | No issues found |
| Android instrumentation | **5 passed** on dedicated CampusDriver Android 17 emulator; no personal phone targeted |
| Native foreground-service end-to-end | **Passed**: native login, denied precise location/notifications, disabled GPS prevents trip start, foreground uploads, student/admin updates, decreasing pickup distance, ETA/next stop, force-stop/reopen/explicit resume, completed trip and stopped service; emulator/local DB only |

Native QA injected synthetic fixes through the Android emulator into the actual foreground service. ETA is asserted available and remaining pickup distance decreases. ETA seconds are not required to decrease when measured speed replaces an initial fallback; the separate controlled-speed HTTP/browser integration verifies decreasing ETA. The QA harness was corrected for this distinction and Android system settings/task navigation before the final passing run.

Backend coverage includes admin CRUD/protections, uniqueness/FKs/active assignments, invalid pickup membership, idempotent route imports, all role boundaries and object enumeration, trip repeated start/end, duplicate/out-of-order GPS, accuracy/range/timestamp/jump rejection, rollback, no-location/stale/completed states, GIS direction/geometry/off-route/progress and ETA stationary/passed-stop/fallback cases. Query budgets measure SQL count, not a production load/latency benchmark.

Browser screenshots were regenerated and mobile admin/student images visually reviewed. Test maps may stub tile requests; this is not a public OSM availability test.

## Acceptance items and limitations

1. **Real R001 data is missing.** Read-only Supabase inspection found no R001, zero associated stops/geometry and no active trips. The authoritative CSV was not supplied in the checkout. Synthetic 21-stop QA fixtures never went into Supabase. Import/review the real data before presenting R001 as available.
2. **Restricted runtime role remains an operator step.** The current managed connection is not superuser but has BYPASSRLS. Browser grants were removed, but a separate non-owner/NOBYPASSRLS server role and scoped RLS policies must be provisioned and verified before deployment. Instructions are in supabase-setup.md; no managed postgres role was altered.
3. **No physical GPS acceptance.** Build/unit/instrumentation and emulator-injected fixes cannot establish outdoor reception, screen-lock delivery, OEM power restrictions or real travel. A connected personal device was not targeted.
4. **No public deployment/signing/restore claim.** Actual HTTPS host/certificate, release signing, production proxy validation and isolated backup-restore rehearsal remain deployment tasks. Release URL defaults to example.invalid until configured.
5. **External services.** Public OSM/OSRM availability and usage limits remain external dependencies. Approximate stop connections are labelled and cannot support road-distance ETA. ETA has no live traffic feed and is an estimate, with explicit unavailable reasons.
6. **Single-host throttling.** File-cache counters are approximate under concurrency; proxy-level login/request limits are needed. Behind a proxy the direct IP budget may apply collectively unless trusted client-address handling is designed at that proxy. No untrusted forwarded-IP headers are accepted by Django's login gate.
7. **Production deployment warnings.** HSTS subdomain/preload warnings W005/W021 are intentionally visible until domain readiness is verified; they are not silently suppressed. Other production warnings/errors fail the smoke check.
8. **Pinned build maintenance.** Gradle reports deprecated plugin features for future Gradle 9 compatibility. Pinned Gradle 8.13 builds pass; upgrade only with a verified AGP/toolchain combination.

Software verification is substantial, but full production/data/device acceptance is **pending** the above concrete items. Do not treat synthetic test success as evidence that the college's live route and physical GPS demonstration have run.
