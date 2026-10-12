"""Public lzpoke GTL snapshots and history, without login or game interaction."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from functools import lru_cache
from email.utils import parsedate_to_datetime
from http.client import HTTPException
import gzip
import json
import math
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request

from live_data import LiveClient, FeedError
from species_data import resource_path

BASE_URL = 'https://tool.lzpoke.com'
API_URL = BASE_URL + '/api/market-prices'
SOURCE_URLS = {'items': BASE_URL + '/market', 'pokemon': BASE_URL + '/market/pokemon'}
MAX_BYTES = 4 * 1024 * 1024
BEIJING = timezone(timedelta(hours=8))
EGG_GROUPS = dict(enumerate(('无性别', '怪兽组', '水中1组', '虫组', '飞行组', '陆上组',
                           '妖精组', '植物组', '人形组', '水中3组', '矿物组', '不定形组',
                           '水中2组', '百变怪', '龙组')))
STATS = {'hp': 'HP', 'atk': '攻击', 'def': '防御', 'spa': '特攻', 'spd': '特防', 'spe': '速度'}
FAMILY_SERIES = {'any': '最低价（不限条件）', 'male': '雄性（不限种类）', 'female': '雌性（不限种类）',
                 'alpha': '头目（不限性别）', 'shiny': '闪光（不限性别）', 'alpha_shiny': '头目闪光（不限性别）'}
PARTICLES = {0: '闪光质子', 2: '鬼火', 3: '蝙蝠', 4: '幽灵', 5: '眼瞳', 6: '欢乐南瓜王',
             7: '耀星', 8: '雪花', 9: '礼物', 10: '纸灯笼', 11: '烟花', 12: '恶臭', 13: '黑洞',
             14: '女巫的瘴气', 15: '南瓜小孩的款待', 16: '巫婆猫', 17: '南瓜猫', 18: '小白猫',
             19: '镰刀飞旋', 20: '蛛网', 21: '丧尸之握', 22: '生肖', 23: '狼嚎', 24: '墓地',
             25: '帝殒', 26: '赤龙', 27: '周年蛋糕', 28: '关都伙伴', 29: '闪光关都伙伴',
             30: '鬼盆栽', 31: '闪光鬼盆栽', 32: '圣诞装饰', 33: '春精灵', 35: '幽灵猫',
             36: '闪光幽灵猫', 37: '暗晶', 38: '闪光暗晶', 39: '白莲花', 40: '血莲花'}


class MarketError(FeedError):
    pass


def timestamp(value):
    if value is None or value == '':
        return None
    if not isinstance(value, str) or len(value) > 64:
        raise MarketError('行情时间格式已变化。')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError('Timezone missing')
        return result.timestamp()
    except (ValueError, OverflowError, OSError):
        raise MarketError('行情时间格式已变化。') from None


def number(value, *, optional=True):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or value > 10**15 or int(value) != value:
        raise MarketError('行情数值格式已变化。')
    return int(value)


def text(value, limit=160):
    if not isinstance(value, str) or len(value) > limit:
        raise MarketError('行情资料格式已变化。')
    return value


@dataclass(frozen=True)
class Quote:
    price: int | None
    quantity: int | None
    listings: int | None
    at: float | None
    stale: bool = False
    provided: bool = True

    @classmethod
    def parse(cls, row):
        if not isinstance(row, dict):
            raise MarketError('行情资料格式已变化。')
        return cls(number(row.get('price')), number(row.get('quantity', row.get('listings'))),
                   number(row.get('listings')), timestamp(row.get('at')), row.get('stale') is True)


MISSING = Quote(None, None, None, None, provided=False)


@dataclass(frozen=True)
class Snapshot:
    items: dict[int, Quote]
    queries: dict[tuple[int, str], Quote]
    updated_at: float | None
    source_at: float | None
    stale: bool
    interval: int
    minimum_interval: int
    payload: dict


def parse_snapshot(value):
    if not isinstance(value, dict) or not isinstance(value.get('items'), list) or not isinstance(value.get('pokemonQueries'), list):
        raise MarketError('行情接口格式已变化，请查看来源网页。')
    items, queries = {}, {}
    if len(value['items']) > 15000 or len(value['pokemonQueries']) > 30000:
        raise MarketError('行情资料过大，已停止读取。')
    for row in value['items']:
        if not isinstance(row, dict):
            raise MarketError('道具行情格式已变化。')
        item_id = number(row.get('itemId'), optional=False)
        if not item_id or item_id in items:
            raise MarketError('道具行情编号不正确。')
        items[item_id] = Quote.parse(row)
    for row in value['pokemonQueries']:
        if not isinstance(row, dict):
            raise MarketError('宝可梦行情格式已变化。')
        key = (number(row.get('familyId'), optional=False), text(row.get('query'), 90))
        if key in queries:
            raise MarketError('宝可梦行情条件重复。')
        queries[key] = Quote.parse(row)
    def interval(key, default, low):
        val = number(value.get(key, default * 1000), optional=False)
        return max(low, min(3600, val // 1000))
    payload = {key: value.get(key) for key in ('updatedAt', 'refreshedAt', 'sourceUpdatedAt', 'pokemonUpdatedAt', 'stale')}
    for key in ('updatedAt', 'refreshedAt', 'sourceUpdatedAt', 'pokemonUpdatedAt'):
        timestamp(payload[key])
    payload['stale'] = value.get('stale') is True
    payload.update(refreshIntervalMs=interval('refreshIntervalMs', 600, 60) * 1000,
                   refreshIntervalMinMs=interval('refreshIntervalMinMs', 60, 15) * 1000)
    def cache_quote(quote):
        return {'price': quote.price, 'quantity': quote.quantity, 'listings': quote.listings,
                'at': datetime.fromtimestamp(quote.at, timezone.utc).isoformat() if quote.at is not None else None,
                'stale': quote.stale}
    payload['items'] = [dict(itemId=key, **cache_quote(quote)) for key, quote in items.items()]
    payload['pokemonQueries'] = [dict(familyId=key[0], query=key[1], **cache_quote(quote)) for key, quote in queries.items()]
    return Snapshot(items, queries, timestamp(value.get('refreshedAt') or value.get('updatedAt')),
                    timestamp(value.get('sourceUpdatedAt') or value.get('pokemonUpdatedAt')),
                    value.get('stale') is True, interval('refreshIntervalMs', 600, 60),
                    interval('refreshIntervalMinMs', 60, 15), payload)


@dataclass(frozen=True)
class MarketRow:
    key: str
    name: str
    category: str
    quote: Quote
    chart: str
    series: str
    item_id: int | None = None
    search: str = ''

    @property
    def series_choices(self):
        if self.chart.startswith('family:'):
            return FAMILY_SERIES
        if self.chart.startswith('egg:'):
            group = int(self.chart.split(':')[1])
            return {'all': '不限性别'} if group in (0, 13) else {'male': '雄性', 'female': '雌性'}
        if self.chart.startswith('particle:'):
            return {'normal': '普通', 'alpha': '头目', 'shiny': '闪光', 'alpha_shiny': '头目闪光'}
        return {self.series: '当前报价'}


@lru_cache(maxsize=1)
def load_catalog():
    with gzip.open(resource_path('data', 'market_catalog.json.gz'), 'rt', encoding='utf-8') as stream:
        value = json.load(stream)
    if value.get('schema') != 1 or len(value.get('monsters', [])) != 649:
        raise MarketError('道具与宝可梦名称资料不完整，请重新下载软件。')
    value['items_by_id'] = {item['id']: item for item in value['items']}
    value['monsters_by_id'] = {item['id']: item for item in value['monsters']}
    adjacency = {item['id']: set() for item in value['monsters']}
    for item in value['monsters']:
        for target in item['evolutions']:
            if target in adjacency:
                adjacency[item['id']].add(target)
                adjacency[target].add(item['id'])
    families, seen = {}, set()
    for start in adjacency:
        if start in seen:
            continue
        stack, members = [start], []
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            members.append(current)
            stack.extend(adjacency[current] - seen)
        families[min(members)] = [value['monsters_by_id'][i] for i in sorted(members)]
    value['families'] = families
    return value


def normalized(value):
    return ''.join(value.casefold().split())


def item_rows(snapshot, catalog, search='', category='全部分类'):
    query = normalized(search)
    result = []
    for item_id, quote in snapshot.items.items():
        info = catalog['items_by_id'].get(item_id, {'name': f'道具 #{item_id}', 'category': '其他'})
        kind = info['category']
        keywords = f"{info['name']} {info.get('english_name', '')} {item_id}"
        if query not in normalized(keywords) or category != '全部分类' and category != kind:
            continue
        label = kind + (' · ' + info['slot'] if info.get('slot') else '')
        result.append(MarketRow(f'item:{item_id}', info['name'], label, quote, '', '', item_id, keywords))
    return result


def pokemon_rows(snapshot, catalog, *, mode='进化族群', search='', variant='全部', gender='不限性别', egg_group='全部蛋组', tier='全部分级'):
    query = normalized(search)
    group = None if egg_group == '全部蛋组' else egg_group
    flags = {'全部': '', '头目': 'alpha', '闪光': 'shiny', '头目闪光': 'alpha_shiny'}[variant]
    sex = {'不限性别': '', '雄性': 'male', '雌性': 'female'}[gender]
    condition = '_'.join(filter(None, (flags, sex))) or 'any'
    result = []
    if mode == '蛋组1V':
        for group_id, name in EGG_GROUPS.items():
            if group is not None and group != name:
                continue
            genders = ('all',) if group_id in (0, 13) else ('male', 'female')
            for stat, stat_name in STATS.items():
                for series in genders:
                    if sex and series != sex:
                        continue
                    label = '不限性别' if series == 'all' else '雄性' if series == 'male' else '雌性'
                    name_text = f'{name} 1V {stat_name}'
                    if query not in normalized(name_text):
                        continue
                    quote_key = f'egg:{group_id}:iv_{stat}' + ('' if series == 'all' else ':' + series)
                    quote = snapshot.queries.get((0, quote_key), MISSING)
                    result.append(MarketRow(quote_key, name_text, label, quote, f'egg:{group_id}:{stat}', series))
        return result
    if mode == '粒子':
        for (family_id, key), quote in snapshot.queries.items():
            match = re.fullmatch(r'(alpha_shiny_|alpha_|shiny_)?particle:(\d+)', key)
            if family_id or not match:
                continue
            particle_id = int(match[2])
            if particle_id in (1, 34):
                continue
            prefix = (match[1] or '').rstrip('_')
            if flags and flags != prefix:
                continue
            name = PARTICLES.get(particle_id, f'粒子 #{particle_id}')
            if query not in normalized(f'{name} {particle_id}'):
                continue
            label = {'': '普通', 'alpha': '头目', 'shiny': '闪光', 'alpha_shiny': '头目闪光'}[prefix]
            result.append(MarketRow(key, name, label, quote, f'particle:{particle_id}', prefix or 'normal'))
        return result
    ids = sorted({family for family, key in snapshot.queries if family > 0 and
                  (key == 'species' if mode == '单种宝可梦' else key != 'species')})
    for item_id in ids:
        info = catalog['monsters_by_id'].get(item_id, {'id': item_id, 'name': f'宝可梦 #{item_id}', 'egg_groups': [], 'tiers': []})
        members = [info] if mode == '单种宝可梦' else catalog['families'].get(item_id, [info])
        keywords = ' '.join(f"{item['name']} {item.get('english_name', '')} {item['id']}" for item in members)
        if query not in normalized(keywords) or group is not None and not any(group in item['egg_groups'] for item in members):
            continue
        if tier != '全部分级' and not any(tier in item.get('tiers', []) for item in members):
            continue
        key = 'species' if mode == '单种宝可梦' else condition
        quote = snapshot.queries.get((item_id, key), MISSING)
        groups = ' / '.join(dict.fromkeys(group for item in members for group in item['egg_groups']))
        name = ' / '.join(item['name'] for item in members)
        series = 'species' if key == 'species' else flags or sex or 'any'
        result.append(MarketRow(f'{mode}:{item_id}:{key}', name, groups, quote,
                                f'species:{item_id}' if mode == '单种宝可梦' else f'family:{item_id}', series, search=keywords))
    return result


def sorted_rows(rows, column='price', descending=False):
    def key(row):
        return {'name': row.name, 'category': row.category, 'price': row.quote.price,
                'quantity': row.quote.quantity, 'at': row.quote.at}.get(column)
    known = [row for row in rows if key(row) is not None]
    missing = [row for row in rows if key(row) is None]
    return sorted(known, key=key, reverse=descending) + missing


def quote_state(quote, *, now=None):
    if not quote.provided:
        return '未提供此条件'
    if quote.stale or quote.at is not None and (time.time() if now is None else now) - quote.at > 86400:
        return '旧数据'
    if quote.price is None:
        return '暂无挂牌' if quote.quantity == 0 else '暂无报价'
    return '有报价'


def format_price(value):
    return '—' if value is None else f'{value:,}'


def format_time(value):
    return '时间未知' if value is None else datetime.fromtimestamp(value, BEIJING).strftime('%m-%d %H:%M')


@dataclass(frozen=True)
class HistoryPoint:
    at: float
    price: int | None
    quantity: int | None


def parse_history(value, *, chart='', series=''):
    if not isinstance(value, dict) or not isinstance(value.get('history'), list) or len(value['history']) > 100000:
        raise MarketError('历史行情格式已变化。')
    if chart and (value.get('chart') != chart or value.get('series') != series):
        raise MarketError('网站未提供该条件的历史走势。')
    points = {}
    for row in value['history']:
        quote = Quote.parse(row)
        if quote.at is not None:
            points[quote.at] = HistoryPoint(quote.at, quote.price, quote.quantity)
    return tuple(points[key] for key in sorted(points))


def candles(points, interval=86400):
    buckets = {}
    for point in points:
        if point.price is None:
            continue
        bucket = int((point.at + 8 * 3600) // interval) * interval - 8 * 3600
        buckets.setdefault(bucket, []).append(point)
    return tuple((at, values[0].price, max(p.price for p in values), min(p.price for p in values), values[-1].price)
                 for at, values in sorted(buckets.items()))


class MarketClient:
    def __init__(self, opener=None):
        self.opener = opener if opener is not None else LiveClient().opener

    def _get(self, query=None):
        url = API_URL + ('?' + urlencode(query) if query else '')
        request = Request(url, headers={'User-Agent': 'PokeMMO-Breeder-Helper/0.2.31',
                                        'Accept': 'application/json', 'Accept-Encoding': 'identity'})
        try:
            with self.opener.open(request, timeout=18) as response:
                if urlsplit(response.url).scheme != 'https' or urlsplit(response.url).hostname != 'tool.lzpoke.com':
                    raise MarketError('行情来源地址已变化。')
                content = response.read(MAX_BYTES + 1)
                if len(content) > MAX_BYTES:
                    raise MarketError('行情资料过大，已停止读取。')
            value = json.loads(content.decode('utf-8-sig'))
            if not isinstance(value, dict) or value.get('error'):
                raise MarketError('网站暂时无法提供行情，请稍后重试。')
            return value
        except HTTPError as error:
            delay = error.headers.get('Retry-After', '') if error.headers else ''
            retry = max(60, int(delay)) if delay.isdigit() else 60 if error.code == 429 else 0
            if delay and not delay.isdigit():
                try:
                    retry = max(60, int(parsedate_to_datetime(delay).timestamp() - time.time()))
                except (ValueError, TypeError, OverflowError):
                    pass
            raise MarketError('请求过于频繁，请稍后刷新。' if error.code == 429 else f'行情服务暂时不可用（{error.code}）。', retry) from None
        except (URLError, TimeoutError, OSError, HTTPException):
            raise MarketError('行情连接失败，请检查网络。') from None
        except (UnicodeError, json.JSONDecodeError):
            raise MarketError('行情接口返回了无法识别的数据。') from None

    def snapshot(self):
        return parse_snapshot(self._get())

    def history(self, row, series):
        if series not in row.series_choices:
            raise MarketError('请选择可用的历史条件。')
        query = {'itemId': str(row.item_id)} if row.item_id is not None else {'chart': row.chart, 'series': series}
        return parse_history(self._get(query), chart=row.chart, series=series)


def save_cache(path, snapshot, fetched_at):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    data = {'schema': 1, 'fetched_at': fetched_at, 'payload': snapshot.payload}
    temporary.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def load_cache(path):
    try:
        if path.stat().st_size > MAX_BYTES * 2:
            return None
        value = json.loads(path.read_text(encoding='utf-8'))
        fetched_at = value.get('fetched_at')
        if value.get('schema') != 1 or isinstance(fetched_at, bool) or not isinstance(fetched_at, (int, float)) or not math.isfinite(fetched_at):
            return None
        return parse_snapshot(value['payload']), fetched_at
    except (OSError, ValueError, KeyError, TypeError):
        return None
