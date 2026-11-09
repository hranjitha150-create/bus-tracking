# Deployment and recovery

No provider or domain is assumed. Choose a host that can reach Supabase and terminate HTTPS with a valid certificate. Do not expose Django runserver, PostgreSQL or an untrusted proxy directly to the internet.

## Prepare configuration

### Vercel hostname configuration

For this project's deployment, set `DJANGO_ALLOWED_HOSTS=bus-tracking-peach-gamma.vercel.app`
in Vercel's **Production** environment and redeploy. Use bare hostnames, without
`https://`, paths, or a trailing slash. Updating the local `.env` does not update
an existing Vercel deployment. A missing host produces Django's generic HTTP 400;
the function logs identify it as `DisallowedHost` / `Invalid HTTP_HOST header`.

Settings also accept exact domains supplied by `VERCEL_URL`, `VERCEL_BRANCH_URL`
and `VERCEL_PROJECT_PRODUCTION_URL` when `VERCEL=1`. Enable access to system
environment variables in Vercel for this automatic configuration. Custom domains
can still be listed explicitly in `DJANGO_ALLOWED_HOSTS`. Other Vercel projects
are not allowed; do not use `*` or `.vercel.app` as a workaround.

Keep Root Directory `backend`, the Django preset, and the default build/output
settings. Override the install command to `pip install -r requirements-production.txt`.
Use `DJANGO_SETTINGS_MODULE=config.production` and `DJANGO_DEBUG=False`.
This hostname fix does not replace the production file cache: Vercel deployment
still needs a shared cache for login rate limits instead of the single-host
filesystem configuration below. Do not use temporary storage for shared limits.

Install `backend/requirements-production.txt`. Use `backend/.env.production.example` as a reference; set real values privately in the process environment or protected backend/.env. Preserve existing development credentials. Generate a unique secret, exact allowed hosts and TLS PostgreSQL URL for a restricted runtime role. Follow [Supabase setup](supabase-setup.md) for separate migration-owner credentials.

Same-origin templates need no CORS entries. Only list exact HTTPS origins for a separately hosted authorized browser client. Native Android bearer requests need no CORS entry. CSRF trusted origins are for intentional cross-origin browser form use; do not add wildcard origins.

Run from repository root (using controlled migration credentials for migrate/audit):

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-production.txt
$env:DJANGO_SETTINGS_MODULE = 'config.production'
.\.venv\Scripts\python.exe backend\manage.py check --deploy
.\.venv\Scripts\python.exe backend\manage.py migrate --plan
.\.venv\Scripts\python.exe backend\manage.py migrate
.\.venv\Scripts\python.exe backend\manage.py audit_database_access --apply
.\.venv\Scripts\python.exe backend\manage.py collectstatic --noinput
```

The profile forcibly disables DEBUG/replay, rejects weak secrets, wildcard hosts, insecure origins and non-TLS DB URLs. `security.W005` and `security.W021` remain by default because HSTS include-subdomains/preload require ownership and HTTPS readiness of the domain tree. Decide these explicitly; do not blindly enable/preload an unowned example domain. The production smoke test allows these two warnings only.

After switching DATABASE_URL to the restricted runtime role, start from `backend/`:

```powershell
$env:DJANGO_SETTINGS_MODULE = 'config.production'
..\.venv\Scripts\waitress-serve.exe --listen=127.0.0.1:8000 config.wsgi:application
```

On Linux the corresponding virtualenv executable is `.venv/bin/waitress-serve`. Run it under a service manager with restart limits and a dedicated OS account. Give that account write access only to required runtime/cache/log locations. Keep `DJANGO_CACHE_DIR` outside static assets, persistent across workers on this one host and inaccessible to web clients.

## HTTPS proxy

Bind the application to loopback. Configure the TLS proxy to preserve the validated Host and replace, not append/trust, incoming X-Forwarded-Proto. Only then set `DJANGO_TRUST_PROXY_HTTPS=True`; otherwise secure redirect may loop. For example, an operator-managed Nginx location can use:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Configure the server's actual TLS certificate, host allowlist, HTTP-to-HTTPS redirect and proxy request/login rate limits separately. The minimal snippet is not a full TLS server configuration. Restrict client body size (CSV imports) and timeouts. Verify login/CSRF, native bearer login, student map and GPS write through the real HTTPS origin before distribution.

WhiteNoise serves collected, hashed, compressed static assets; recollect on each code release. CDN Bootstrap/Leaflet and OSM tile hosts are in the CSP. If replacing those providers or hosting assets locally, update CSP deliberately. Public OSM can block excessive use; do not rotate hosts to evade a block. Review attribution/provider policy or use approved hosting.

## Operations

Schedule `manage.py prune_location_history` daily under production settings. The configured retention defaults to 30 days. Monitor rejected GPS rates, stale buses, DB space, login 429s and server errors. Logs redact known secrets and bearer tokens, but should still be access-controlled; avoid request-body logging. DB trace logging is disabled. Update dependencies through reviewed/tested changes rather than unpinned upgrades.

The app uses TLS `sslmode=require` by default. For stronger server identity validation, configure `verify-full` with a trusted CA through PostgreSQL environment/connection options supported by your host.

## Backup and recovery

Use Supabase's available project backup facilities where offered; do not assume a paid retention/PITR plan. Maintain independently encrypted logical backups with PostgreSQL tooling and a protected password file/secret mechanism. Never pass passwords on a command line or commit dumps. Use an explicit table inventory from Django model metadata (including auto-created M2M and django_migrations); back up those application tables, associated sequences/schema/constraints and required role-policy definitions. Avoid copying unrelated Supabase auth/storage internals into a replacement project.

A generic operator command for a dedicated application-only database is `pg_dump --format=custom --file=college-backup.dump DATABASE_NAME` with host/user/password supplied privately. For a mixed Supabase project, construct reviewed repeated `--table=public.EXACT_DJANGO_TABLE` options and verify dependent sequences/DDL are included. Record PostgreSQL version and migration version. Store configuration/signing keys separately with restricted access and an off-host backup copy.

Recovery rehearsal: create an isolated empty PostgreSQL database, provision required owner/runtime roles, restore with `pg_restore --no-owner --dbname=RESTORE_DB college-backup.dump`, review grants/RLS, run migrations/checks and verify accounts, assignments, 21 ordered stops and historical trips. Test authentication and new GPS writes there. A table-filtered dump may require reviewed dependency/role restoration; do not call a backup usable until rehearsal succeeds. Real managed Supabase restore was not performed during this audit.

For deployment rollback, retain the previous code/static bundle and database backup; review migration reversibility before downgrading. Do not run blanket reverse migrations against a live project. Rotate secrets after suspected compromise and revoke affected access tokens/sessions. No public deployment or certificate provisioning was performed by this task.

References: [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/), [proxy header precautions](https://docs.djangoproject.com/en/5.2/ref/settings/#secure-proxy-ssl-header), [OSM tile usage](https://operations.osmfoundation.org/policies/tiles/).
