"""Inspect/revoke browser Data API access to Django-owned tables only."""
from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction


def django_tables():
    return sorted({model._meta.db_table for model in apps.get_models(include_auto_created=True)} | {'django_migrations'})


def inspect_access():
    with connection.cursor() as cursor:
        cursor.execute('SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user')
        role, superuser, bypass = cursor.fetchone()
        cursor.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated')")
        browser_roles = [row[0] for row in cursor.fetchall()]
        cursor.execute('''SELECT c.oid, n.nspname, c.relname, c.relrowsecurity,
                         pg_get_userbyid(c.relowner), c.relacl::text
                         FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                         WHERE c.relkind IN ('r','p') AND n.nspname=current_schema() AND c.relname=ANY(%s)''', [django_tables()])
        tables = cursor.fetchall()
        issues = []
        for oid, schema, table, rls, owner, acl in tables:
            for browser_role in browser_roles:
                cursor.execute('SELECT has_table_privilege(%s,%s,\'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER\')', [browser_role, oid])
                if cursor.fetchone()[0]:
                    issues.append({'schema': schema, 'table': table, 'role': browser_role, 'rls': rls})
            # PUBLIC privileges matter even on non-Supabase PostgreSQL servers.
            cursor.execute('SELECT EXISTS(SELECT 1 FROM aclexplode(COALESCE(%s::aclitem[], acldefault(\'r\', (SELECT relowner FROM pg_class WHERE oid=%s)))) WHERE grantee=0)', [acl, oid])
            if cursor.fetchone()[0]:
                issues.append({'schema': schema, 'table': table, 'role': 'PUBLIC', 'rls': rls})
        return {'database_role': role, 'superuser': superuser, 'bypass_rls': bypass, 'tables_checked': len(tables),
                'issues': issues, 'browser_roles': browser_roles, 'tables': tables}


class Command(BaseCommand):
    help = 'Audit Django table grants; --apply revokes browser-role/PUBLIC access without exposing credentials.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        report = inspect_access()
        if options['apply']:
            with transaction.atomic(), connection.cursor() as cursor:
                roles = ['PUBLIC'] + [connection.ops.quote_name(role) for role in report['browser_roles']]
                for oid, schema, table, rls, owner, acl in report['tables']:
                    target = connection.ops.quote_name(schema)+'.'+connection.ops.quote_name(table)
                    cursor.execute('REVOKE ALL PRIVILEGES ON TABLE '+target+' FROM '+', '.join(roles))
                    cursor.execute('SELECT pg_get_serial_sequence(%s, attname) FROM pg_attribute WHERE attrelid=%s AND attnum>0 AND NOT attisdropped', [f'{schema}.{table}', oid])
                    for (sequence,) in cursor.fetchall():
                        if not sequence:
                            continue
                        # pg_get_serial_sequence is server-generated and each identifier is quoted.
                        cursor.execute('REVOKE ALL PRIVILEGES ON SEQUENCE '+'.'.join(connection.ops.quote_name(part.strip('"')) for part in sequence.split('.'))+' FROM '+', '.join(roles))
            report = inspect_access()
        self.stdout.write(f"Checked {report['tables_checked']} Django tables. Role superuser={report['superuser']}; bypass_rls={report['bypass_rls']}.")
        for issue in report['issues']:
            self.stdout.write(f"Browser grant: {issue['schema']}.{issue['table']} -> {issue['role']} (RLS={issue['rls']}).")
        if report['issues']:
            raise CommandError('Browser grants remain. Revoke app-table access or disable the Supabase Data API before production.')
        self.stdout.write(self.style.SUCCESS('No Django table privileges granted to PUBLIC/anon/authenticated.'))
