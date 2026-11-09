"""Optional real-browser smoke checks, exclusively on a disposable PostgreSQL DB.

Run from the repository root with the project's Python. Requires Playwright in
this environment (or the base Python site-packages) and its Chromium browser.
"""
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.append(str(Path(sys.base_prefix) / 'Lib' / 'site-packages'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.test_settings'
os.environ['DJANGO_ALLOWED_HOSTS'] = 'localhost,127.0.0.1,testserver'
os.environ['DJANGO_DEBUG'] = 'True'


def main():
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.test.runner import DiscoverRunner
    from django.db import connection
    from tracking.tests import TransportTests
    from playwright.sync_api import sync_playwright
    db = connection.settings_dict
    if db['HOST'] != '127.0.0.1' or str(db['PORT']) != '55432' or db['USER'] != 'postgres':
        raise RuntimeError('Browser smoke harness expects the isolated local PostgreSQL test cluster on 55432.')
    runner = DiscoverRunner(verbosity=0, interactive=False)
    database = runner.setup_databases()
    server = None
    try:
        fixture = type('BrowserFixture', (), {})
        TransportTests.setUpTestData.__func__(fixture)
        password = 'Browser-only!pass-483'
        user = get_user_model().objects.get(pk=fixture.admin.pk)
        user.set_password(password)
        user.save()
        env = os.environ.copy()
        # This harness uses the dedicated local test database, never backend/.env.
        db = connection.settings_dict
        env['TEST_DATABASE_URL'] = f"postgresql://postgres@127.0.0.1:55432/{db['NAME']}?sslmode=disable"
        server = subprocess.Popen([sys.executable, str(BACKEND / 'manage.py'), 'runserver', '127.0.0.1:8002', '--noreload', '--settings=config.test_settings'],
            cwd=BACKEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for _ in range(40):
            try:
                if urlopen('http://127.0.0.1:8002/login/', timeout=1).status == 200:
                    break
            except OSError:
                time.sleep(.25)
        else:
            raise RuntimeError('Preview server did not start.')
        screenshots = ROOT / 'docs' / 'screenshots'
        screenshots.mkdir(exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1050}, device_scale_factor=1)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto('http://127.0.0.1:8002/login/')
            page.fill('#id_username', user.email)
            page.fill('#id_password', password)
            page.get_by_role('button', name='Sign in').click()
            page.wait_for_url('**/dashboard/admin/')
            page.get_by_role('heading', name='Transport overview').wait_for()
            page.wait_for_function("getComputedStyle(document.querySelector('.stats-grid')).display === 'grid'")
            page.screenshot(path=str(screenshots / 'admin-desktop.png'), full_page=True)
            # Use the actual HTML creation flow, then search for its saved record.
            page.goto('http://127.0.0.1:8002/portal/buses/add/')
            page.fill('#id_bus_number', 'BROWSER-03')
            page.fill('#id_registration_number', 'TEST-BROWSER-03')
            page.fill('#id_capacity', '30')
            page.get_by_role('button', name='Save changes').click()
            page.wait_for_url('**/portal/buses/*/')
            page.get_by_role('heading', name='BROWSER-03', exact=True).wait_for()
            # Create a separate route, add several stops, then replace from its CSV.
            page.goto('http://127.0.0.1:8002/portal/routes/add/')
            page.fill('#id_route_code', 'BROWSER-R2')
            page.fill('#id_route_name', 'Browser multi-stop route')
            page.fill('#id_start_location', 'Town')
            page.fill('#id_destination', 'College')
            page.select_option('#id_direction', 'TO_COLLEGE')
            page.get_by_role('button', name='Save changes').click()
            page.wait_for_url('**/portal/routes/*/')
            page.get_by_role('link', name='Add multiple stops', exact=False).click()
            for index in (0, 1):
                page.fill(f'#id_stops-{index}-name', f'Browser stop {index + 1}')
                page.fill(f'#id_stops-{index}-latitude', f'10.{index + 1}')
                page.fill(f'#id_stops-{index}-longitude', f'70.{index + 1}')
            page.get_by_role('button', name='Add another stop').click()
            assert page.locator('#id_stops-2-name').count() == 1
            page.locator('[data-stop-row]').nth(2).get_by_role('button', name='Remove this stop').click()
            page.get_by_role('button', name='Save all stops').click()
            page.wait_for_url('**/portal/routes/*/')
            page.get_by_text('2 ordered stops', exact=True).wait_for()
            page.get_by_role('link', name='Import CSV', exact=True).click()
            csv_bytes = b'route_id,stop_order_shared,stop_name,latitude,longitude\nBROWSER-R2,1,Town stop,10.1,70.1\nBROWSER-R2,2,Middle stop,10.2,70.2\nBROWSER-R2,3,College stop,10.3,70.3\n'
            page.set_input_files('#id_file', {'name': 'route.csv', 'mimeType': 'text/csv', 'buffer': csv_bytes})
            page.get_by_role('button', name='Validate & import').click()
            page.wait_for_url('**/portal/routes/*/')
            page.get_by_text('3 ordered stops', exact=True).wait_for()
            # Dynamic pickup loading and a successful reassignment.
            page.goto('http://127.0.0.1:8002/portal/assignments/student/add/')
            page.select_option('#id_student', str(fixture.student.pk))
            page.select_option('#id_bus', str(fixture.other_bus.pk))
            page.wait_for_function("document.querySelector('#id_pickup_stop').options.length > 1 && !document.querySelector('#id_pickup_stop').disabled")
            page.select_option('#id_pickup_stop', str(fixture.stop.pk))
            page.get_by_role('button', name='Save changes').click()
            page.wait_for_url('**/portal/assignments/')
            # Leaflet initializes and the authenticated refresh endpoint works.
            page.goto(f'http://127.0.0.1:8002/portal/map/?route={fixture.route.pk}')
            page.wait_for_function("document.querySelector('#fleet-map').classList.contains('leaflet-container')")
            page.get_by_role('button', name='Refresh positions').click()
            page.wait_for_function("document.querySelector('#map-feedback').textContent.includes('Refreshed')")
            # A first GPS fix arriving after map load must create a labeled bus.
            fleet = page.evaluate("JSON.parse(document.querySelector('#fleet-data').textContent)")
            fleet[0].update(latitude=10.1234567, longitude=70.07, gps_status='live')
            live_url = page.locator('#fleet-map').get_attribute('data-live-url')
            page.route('**' + live_url, lambda route: route.fulfill(json={'results': fleet}))
            page.get_by_role('button', name='Refresh positions').click()
            page.wait_for_function("document.querySelector('.bus-marker.live .map-bus-symbol') !== null")
            assert page.locator('.bus-map-label').inner_text() == fleet[0]['bus_number']
            page.wait_for_function("""() => {
                const marker = document.querySelector('.bus-marker.live').getBoundingClientRect();
                const map = document.querySelector('#fleet-map').getBoundingClientRect();
                return marker.left >= map.left && marker.right <= map.right && marker.top >= map.top && marker.bottom <= map.bottom;
            }""")
            page.screenshot(path=str(screenshots / 'admin-map.png'), full_page=True)
            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto('http://127.0.0.1:8002/dashboard/admin/')
            page.get_by_role('button', name='Toggle navigation').click()
            assert page.locator('#menu-toggle').get_attribute('aria-expanded') == 'true'
            page.keyboard.press('Escape')
            assert page.locator('#menu-toggle').get_attribute('aria-expanded') == 'false'
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile page overflows'
            page.screenshot(path=str(screenshots / 'admin-mobile.png'), full_page=True)
            assert not errors, errors
            browser.close()
        print('Browser smoke passed: session login, bus creation, dynamic pickup selection, assignment save, Leaflet, fleet refresh and mobile navigation. No JavaScript page errors.')
    finally:
        if server:
            server.terminate()
            server.wait(timeout=10)
        connection.close()
        runner.teardown_databases(database)


if __name__ == '__main__':
    main()
