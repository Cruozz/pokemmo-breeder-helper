"""Read the two public Alphapedia pages; never execute remote scripts."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import ProxyHandler, Request, build_opener, getproxies

BASE_URL = "https://alpha.pokemmotools.org"
SOURCE_URLS = {"alpha": BASE_URL + "/", "cave": BASE_URL + "/rotations"}
MAX_RESPONSE_BYTES = 3 * 1024 * 1024
INTERVALS = {"30 秒": 30, "1 分钟": 60, "3 分钟": 180, "5 分钟": 300}
REGION_NAMES = {"Kanto": "关都", "Johto": "城都", "Hoenn": "丰缘", "Sinnoh": "神奥", "Unova": "合众"}
LOCATION_NAMES = {"Sky Pillar": "天空之柱", "New Mauville": "新紫堇", "Seafoam Islands": "双子岛",
                  "Victory Road": "冠军之路", "Mt. Moon": "月见山", "Rock Tunnel": "岩山隧道",
                  "Meteor Falls": "流星瀑布", "Abundant Shrine": "丰饶之祠"}


class FeedError(ValueError):
    def __init__(self, message: str, retry_after: int = 0):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(frozen=True)
class AlphaReport:
    name: str
    species_id: int | None
    region: str
    location: str
    reported_at: float | None
    expires_at: float | None


@dataclass(frozen=True)
class CaveRotation:
    window_key: str
    gem_type: str
    singles: tuple[str, ...]
    rare_singles: tuple[str, ...]
    hordes: tuple[str, ...]

    @property
    def starts_at(self) -> float:
        date, slot = self.window_key.split("-")
        return datetime.strptime(date, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp() + int(slot) * 21600

    @property
    def expires_at(self) -> float:
        return self.starts_at + 21600


class Node:
    def __init__(self, tag="", attrs=()):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []
        self.parts = []

    @property
    def text(self):
        return "".join(part.text if isinstance(part, Node) else part for part in self.parts).strip()

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def by_id(self, value):
        return next((node for node in self.walk() if node.attrs.get("id") == value), None)


class PageParser(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        # HTMLParser incorrectly reads raw '&timestamp' as '&times' + 'tamp'.
        # Preserve ambiguous query ampersands as browsers do in attributes.
        href = re.search(r'\bhref\s*=\s*(["\'])(.*?)\1', self.get_starttag_text(), re.I | re.S)
        if href:
            node.attrs["href"] = unescape(re.sub(r"&(?!(?:#[0-9]+|#x[0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]+);)", "&amp;", href[2]))
        self.stack[-1].children.append(node)
        self.stack[-1].parts.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].parts.append(data)


def _text(value, *, blank=True):
    if not isinstance(value, str) or len(value) > 160 or (not blank and not value.strip()):
        raise FeedError("网站资料格式已变化，请稍后重试或查看来源网页。")
    return " ".join(value.split())


def parse_alpha(html: str) -> AlphaReport:
    root = PageParser(html).root
    value = root.by_id("latestPingValue")
    detail = root.by_id("latestPingDetailsContainer")
    if value is None or detail is None:
        raise FeedError("未读取到头目资料，请稍后重试或查看来源网页。")
    name = _text(value.attrs.get("data-raw-pokemon", ""), blank=False)
    species_id = None
    for node in value.walk():
        match = re.fullmatch(r"/pokedex/(\d+)", node.attrs.get("href", ""))
        if match and 1 <= int(match[1]) <= 649:
            species_id = int(match[1])
    region = location = ""
    expires_at = None
    for node in detail.walk():
        if "data-region" in node.attrs:
            region = _text(node.attrs["data-region"])
        if "data-location" in node.attrs:
            location = _text(node.attrs["data-location"])
        url = urlsplit(node.attrs.get("href", ""))
        if url.path == "/alpha-list":
            timestamp = parse_qs(url.query).get("timestamp", [""])[0]
            if timestamp.isdigit() and 1_000_000_000 < int(timestamp) < 10_000_000_000:
                expires_at = float(timestamp)
    reported_at = None
    stamp = root.by_id("latestPingTime")
    # Only parse the explicitly labelled UTC timestamp, never the desktop timezone.
    match = re.search(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) UTC(?:\s|$)", stamp.text if stamp else "")
    if match:
        try:
            reported_at = datetime.strptime(match[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            pass
    if not region or not location:
        raise FeedError("头目地点资料不完整，请查看来源网页。")
    return AlphaReport(name, species_id, region, location, reported_at, expires_at)


def parse_cave(html: str) -> CaveRotation:
    root = PageParser(html).root
    node = root.by_id("rotations-data")
    match = re.search(r'window\.ROTATION_WINDOW_KEY\s*=\s*["\'](\d{8}-[0-3])["\']', html)
    if node is None or match is None:
        raise FeedError("未读取到当前洞窟轮换，请稍后重试或查看来源网页。")
    try:
        raw = json.loads(node.text)["altering_cave"]
        groups = []
        for key, count in (("singles", 5), ("rare_singles", 2), ("hordes", 2)):
            group = raw[key]
            if not isinstance(group, list) or len(group) != count:
                raise ValueError("unexpected encounter slots")
            groups.append(tuple(_text(name) for name in group))
        result = CaveRotation(match[1], _text(raw["gem_type"]), *groups)
        result.starts_at  # Validate the date before accepting the snapshot.
        return result
    except (KeyError, TypeError, ValueError) as error:
        raise FeedError("洞窟资料格式已变化，请查看来源网页。") from error


def location_label(region: str, location: str) -> str:
    route = re.fullmatch(r"Route (\d+)", location)
    place = f"{route[1]} 号道路" if route else LOCATION_NAMES.get(location, location)
    return f"{REGION_NAMES.get(region, region)} · {place}"


def local_time(timestamp: float | None) -> str:
    return datetime.fromtimestamp(timestamp).astimezone().strftime("%m-%d %H:%M") if timestamp else "未提供"


def alpha_status(report: AlphaReport, now: float) -> str:
    if report.reported_at is not None and report.reported_at > now + 120:
        return "时间异常，请核对电脑时间"
    if report.expires_at is None:
        return "结束时间未提供，当前是否出现待确认"
    if now >= report.expires_at:
        return "预计已结束 · 暂无新的头目上报"
    minutes = max(1, int((report.expires_at - now + 59) // 60))
    return f"预计仍在出现 · 约剩 {minutes} 分钟"


def cave_status(report: CaveRotation, now: float) -> str:
    if now < report.starts_at:
        return "该轮换尚未开始，请核对电脑时间"
    if now >= report.expires_at:
        return "该轮换已结束 · 等待新资料"
    return f"本轮 {local_time(report.starts_at)} — {local_time(report.expires_at)}"


class LiveClient:
    def __init__(self, opener=None):
        proxies = getproxies()
        fallback = os.environ.get("ALL_PROXY", "")
        if urlsplit(fallback).scheme in {"http", "https"}:
            proxies.setdefault("https", fallback)
        self.opener = opener if opener is not None else build_opener(ProxyHandler(proxies))

    def fetch(self, kind: str):
        request = Request(SOURCE_URLS[kind], headers={
            "User-Agent": "PokeMMO-Breeder-Helper/0.2.17 (+https://github.com/Cruozz/pokemmo-breeder-helper)",
            "Accept": "text/html", "Cache-Control": "no-cache", "Accept-Encoding": "identity",
        })
        try:
            with self.opener.open(request, timeout=12) as response:
                if urlsplit(response.url).hostname != "alpha.pokemmotools.org":
                    raise FeedError("来源网页地址已变化。")
                content = response.read(MAX_RESPONSE_BYTES + 1)
                if len(content) > MAX_RESPONSE_BYTES:
                    raise FeedError("网站返回内容过大，已停止读取。")
                html = content.decode("utf-8-sig")
            return parse_alpha(html) if kind == "alpha" else parse_cave(html)
        except HTTPError as error:
            delay = error.headers.get("Retry-After", "") if error.headers else ""
            retry = max(30, int(delay)) if delay.isdigit() else 0
            if delay and not delay.isdigit():
                try:
                    retry = max(30, int(parsedate_to_datetime(delay).timestamp() - time.time()))
                except (TypeError, ValueError, OverflowError):
                    pass
            message = "网站请求过于频繁，已延后重试。" if error.code == 429 else f"网站暂时不可用（{error.code}）。"
            raise FeedError(message, retry) from error
        except (URLError, TimeoutError, socket.timeout, OSError) as error:
            raise FeedError("连接失败，请检查网络；稍后自动重试。") from error
        except UnicodeError as error:
            raise FeedError("网站返回了无法识别的资料。") from error


def load_cache(path: Path) -> dict:
    try:
        if path.stat().st_size > 32768:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != 1:
            return {}
        result = {"interval": data.get("interval", 60), "auto": data.get("auto", True), "feeds": {}}
        for kind in ("alpha", "cave"):
            saved = data.get("feeds", {}).get(kind)
            if not isinstance(saved, dict):
                continue
            raw, verified = saved["data"], float(saved["verified_at"])
            if not 0 < verified <= time.time() + 120:
                continue
            if kind == "alpha":
                record = AlphaReport(**raw)
                for value in (record.name, record.region, record.location):
                    _text(value, blank=False)
                if record.species_id is not None and (type(record.species_id) is not int or not 1 <= record.species_id <= 649):
                    continue
                if any(value is not None and (type(value) not in (int, float) or not 0 < value < 10_000_000_000)
                       for value in (record.reported_at, record.expires_at)):
                    continue
            else:
                record = CaveRotation(**raw)
                if not re.fullmatch(r"\d{8}-[0-3]", record.window_key):
                    continue
                record.starts_at
                _text(record.gem_type)
                for key, count in (("singles", 5), ("rare_singles", 2), ("hordes", 2)):
                    if not isinstance(getattr(record, key), list) or len(getattr(record, key)) != count:
                        raise ValueError("invalid cache slots")
                    for name in getattr(record, key):
                        _text(name)
            result["feeds"][kind] = (record, verified)
        return result
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return {}


def save_cache(path: Path, feeds: dict, interval: int, auto: bool) -> None:
    data = {"version": 1, "interval": interval, "auto": auto, "feeds": {
        kind: {"data": asdict(state.data), "verified_at": state.verified_at}
        for kind, state in feeds.items() if state.data is not None
    }}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
