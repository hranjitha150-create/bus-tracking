"""Prepare a new disposable AVD in this checkout, without using a personal AVD."""
import os
from pathlib import Path
sdk = Path(os.environ['ANDROID_HOME'])
images = list((sdk / 'system-images').glob('*/*/x86_64/system.img'))
if not images:
    raise SystemExit('Install an x86_64 Android system image first.')
image = sorted(images)[-1].parent
props = dict(line.split('=', 1) for line in (image / 'source.properties').read_text().splitlines() if '=' in line)
root = Path(__file__).resolve().parents[1] / '.emulator-test'
avd = root / 'CampusDriver.avd'
avd.mkdir(parents=True, exist_ok=True)
(root / 'CampusDriver.ini').write_text(f'avd.ini.encoding=UTF-8\npath={avd}\ntarget=android-{props["AndroidVersion.ApiLevel"]}\n')
(avd / 'config.ini').write_text(
    'avd.ini.encoding=UTF-8\nAvdId=CampusDriver\navd.ini.displayname=Campus Driver Disposable Test\n'
    f'image.sysdir.1={image}{os.sep}\nabi.type=x86_64\nhw.cpu.arch=x86_64\n'
    'hw.cpu.ncore=2\nhw.ramSize=2048\nhw.lcd.width=1080\nhw.lcd.height=1920\nhw.lcd.density=420\n'
    f'tag.id={props.get("SystemImage.TagId", "google_apis")}\n'
    f'target=android-{props["AndroidVersion.ApiLevel"]}\n'
    'disk.dataPartition.size=2G\nhw.keyboard=yes\nhw.gpu.enabled=yes\nhw.gpu.mode=swiftshader_indirect\n')
print('Prepared dedicated test AVD:', root)
