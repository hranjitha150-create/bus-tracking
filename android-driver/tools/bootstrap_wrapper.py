"""Fetch official Gradle 8.13 wrapper files and pin its distribution checksum."""
from pathlib import Path
from urllib.request import urlopen
ROOT = Path(__file__).resolve().parents[1]
base = 'https://raw.githubusercontent.com/gradle/gradle/v8.13.0/'
for name in ['gradlew', 'gradlew.bat', 'gradle/wrapper/gradle-wrapper.jar']:
    dest = ROOT / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(base + name, timeout=60) as response:
        dest.write_bytes(response.read())
with urlopen('https://services.gradle.org/distributions/gradle-8.13-bin.zip.sha256', timeout=60) as response:
    checksum = response.read().decode().strip()
if len(checksum) != 64 or any(c not in '0123456789abcdef' for c in checksum):
    raise ValueError('Invalid distribution checksum')
(ROOT / 'gradle/wrapper/gradle-wrapper.properties').write_text(
    'distributionBase=GRADLE_USER_HOME\ndistributionPath=wrapper/dists\n'
    'distributionUrl=https\\://services.gradle.org/distributions/gradle-8.13-bin.zip\n'
    f'distributionSha256Sum={checksum}\nnetworkTimeout=60000\nvalidateDistributionUrl=true\n'
    'zipStoreBase=GRADLE_USER_HOME\nzipStorePath=wrapper/dists\n', encoding='utf-8')
print('Official Gradle wrapper installed with distribution SHA-256.')
