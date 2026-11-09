# Testing guide

Tests use actual PostgreSQL semantics, not SQLite. `config.test_settings` defaults to local `127.0.0.1:55432/college_bus_test` with SSL disabled only for that loopback test server. Override `TEST_DATABASE_URL` privately for a dedicated disposable test database; the QA role needs CREATEDB and the grant-audit test needs CREATEROLE (its temporary NOLOGIN role is rolled back). Never use these privileged QA credentials in production. Browser/native scripts create/drop the same test database, so run them sequentially.

From repository root:

```powershell
.\.venv\Scripts\python.exe backend\manage.py check
.\.venv\Scripts\python.exe backend\manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe backend\manage.py migrate --check
.\.venv\Scripts\python.exe backend\manage.py audit_database_access
.\.venv\Scripts\python.exe backend\manage.py test accounts admin_portal assignments buses drivers eta routes students tracking --settings=config.test_settings
.\.venv\Scripts\python.exe backend\tools\production_check.py
```

Production smoke uses generated dummy credentials and no database connection. It enforces production flags, checks deployment warnings, collects assets and requests the hashed JavaScript through WhiteNoise over Django's test client. It does not prove an actual TLS proxy/certificate setup.

Browser scripts require Playwright/Chromium on the QA machine (`pip install playwright`, `python -m playwright install chromium`, in the virtualenv). They start isolated local Django servers and use synthetic fixtures:

```powershell
.\.venv\Scripts\python.exe backend\admin_portal\browser_smoke.py
.\.venv\Scripts\python.exe backend\students\browser_smoke.py
.\.venv\Scripts\python.exe backend\eta\browser_smoke.py
```

They exercise desktop/mobile portal navigation, forms, 21 ordered test stops, marker updates, offline/stale/error states and HTTP GPS→PostgreSQL→student/admin progress/ETA/completion. Screenshots are under docs/screenshots. Automated tests can stub remote tile requests for deterministic UI checks; passing UI tests does not prove public tile-provider availability.

Android, from `android-driver/`:

```powershell
.\gradlew.bat assembleDebug assembleRelease assembleIntegration testDebugUnitTest lintDebug assembleDebugAndroidTest
# Select ONLY a disposable emulator; never run indiscriminately on attached phones.
$env:ANDROID_SERIAL = 'emulator-5556'
.\gradlew.bat connectedDebugAndroidTest '-Pandroid.injected.device.serial=emulator-5556'
```

Build reports are in `android-driver/app/build/reports/`. Release APK is unsigned until you configure your own signing. Unit tests use MockWebServer and cover bearer headers, paths, parsing, errors, sample validation, latest-only retry and backoff. Instrumented tests cover Keystore, login fields, permissions/service declarations and mocked Android Location extraction.

Optional native end-to-end QA requires the dedicated `CampusDriver` AVD online on emulator-5556, API supporting notifications, SDK path in ANDROID_HOME and local test PostgreSQL on 55432. Build `assembleIntegration` first. From repository root run:

```powershell
.\.venv\Scripts\python.exe -u backend\tools\android_integration.py
```

This installs/clears only `com.campustransit.driver.integration`, starts port8005, supplies synthetic emulator GPS and drops its temporary database on exit. It refuses an arbitrary device/AVD or nonlocal database. Permission dialogs can vary by Android system image. It does not prove real-device GPS and does not mutate Supabase.

Physical acceptance checklist: real outdoor fix, accuracy and timestamps; denied/approximate permissions; disabled notification/channel; GPS off mid-trip; no internet and reconnect; screen lock/OEM battery behavior; app force-stop/reopen/explicit resume; expired token/revoked assignment; online/offline End Trip; no coordinates after completion. Record device/OS, server version and observed timestamps. These remain manual unless an actual device session is performed.

Executed counts/results are maintained in [Phase 6 audit](phase6-audit.md); historical phase reports describe earlier runs only.
