#!/usr/bin/env python3
"""
generate_feed_from_tilda.py

Парсер для распакованной папки Tilda -> Yandex.Direct торговые объявления (feed.xml)
- Ищет HTML-файлы в указанной папке (rec/, pages/ и т.п.).
- Для каждой найденной карточки пытается извлечь: id, name, url, price, currencyId, picture, category, description.
- description ставится одинаковый для всех товаров (константа DESCRIPTION_CONST).
- Результат: feed.xml в текущей директории.

Запуск:
    python3 generate_feed_from_tilda.py --input-dir ./site_unpacked --base-url https://example.com

Примечания:
- Скрипт не загружает изображения — он подставляет абсолютные URL, составленные из base-url + относительного пути, встречающегося в HTML (например images/...).
- Если в HTML нет цены — товар пропускается (или ставится price=0, опция).
"""

import argparse
import os
import re
import sys
import uuid
from html import unescape
from pathlib import Path
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

DESCRIPTION_CONST = "Бесплатная техподдержка на весь срок. Доставка РФ. В наличии и на заказ. Гарантия."
DEFAULT_CURRENCY = "RUR"

def find_html_files(root: Path):
    exts = {'.html', '.htm'}
    for p in root.rglob('*'):
        if p.suffix.lower() in exts:
            yield p


def extract_text(el):
    return '' if el is None else ' '.join(el.stripped_strings)


def guess_price(text):
    # простая регулярка для чисел, возможны форматы 1 234, 1234.56, 1234
    if not text:
        return None
    m = re.search(r"(\d[\d\s]{0,6}(?:[.,]\d{1,2})?)", text)
    if not m:
        return None
    price = m.group(1).replace(' ', '').replace(',', '.')
    try:
        return str(int(float(price)))
    except Exception:
        try:
            return price
        except Exception:
            return None


def make_absolute_url(base_url, rel_path):
    if not rel_path:
        return ''
    rel = rel_path.strip()
    if rel.startswith('http://') or rel.startswith('https://'):
        return rel
    if rel.startswith('/'):
        return base_url.rstrip('/') + rel
    return base_url.rstrip('/') + '/' + rel


def parse_html_file(path: Path, base_url: str):
    text = path.read_text(encoding='utf-8', errors='ignore')
    soup = BeautifulSoup(text, 'lxml')

    items = []

    # Strategy: look for common Tilda product blocks: elements with data-attr like data-product-id, t-store, t-store__item, or blocks with class t-store__item or t-record
    # 1) search for elements with data-product-id or data-product
    for el in soup.select('[data-product-id], [data-product]'):
        items.append(el)

    # 2) t-store items
    items += soup.select('.t-store__item, .t-store-item, .t-shop__item, .t-product')

    # 3) cards inside blocks: look for .t-item or .js-product
    items += soup.select('.t-item, .js-product, .product, .product-item')

    # fall back: if page looks like single product page, try to extract from meta and main blocks
    if not items:
        # heuristic: find main title and price elements
        title = soup.find(['h1', 'h2', 'h3'], class_=re.compile('title|t-title|product', re.I))
        if not title:
            title = soup.find(['h1', 'h2', 'h3'])
        price_el = soup.find(text=re.compile('Цена|Стоимость|₽|руб', re.I))
        image = soup.find('img')
        if title:
            items = [soup]

    parsed = []
    seen = set()

    for el in items:
        try:
            # name
            name = None
            # attempt common selectors
            sel_title = el.select_one('.t-name, .t-store__title, .t-store__name, .product-name, .title, h3, h2, h1')
            if sel_title:
                name = extract_text(sel_title)
            else:
                # try meta
                meta_title = soup.find('meta', property='og:title') or soup.find('meta', attrs={'name':'title'})
                name = meta_title['content'] if meta_title and meta_title.get('content') else None

            if not name:
                continue

            # id
            pid = None
            if el.has_attr('data-product-id'):
                pid = el['data-product-id']
            elif el.has_attr('data-pid'):
                pid = el['data-pid']
            else:
                # try link or generate from name
                link = el.find('a', href=True)
                if link:
                    pid = re.sub('[^0-9a-zA-Z_-]', '', os.path.basename(link['href'])) or None
                if not pid:
                    pid = str(uuid.uuid5(uuid.NAMESPACE_URL, name))[:16]

            if pid in seen:
                continue
            seen.add(pid)

            # url
            url = None
            link = el.find('a', href=True)
            if link:
                url = make_absolute_url(base_url, link['href'])
            else:
                # if element is the whole page, use canonical or base
                can = soup.find('link', rel='canonical')
                if can and can.get('href'):
                    url = can['href']
                else:
                    url = base_url

            # price
            price = None
            # check common price selectors or text
            price_sel = el.select_one('.t-store__price, .price, .product-price, .t-price')
            if price_sel:
                price = guess_price(extract_text(price_sel))
            else:
                # search nearby text
                txt = el.get_text(separator=' ')
                price = guess_price(txt)
                if not price:
                    # search entire page
                    price = guess_price(soup.get_text())

            # picture
            pic = None
            img = el.find('img')
            if img and img.get('src'):
                pic = make_absolute_url(base_url, img['src'])
            else:
                # try meta og:image
                og = soup.find('meta', property='og:image')
                if og and og.get('content'):
                    pic = make_absolute_url(base_url, og['content'])

            # category: try breadcrumbs or section title
            cat = None
            bc = soup.select_one('.t-breadcrumbs, .breadcrumbs, .t-records__crumbs')
            if bc:
                cat = extract_text(bc)
            else:
                # try parent page title from h1 in the page
                page_h1 = soup.find('h1')
                if page_h1:
                    cat = extract_text(page_h1)
            # description: constant
            desc = DESCRIPTION_CONST

            parsed.append({
                'id': pid,
                'name': unescape(name).strip(),
                'url': url,
                'price': price or '0',
                'currencyId': DEFAULT_CURRENCY,
                'picture': pic or '',
                'category': (cat or '').strip(),
                'description': desc,
            })
        except Exception as e:
            # skip element on error
            print('Warning: skip element', e, file=sys.stderr)
            continue

    return parsed


