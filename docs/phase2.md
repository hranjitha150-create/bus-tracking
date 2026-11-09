# College admin portal — Phase 2

Start the existing Django app with `python backend/manage.py runserver`, then sign in at `/login/` as an ADMIN. The original `/dashboard/admin/` URL now serves the full dashboard. Students and drivers retain their Phase 1 redirects and are forbidden from admin screens and APIs. This phase adds no database models or schema migrations; the Supabase PostgreSQL architecture and existing data remain intact.

## Portal workflow

1. **Buses:** create, search, filter, inspect, edit and deactivate at `/portal/buses/`. Capacity must be positive and cannot fall below the active student count. Identifiers remain unique. No hard-delete operation is exposed.
2. **Routes & stops:** add routes at `/portal/routes/`, using a stable unique route code. The route detail page lists ordered stops, source metadata and coordinates. Add/edit stops, insert at a position, remove unused stops, or update all order numbers as a consecutive sequence. Shared stop edits apply to every route using that stop. Optional GeoJSON geometry is validated; otherwise a dashed line shows stop sequence only.
3. **Drivers:** register a driver and login account at `/portal/drivers/`. Password validation uses Django's configured validators. Editing supports password changes, phone/license updates and activation status. Password changes and account deactivation revoke bearer tokens.
4. **Driver and route assignment:** use `/portal/assignments/driver/add/`. The selected driver, bus and route must be active. An already assigned driver cannot take another bus until their previous assignment ends. Selecting a new driver or route for the same bus replaces the previous assignment while retaining history. Every current student pickup must remain on the new route.
5. **Students:** register students and login accounts at `/portal/students/`. Assign a bus at `/portal/assignments/student/add/`; the pickup dropdown loads only stops on that bus's current active route. Server validation repeats these checks even if a request is forged. Changing a student assignment retains history and creates exactly one active assignment. Bus capacity and active student status are checked.
6. **Assignments:** `/portal/assignments/` provides searchable driver/route and student histories, independent pagination and confirmation pages to end assignments. A driver assignment cannot end while active student pickups depend on it; replace the driver on that bus first, or end the student assignments.
7. **Fleet map:** `/portal/map/` lists all registered vehicles, their active status, route, driver, trip status and recorded/received timestamps. Select a route overlay. Refresh manually or allow the 30-second refresh. No sample coordinates are seeded into the application.

## Deactivation and trip protection

All HTML and API mutations share `admin_portal/services.py`. PostgreSQL transaction advisory locking serializes portal changes; bus row locks coordinate with Phase 1 trip start/complete. Database partial unique constraints remain the final protection against conflicting active assignments/trips. Direct raw SQL is outside these service-level guarantees.

- Deactivating a bus is blocked during an ACTIVE trip. Otherwise it ends its active student/driver assignments and cancels SCHEDULED trips. Reactivation does not restore assignments.
- Driver deactivation is blocked during an ACTIVE trip and while active student assignments depend on that driver's bus route. Replace the driver first. Otherwise it ends the driver's assignments and cancels SCHEDULED trips.
- Student deactivation ends that student's active assignment and revokes their bearer tokens.
- Route deactivation is blocked while driver/bus assignments use it. Route edits, stop edits, reorder/removal and CSV replacement are blocked during ACTIVE trips. Removing a pickup stop or replacing stops cannot orphan active student pickups.
- Replacing a driver/bus/route assignment cancels obsolete SCHEDULED trips on the bus; historical completed trips and all former assignments are retained.

## Dashboard and GPS semantics

Statistics query actual Bus, Driver, Student, Route and Trip records. Recent activity combines stored assignment timestamps with actual trip start/end events; it is an activity feed, not a complete audit log. There are no fabricated activity entries or hardcoded fleet totals.

GPS statuses are `live`, `stale`, `unavailable`, `not_started` and `inactive`. A position is live only when it belongs to the current ACTIVE trip and both its device `recorded_at` and server `received_at` are within 120 seconds and not in the future. An active trip without a matching location is unavailable. Previous-trip locations may be displayed as historical positions but never become a live position for a new trip. Coordinates remain null for buses that have no stored sample. Dashboard stale alerts count current-trip samples older than the freshness window. No GPS ingestion or Android functionality was added.

Bootstrap 5.3.8 and Leaflet 1.9.4 load from pinned CDNs with integrity checks. OpenStreetMap tiles require internet access. Library/tile failures have visible feedback; record tables remain available. Map text uses DOM text nodes and Django's `json_script` to avoid treating stored names as executable markup. Standard OpenStreetMap attribution is retained. Review the [OpenStreetMap tile usage policy](https://operations.osmfoundation.org/policies/tiles/) for production traffic.

