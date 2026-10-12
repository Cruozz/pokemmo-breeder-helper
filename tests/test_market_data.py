import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from market_data import (API_URL, MarketClient, MarketError, MISSING, Quote, HistoryPoint,
                         parse_snapshot, parse_history, load_catalog, item_rows, pokemon_rows,
                         sorted_rows, candles, save_cache, load_cache, quote_state, format_price)


def fixture():
    at = '2026-10-12T01:00:00Z'
    def query(family, key, price, quantity=2):
        return {'familyId': family, 'query': key, 'price': price, 'quantity': quantity, 'listings': quantity, 'at': at}
    return {'items': [{'itemId': 5229, 'price': 6000, 'quantity': 5, 'listings': 3, 'at': at},
                      {'itemId': 121, 'price': None, 'quantity': 0, 'listings': 0, 'at': at}],
            'pokemonQueries': [query(92, 'any', 1200, 10), query(92, 'male', 1400), query(92, 'alpha_female', 122222, 3),
                               query(94, 'species', 3000), query(0, 'egg:11:iv_hp:male', 4500),
                               query(0, 'egg:11:iv_hp:female', 5500), query(0, 'egg:13:iv_spe', 4000),
                               query(0, 'alpha_particle:18', 1000000)],
            'updatedAt': at, 'sourceUpdatedAt': at, 'stale': False,
            'refreshIntervalMs': 600000, 'refreshIntervalMinMs': 60000}


class MarketDataTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = parse_snapshot(fixture())
        self.catalog = load_catalog()

    def test_family_query_preserves_combined_gender_alpha_and_quantity(self):
        rows = pokemon_rows(self.snapshot, self.catalog, search='耿鬼', variant='头目', gender='雌性')
        self.assertEqual(len(rows), 1)
        self.assertIn('鬼斯', rows[0].name)
        self.assertEqual((rows[0].quote.price, rows[0].quote.quantity), (122222, 3))
        self.assertEqual((rows[0].chart, rows[0].series), ('family:92', 'alpha'))
        self.assertIn('不限性别', rows[0].series_choices['alpha'])

    def test_missing_condition_never_falls_back_to_any_or_zero(self):
        row = pokemon_rows(self.snapshot, self.catalog, search='耿鬼', variant='闪光')[0]
        self.assertIs(row.quote, MISSING)
        self.assertEqual(quote_state(row.quote), '未提供此条件')
        self.assertEqual(format_price(row.quote.price), '—')

    def test_no_listings_is_distinct_from_missing_and_real_zero(self):
        quote = self.snapshot.items[121]
        self.assertEqual(quote_state(quote, now=quote.at), '暂无挂牌')
        self.assertEqual(format_price(0), '0')
        self.assertEqual(format_price(None), '—')

    def test_species_mode_uses_specific_quote_not_family(self):
        rows = pokemon_rows(self.snapshot, self.catalog, mode='单种宝可梦', search='耿鬼', variant='头目')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].name, '耿鬼')
        self.assertEqual((rows[0].quote.price, rows[0].chart, rows[0].series), (3000, 'species:94', 'species'))

    def test_egg_stats_keep_sexes_and_genderless_ditto_separate(self):
        rows = pokemon_rows(self.snapshot, self.catalog, mode='蛋组1V', search='HP', egg_group='不定形组')
        self.assertEqual([(r.quote.price, r.series) for r in rows], [(4500, 'male'), (5500, 'female')])
        rows = pokemon_rows(self.snapshot, self.catalog, mode='蛋组1V', search='速度', egg_group='百变怪')
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].quote.price, rows[0].series), (4000, 'all'))

    def test_english_search_egg_group_and_tier_filters(self):
        self.assertEqual(len(pokemon_rows(self.snapshot, self.catalog, search='gEngar', egg_group='不定形组')), 1)
        self.assertEqual(pokemon_rows(self.snapshot, self.catalog, search='耿鬼', egg_group='飞行组'), [])
        self.assertEqual(len(pokemon_rows(self.snapshot, self.catalog, search='耿鬼', tier='LC')), 1)
        self.assertEqual(pokemon_rows(self.snapshot, self.catalog, mode='单种宝可梦', search='耿鬼', tier='LC'), [])

    def test_particles_have_their_own_chart_and_do_not_become_species(self):
        rows = pokemon_rows(self.snapshot, self.catalog, mode='粒子', search='小白猫', variant='头目')
        self.assertEqual([(r.name, r.chart, r.series) for r in rows], [('小白猫', 'particle:18', 'alpha')])

    def test_item_catalog_and_category_filter_cover_breeding_item(self):
        rows = item_rows(self.snapshot, self.catalog, search='不变之石', category='培育道具')
        self.assertEqual([(r.item_id, r.quote.price) for r in rows], [(5229, 6000)])
        self.assertEqual(item_rows(self.snapshot, self.catalog, category='时装'), [])

    def test_missing_prices_sort_last_in_both_directions(self):
        rows = item_rows(self.snapshot, self.catalog)
        for reverse in (False, True):
            self.assertIsNone(sorted_rows(rows, 'price', reverse)[-1].quote.price)

    def test_malformed_and_nonfinite_prices_are_rejected(self):
        for value in (-1, True, float('nan'), float('inf'), '123', []):
            bad = fixture()
            bad['items'][0]['price'] = value
            with self.subTest(value=value), self.assertRaises(MarketError):
                parse_snapshot(bad)
        with self.assertRaises(MarketError):
            parse_snapshot({'items': []})

    def test_duplicate_items_and_condition_keys_are_rejected(self):
        for key in ('items', 'pokemonQueries'):
            bad = fixture()
            bad[key].append(copy.deepcopy(bad[key][0]))
            with self.assertRaises(MarketError):
                parse_snapshot(bad)

    def test_history_default_series_cannot_silently_replace_requested_series(self):
        with self.assertRaises(MarketError):
            parse_history({'chart': 'family:92', 'series': 'any', 'history': []}, chart='family:92', series='alpha')

    def test_history_sorts_deduplicates_and_preserves_no_quote_gaps(self):
        history = {'history': [{'at': '2026-10-12T02:00:00Z', 'price': None},
                               {'at': '2026-10-12T01:00:00Z', 'price': 100},
                               {'at': '2026-10-12T01:00:00Z', 'price': 200}]}
        points = parse_history(history)
        self.assertEqual([point.price for point in points], [200, None])
        self.assertLess(points[0].at, points[1].at)

    def test_candles_use_open_high_low_close_and_skip_missing(self):
        points = tuple(HistoryPoint(100 + i, price, 1) for i, price in enumerate([20, 10, None, 35, 25]))
        values = candles(points, 86400)
        self.assertEqual(values[0][1:], (20, 35, 10, 25))

    def test_cache_roundtrip_and_corrupt_cache_are_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'market.json'
            save_cache(path, self.snapshot, 100)
            restored, fetched = load_cache(path)
            self.assertEqual(restored.items, self.snapshot.items)
            self.assertEqual(restored.queries, self.snapshot.queries)
            self.assertEqual(fetched, 100)
            path.write_text('{corrupt')
            self.assertIsNone(load_cache(path))


