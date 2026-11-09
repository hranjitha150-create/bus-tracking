# Database schema

PostgreSQL is required for partial unique constraints and row/advisory locks. Django migrations are authoritative; do not rebuild tables through the Supabase editor.

| Model | Relationships and purpose |
| --- | --- |
| CustomUser | Unique email, hashed password, role and active state |
| AccessToken | User FK, unique token digest and expiry; no raw token |
| Student | One-to-one user, unique enrollment, department, semester 1–12 |
| Driver | One-to-one user, unique licence, phone |
| Bus | Unique bus number/registration, positive capacity, active state |
| Route | Unique route_code, endpoints, direction, optional GeoJSON LineString |
| BusStop | Name, decimal coordinates, address and original CSV metadata |
| RouteStop | Route FK, protected stop FK; unique route/order and route/stop |
| DriverAssignment | Protected driver/bus/route FKs; unique active driver and active bus |
| StudentBusAssignment | Protected student/bus/pickup FKs; unique active student |
| Trip | Protected bus/driver/route FKs, type/status, timestamps, simulation flag |
| BusLocation | One latest row per bus; trip FK and GPS sample |
| LocationHistory | Accepted historical GPS samples and bus/trip FKs |
| TripProgress | One-to-one trip, geometry signature, metre progress, speed, matching state |

Trips enforce unique active bus/driver, valid status/type and ordered/required timestamps. Database checks validate coordinate ranges, finite nonnegative speed/accuracy/progress and positive capacity/order. Stops have unique (name, latitude, longitude).

Profile roles, pickup-route membership, location bus-trip matching and geometry shape require model/service/API validation. Use provided services; raw SQL and direct `.save()` can bypass application validation.

Indexes cover trip (bus,status)/(driver,status), assignment (bus,is_active), and history (trip,recorded_at)/(bus,recorded_at). Latest reads do not scan history. Regression tests bound student snapshots at eight SELECTs and keep fleet SELECT count constant as tracked buses increase.

History defaults to 30-day retention. Schedule `prune_location_history` daily; it deletes expired history in batches and preserves latest positions/progress. `LOCATION_HISTORY_MIN_INTERVAL_SECONDS` reduces history density without reducing latest updates.

Each app's `migrations/` is the schema history. Use `makemigrations --check --dry-run` and `migrate --check`. Phase 6 introduces no model migration. Explicit access-grant hardening is independent of schema migrations.
