#!/usr/bin/env python3
"""
clean_feed.py
- adds XML declaration
- replaces currencyId RUR -> RUB
- removes service/contact offers by id (politika, tel..., crossexport, order ...)
- removes offers with empty category
- removes offers with price <= 0
- pretty-prints and creates preview.csv (id,name,price,url,category)
Usage:
python clean_feed.py feed.xml
Outputs:
feed.cleaned.xml and preview.csv
"""
import sys
import re
import xml.etree.ElementTree as ET
import csv
from pathlib import Path

if len(sys.argv) < 2:
    print('Usage: python clean_feed.py feed.xml')
    sys.exit(2)

infile = Path(sys.argv[1])
if not infile.exists():
    print('File not found:', infile)
    sys.exit(2)

outfile = infile.with_name('feed.cleaned.xml')
preview_csv = infile.with_name('preview.csv')

# IDs or patterns to remove (case-insensitive)
bad_id_re = re.compile(r'(politika|^tel|crossexport|order|^tel\+?|^tel:)', re.I)

# parse with utf-8
parser = ET.XMLParser(encoding='utf-8')
try:
    tree = ET.parse(str(infile), parser=parser)
except Exception as e:
    print('XML parse error:', e)
    sys.exit(3)

root = tree.getroot()

offers_parent = root.find('.//offers')
if offers_parent is None:
    print('No <offers> element found')
    sys.exit(4)

offers = list(offers_parent.findall('offer'))
kept = []
removed_count = 0

for o in offers:
    oid = (o.get('id') or '').strip()
    # remove by id pattern
    if bad_id_re.search(oid):
        removed_count += 1
        offers_parent.remove(o)
        continue
    # remove if category empty or missing
    cat = (o.findtext('category') or '').strip()
    if cat == '':
        removed_count += 1
        offers_parent.remove(o)
        continue
    # price check
    price_text = (o.findtext('price') or '').strip()
    try:
        price_val = float(price_text.replace(',', '.')) if price_text != '' else 0.0
    except Exception:
        price_val = 0.0
    if price_val <= 0:
        removed_count += 1
        offers_parent.remove(o)
        continue
    # normalize currencyId
    cur = o.find('currencyId')
    if cur is not None and (cur.text or '').strip().upper() == 'RUR':
        cur.text = 'RUB'
    kept.append(o)

# pretty print
def indent(elem, level=0):
    i = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        for e in elem:
            indent(e, level + 1)
        if not e.tail or not e.tail.strip():
            e.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i

indent(root)

# write with declaration
xml_bytes = ET.tostring(root, encoding='utf-8')
with open(outfile, 'wb') as f:
    f.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
    f.write(xml_bytes)

# write preview.csv
with open(preview_csv, 'w', newline='', encoding='utf-8') as cf:
    w = csv.writer(cf)
    w.writerow(['id','name','price','url','category'])
    for o in kept:
        oid = o.get('id','')
        name = (o.findtext('name') or '').strip()
        price = (o.findtext('price') or '').strip()
        url = (o.findtext('url') or '').strip()
        cat = (o.findtext('category') or '').strip()
        w.writerow([oid, name, price, url, cat])

print(f'Processed {len(offers)} offers, kept {len(kept)}, removed {removed_count}.')
print('Saved:', outfile, 'and', preview_csv)