## Import R001

Use **Routes & stops → Import R001 CSV** (`/portal/routes/import/`) or the existing command:

```powershell
.\.venv\Scripts\python.exe backend\manage.py import_bus_route backend/data/bus_route_stops.csv
```

The command, upload page and API share the same parser and transaction-protected persistence. Required logical columns are `name`, `latitude`, `longitude` and `stop_order`; aliases are documented in the root README. The source must contain exactly 21 stops ordered 1–21, beginning with NIE Golden Jubilee and ending at North Campus Last Stop. Optional original columns are preserved as metadata. Uploads are limited to 2 MB.

The stable key is `route_code=R001`. Repeated imports reuse identical stops without duplicating the route. Changed names/coordinates create a new stop record while keeping historical references. Re-import is rejected if current pickups would be orphaned or an ACTIVE trip uses R001. Source observations and uncertain names remain provisional. No supplied CSV was present during Phase 2, so the real route import remains pending; use the mentor's original file, not the synthetic test fixture.

## Admin REST API

All endpoints below require an authenticated ADMIN, using a CSRF-protected session or the existing HTTPS bearer token. Anonymous requests return 401; authenticated non-admins return 403. Models are never physically deleted through these endpoints.

| Endpoint | Methods | Purpose |
| --- | --- | --- |
| `/api/admin/buses/` | GET, POST | Search/paginate or create buses |
| `/api/admin/buses/{id}/` | GET, PATCH | Inspect/update/deactivate a bus |
| `/api/admin/students/` | GET, POST | Search/paginate or register student + user |
| `/api/admin/students/{id}/` | GET, PATCH | Update student/account or deactivate |
| `/api/admin/drivers/` | GET, POST | Search/paginate or register driver + user |
| `/api/admin/drivers/{id}/` | GET, PATCH | Update driver/account or deactivate |
| `/api/admin/routes/` | GET, POST | Search/paginate or create routes |
| `/api/admin/routes/{id}/` | GET, PATCH | Inspect ordered stops or update route |
| `/api/admin/routes/import/` | POST | Multipart `file` plus optional `direction` |
| `/api/admin/assignments/` | POST | Create/replace validated student or driver assignment |
| `/api/admin/assignments/{kind}/{id}/end/` | POST | End an assignment with relationship checks |
| `/api/admin/pickup-stops/?bus={id}` | GET | Ordered available pickup choices for the bus |
| `/api/admin/live-buses/` | GET | Actual fleet GPS/status snapshot, including buses without locations |

Collection APIs accept `?search=...&page=...`; page size is 50. Standard list responses contain `count`, `next`, `previous` and `results`. Successful detail/create responses contain the public record fields and ID. Passwords and token digests are never returned. Admin errors consistently contain `detail` and `errors` (field errors when available). Phase 1 API response formats are unchanged.

Student creation uses `full_name`, `email`, `password`, `phone`, `enrollment_number`, `department`, `semester` and optional `is_active`. Driver creation uses the same account fields with `license_number`. Password is required on creation and optional on PATCH. Roles are set by the server and cannot be chosen through these serializers.

Student assignment body:

```json
{"kind": "student", "student": 12, "bus": 3, "pickup_stop": 7}
```

Driver and route assignment body:

```json
{"kind": "driver", "driver": 4, "bus": 3, "route": 2}
```

IDs above illustrate the request shape only; use actual record IDs from your database. Repeating an identical assignment returns the current assignment without adding a duplicate history entry.

## Validation commands

Use a dedicated local PostgreSQL database for tests, never a production Supabase URL:

```powershell
.\.venv\Scripts\python.exe backend\manage.py test accounts routes tracking admin_portal --settings=config.test_settings --noinput
.\.venv\Scripts\python.exe backend\manage.py check
.\.venv\Scripts\python.exe backend\manage.py makemigrations --check --dry-run
node --check backend/static/js/admin.js
node --check backend/static/js/fleet-map.js
```

Optional `backend/admin_portal/browser_smoke.py` requires Playwright and an installed Chromium browser. It creates/drops a dedicated test database on the isolated local PostgreSQL cluster (`127.0.0.1:55432`), starts/stops its own preview server, exercises browser workflows and writes synthetic-fixture screenshots under `docs/screenshots/`. It refuses other database hosts/ports. It is not a production data seed or a runtime dependency.
