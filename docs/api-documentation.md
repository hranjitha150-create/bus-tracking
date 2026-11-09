# API documentation

Use the Django HTTPS origin, JSON request bodies and `Authorization: Bearer <token>` for native requests. Session mutations require CSRF. Login with cookies or an Origin header also requires CSRF. Never log passwords or raw tokens.

## Authentication

| Method/path | Contract |
| --- | --- |
| POST `/api/auth/login/` | `{email,password}` → `{token,token_type:"Bearer",expires_at,user:{id,full_name,email,role}}` |
| POST `/api/auth/logout/` | Revoke bearer token / log out session; 204 |
| GET `/api/auth/me/` | Current `{id,full_name,email,role}` |

Opaque tokens expire after 12 hours; inactive users are rejected. Website/API login share budgets of 10 attempts/account and 60/remote IP per minute. 429 includes Retry-After. Proxy rate limiting remains recommended.

## ADMIN only

| Methods/path | Purpose |
| --- | --- |
| GET/POST `/api/admin/buses/` | List/create bus_number,registration_number,capacity,description,is_active |
| GET/PATCH `/api/admin/buses/{id}/` | Retrieve/update/deactivate |
| GET/POST `/api/admin/students/` | Account/profile: full_name,email,password,phone,is_active,enrollment_number,department,semester |
| GET/PATCH `/api/admin/students/{id}/` | Retrieve/update |
| GET/POST `/api/admin/drivers/` | Account/profile: full_name,email,password,phone,is_active,license_number |
| GET/PATCH `/api/admin/drivers/{id}/` | Retrieve/update |
| GET/POST `/api/admin/routes/` | route_code,route_name,start_location,destination,direction,is_active,geometry |
| GET/PATCH `/api/admin/routes/{id}/` | Details including ordered stops / update |
| POST `/api/admin/routes/import/` | Multipart `file` and optional `direction`; idempotent R001 import |
| POST `/api/admin/assignments/` | Create or replace assignments; read assignments in portal |
| POST `/api/admin/assignments/{student|driver}/{id}/end/` | End assignment with protection checks |
| GET `/api/admin/pickup-stops/?bus={id}` | Valid stops for bus's active route |
| GET `/api/admin/live-buses/` | `{count,results:[...]}` actual fleet, GPS/trip/progress |

Assignment body: `{kind:"driver",driver:<id>,bus:<id>,route:<id>}` or `{kind:"student",student:<id>,bus:<id>,pickup_stop:<id>}`. Relationships are validated transactionally. Route/stop editing and reorder forms live in `/portal/`.

Resource lists use `{count,next,previous,results}` pagination (50/page), `?page=` and `?search=`. Admin viewsets expose no DELETE. Error envelopes use `{detail,errors}`. Driver/student responses retain existing contracts.

## STUDENT only

| GET path | Response |
| --- | --- |
| `/api/student/dashboard/` | Full assigned snapshot |
| `/api/student/my-bus/` | Same snapshot |
| `/api/student/my-bus/location/` | Same snapshot; polling URL |
| `/api/student/my-route/` | Scoped route/geometry/pickup subset |
| `/api/student/my-bus/eta/` | ETA fields plus assignment_status,bus_id,pickup_stop_id,generated_at |

Snapshot fields: status,student,assignment,bus,route,pickup_stop,active_trip,trip,trip_status,location,gps,progress,eta,generated_at,poll_interval_seconds. Missing profile/assignment/location gives nulls and explicit states. Bus ID parameters cannot change authorization. Ordered route stops contain IDs, names, coordinates and order. Geometry has an explicit mode/label.

ETA unavailable: `{status:"unavailable",reason,seconds:null,arrival_at:null,message}`. Available includes seconds,arrival_at,distance_m,speed_kmh,speed_source,assumed_dwell_seconds,is_simulated. No traffic-based guarantee is implied.

## DRIVER only

| Method/path | Contract |
| --- | --- |
| GET `/api/driver/assignment/` | assigned/unassigned, driver,bus,route+stops,active_trip,latest trip,interval |
| POST `/api/driver/trips/start/` | `{}`; assignment-derived trip, `{trip,created}`; repeat reuses active trip |
| POST `/api/driver/trips/{id}/location/` | latitude,longitude,speed,accuracy,recorded_at |
| POST `/api/driver/trips/{id}/end/` | `{}`; idempotent completion of owned authorized trip |

Speed input is **m/s**, accuracy/distances **metres**, display speed **km/h**, ETA **seconds**. Coordinates are degrees; GeoJSON pairs are `[longitude,latitude]`. Timestamps use timezone-aware ISO-8601. Default freshness is 120 seconds for recorded and received time; max speed 45 m/s and accuracy 100 m. Excessive future timestamps, old or implausible fixes are rejected.

GPS accepted=201, identical retry=200, invalid=400, unauthorized trip=404/403, closed/conflicting/out-of-order=409. Older fixes never overwrite newer ones. Authentication failures are 401 for bearer requests; session/role denials may be 403.

Legacy `/api/buses/` and `/api/trips/` retain role-scoped querysets. New Android code uses dedicated driver APIs. `/api/development/trips/start/` and `/api/development/trips/{id}/location/` are gated development simulation endpoints, always disabled in production.
