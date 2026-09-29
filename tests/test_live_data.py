from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

from live_data import (
    AlphaReport, CaveRotation, FeedError, LiveClient, alpha_status, cave_status,
    load_cache, location_label, parse_alpha, parse_cave, save_cache, next_cave_refresh, cave_refresh_time,
)

ALPHA_HTML = '''<span id="latestPingTime">2026-09-28 19:24:38 UTC (UTC+00:00)</span>
<p id="latestPingValue" data-raw-pokemon="Salamence"><a href="/pokedex/373">Salamence</a></p>
<div id="latestPingDetailsContainer"><span data-region="Hoenn">Hoenn</span><br>
<span data-location="Sky Pillar">Sky Pillar</span>
<a href="/alpha-list?pokemon=Salamence&region=Hoenn&location=Sky+Pillar&timestamp=1790627978">Open</a></div>'''
CAVE_DATA = {"altering_cave": {"gem_type": "Bug", "singles": ["Venomoth", "Ferroseed", "Duosion", "Parasect", "Staryu"],
                              "rare_singles": ["Ninjask", "Larvesta"], "hordes": ["Shellos", "Pinsir"]}}
CAVE_HTML = '<script id="rotations-data" type="application/json">' + json.dumps(CAVE_DATA) + '</script><script>window.ROTATION_WINDOW_KEY = "20260929-0";</script>'


class LiveDataTests(unittest.TestCase):
    def test_fixed_cave_times_cover_all_slots_midnight_and_exact_boundaries(self):
        for hour, expected in ((17, "09-29 02:00"), (18, "09-29 08:00"), (23, "09-29 08:00")):
            instant = datetime(2026, 9, 28, hour, tzinfo=timezone.utc).timestamp()
            self.assertEqual(cave_refresh_time(next_cave_refresh(instant)), expected)
        for hour, expected in ((0, "09-29 14:00"), (6, "09-29 20:00"), (12, "09-30 02:00"), (18, "09-30 08:00")):
            instant = datetime(2026, 9, 29, hour, tzinfo=timezone.utc).timestamp()
            self.assertEqual(cave_refresh_time(next_cave_refresh(instant)), expected)
            self.assertEqual(next_cave_refresh(instant - 0.1), instant)

    def test_alpha_raw_ampersands_preserve_despawn_timestamp(self):
        report = parse_alpha(ALPHA_HTML)
        self.assertEqual(report.species_id, 373)
        self.assertEqual(report.expires_at, 1790627978)
        self.assertEqual(report.expires_at - report.reported_at, 75 * 60)
        self.assertEqual(location_label(report.region, report.location), "丰缘 · 天空之柱")
        self.assertEqual(parse_alpha(ALPHA_HTML.replace("&", "&amp;")), report)

    def test_ended_and_unknown_alpha_never_shown_as_active(self):
        report = parse_alpha(ALPHA_HTML)
        self.assertIn("预计仍在出现", alpha_status(report, report.expires_at - 1))
        self.assertIn("预计已结束", alpha_status(report, report.expires_at))
        unknown = parse_alpha(ALPHA_HTML.replace("timestamp=1790627978", "unused=1790627978"))
        self.assertIn("待确认", alpha_status(unknown, 1790625000))
        self.assertIn("时间异常", alpha_status(report, report.reported_at - 1000))

    def test_cave_categories_and_utc_window(self):
        cave = parse_cave(CAVE_HTML)
        self.assertEqual(cave.singles[0], "Venomoth")
        self.assertEqual(cave.hordes, ("Shellos", "Pinsir"))
        self.assertEqual(cave.expires_at - cave.starts_at, 21600)
        self.assertEqual(cave.starts_at, datetime(2026, 9, 29, tzinfo=timezone.utc).timestamp())
        self.assertIn("已结束", cave_status(cave, cave.expires_at))
        self.assertIn("尚未开始", cave_status(cave, cave.starts_at - 1))

    def test_missing_or_changed_source_is_error_not_empty_current_data(self):
        for parser, html in ((parse_alpha, "<h1>Access denied</h1>"),
                             (parse_alpha, ALPHA_HTML.replace("data-location", "removed-location")),
                             (parse_cave, CAVE_HTML.replace("rotations-data", "new-data")),
                             (parse_cave, CAVE_HTML.replace("20260929-0", "20260999-0")),
                             (parse_cave, CAVE_HTML.replace('"Pinsir"', 'null'))):
            with self.subTest(parser=parser.__name__, html=html[:30]), self.assertRaises(FeedError):
                parser(html)

    def test_cave_unreported_slots_are_preserved(self):
        report = parse_cave(CAVE_HTML.replace('"Venomoth"', '""'))
        self.assertEqual(report.singles[0], "")
        self.assertEqual(len(report.singles), 5)

    def test_network_timeouts_and_rate_limit_are_user_readable(self):
        opener = Mock()
        opener.open.side_effect = URLError("private proxy credentials should never appear")
        with self.assertRaises(FeedError) as result:
            LiveClient(opener).fetch("alpha")
        self.assertNotIn("credentials", str(result.exception))
        opener.open.side_effect = HTTPError("https://alpha.pokemmotools.org/", 429, "limit", {"Retry-After": "600"}, BytesIO())
        with self.assertRaises(FeedError) as result:
            LiveClient(opener).fetch("cave")
        self.assertEqual(result.exception.retry_after, 600)

    def test_network_reads_public_page_with_bounded_size_and_timeout(self):
        response = BytesIO(ALPHA_HTML.encode())
        response.url = "https://alpha.pokemmotools.org/"
        opener = Mock()
        opener.open.return_value = response
        self.assertEqual(LiveClient(opener).fetch("alpha").species_id, 373)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 12)

    def test_cache_roundtrip_preserves_original_fetch_time_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "live.json"
            verified = time.time() - 1000
            feeds = {"alpha": SimpleNamespace(data=parse_alpha(ALPHA_HTML), verified_at=verified),
                     "cave": SimpleNamespace(data=parse_cave(CAVE_HTML), verified_at=verified)}
            save_cache(path, feeds, 180, False)
            restored = load_cache(path)
            self.assertEqual(restored["interval"], 180)
            self.assertFalse(restored["auto"])
            self.assertEqual(restored["feeds"]["alpha"][1], verified)
            self.assertEqual(tuple(restored["feeds"]["cave"][0].hordes), ("Shellos", "Pinsir"))
            path.write_text('{bad json', encoding="utf-8")
            self.assertEqual(load_cache(path), {})
            path.write_text('[]', encoding="utf-8")
            self.assertEqual(load_cache(path), {})


if __name__ == "__main__":
    unittest.main()
