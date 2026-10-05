"""Bounded NPO web crawler used when the site's JSON API is unavailable."""

from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import quote_plus, urljoin, urlsplit

from .client import ApiUnavailable, NPOClient

_MAX_PAGES = 24
_MAX_RECORDS = 4000


class CrawlError(RuntimeError):
    pass


@dataclass
class CrawledPage:
    url: str
    title: str | None
    description: str | None
    image: str | None
    records: list[dict]
    links: list[str]


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.links: list[str] = []
        self._script_kind: str | None = None
        self._script_chunks: list[str] = []
        self.scripts: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "meta":
            key = values.get("property") or values.get("name")
            value = values.get("content")
            if key and value:
                self.meta[key] = value
        elif tag == "a" and values.get("href"):
            self.links.append(values["href"])
        elif tag == "script":
            script_type = (values.get("type") or "").casefold()
            script_id = values.get("id") or ""
            if script_id == "__NEXT_DATA__" or script_type == "application/ld+json":
                self._script_kind = script_id or script_type
                self._script_chunks = []

    def handle_data(self, data):
        if self._script_kind:
            self._script_chunks.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._script_kind:
            self.scripts.append((self._script_kind, "".join(self._script_chunks)))
            self._script_kind = None
            self._script_chunks = []


def _walk_records(value) -> list[dict]:
    result: list[dict] = []
    stack = [value]
    seen = 0
    while stack and len(result) < _MAX_RECORDS:
        current = stack.pop()
        seen += 1
        if seen > 30000:
            break
        if isinstance(current, dict):
            if any(key in current for key in ("productId", "guid", "slug", "series", "season")):
                result.append(current)
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return result


def _safe_link(base: str, value: str) -> str | None:
    try:
        url = urljoin(base, value)
        parsed = urlsplit(url)
    except ValueError:
        return None
    if (parsed.scheme not in {"http", "https"} or
            (parsed.hostname or "").lower() not in {"npo.nl", "www.npo.nl"} or
            not parsed.path.startswith("/start/")):
        return None
    return parsed._replace(scheme="https", netloc="npo.nl", fragment="").geturl()


def parse(url: str, html: str) -> CrawledPage:
    parser = _PageParser()
    try:
        parser.feed(html)
    except Exception as exc:
        raise CrawlError("NPO page could not be parsed") from exc
    records: list[dict] = []
    for _, text in parser.scripts:
        try:
            records.extend(_walk_records(json.loads(text)))
        except (json.JSONDecodeError, TypeError):
            continue

    # Keep a narrow last-resort extraction for pages whose hydration object is
    # serialized inside another script rather than __NEXT_DATA__.
    if not any(record.get("productId") for record in records):
        for product_id in re.findall(r'"productId"\s*:\s*"([A-Za-z0-9_.:-]{2,160})"', html):
            records.append({"productId": product_id})

    links = []
    for raw in parser.links:
        link = _safe_link(url, raw)
        if link and link not in links:
            links.append(link)
    title = parser.meta.get("og:title") or parser.meta.get("twitter:title")
    description = parser.meta.get("og:description") or parser.meta.get("description")
    image = parser.meta.get("og:image") or parser.meta.get("twitter:image")
    return CrawledPage(url, title, description, image, records, links)


def page(url: str, client: NPOClient) -> CrawledPage:
    try:
        return parse(url, client.html(url))
    except ApiUnavailable as exc:
        raise CrawlError("NPO web page is unavailable") from exc


def _program_url(record: dict, fallback: str) -> str:
    slug = record.get("slug")
    series = record.get("series") if isinstance(record.get("series"), dict) else {}
    season = record.get("season") if isinstance(record.get("season"), dict) else {}
    series_slug, season_slug = series.get("slug"), season.get("slug")
    if all(isinstance(value, str) and value for value in (series_slug, season_slug, slug)):
        return f"https://npo.nl/start/serie/{series_slug}/{season_slug}/{slug}/afspelen"
    if isinstance(slug, str) and slug:
        return f"https://npo.nl/start/video/{slug}"
    return fallback


def program(url: str, client: NPOClient) -> dict:
    crawled = page(url, client)
    path_slug = next((part for part in reversed(urlsplit(url).path.split("/"))
                      if part and part not in {"afspelen", "start", "serie", "video"}), "")
    candidates = [record for record in crawled.records if record.get("productId")]
    if not candidates:
        raise CrawlError("NPO page contains no playable media identity")

    def score(record):
        slug = str(record.get("slug") or "")
        return (
            2 if slug == path_slug else 0,
            1 if record.get("title") else 0,
            1 if isinstance(record.get("series"), dict) else 0,
        )

    selected = max(candidates, key=score)
    return {
        **selected,
        "_crawler_url": _program_url(selected, url),
        "_crawler_title": crawled.title,
        "_crawler_description": crawled.description,
        "_crawler_image": crawled.image,
    }


def series(url: str, client: NPOClient) -> tuple[dict, list[dict]]:
    parsed = urlsplit(url)
    parts = [part for part in parsed.path.split("/") if part]
    try:
        series_index = parts.index("serie")
        slug = parts[series_index + 1]
    except (ValueError, IndexError) as exc:
        raise CrawlError("NPO series URL is invalid") from exc

    root = f"https://npo.nl/start/serie/{slug}"
    queue = deque([(root, 0)])
    visited: set[str] = set()
    programs: dict[str, dict] = {}
    series_record: dict | None = None
    root_page: CrawledPage | None = None

    while queue and len(visited) < _MAX_PAGES:
        current, depth = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        crawled = page(current, client)
        if root_page is None:
            root_page = crawled
        for record in crawled.records:
            if record.get("productId"):
                product_id = str(record["productId"])
                programs.setdefault(product_id, {
                    **record,
                    "_crawler_url": _program_url(record, current),
                })
            record_slug = record.get("slug")
            record_type = str(record.get("type") or "")
            if (record_slug == slug and not record.get("productId")) or (
                    record_type.endswith("series") and record_slug == slug):
                series_record = series_record or record
        if depth >= 2:
            continue
        prefix = f"/start/serie/{slug}"
        for link in crawled.links:
            if urlsplit(link).path.startswith(prefix) and link not in visited:
                queue.append((link, depth + 1))

    if root_page is None:
        raise CrawlError("NPO series could not be crawled")
    metadata = {
        **(series_record or {}),
        "slug": (series_record or {}).get("slug") or slug,
        "title": (series_record or {}).get("title") or root_page.title or slug.replace("-", " ").title(),
        "synopsis": (series_record or {}).get("synopsis") or root_page.description,
        "_crawler_image": root_page.image,
    }
    return metadata, list(programs.values())


def search(query: str, client: NPOClient, limit: int = 30) -> list[dict]:
    if not query.strip():
        return []
    url = f"https://npo.nl/start/zoeken?query={quote_plus(query.strip())}"
    crawled = page(url, client)
    needle = query.casefold().strip()
    results: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for record in crawled.records:
        title = str(record.get("title") or record.get("mainTitle") or "")
        if needle not in title.casefold():
            continue
        kind = "program" if record.get("productId") else "series"
        identity = str(record.get("productId") or record.get("guid") or record.get("slug") or "")
        if not identity or (kind, identity) in seen:
            continue
        seen.add((kind, identity))
        results.append(record)
        if len(results) >= limit:
            break
    return results
