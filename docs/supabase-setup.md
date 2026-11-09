# Supabase PostgreSQL setup

Only Django connects to PostgreSQL. Browser and Android clients call Django; no Supabase publishable/anon/service key belongs in either client. Existing Django accounts are independent of Supabase Auth.

1. In the Supabase project connection dialog, copy a direct PostgreSQL connection or session pooler connection supported by your network. Use the supplied host, port and username exactly. Prefer direct/session mode for migrations.
2. Set `DATABASE_URL` privately in `backend/.env` for development or server environment for production. Format: `postgresql://USER:URL_ENCODED_PASSWORD@HOST:PORT/postgres?sslmode=require`. URL-encode password characters; do not paste the URL into logs, screenshots or source control.
3. Set `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS` and local `DJANGO_DEBUG`. Production uses `config.production` and TLS. The app disables prepared statements/server-side cursors for pooler compatibility.
4. From repository root run:

```powershell
.\.venv\Scripts\python.exe backend\manage.py check
.\.venv\Scripts\python.exe backend\manage.py migrate
.\.venv\Scripts\python.exe backend\manage.py migrate --check
.\.venv\Scripts\python.exe backend\manage.py audit_database_access
# With the migration owner, remove unintended browser-role grants if reported:
.\.venv\Scripts\python.exe backend\manage.py audit_database_access --apply
```

The audit targets only Django-owned model/M2M tables and django_migrations, plus their sequences when applying revocation. It leaves Supabase auth/storage tables untouched. Recheck after every migration because project default grants may apply to newly created tables. Keep RLS enabled. Never grant broad `anon`/`authenticated` policies to make Django work. If this project's Data API is unused, disable it in Supabase settings as an additional boundary.

## Separate runtime credentials before deployment

At this audit the connected managed role was not superuser but had **BYPASSRLS**. Removing browser grants does not make that runtime role least-privileged. Do not alter Supabase's managed postgres role. Keep it only for controlled migrations/maintenance; provision a separate login role for the server.

Have the database operator create a unique `college_runtime` role with `NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS`, a generated secret and no membership in managed roles. Grant CONNECT on the application database, USAGE on public, and SELECT/INSERT/UPDATE/DELETE only on the explicit Django table inventory. Grant USAGE/SELECT only on associated sequences. It must not own tables or receive CREATE/TRUNCATE/role-management rights.

For each Django table with RLS enabled, create a server-role-only policy such as the following example (substitute a reviewed, explicit table name; repeat only for application tables):

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.buses_bus TO college_runtime;
CREATE POLICY college_server_access ON public.buses_bus
  FOR ALL TO college_runtime USING (true) WITH CHECK (true);
```

This policy trusts the private Django server role; student/driver row authorization remains in Django. It grants nothing to browser roles. Review existing restrictive policies and sequence grants before switching. Do not execute `GRANT ALL ON ALL TABLES IN SCHEMA public` against a mixed Supabase project. If django_migrations access is needed for checks, grant SELECT there; actual migrations continue using the owner credentials.

Stage the role switch: verify login, sessions, CRUD, assignment, GPS/history/progress and pruning against an isolated restored database first. Verify runtime cannot create/drop tables, change roles or access unrelated schemas. Set production DATABASE_URL to the restricted role, retain owner credentials separately, then rerun audit (expect superuser=False,bypass_rls=False). New migrations require explicit grants/policies on their new tables. This provisioning was documented, not executed against the user's managed account.

The real R001 route is absent in the audited database. Follow [route import](route-import.md) using the actual CSV. Follow [deployment/recovery](deployment-guide.md) before exposing the service.

References: [Supabase API grants](https://supabase.com/docs/guides/api/securing-your-api), [row security](https://supabase.com/docs/guides/database/postgres/row-level-security), [connection options](https://supabase.com/docs/guides/database/connecting-to-postgres).
