# Phase 1 verification

Verified on 2026-11-06 with Python 3.11.9, Django 5.2.19 and an isolated local PostgreSQL 17 cluster. This was a PostgreSQL test database, not an SQLite fallback or a live Supabase project.

## Executed checks

- `python backend/manage.py test accounts routes tracking --settings=config.test_settings --noinput`: **31 tests passed**. The suite created and dropped its own test database.
- `python backend/manage.py test accounts.tests.RoleUnitTests routes.tests.CSVValidationTests --settings=config.test_settings`: **9 tests passed without a database** (a subset of the 31 tests).
- `python backend/manage.py check --settings=config.test_settings`: no issues.
- `python backend/manage.py makemigrations --check --dry-run --settings=config.test_settings`: no changes detected.
- `python -m compileall -q backend`: successful.
- `python backend/manage.py migrate --settings=config.test_settings --noinput`: all migrations applied to the isolated validation database.
- `python backend/manage.py migrate tracking 0001 --settings=config.test_settings --noinput` followed by `migrate`: the composite location/trip constraint migration reversed and reapplied successfully.

The test suite covers role choices and permission checks; hashed passwords; login, logout, expiry, disabled accounts and anonymous access; website role redirects and CSRF; student bus scoping; driver ownership and assignment revocation; trip transitions; profile/assignment validation; partial uniqueness and geographic/time checks; matching bus/trip foreign keys; latest-location uniqueness; and CSV validation, exact count, order, metadata, idempotency and rollback.

## Migration files created

Initial migrations for accounts, students, drivers, buses, routes, assignments and tracking, plus `tracking/0002_location_trip_integrity.py`. Django's built-in auth, contenttypes and sessions migrations are used. There is no ETA model yet.

## External configuration still required

1. Supply the real Supabase PostgreSQL direct/session pooler URL and a deployment secret in `backend/.env`; configure hosts, CSRF and CORS origins.
2. Run migrations against that Supabase database and provision real college accounts, profiles, buses and assignments. No migration was run against Supabase in this session.
3. Supply `backend/data/bus_route_stops.csv`. The actual file was unavailable, so only synthetic test fixtures were imported in disposable test databases. No production coordinates or route stops were invented. Confirm its headers and provisional route direction before importing.
4. Configure HTTPS, static serving and a shared throttle cache for production as described in the README. Review Supabase Data API exposure/RLS if application tables are exposed outside Django.

The temporary `.postgres-test/` cluster and `.venv/` dependency environment are ignored by version control. The temporary database server was stopped after validation. No application `.env` containing credentials was created.
