"""Build names and classifications only; live market prices are never bundled."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'data/market_catalog.json.gz')
    options = parser.parse_args()
    sources = {}
    def read(name):
        data = (options.input_dir / (name + '.json')).read_bytes()
        sources[name] = {'url': 'https://tool.lzpoke.com/data/' + name + '.json',
                         'sha256': hashlib.sha256(data).hexdigest()}
        return json.loads(data)
    categories = {'berry': '树果', 'capture_ball': '捕捉球', 'breeding_item': '培育道具',
                  'cosmetic': '时装', 'mystery_box_or_event_box': '礼盒'}
    by_name = {item['name']: categories[item['category']] for item in read('full-item-dex')['items']
               if item.get('category') in categories}
    items = {item['id']: {'id': item['id'], 'name': item['name'],
                         'category': by_name.get(item['name'], '其他')}
             for item in read('items')}
    for item in read('cosmetics')['items']:
        item_id = item.get('market_item_id')
        if item_id:
            record = items.setdefault(item_id, {'id': item_id, 'name': item['name']})
            record.update(category='时装', english_name=item.get('english_name', ''),
                          slot=item.get('slot_name', ''))
    tiers = {item['monsterId']: item for item in read('pvp-tiers')['entries']}
    monsters = []
    for item in read('monsters'):
        if not 1 <= item['id'] <= 649:
            continue
        tier = tiers.get(item['id'], {})
        monsters.append({'id': item['id'], 'name': item['name'], 'english_name': tier.get('en', ''),
                         'egg_groups': item.get('egg_groups', []),
                         'evolutions': [e['id'] for e in item.get('evolutions', [])],
                         'tiers': tier.get('labels', [])})
    if len(monsters) != 649:
        raise ValueError('Incomplete market species catalogue')
    result = {'schema': 1, 'collected_at': '2026-10-12', 'sources': sources,
              'items': sorted(items.values(), key=lambda item: item['id']), 'monsters': monsters}
    options.output.write_bytes(gzip.compress(json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode(), mtime=0))
    print(json.dumps({'items': len(items), 'monsters': len(monsters),
                      'categories': Counter(item['category'] for item in items.values()),
                      'bytes': options.output.stat().st_size}, ensure_ascii=False))


if __name__ == '__main__':
    main()
