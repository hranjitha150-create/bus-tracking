Place the mentor's actual `bus_route_stops.csv` here. No source file or coordinates were supplied with Phase 1.

Required columns: `stop_order,name,latitude,longitude`. The importer also accepts documented aliases (see the root README). It preserves every original column in `BusStop.original_metadata`. Optional `address` and `route_code` are supported. R001 must have exactly 21 rows ordered 1–21, starting at NIE Golden Jubilee and ending at North Campus Last Stop. CSV observations and uncertain names remain provisional; importing does not verify them.

No road geometry is inferred from stops. Route.geometry is an optional GeoJSON LineString for a later authoritative source.
