# Campus Transit — Java Android driver app

Native Java/XML Android Studio project, audited through Phase 6. It uses Django bearer login and assignment-derived driver APIs. Features include login, dashboard, assigned bus, ordered route stops, trip start/end, a visible foreground GPS service, encrypted session storage and bounded network retry. Current integration results and acceptance limits are in [Phase 6 audit](../docs/phase6-audit.md).

## Build and connect

Open `android-driver/` in Android Studio. Select **JDK 17 or 21**, install **Android SDK Platform 36**, and let Gradle sync. The project pins AGP 8.13.2 and Gradle 8.13 with the official distribution checksum. It targets API 36 and supports API 26+. Android Studio generates the ignored `local.properties` file for your SDK location.

From this directory on Windows:

```powershell
# Use your own installed paths if these environment variables are not configured.
$env:JAVA_HOME = 'C:\path\to\jdk-17'
$env:ANDROID_HOME = 'C:\path\to\Android\Sdk'
.\gradlew.bat assembleDebug testDebugUnitTest lintDebug
```

On macOS/Linux run `chmod +x gradlew` then `./gradlew ...`. The installable debug APK is `app/build/outputs/apk/debug/app-debug.apk`. Release builds produce `app/build/outputs/apk/release/app-release-unsigned.apk`; configure your own release signing before distribution.

The checked-in `gradle.properties` configures both debug and release builds to use
`https://bus-tracking-peach-gamma.vercel.app/`. Physical phones can reach this
backend over Wi-Fi or mobile data without a USB connection or local Django server.
Rebuild and reinstall the APK after changing the URL; it is embedded at build time.

For local emulator development, override the debug URL when building:

```powershell
.\gradlew.bat assembleDebug -PDRIVER_DEBUG_API_URL=http://10.0.2.2:8000/
```

`10.0.2.2` is the emulator's address for your host computer. Add `10.0.2.2` to development `DJANGO_ALLOWED_HOSTS`, use `DJANGO_DEBUG=True` and start the backend from the repository root:

```powershell
.\.venv\Scripts\python.exe backend\manage.py runserver
```

Sign in using a **DRIVER account provisioned in the admin portal**, with an active bus/route assignment. There is no seeded account or default password. Student/admin credentials cannot use the driver APIs. The app connects to Django, not directly to Supabase; it needs no database credentials or Google location API key.

For a USB-connected physical phone and local development:

```powershell
adb reverse tcp:8000 tcp:8000
.\gradlew.bat assembleDebug -PDRIVER_DEBUG_API_URL=http://127.0.0.1:8000/
adb install -r app\build\outputs\apk\debug\app-debug.apk
```

Debug HTTP is allowed only for `10.0.2.2`, `127.0.0.1` and `localhost`. Use an HTTPS deployment for remote/Wi-Fi testing. Production disallows cleartext HTTP and does not follow redirects. Configure the release URL with a trailing slash:

```powershell
.\gradlew.bat assembleRelease -PDRIVER_API_URL=https://transport.your-college.example/
```

The release URL is configured in `gradle.properties`; `https://example.invalid/` is only the fallback if that property is removed. No TLS verification bypass is included. Native bearer requests do not require browser CORS/CSRF origin settings.

## Screens and lifecycle

- **Login:** college email/password; password input is cleared on submission and never persisted. Bearer token/expiry are AES-256-GCM encrypted with a Keystore key. Backup and device transfer of session data are disabled.
- **Dashboard:** authenticated driver's name, assigned bus, route start/destination/direction, current/latest trip and GPS status. On opening the signed-in dashboard, the app requests precise foreground location permission and prompts to enable phone GPS if disabled. Denial leaves the app usable; Start trip can request permission again. Startup does not access GPS coordinates, start a trip or transmit location. Missing assignment gives a clear message.
- **Assigned Bus:** registration, capacity, description and route. **Route Details:** actual stored stops in order, coordinates and endpoint labels; missing stops display an empty state.
- **Start trip:** obtain precise foreground location and notification permissions, check GPS is enabled, then create/activate the assignment-derived trip on Django. Only a confirmed server trip can start local GPS sharing. The service verifies the active trip again before requesting location.
- **Active Trip:** current trip, upload status, Stop sharing only, Resume sharing and End trip. The persistent notification also offers Stop sharing.
- **End trip:** stops local GPS immediately, then requests server completion. On failure, sharing stays off and completion remains unconfirmed; refresh/retry after reconnecting. Successful/idempotent completion displays COMPLETED.
- **Sign out:** stops sharing, deletes the local encrypted token and attempts server revocation. Offline local sign-out still works, but unreachable-server revocation cannot be confirmed; the old token remains subject to its existing 12-hour expiry.

Foreground sharing continues during normal background operation and screen locking, subject to Android/OEM power management. No background-location permission or boot receiver is requested. Service launch occurs only from a visible activity. After process death, force-stop or reboot, sharing does **not** restart silently: reopen, refresh the server state and explicitly tap **Resume location sharing**. A start response received after the activity leaves the foreground does not start GPS automatically.

## GPS configuration and delivery

`LocationManager.GPS_PROVIDER` supplies real coordinates, speed in metres/second, accuracy in metres and device UTC timestamps. A fix without a reported speed uses zero; coordinates always come from Android. Missing accuracy, non-finite/out-of-range values, stale elapsed-realtime ages and invalid clock values are rejected. No application test/mock coordinate source is used by the production service.

