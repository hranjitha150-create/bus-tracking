"""Move literal XML layout text to reusable Android string resources."""
from pathlib import Path
import re
import xml.etree.ElementTree as ET
ROOT = Path(__file__).resolve().parents[1] / 'app/src/main/res'
strings = ET.parse(ROOT / 'values/strings.xml').getroot()
known = {node.text: node.attrib['name'] for node in strings}
used = set(known.values())
for path in (ROOT / 'layout').glob('*.xml'):
    text = path.read_text(encoding='utf-8')
    def replace(match):
        value = match.group(2)
        if value.startswith(('@', '?')):
            return match.group(0)
        if value not in known:
            name = 'text_' + re.sub(r'[^a-z0-9]+', '_', value.lower()).strip('_')[:65]
            while name in used:
                name += '_alt'
            used.add(name)
            known[value] = name
            ET.SubElement(strings, 'string', name=name).text = value
        return f'android:{match.group(1)}="@string/{known[value]}"'
    text = re.sub(r'android:(text|hint|contentDescription)="([^"@?][^"]*)"', replace, text)
    # The theme provides the background; avoid painting it twice.
    text = text.replace(' android:background="@color/surface"', '')
    path.write_text(text, encoding='utf-8')
ET.indent(strings)
ET.ElementTree(strings).write(ROOT / 'values/strings.xml', encoding='utf-8', xml_declaration=True)
