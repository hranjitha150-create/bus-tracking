# College demonstration

Prerequisites: running Django/Supabase connection, created ADMIN account, actual R001 CSV imported and reviewed. To show an available ETA, store validated road geometry first. The real CSV is not in this checkout and R001 was absent at audit time. Use an explicitly separate development database for demonstration identities; do not publish their passwords.

1. Sign in at `/login/` as ADMIN and open the portal dashboard.
2. Open Routes & stops and select R001.
3. Confirm all 21 ordered stops/coordinates, from NIE Golden Jubilee to North Campus Last Stop. Confirm the line is labelled road geometry or approximate correctly.
4. Register `College Bus 01` with a unique actual/demo registration and positive capacity.
5. Create a DRIVER account and assign it to College Bus 01 and R001.
6. Register a demo STUDENT account with a unique enrollment number.
7. Assign that student to College Bus 01 and a pickup stop selected from R001. An unrelated stop must be rejected.
8. Open the Java Android app configured for this Django server and sign in as the assigned driver.
9. Grant precise location/notifications, enable GPS and tap Start Trip. Verify ACTIVE and the visible tracking notification.
10. On a physical device, wait for a real outdoor fix and travel safely along the route. Never drive while operating the phone; have a passenger demonstrate.
11. Confirm Django accepts a sample and the matching bus's recorded/received times change in the admin fleet view. This server uses Supabase when configured with that connection.
12. In a separate browser/mobile session sign in as the demo student.
13. Verify My Bus shows only College Bus 01. Student APIs have no arbitrary bus selector; admin endpoints deny this role.
14. Open Live Tracking and observe the existing bus marker update at the configured poll interval.
15. Show next stop, remaining route distance and pickup ETA when geometry/GPS allow. Missing geometry, stale or off-route GPS should explain why ETA is unavailable.
16. In the admin session monitor active trip, GPS freshness and progress.
17. Tap End Trip in Android and confirm COMPLETED; local sharing stops immediately, server completion must be confirmed.
18. Refresh/wait for student and admin polling. Both show completion and last-known GPS rather than false live transmission; ETA becomes unavailable.

Without a physical device, use [development replay](route-import.md) on a separate DEBUG server with the actual imported stops. Skip Android steps 8–10 and run `replay_bus_route`; the UI must show **SIMULATED**. Replay completes on exit. The native emulator QA is another isolated synthetic path; it verifies Android→local Django/PostgreSQL, not actual Supabase or real R001 geography.

For error demonstrations: disable connectivity to show network feedback; pause sharing >120 seconds to show stale GPS; sign in with an unassigned student to show the empty state. Do not create fake production GPS samples or represent approximate lines as verified driving geometry.
