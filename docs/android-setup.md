# Android setup

The app uses Java/XML, AndroidX, Retrofit, Android location APIs and a foreground service. Minimum API 26, compile/target API 36, JDK 17+, Gradle 8.13 and AGP 8.13.2 are pinned. No Kotlin/Flutter/React Native implementation exists.

1. Open `android-driver/` in Android Studio.
2. Install SDK Platform 36 and configure JDK 17 (or compatible 21). Let Gradle sync; keep generated local.properties private.
3. Configure Django development hosts to include `localhost,127.0.0.1,10.0.2.2`, set DEBUG=True locally and start Django on port 8000.
4. Create a DRIVER account and active bus/route assignment in the admin portal. There are no built-in credentials.
5. Run the debug variant on an emulator. Its default base URL is `http://10.0.2.2:8000/`. Log in with the driver's Django email/password.
6. Allow precise foreground location and notifications. Enable device GPS, then Start Trip. A confirmed server start is required before sharing.
7. End Trip and confirm COMPLETED. Stop sharing alone stops GPS but does not complete the server trip. After force-stop/reboot, reopen and explicitly Resume sharing.

From `android-driver/` on Windows:

```powershell
$env:JAVA_HOME = 'C:\path\to\jdk-17'
$env:ANDROID_HOME = 'C:\path\to\Android\Sdk'
.\gradlew.bat assembleDebug testDebugUnitTest lintDebug
```

Install `app/build/outputs/apk/debug/app-debug.apk`. On a USB phone, select that device explicitly and use `adb -s DEVICE_SERIAL reverse tcp:8000 tcp:8000`, then build with `-PDRIVER_DEBUG_API_URL=http://127.0.0.1:8000/`. Local HTTP is limited to emulator/loopback addresses. Remote/Wi-Fi connections require HTTPS.

Release build:

```powershell
.\gradlew.bat assembleRelease -PDRIVER_API_URL=https://YOUR_HTTPS_HOST/
```

Use an actual trusted HTTPS host and retain the trailing slash. The default release URL is intentionally unusable (`https://example.invalid/`). Configure a private release signing key through Android Studio's Generate Signed Bundle/APK workflow before distribution; unsigned build success is not a signed release. Store signing credentials outside the repository and back up the key securely. Configure GPS target interval using `-PGPS_INTERVAL_SECONDS=10` (5–300); Android does not guarantee exact intervals.

No background-location permission or boot receiver is requested. Foreground tracking has a visible notification and checks notification/channel availability. Screen lock/OEM battery behavior requires physical testing. Tokens are Keystore-encrypted; passwords are never saved. Latest-only retry drops stale fixes instead of replaying a backlog.

The `integration` build is QA-only, uses a separate package suffix `.integration` and fixed local port 8005. Build with `assembleIntegration`; `backend/tools/android_integration.py` uses only the disposable CampusDriver emulator on port 5556 and local PostgreSQL. It never installs on an arbitrary attached phone. See [testing](testing-guide.md) and [detailed Android lifecycle notes](../android-driver/README.md).
