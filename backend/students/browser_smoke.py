"""Real-browser Phase 3 checks on a disposable local PostgreSQL database only.

Requires Playwright/Chromium. All coordinates and accounts here are test fixtures.
No Supabase writes, test endpoints or GPS ingestion endpoints are introduced.
"""
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen
from concurrent.futures import ThreadPoolExecutor

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.append(str(Path(sys.base_prefix) / 'Lib' / 'site-packages'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.test_settings'
os.environ['DJANGO_ALLOWED_HOSTS'] = 'localhost,127.0.0.1,testserver'
os.environ['DJANGO_DEBUG'] = 'True'
os.environ['STUDENT_POLL_INTERVAL_SECONDS'] = '2'


def db_call(fn):
    # Playwright's synchronous API runs an event loop. ORM updates belong on a
    # separate thread, with its own connection closed before database teardown.
    def run():
        from django.db import connections
        try:
            return fn()
        finally:
            connections.close_all()
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(run).result()


def main():
    import django
    django.setup()
    from django.test.runner import DiscoverRunner
    from django.db import connection
    from django.utils import timezone
    from datetime import timedelta
    from students.tests import student_fixture
    from assignments.models import StudentBusAssignment
    from routes.models import Route
    from tracking.models import BusLocation
    from admin_portal.services import assign_student
    from playwright.sync_api import sync_playwright
    db = connection.settings_dict
    if db['HOST'] != '127.0.0.1' or str(db['PORT']) != '55432' or db['USER'] != 'postgres':
        raise RuntimeError('Browser checks require the isolated local PostgreSQL cluster on 55432.')
    runner = DiscoverRunner(verbosity=0, interactive=False)
    database = runner.setup_databases()
    server = None
    try:
        fixture = type('BrowserFixture', (), {})
        student_fixture(fixture)
        start_stop = fixture.route.route_stops.first().stop
        password = 'Browser-student-only!483'
        user = fixture.student_user
        user.set_password(password)
        user.save()
        fixture.trip.status, fixture.trip.start_time = 'ACTIVE', timezone.now()
        fixture.trip.save()
        location = BusLocation.objects.create(bus=fixture.bus, trip=fixture.trip, latitude='10.1234567', longitude='70.0700000')
        env = os.environ.copy()
        env['TEST_DATABASE_URL'] = f"postgresql://postgres@127.0.0.1:55432/{connection.settings_dict['NAME']}?sslmode=disable"
        server = subprocess.Popen([sys.executable, str(BACKEND / 'manage.py'), 'runserver', '127.0.0.1:8003', '--noreload', '--settings=config.test_settings'],
            cwd=BACKEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        base = 'http://127.0.0.1:8003'
        for _ in range(40):
            try:
                if urlopen(base + '/login/', timeout=1).status == 200:
                    break
            except OSError:
                time.sleep(.25)
        else:
            raise RuntimeError('Student preview server did not start.')
        screenshots = ROOT / 'docs' / 'screenshots'
        screenshots.mkdir(exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1050}, device_scale_factor=1)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/login/')
            page.fill('#id_username', user.email)
            page.fill('#id_password', password)
            page.get_by_role('button', name='Sign in').click()
            page.wait_for_url('**/dashboard/student/')
            page.get_by_role('heading', name='Your campus commute').wait_for()
            page.screenshot(path=str(screenshots / 'student-dashboard.png'), full_page=True)
            page.goto(base + '/student/route/')
            page.wait_for_function("document.querySelectorAll('.student-stop-icon').length === 21")
            assert page.locator('#student-stop-list .route-stop').count() == 21
            assert page.locator('.student-stop-icon.pickup').count() == 1
            assert page.locator('.student-stop-icon.start').count() == 1
            assert page.locator('.student-stop-icon.destination').count() == 1
            assert page.locator('.route-stop.is-pickup .stop-number').inner_text() == '7'
            assert 'NIE Golden Jubilee' in page.locator('.route-stop').first.inner_text()
            assert 'North Campus Last Stop' in page.locator('.route-stop').last.inner_text()
            assert 'not a verified driving route' in page.locator('.geometry-caption').inner_text()
            # A pickup may also be the start: preserve both roles on that marker.
            db_call(lambda: assign_student(fixture.student, fixture.bus, start_stop))
            page.wait_for_function("document.querySelector('.student-stop-icon.start.pickup') !== null", timeout=10000)
            assert page.locator('.student-stop-icon').count() == 21
            db_call(lambda: assign_student(fixture.student, fixture.bus, fixture.pickup))
            page.goto(base + '/student/tracking/')
            page.wait_for_function("document.querySelectorAll('.student-bus-icon.fresh').length === 1")
            page.evaluate("window.__originalMarker = document.querySelector('.student-bus-icon'); window.__mapIdentity = document.querySelector('#student-map')._leaflet_id; window.__oldTransform = __originalMarker.style.transform")
            # No button click: wait for the configurable periodic fetch to move the marker.
            db_call(lambda: BusLocation.objects.filter(pk=location.pk).update(latitude='10.1244567', longitude='70.0800000', recorded_at=timezone.now(), received_at=timezone.now()))
            page.wait_for_function("document.querySelector('[data-bind=\"bus-coordinates\"]').textContent.includes('70.0800000')", timeout=10000)
            assert page.evaluate("document.querySelector('.student-bus-icon') === __originalMarker"), 'Fresh polling recreated the marker'
            assert page.evaluate("document.querySelector('#student-map')._leaflet_id === __mapIdentity"), 'Polling recreated the map'
            assert page.evaluate("__originalMarker.style.transform !== __oldTransform"), 'Marker did not move'
            assert page.locator('.student-bus-icon').count() == 1
            page.screenshot(path=str(screenshots / 'student-tracking.png'), full_page=True)

            db_call(lambda: BusLocation.objects.filter(pk=location.pk).update(recorded_at=timezone.now() - timedelta(minutes=5)))
            page.get_by_role('button', name='Refresh', exact=False).click()
            page.wait_for_function("document.querySelector('.student-bus-icon.stale') !== null")
            assert 'stale' in page.locator('[data-gps-badge]').first.inner_text().lower()
            assert page.locator('[data-bind="eta-value"]').first.inner_text() == 'Unavailable'
            # Age out an initially fresh sample in the browser without another fetch.
            db_call(lambda: BusLocation.objects.filter(pk=location.pk).update(recorded_at=timezone.now(), received_at=timezone.now()))
            page.get_by_role('button', name='Refresh', exact=False).click()
            page.wait_for_function("document.querySelector('.student-bus-icon.fresh') !== null")
            page.evaluate("window.__realDateNow = Date.now; Date.now = () => __realDateNow() + 180000")
            page.wait_for_function("document.querySelector('.student-bus-icon.stale') !== null", timeout=2000)
            page.evaluate('Date.now = __realDateNow')

            # A backend error retains a labeled last-known position, never live status.
            page.route('**/api/student/my-bus/location/', lambda route: route.fulfill(status=503, json={'detail': 'Simulated test outage'}))
            page.get_by_role('button', name='Refresh', exact=False).click()
            page.wait_for_function("!document.querySelector('#connection-status').hidden")
            assert 'could not refresh' in page.locator('#connection-status').inner_text()
            assert page.locator('.student-bus-icon.fresh').count() == 0
            page.unroute('**/api/student/my-bus/location/')
            page.get_by_role('button', name='Refresh', exact=False).click()
            page.wait_for_function("document.querySelector('#connection-status').hidden")
            context.set_offline(True)
            page.wait_for_function("document.querySelector('#connection-status').textContent.includes('offline')")
            assert page.locator('.student-bus-icon.fresh').count() == 0
            context.set_offline(False)
            page.wait_for_function("document.querySelector('#connection-status').hidden")

            db_call(lambda: Route.objects.filter(pk=fixture.route.pk).update(geometry={'type': 'Polygon'}))
            page.get_by_role('button', name='Refresh', exact=False).click()
            page.wait_for_function("document.querySelector('.geometry-caption').textContent.includes('invalid')")
            assert page.locator('.student-stop-icon').count() == 21
            fixture.trip.status, fixture.trip.end_time = 'COMPLETED', timezone.now()
            db_call(fixture.trip.save)
            page.get_by_role('button', name='Refresh', exact=False).click()
            page.wait_for_function("document.querySelector('.student-bus-icon.completed') !== null")
            assert page.locator('[data-bind="trip-label"]').first.inner_text() == 'Completed'
            db_call(lambda: BusLocation.objects.filter(pk=location.pk).delete())
            page.get_by_role('button', name='Refresh', exact=False).click()
            page.wait_for_function("document.querySelectorAll('.student-bus-icon').length === 0")

            db_call(lambda: assign_student(fixture.student, fixture.other_bus, fixture.pickup))
            page.wait_for_function("window.StudentTransit.getSnapshot().bus.bus_number === 'B2'", timeout=10000)
            assert page.locator('.student-bus-icon').count() == 0
            db_call(lambda: StudentBusAssignment.objects.filter(student=fixture.student, is_active=True).update(is_active=False))
            page.wait_for_function("!document.querySelector('[data-unassigned]').hidden", timeout=10000)
            assert page.locator('.student-stop-icon').count() == 0
            assert page.evaluate('window.StudentTransit.getSnapshot().bus === null')

            # Restore only the synthetic test assignment for the mobile screenshot.
            db_call(lambda: Route.objects.filter(pk=fixture.route.pk).update(geometry={}))
            db_call(lambda: assign_student(fixture.student, fixture.bus, fixture.pickup))
            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(base + '/student/route/')
            page.wait_for_function("document.querySelectorAll('.student-stop-icon').length === 21")
            page.get_by_role('button', name='Toggle navigation').click()
            assert page.locator('#student-menu').get_attribute('aria-expanded') == 'true'
            page.keyboard.press('Escape')
            assert page.locator('#student-menu').get_attribute('aria-expanded') == 'false'
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Student mobile page overflowed'
            page.screenshot(path=str(screenshots / 'student-mobile.png'), full_page=True)

            # Map-library failure still leaves the route list and all textual data.
            page.route('**/leaflet@1.9.4/dist/leaflet.js', lambda route: route.abort())
            page.goto(base + '/student/route/')
            page.locator('.map-load-failed').wait_for()
            assert page.locator('#student-stop-list .route-stop').count() == 21
            page.unroute('**/leaflet@1.9.4/dist/leaflet.js')
            page.goto(base + '/student/tracking/')
            page.wait_for_function("document.querySelectorAll('.student-stop-icon').length === 21")
            page.route('**/api/student/my-bus/location/', lambda route: route.fulfill(status=401, json={'detail': 'Test session expired'}))
            page.get_by_role('button', name='Refresh', exact=False).click()
            page.locator('#session-login').wait_for(state='visible')
            assert page.evaluate('window.StudentTransit.getSnapshot().bus === null')
            assert page.locator('.student-stop-icon').count() == 0
            assert not errors, errors
            browser.close()
        print('Student browser checks passed: 21 ordered stops, start/destination/pickup markers, polling moves one marker without recreating the map, stale/missing/completed GPS, clock aging, API/network errors and recovery, reassignment/revocation, missing map library, session expiry and mobile layout.')
    finally:
        if server:
            server.terminate()
            server.wait(timeout=10)
        connection.close()
        runner.teardown_databases(database)


if __name__ == '__main__':
    main()
