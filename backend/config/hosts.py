"""Build an exact host allowlist from configuration, never request headers."""
import re


def deployment_hosts(configured, environment):
    hosts = list(configured)
    if environment.get('VERCEL') != '1':
        return hosts
    for key in ('VERCEL_URL', 'VERCEL_BRANCH_URL', 'VERCEL_PROJECT_PRODUCTION_URL'):
        host = environment.get(key, '').strip().lower()
        # Platform variables contain bare DNS names, including custom domains.
        # Reject schemes, ports, paths and wildcard entries.
        if len(host) <= 253 and re.fullmatch(
            r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+'
            r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', host
        ) and host not in hosts:
            hosts.append(host)
    return hosts