The default target interval is **10 seconds**. Configure it when building:

```powershell
.\gradlew.bat assembleDebug -PGPS_INTERVAL_SECONDS=15
```

Valid intervals are 5–300 seconds. Actual delivery is not guaranteed due to satellite availability, permissions, Android power management and OEM behavior.

Only the newest pending fix is retained, in memory. No disk backlog is replayed. Acknowledging an in-flight old request cannot clear a newer pending sample. Network failure uses 2/4/8/16/30-second backoff with at most five attempts per cycle, then a 60-second cooldown. Reconnection retries the newest valid fix. Samples older than 120 seconds are discarded. Authentication, authorization or closed-trip failures stop sharing; invalid/out-of-order individual samples are dropped. Server checks independently prevent older fixes from overwriting newer positions.

## Backend API contract

| Endpoint | Behavior |
| --- | --- |
| `POST /api/auth/login/` | Existing email/password login; token, expiry and role |
| `POST /api/auth/logout/` | Existing bearer-token revocation |
| `GET /api/driver/assignment/` | Current driver's bus/route, ordered stops, active/latest trip |
| `POST /api/driver/trips/start/` | Start the correct assignment-derived trip; bus/route/driver IDs cannot select another assignment |
| `POST /api/driver/trips/{id}/location/` | Publish GPS for the owned active trip |
| `POST /api/driver/trips/{id}/end/` | Complete the currently assigned owned trip |

Assignment includes `status: assigned|unassigned`, `driver`, `bus`, `route`, `active_trip`, `trip` and an interval recommendation. New trip type follows route direction: TO_COLLEGE → PICKUP, FROM_COLLEGE → DROP. Repeated start while that trip is active reuses its ID. Row locks and existing database partial unique constraints prevent conflicting active trips.

Location requests contain numeric `latitude`, `longitude`, `speed`, `accuracy`, plus a timezone-aware ISO-8601 `recorded_at` string. The timestamp must be within 120 seconds of server time, no more than 30 seconds ahead, and not more than five seconds before trip start. Speed/accuracy must be finite and nonnegative. Coordinates are stored to seven decimal places.

Accepted GPS creates LocationHistory and updates the one latest BusLocation in the same transaction, including a server received timestamp. Responses: **201** accepted; **200** duplicate; **400** invalid/old sample; **401** expired session; **403** revoked assignment; **404** missing/someone else's trip; **409** closed/conflicting trip or older sample (`code: out_of_order`). An identical trip/timestamp/payload retry neither duplicates history nor refreshes its received timestamp. Reusing that timestamp with different values is rejected.

All driver mutations require current active driver/bus/route relationships. Student and admin roles cannot publish through driver endpoints. No schema migrations were needed; Phase 1 models and Phase 2/3 APIs are preserved. Supply the mentor's actual R001 CSV through the existing admin importer to display real stops; none are invented by the Android app.

## Tests and physical-device validation

```powershell
.\gradlew.bat testDebugUnitTest lintDebug
.\gradlew.bat connectedDebugAndroidTest
```

JVM tests use MockWebServer for login, bearer headers, assignment/start/GPS/end paths, response parsing, auth errors and redirects. Pure Java tests cover GPS validity, newest-only queue acknowledgements and bounded retry. Instrumented tests exercise Keystore storage, login empty-field validation, private-service/no-background-permission declarations and mocked Android Location extraction.

Reports: `app/build/reports/tests/testDebugUnitTest/index.html`, `app/build/reports/lint-results-debug.html`, and `app/build/reports/androidTests/connected/debug/index.html`. See [Phase 4 verification](../docs/phase4-verification.md) for checks actually executed.

Before deployment, verify on a **physical Android phone**:

1. Correct/incorrect credentials, wrong roles, missing assignments and actual route stops.
2. Denied/approximate-only location, denied notifications and permission removal: no unauthorized GPS transmission; app settings guidance works.
3. GPS disabled and missing fixes: no fabricated location. Enable GPS, start a trip outdoors and confirm actual updates in the admin/student maps.
4. Screen lock and background operation: persistent notification, timestamps, battery behavior and your phone's OEM restrictions.
5. Internet loss/recovery: newest-only retries; student map turns stale rather than retaining false live status.
6. Notification Stop sharing: updates cease while the server trip stays active. App reopening requires explicit Resume sharing.
7. Force-stop/reboot: no silent GPS restart; resume only after opening the app and verifying the active trip.
8. Online and offline End trip: sharing stops locally; server completion is confirmed or clearly unconfirmed. Repeating a completed end does not change the end timestamp.
9. Token expiry, assignment revocation and logout: further uploads stop and the user sees the appropriate recovery state.

Emulator mocks cannot establish real satellite reception, screen-lock delivery or physical-device power behavior. Those checks remain separate from build and API validation.

Implementation references: [Android foreground service restrictions](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start), [LocationManager](https://developer.android.com/reference/android/location/LocationManager), [Keystore](https://developer.android.com/privacy-and-security/keystore), and [AGP 8.13 compatibility](https://developer.android.com/build/releases/agp-8-13-0-release-notes).
