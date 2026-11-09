import unittest

from django.core.exceptions import DisallowedHost
from django.http import HttpRequest
from django.test import override_settings

from .hosts import deployment_hosts


class DeploymentHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from django.conf import settings
        if not settings.configured:
            settings.configure(DEFAULT_CHARSET='utf-8')

    def test_project_and_deployment_domains_work_but_other_projects_do_not(self):
        environment = {
            'VERCEL': '1',
            'VERCEL_URL': 'bus-tracking-build123.vercel.app',
            'VERCEL_BRANCH_URL': 'bus-tracking-git-main-team.vercel.app',
            'VERCEL_PROJECT_PRODUCTION_URL': 'bus-tracking-peach-gamma.vercel.app',
        }
        hosts = deployment_hosts(['transport.college.example'], environment)
        with override_settings(ALLOWED_HOSTS=hosts):
            for host in [*environment.values(), 'transport.college.example']:
                if host == '1':
                    continue
                request = HttpRequest()
                request.META['HTTP_HOST'] = host
                self.assertEqual(request.get_host(), host)
            for host in ('other-project.vercel.app', 'attacker.example'):
                request = HttpRequest()
                request.META['HTTP_HOST'] = host
                with self.assertRaises(DisallowedHost):
                    request.get_host()

    def test_local_configuration_stays_unchanged(self):
        self.assertEqual(deployment_hosts(['localhost'], {
            'VERCEL_URL': 'preview.vercel.app',
        }), ['localhost'])

    def test_custom_production_domain_is_supported(self):
        self.assertEqual(deployment_hosts([], {
            'VERCEL': '1', 'VERCEL_PROJECT_PRODUCTION_URL': 'transport.college.example',
        }), ['transport.college.example'])

    def test_invalid_platform_values_cannot_disable_host_validation(self):
        for value in ('*', '.vercel.app', 'https://bus.vercel.app',
                      'bus.vercel.app/path', 'bus.vercel.app:443',
                      'bus.vercel.app@attacker.example', '-bad.vercel.app'):
            with self.subTest(value=value):
                self.assertEqual(deployment_hosts(['localhost'], {
                    'VERCEL': '1', 'VERCEL_URL': value,
                }), ['localhost'])
