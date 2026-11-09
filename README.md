# College Bus Tracking System

Django/DRF, Supabase PostgreSQL, Bootstrap templates, Leaflet/OpenStreetMap and a native Java/XML Android driver application. Students see only their assigned bus; Django derives it from their authenticated account.

Phase 6 adds security hardening, query optimization, integration checks and deployment documentation. Production acceptance still requires the authoritative R001 CSV, a restricted runtime database role, a configured HTTPS host and physical-device GPS validation. The connected Supabase database had **no R001 route** at this audit. Automated 21-stop fixtures are synthetic and never imported into Supabase.

## Run Django on Windows

From the repository root:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
# First installation only: copy backend/.env.example to backend/.env.
# Keep your existing .env; configure its PostgreSQL URL and secret locally.
.\.venv\Scripts\python.exe backend\manage.py check
.\.venv\Scripts\python.exe backend\manage.py migrate
.\.venv\Scripts\python.exe backend\manage.py createsuperuser
.\.venv\Scripts\python.exe backend\manage.py runserver
```

Generate a secret with `.\.venv\Scripts\python.exe -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`. Use `DJANGO_DEBUG=True` only locally. Open `http://127.0.0.1:8000/login/`. Reuse your existing admin account when one has already been created.

## Project structure

```text
backend/
  accounts/          authentication, roles and hashed bearer tokens
  admin_portal/      management pages/APIs and assignment services
  students/          assigned-bus-only portal and APIs
  drivers/           assignment-derived trip/GPS APIs
  buses/ routes/ assignments/ tracking/ eta/
  config/            development, isolated test and production settings
  templates/ static/ tools/
android-driver/
  app/src/main/java/com/campustransit/driver/
    activities/ api/ models/ services/ utils/
  app/src/main/res/   XML layouts and resources
  app/src/test/ app/src/androidTest/
docs/                setup, contracts, verification and demonstration
```

## Features

- Admin dashboard and bus, driver, student, route/stop and assignment management.
- Idempotent R001 CSV importer validating 21 ordered stops and actual coordinates.
- Responsive student overview, bus, route, pickup, profile and polling map.
- Android login, dashboard, route, trip start/end, encrypted tokens and foreground GPS.
- Authorized GPS ingestion, history, freshness, jump checks and newest-only updates.
- Directional stored road geometry, route progress and pickup ETA with unavailable states.
- Production settings, hashed static files, login throttling and secret-redacted logs.
- PostgreSQL, browser, Android unit/instrumentation and isolated integration checks.

No Google Maps key or Supabase client key is required. Public OSM tiles have usage limits; attribution, origin referrer and tile-error feedback are included. Road routing is optional; stop connections are labelled approximate and ETA requires valid stored geometry.

| Topic | Guide |
| --- | --- |
| Architecture and trust boundaries | [Architecture](docs/architecture.md) |
| Tables and constraints | [Database schema](docs/database-schema.md) |
| Endpoints and units | [API documentation](docs/api-documentation.md) |
| PostgreSQL and restricted access | [Supabase setup](docs/supabase-setup.md) |
| Android Studio and builds | [Android setup](docs/android-setup.md) |
| Actual R001 data and geometry | [Route import](docs/route-import.md) |
| Repeatable checks | [Testing guide](docs/testing-guide.md) |
| HTTPS and recovery | [Deployment guide](docs/deployment-guide.md) |
| College demonstration | [Demonstration](docs/demonstration.md) |
| Executed results and limitations | [Phase 6 audit](docs/phase6-audit.md) |
"# bus-tracking" 
