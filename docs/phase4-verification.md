# Phase 4 verification — 2026-11-06

Phase 5 adds an additive progress/simulation migration and the ETA engine. The no-migration and ETA-deferred notes below describe Phase 4's original verified state; see [Phase 5 verification](phase5-verification.md) for current deployment status.

## Executed successfully

- **112 Django tests passed** on the isolated PostgreSQL 17 test database: all 91 previous tests plus 21 driver API/concurrency tests. Normal Supabase records were not seeded or modified.
- **Gradle build passed:** `assembleDebug assembleRelease testDebugUnitTest lintDebug connectedDebugAndroidTest --no-daemon --console=plain`.
- **6 JVM tests passed**, no skips/failures: MockWebServer login/bearer/API contracts, redirect/error handling, GPS validation, latest-only pending queue and bounded retry.
- **5 instrumented tests passed**, no skips/failures, on a separate disposable headless Android emulator (API 37 / Android 17 system image available on this machine). Tests cover encrypted Keystore storage/clear, login empty-field validation, no automatic service startup, mocked Android Location extraction and manifest service/privacy permissions. The application itself targets stable API 36 with minimum API 26.
- **Android lint:** no issues found on the final source. The original resource API-compatibility issues and localization/accessibility warnings were corrected.
- **Django system checks:** no issues. Python compilation succeeded. `makemigrations --check --dry-run` reported no changes.
- **Supabase:** read-only `migrate --check` succeeded. Phase 4 uses the existing tables and requires no new schema migrations.
- The native login screen was opened on the disposable emulator and visually reviewed: [login screenshot](screenshots/driver-login.png).

Build environment: JDK 17, Gradle 8.13, AGP 8.13.2, compile/target SDK 36. The Gradle wrapper files are included and its distribution SHA-256 is pinned. Both debug APK and unsigned release APK were produced:

- `android-driver/app/build/outputs/apk/debug/app-debug.apk`
- `android-driver/app/build/outputs/apk/release/app-release-unsigned.apk`

The first emulator test attempt encountered an offline/ADB authorization mismatch; after resolving the test daemon's user context, the final instrumented run completed successfully. No personal emulator data was used; a new AVD was created under the ignored `android-driver/.emulator-test/` directory.

## Backend test coverage

Driver API tests exercise assignment-derived access, correct scheduled-trip activation and new trip creation, server-derived direction/type, idempotent starts, conflicting-trip protection, two concurrent starts returning one trip, real bearer login/logout/expiry, role denial, other-driver trip denial, assignment revocation, numeric/time GPS validation, coordinate precision, latest-location/history atomicity, safe duplicate samples, different samples sharing a timestamp, older queued sample rejection, student consumption of published locations, and idempotent completion with rejection of further uploads.

Location writes lock the bus, re-read current authorization and lock the trip. All supported driver writes on a bus serialize through this lock. LocationHistory and latest BusLocation update in the same transaction. The Android client does not choose bus/route/driver IDs for trip creation.

## Verification limits and setup still required

- **No physical-device GPS testing was performed.** The emulator tests use explicitly constructed mock Location objects. Real satellite acquisition, physical movement, OEM battery management, screen locking/background delivery and recovery must be tested on an actual driver phone using the checklist in [Android setup instructions](../android-driver/README.md).
- Tests validate Django APIs and Retrofit through their respective integration tests; no actual college driver's phone/session was used against the production Supabase deployment.
- Configure the actual Django HTTPS URL before release. The checked-in debug URL is the emulator host alias; the release URL is intentionally `https://example.invalid/`. Release signing is deployment-specific and remains to be configured.
- Create a real DRIVER user and active bus/route assignment in the admin portal. Supply/import the mentor's actual R001 CSV to populate its real stops; no coordinates or accounts were fabricated in Supabase.
- No Phase 5 ETA algorithm is included. Existing student ETA remains explicitly unavailable until that phase.

The temporary emulator and isolated PostgreSQL server are stopped after verification. The installable debug APK, test reports and source remain in the workspace.
