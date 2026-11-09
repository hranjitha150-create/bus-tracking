"""QA only: native emulator -> local Django/PostgreSQL -> student/admin APIs.

Requires app-integration.apk and the dedicated CampusDriver emulator on 5556.
Coordinates/accounts are synthetic fixtures; Supabase is never used by this test.
"""
import os
import sys
import json
import re
import time
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
os.environ.update(DJANGO_SETTINGS_MODULE='config.test_settings', DJANGO_DEBUG='True',
    DJANGO_ALLOWED_HOSTS='localhost,127.0.0.1,10.0.2.2,testserver')
PACKAGE = 'com.campustransit.driver.integration'


def main():
    import django
    django.setup()
    from django.db import connection
    from django.test.runner import DiscoverRunner
    from eta.tests import LiveIntegrationTests
    db = connection.settings_dict
    if db['HOST'] != '127.0.0.1' or str(db['PORT']) != '55432':
        raise RuntimeError('Native QA requires the isolated local PostgreSQL test server.')
    sdk = Path(os.environ['ANDROID_HOME'])
    adb = str(sdk/'platform-tools/adb.exe')
    def device(*args):
        result = subprocess.run([adb, '-s', 'emulator-5556', *args], capture_output=True, timeout=30)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors='replace'))
        return result.stdout.decode(errors='replace')
    if 'CampusDriver' not in device('emu','avd','name'):
        raise RuntimeError('Refusing to use a personal device/emulator.')
    runner = DiscoverRunner(verbosity=0, interactive=False)
    database = runner.setup_databases()
    server = None
    try:
        fixture = type('QA', (), {})
        LiveIntegrationTests.setUpTestData.__func__(fixture)
        fixture.bus.bus_number = 'College Bus 01'
        fixture.bus.save()
        fixture.route.route_name = 'SIMULATED R001 QA fixture'
        fixture.route.save()
        fixture.driver_user.full_name = 'SIMULATED QA Driver'
        fixture.driver_user.save()
        env = os.environ.copy()
        env['TEST_DATABASE_URL'] = f"postgresql://postgres@127.0.0.1:55432/{connection.settings_dict['NAME']}?sslmode=disable"
        base = 'http://127.0.0.1:8005'
        server = subprocess.Popen([sys.executable,str(BACKEND/'manage.py'),'runserver','127.0.0.1:8005','--noreload','--settings=config.test_settings'], env=env,
            cwd=BACKEND, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        for _ in range(40):
            try:
                if urlopen(base+'/login/', timeout=1).status == 200: break
            except OSError: time.sleep(.25)
        else:
            raise RuntimeError('Isolated native QA HTTP server did not start.')
        def api(path, body=None, token=None):
            headers = {'Content-Type':'application/json'}
            if token: headers['Authorization'] = 'Bearer '+token
            with urlopen(Request(base+path, json.dumps(body).encode() if body is not None else None, headers), timeout=10) as response:
                return json.load(response)
        student_token = api('/api/auth/login/', {'email':'student@example.test','password':'password123'})['token']
        driver_token = api('/api/auth/login/', {'email':'driver@example.test','password':'password123'})['token']
        admin_token = api('/api/auth/login/', {'email':'admin@example.test','password':'password123'})['token']
        work = ROOT/'android-driver/.emulator-test'
        def nodes():
            device('shell','uiautomator','dump','/sdcard/campus-ui.xml')
            device('pull','/sdcard/campus-ui.xml',str(work/'ui.xml'))
            return list(ET.parse(work/'ui.xml').iter('node'))
        def find(resource=None, text=None):
            for node in nodes():
                if resource and node.get('resource-id','').endswith('id/'+resource): return node
                if text and text.lower() in node.get('text','').lower(): return node
            return None
        def wait(resource=None, text=None, seconds=30):
            deadline = time.monotonic()+seconds
            while time.monotonic()<deadline:
                node = find(resource,text)
                if node is not None: return node
                time.sleep(.5)
            raise AssertionError(f'Native screen did not show {resource or text}')
        def tap(node):
            x1,y1,x2,y2 = map(int,re.findall(r'\d+',node.get('bounds')))
            device('shell','input','tap',str((x1+x2)//2),str((y1+y2)//2))
        def reveal(resource=None,text=None):
            # The dashboard intentionally scrolls on smaller screens.
            for _ in range(6):
                node = find(resource,text)
                if node is not None:
                    return node
                device('shell','input','swipe','540','1650','540','600','350')
            return wait(resource,text)
        def click(resource=None,text=None): tap(reveal(resource,text))
        print('Native QA: server ready; exercising login and permissions.', flush=True)
        device('install','-r',str(ROOT/'android-driver/app/build/outputs/apk/integration/app-integration.apk'))
        device('shell','pm','clear',PACKAGE)
        device('emu','geo','fix','77.001','12')
        device('shell','am','start','-n',PACKAGE+'/com.campustransit.driver.activities.LoginActivity')
        click('email'); device('shell','input','text','driver@example.test')
        click('password'); device('shell','input','text','password123'); device('shell','input','keyevent','4')
        click('login')
        wait(text='College Bus 01')
        click('startTrip')
        click('permission_deny_button')
        wait(text='Permission needed')
        assert api('/api/driver/assignment/',token=driver_token)['active_trip'] is None
        click(text='Not now')
        # Restore location consent via emulator settings after exercising denial.
        device('shell','pm','grant',PACKAGE,'android.permission.ACCESS_FINE_LOCATION')
        device('shell','pm','grant',PACKAGE,'android.permission.ACCESS_COARSE_LOCATION')
        click('startTrip')
        click('permission_deny_button')
        wait(text='Permission needed')
        assert api('/api/driver/assignment/',token=driver_token)['active_trip'] is None
        click(text='Not now')
        device('shell','pm','grant',PACKAGE,'android.permission.POST_NOTIFICATIONS')
        device('shell','cmd','location','set-location-enabled','false')
        time.sleep(1)
        warning = find(text='Close')
        if warning is not None:
            tap(warning)
        click('startTrip')
        assert api('/api/driver/assignment/',token=driver_token)['active_trip'] is None
        device('shell','cmd','location','set-location-enabled','true')
        device('shell','am','force-stop',PACKAGE)
        device('shell','input','keyevent','3')
        device('shell','am','start','-W','-f','0x10008000','-n',PACKAGE+'/com.campustransit.driver.activities.LoginActivity')
        print('Native QA: permission denial and GPS disabled checks passed; starting trip.', flush=True)
        click('startTrip')
        wait(text='ACTIVE')
        device('emu','geo','fix','77.001','12')
        def wait_location(expected=None):
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                data=api('/api/student/my-bus/location/',token=student_token)
                if data['location'] and (expected is None or abs(data['location']['longitude']-expected)<.0000001): return data
                time.sleep(1)
            raise AssertionError('Native service GPS did not reach the student API')
        first=wait_location(77.001)
        assert first['bus']['bus_number']=='College Bus 01'
        assert first['eta']['status']=='available', first['eta']
        time.sleep(11)
        device('emu','geo','fix','77.0014','12')
        moved=wait_location(77.0014)
        # Real location-provider speed can replace a configured fallback speed.
        # Distance must decrease; ETA need not decrease when its speed source changes.
        assert moved['eta']['status']=='available', moved['eta']
        assert moved['eta']['distance_m']<first['eta']['distance_m']
        assert moved['progress']['next_stop']['order']==2
        print('Native QA: foreground GPS reached student API; route distance decreased and next stop matched.', flush=True)
        fleet=api('/api/admin/live-buses/',token=admin_token)['results']
        assert any(row['bus_number']=='College Bus 01' and row['gps_status']=='live' for row in fleet)
        device('shell','am','force-stop',PACKAGE)
        assert 'TrackingService' not in device('shell','dumpsys','activity','services',PACKAGE)
        device('shell','am','start','-n',PACKAGE+'/com.campustransit.driver.activities.LoginActivity')
        reveal('resumeSharing')
        wait(text='Sharing is off')
        click('resumeSharing')
        time.sleep(2)
        click('endTrip'); click('button1')
        wait(text='COMPLETED')
        done=api('/api/student/my-bus/location/',token=student_token)
        assert done['trip_status']=='COMPLETED' and not done['gps']['is_fresh'] and done['eta']['status']=='unavailable'
        assert 'TrackingService' not in device('shell','dumpsys','activity','services',PACKAGE)
        print('Native end-to-end QA passed: login, denied precise location, denied notifications, GPS disabled, start, actual Android foreground service with emulator-injected synthetic fixes, PostgreSQL/student/admin updates, decreasing pickup distance, ETA, next stop, force-stop/reopen/resume and end. No physical GPS or Supabase fixture writes.')
    finally:
        try:
            device('shell','am','force-stop',PACKAGE)
        except Exception:
            print('QA emulator cleanup was unavailable; verify the integration app is stopped.', flush=True)
        try:
            if server: server.terminate(); server.wait(timeout=10)
        finally:
            connection.close()
            runner.teardown_databases(database)


if __name__=='__main__': main()
