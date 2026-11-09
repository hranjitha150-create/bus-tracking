# R001 source data and geometry

The authoritative `bus_route_stops.csv` is not included in this checkout and R001 was absent in Supabase at the Phase 6 audit. Supply the mentor/college's real file. Do not copy automated synthetic coordinates into production.

CSV canonical columns:

```csv
stop_order,name,latitude,longitude
```

Exactly 21 rows, unique consecutive orders 1–21, valid decimal coordinates and nonempty stop names are required. First stop must be `NIE Golden Jubilee`; last must be `North Campus Last Stop`. Case-insensitive header aliases include stop_name, lat, lon/lng and sequence/order. Optional route_code must be R001. Extra columns are preserved as source metadata; uncertain source names remain provisional. Import rejects malformed/ambiguous headers and duplicate named coordinates before mutating the database.

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