def build_yml(shop_name, shop_url, offers):
    # build simple Yandex.Direct YML (yml_catalog-like)
    # We'll construct XML with root yml_catalog/shop/offers/offer
    root = ET.Element('yml_catalog', date='2020-01-01 00:00')
    shop = ET.SubElement(root, 'shop')
    ET.SubElement(shop, 'name').text = shop_name
    ET.SubElement(shop, 'company').text = shop_name
    ET.SubElement(shop, 'url').text = shop_url

    offers_el = ET.SubElement(shop, 'offers')

    for o in offers:
        offer = ET.SubElement(offers_el, 'offer', id=str(o['id']))
        ET.SubElement(offer, 'url').text = o['url']
        ET.SubElement(offer, 'price').text = str(o.get('price','0'))
        ET.SubElement(offer, 'currencyId').text = o.get('currencyId', DEFAULT_CURRENCY)
        ET.SubElement(offer, 'category').text = o.get('category','')
        ET.SubElement(offer, 'picture').text = o.get('picture','')
        ET.SubElement(offer, 'name').text = o.get('name','')
        ET.SubElement(offer, 'description').text = o.get('description','')

    return ET.tostring(root, encoding='utf-8', method='xml')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-dir', '-i', required=True, help='Путь к распакованной папке Tilda')
    parser.add_argument('--base-url', '-b', required=True, help='Базовый URL для составления абсолютных ссылок (например https://sto.cross-export.ru)')
    parser.add_argument('--shop-name', default='My Shop', help='Название магазина в фиде')
    parser.add_argument('--out', '-o', default='feed.xml', help='Имя выходного файла (feed.xml)')
    args = parser.parse_args()

    root = Path(args.input_dir)
    if not root.exists():
        print('Input dir not found:', root)
        sys.exit(1)

    all_offers = []
    for html_path in find_html_files(root):
        parsed = parse_html_file(html_path, args.base_url)
        if parsed:
            all_offers.extend(parsed)

    # deduplicate by id, keep first
    byid = {}
    for o in all_offers:
        if o['id'] not in byid:
            byid[o['id']] = o

    offers = list(byid.values())
    print(f'Found {len(offers)} offers')

    xmlbytes = build_yml(args.shop_name, args.base_url, offers)
    Path(args.out).write_bytes(xmlbytes)
    print('Wrote', args.out)

if __name__ == '__main__':
    main()
