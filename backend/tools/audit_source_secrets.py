"""Check source for this installation's configured secrets; never print values."""
from pathlib import Path
from urllib.parse import unquote, urlsplit
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[2]
values = dotenv_values(root / 'backend' / '.env')
needles = [values.get('DJANGO_SECRET_KEY'), values.get('DATABASE_URL')]
if values.get('DATABASE_URL'):
    needles.append(unquote(urlsplit(values['DATABASE_URL']).password or ''))
needles = [value for value in needles if value and len(value) >= 12]
excluded = {'.venv', '.postgres-test', '.git', '.gradle', '.emulator-test', '__pycache__', 'build', 'staticfiles', 'runtime'}
extensions = {'.py', '.java', '.js', '.html', '.css', '.xml', '.gradle', '.md', '.json', '.properties', '.txt'}
checked, failures = 0, []
for path in root.rglob('*'):
    if not path.is_file() or excluded.intersection(path.relative_to(root).parts):
        continue
    if path.name.startswith('.env') or path.name == 'note.txt' or path.suffix not in extensions:
        continue
    checked += 1
    source = path.read_text(encoding='utf-8', errors='replace')
    if any(value in source for value in needles):
        failures.append(str(path.relative_to(root)))
if not needles:
    raise SystemExit('No configured secrets available to compare; check not performed.')
print(f'Compared configured secrets against {checked} source/documentation files.')
for failure in failures:
    print('Configured secret found in: ' + failure)
if failures:
    raise SystemExit(1)
print('No configured installation secrets found in checked source files. This is not a general secret scanner.')
