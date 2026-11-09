"""Phase 5 HTTP-to-browser integration, using only disposable synthetic fixtures."""
import os
import sys
import json
import time
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.append(str(Path(sys.base_prefix) / 'Lib' / 'site-packages'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.test_settings'
os.environ['DJANGO_ALLOWED_HOSTS'] = 'localhost,127.0.0.1,testserver'
os.environ['DJANGO_DEBUG'] = 'True'
os.environ['STUDENT_POLL_INTERVAL_SECONDS'] = '5'


def main():
    import django
    django.setup()
    from django.db import connection
    from django.test.runner import DiscoverRunner
    from django.utils import timezone
    from eta.tests import LiveIntegrationTests
    from playwright.sync_api import sync_playwright
    db = connection.settings_dict
    if db['HOST'] != '127.0.0.1' or str(db['PORT']) != '55432' or db['USER'] != 'postgres':
        raise RuntimeError('Use the dedicated local PostgreSQL cluster, not Supabase.')
    runner = DiscoverRunner(verbosity=0, interactive=False)
    database = runner.setup_databases()
    server = None
    try:
        fixture = type('Fixture', (), {})
        LiveIntegrationTests.setUpTestData.__func__(fixture)
        env = os.environ.copy()
        env['TEST_DATABASE_URL'] = f"postgresql://postgres@127.0.0.1:55432/{connection.settings_dict['NAME']}?sslmode=disable"
        base = 'http://127.0.0.1:8004'
        server = subprocess.Popen([sys.executable, str(BACKEND/'manage.py'), 'runserver', '127.0.0.1:8004', '--noreload', '--settings=config.test_settings'],
            cwd=BACKEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for _ in range(40):
            try:
                if urlopen(base+'/login/', timeout=1).status == 200:
                    break
            except OSError:
                time.sleep(.25)
        else:
            raise RuntimeError('Test HTTP server did not start.')
        def post(path, data, token=None):
            headers = {'Content-Type': 'application/json'}
            if token:
                headers['Authorization'] = 'Bearer ' + token
            with urlopen(Request(base+path, json.dumps(data).encode(), headers, method='POST'), timeout=10) as response:
                return json.load(response)
        token = post('/api/auth/login/', {'email': 'driver@example.test', 'password': 'password123'})['token']
        trip = post('/api/driver/trips/start/', {}, token)['trip']['id']
        def gps(lon):
            return post(f'/api/driver/trips/{trip}/location/', {'latitude': 12, 'longitude': lon, 'speed': 5, 'accuracy': 5, 'recorded_at': timezone.now().isoformat()}, token)
        gps(77.001)
        screenshots = ROOT/'docs/screenshots'
        screenshots.mkdir(exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            student = browser.new_context(viewport={'width': 1440, 'height': 1050}).new_page()
            errors = []
            student.on('pageerror', lambda error: errors.append(str(error)))
            def login(page, email):
                page.goto(base+'/login/')
                page.fill('#id_username', email)
                page.fill('#id_password', 'password123')
                page.get_by_role('button', name='Sign in').click()
            login(student, 'student@example.test')
            student.wait_for_url('**/dashboard/student/')
            student.goto(base+'/student/tracking/')
            student.wait_for_function("window.StudentTransit?.getSnapshot().eta.status === 'available' && document.querySelector('.student-bus-icon.fresh')")
            before = student.evaluate('window.StudentTransit.getSnapshot().eta.seconds')
            student.evaluate("window.__marker = document.querySelector('.student-bus-icon'); window.__map = document.querySelector('#student-map')._leaflet_id")
            gps(77.0014)
            student.wait_for_function("window.StudentTransit.getSnapshot().location.longitude === 77.0014", timeout=15000)
            assert student.evaluate('window.StudentTransit.getSnapshot().eta.seconds') < before
            assert student.evaluate('window.StudentTransit.getSnapshot().progress.next_stop.order') == 2
            assert student.evaluate("document.querySelector('.student-bus-icon') === __marker && document.querySelector('#student-map')._leaflet_id === __map")
            assert student.locator('.student-stop-icon').count() == 21
            student.screenshot(path=str(screenshots/'phase5-student-tracking.png'), full_page=True)
            admin = browser.new_context(viewport={'width': 1440, 'height': 1050}).new_page()
            admin.on('pageerror', lambda error: errors.append(str(error)))
            login(admin, 'admin@example.test')
            admin.wait_for_url('**/dashboard/admin/')
            admin.goto(base+f'/portal/map/?route={fixture.route.pk}')
            admin.wait_for_function("document.querySelector('.bus-marker.live') !== null")
            admin.select_option('#inspect-bus', str(fixture.bus.pk))
            admin.wait_for_function("document.querySelector('#bus-inspection').textContent.includes('Next: Synthetic Stop 2')")
            admin.evaluate("window.__marker = document.querySelector('.bus-marker.live')")
            gps(77.0016)
            admin.get_by_role('button', name='Refresh positions').click()
            admin.wait_for_function("document.querySelector('#map-feedback').textContent.includes('Refreshed')")
            assert admin.evaluate("document.querySelector('.bus-marker.live') === __marker")
            admin.screenshot(path=str(screenshots/'phase5-admin-tracking.png'), full_page=True)
            admin.route('**/api/admin/live-buses/', lambda route: route.fulfill(status=503, json={'detail':'Test outage'}))
            admin.get_by_role('button', name='Refresh positions').click()
            admin.wait_for_function("document.querySelector('#bus-inspection').textContent.includes('Refresh failed')")
            assert admin.locator('.bus-marker.live').count() == 0
            admin.unroute('**/api/admin/live-buses/')
            post(f'/api/driver/trips/{trip}/end/', {}, token)
            student.get_by_role('button', name='Refresh', exact=False).click()
            student.wait_for_function("window.StudentTransit.getSnapshot().trip_status === 'COMPLETED'")
            assert student.locator('[data-bind="eta-value"]').first.inner_text() == 'Unavailable'
            admin.get_by_role('button', name='Refresh positions').click()
            admin.wait_for_function("document.querySelector('#bus-inspection').textContent.includes('COMPLETED')")
            assert admin.locator('.bus-marker.live').count() == 0
            assert not errors, errors
            browser.close()
        print('Phase 5 browser integration passed: real HTTP driver login/start/GPS -> PostgreSQL -> automatic student polling, decreasing ETA, next stop, 21 stops, stable markers/maps, admin bus inspection and completion on both portals. Synthetic disposable test fixtures only.')
    finally:
        if server:
            server.terminate()
            server.wait(timeout=10)
        connection.close()
        runner.teardown_databases(database)


if __name__ == '__main__':
    main()