class MarketClientTests(unittest.TestCase):
    def response(self, value, url=API_URL):
        response = Mock(url=url)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps(value).encode()
        opener = Mock()
        opener.open.return_value = response
        return MarketClient(opener), opener

    def test_public_get_snapshot_and_bounded_response(self):
        client, opener = self.response(fixture())
        self.assertEqual(client.snapshot().items[5229].price, 6000)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), 'GET')
        self.assertIsNone(request.data)
        self.assertEqual(request.full_url, API_URL)
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 18)

    def test_history_parameters_are_encoded_and_combined_series_is_not_sent(self):
        snapshot = parse_snapshot(fixture())
        row = pokemon_rows(snapshot, load_catalog(), search='耿鬼', variant='头目', gender='雌性')[0]
        client, opener = self.response({'chart': 'family:92', 'series': 'alpha', 'history': []})
        client.history(row, 'alpha')
        query = parse_qs(urlsplit(opener.open.call_args.args[0].full_url).query)
        self.assertEqual(query, {'chart': ['family:92'], 'series': ['alpha']})
        with self.assertRaises(MarketError):
            client.history(row, 'alpha_female')

    def test_redirect_away_from_source_is_rejected(self):
        client, _ = self.response(fixture(), 'https://elsewhere.example/data')
        with self.assertRaises(MarketError):
            client.snapshot()

    def test_rate_limit_is_propagated_without_immediate_retry(self):
        client = MarketClient(Mock())
        client.opener.open.side_effect = HTTPError(API_URL, 429, 'rate limit', {'Retry-After': '120'}, None)
        with self.assertRaises(MarketError) as caught:
            client.snapshot()
        self.assertEqual(caught.exception.retry_after, 120)
        client.opener.open.assert_called_once()

    def test_oversized_response_and_bad_json_are_rejected(self):
        client, opener = self.response(fixture())
        opener.open.return_value.read.return_value = b' ' * (4 * 1024 * 1024 + 1)
        with self.assertRaises(MarketError):
            client.snapshot()
        opener.open.return_value.read.return_value = b'<html>unavailable</html>'
        with self.assertRaises(MarketError):
            client.snapshot()

    def test_long_server_backoff_is_not_shortened(self):
        client = MarketClient(Mock())
        client.opener.open.side_effect = HTTPError(API_URL, 429, 'rate limit', {'Retry-After': '7200'}, None)
        with self.assertRaises(MarketError) as caught:
            client.snapshot()
        self.assertEqual(caught.exception.retry_after, 7200)
