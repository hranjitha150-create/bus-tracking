# Routes, stops and CSV imports

## Admin workflow

Routes support multiple ordered stops with verified latitude/longitude. No schema
migration is needed: the existing Route, BusStop and RouteStop tables store them.

1. For manual entry, create a route under **Routes & stops**, open it and choose
   **Add multiple stops**. Add rows in travel order and choose **Save all stops**.
   Batches are appended after existing stops; use the existing reorder controls
   to insert/rearrange them. A batch supports 200 rows and a route up to 500 stops.
2. Alternatively choose **Import route CSV** from the routes list. Enter a route
   code or let the file's `route_id` / `route_code` identify it. An explicitly
   entered code overrides the CSV source ID: for example, source R001 can be
   copied to R003 while retaining R001 in the original metadata. Enter an optional
   route name and select direction. A file contains one route and 2–500 stops.
3. Required columns: `stop_order` (also `stop_order_shared`, `sequence`, `order`),
   `name` (also `stop_name`), `latitude` (also `lat`), and `longitude` (also `lon`,
   `lng`). Order must run consecutively from 1. Extra columns are retained in the
   database as original metadata. The supplied 21-stop CSV is accepted unchanged.
4. **Import CSV** on a route's detail page uses that route as the destination, even when the CSV source ID differs. Original source IDs are preserved in metadata. Imports replace
   its stops atomically, derive start/destination from the first/last stop, and clear
   old road geometry. Reimporting identical data does not duplicate stops. Active
   trips and changes that would orphan student pickup assignments block import.
5. Assign a **driver + bus + route** in Assignments. Then assign each **student +
   bus + pickup stop**. The selected bus determines the student's route; the stop
   must belong to it. Students see only their assigned bus's route and GPS.
6. The driver signs into the Android app, grants precise location, enables GPS,
   and taps **Start trip**. Actual phone fixes update the existing driver GPS API,
   admin fleet map and assigned student's tracking map. Merely creating a route
   does not start GPS or fabricate a moving bus.

CSV upload is limited to 2 MB. Coordinates are validated before any writes; invalid
files and conflicts roll back the whole import. No live routes are imported by
the development/test workflow.

## Legacy R001 command-line profile

The command-line `import_bus_route` command retains its strict 21-stop R001
profile below. The admin website and REST uploads use the general workflow above.

The authoritative `bus_route_stops.csv` is not included in this checkout and R001 was absent in Supabase at the Phase 6 audit. Supply the mentor/college's real file. Do not copy automated synthetic coordinates into production.

CSV canonical columns:

```csv
stop_order,name,latitude,longitude
```

Exactly 21 rows, unique consecutive orders 1–21, valid decimal coordinates and nonempty stop names are required. First stop must be `NIE Golden Jubilee`; last must be `North Campus Last Stop`. Case-insensitive header aliases include stop_name, lat, lon/lng and sequence/order. `stop_order_shared` is also accepted for the sequence in the college's source CSV. Optional `route_code` and `route_id` columns must contain R001. Extra columns are preserved as source metadata; uncertain source names remain provisional. Import rejects malformed/ambiguous headers and duplicate named coordinates before mutating the database.

Use `/portal/routes/import/` through the route import link, or from repository root:

```powershell
.\.venv\Scripts\python.exe backend\manage.py import_bus_route 'C:\path\to\bus_route_stops.csv' --direction TO_COLLEGE
```

`route_code` is the stable identifier; reimport updates rather than duplicates R001. Review all 21 names/order/coordinates on the route detail page. Stop/route edits are protected against active trips and invalid student pickups. TO_COLLEGE implies PICKUP; FROM_COLLEGE implies DROP. Set the correct order/direction explicitly; changing a direction label does not magically reverse road geometry or stops.

Stop coordinates are not road geometry. Without valid stored geometry, the map draws a clearly labelled approximate stop-connecting line and ETA remains unavailable. To generate optional directional road geometry once:

```powershell
.\.venv\Scripts\python.exe backend\manage.py generate_route_geometry R001
```

This operator command calls trusted HTTPS `OSRM_BASE_URL`, validates the returned LineString against ordered stops/direction and stores it. Existing geometry is skipped unless `--force`. Complete active trips before replacement. Network/routing failure preserves existing data and approximate visualization. Public OSRM is suitable for occasional development requests, not a traffic/live routing guarantee. Production can use an approved OSRM-compatible service or reviewed stored GeoJSON. Never call OSRM on every GPS update.

For development-only demonstration without a phone, enable `DJANGO_DEBUG=True` and `ENABLE_ROUTE_REPLAY=True`, restart the local server, then:

```powershell
.\.venv\Scripts\python.exe backend\manage.py replay_bus_route --driver-email DRIVER_EMAIL --max-updates 30
```

The command prompts privately for the driver password, requires that driver's real R001 assignment and 21 imported stops, restricts its server to loopback and marks records/UI SIMULATED. Without road geometry it uses approximate connections and cannot produce an ETA. It attempts completion and logout on exit; if interrupted by process termination, verify and end the trip. Disable replay after use. Production settings always disable replay regardless of environment flags.
