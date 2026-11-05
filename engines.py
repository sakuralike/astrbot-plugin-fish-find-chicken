from __future__ import annotations

import asyncio
import html
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

try:
    import aiohttp
except Exception:  # pragma: no cover - exercised only when dependency is missing
    aiohttp = None


HTTP_ENGINES = frozenset({"saucenao", "tracemoe", "iqdb"})
BROWSER_ENGINES = frozenset({"lens", "yandex", "bing", "baidu", "google"})
ENGINE_LABELS = {
    "saucenao": "SauceNAO",
    "tracemoe": "trace.moe",
    "iqdb": "IQDB",
    "lens": "Google Lens",
    "yandex": "Yandex",
    "bing": "Bing",
    "baidu": "百度",
    "google": "Google",
}


@dataclass(frozen=True)
class Candidate:
    engine: str
    platform: str
    account: str
    name: str = ""
    source_url: str = ""
    score: float | None = None
    confidence: bool = False


@dataclass
class EngineResult:
    engine: str
    candidates: list[Candidate] = field(default_factory=list)
    error: str | None = None


class EngineError(RuntimeError):
    def __init__(self, message: str, *, code: str = "engine_failed"):
        super().__init__(message)
        self.code = code


def _safe_url(value: Any) -> str:
    value = str(value or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return value[:2048]


def _safe_text(value: Any, maximum: int = 300) -> str:
    value = html.unescape(str(value or ""))
    value = re.sub(r"\s+", " ", value).strip()
    return value[:maximum]


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return max(0.0, min(100.0, number))


def _platform_from_url(url: str) -> str:
    host = urlparse(url).hostname or ""
    host = host.lower().removeprefix("www.")
    for key, label in (
        ("twitter.com", "X/Twitter"),
        ("x.com", "X/Twitter"),
        ("instagram.com", "Instagram"),
        ("weibo.com", "微博"),
        ("bilibili.com", "哔哩哔哩"),
        ("tiktok.com", "TikTok"),
        ("douyin.com", "抖音"),
        ("facebook.com", "Facebook"),
        ("threads.net", "Threads"),
        ("xiaohongshu.com", "小红书"),
    ):
        if host == key or host.endswith("." + key):
            return label
    return host or "未知平台"


def _account_from_url(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return ""
    return _safe_text(parts[-1].lstrip("@"), 120)


def candidate_from_row(
    engine: str,
    row: dict[str, Any],
    *,
    default_platform: str = "",
) -> Candidate | None:
    url = _safe_url(
        row.get("url")
        or row.get("source")
        or row.get("source_url")
        or row.get("ext_urls", [""])[0]
        if isinstance(row.get("ext_urls"), list)
        else row.get("url") or row.get("source") or row.get("source_url")
    )
    account = _safe_text(
        row.get("account")
        or row.get("username")
        or row.get("user")
        or row.get("author")
        or _account_from_url(url),
        160,
    )
    name = _safe_text(row.get("name") or row.get("title") or row.get("author_name"), 160)
    if not account and not name and not url:
        return None
    return Candidate(
        engine=engine,
        platform=_safe_text(row.get("platform") or default_platform or _platform_from_url(url), 80),
        account=account or name,
        name=name,
        source_url=url,
        score=_float(row.get("score") or row.get("similarity") or row.get("similarity_percent")),
    )


class _AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() != "a":
            return
        self._href = dict(attrs).get("href", "")
        self._text = []

    def handle_data(self, data: str):
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str):
        if tag.lower() == "a" and self._href:
            self.links.append((self._href, " ".join(self._text)))
            self._href = ""
            self._text = []


def parse_saucenao(payload: str | bytes) -> list[Candidate]:
    text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else str(payload)
    parser = _AnchorParser()
    parser.feed(text)
    results: list[Candidate] = []
    for href, title in parser.links:
        url = _safe_url(href)
        if not url or "saucenao.com" in url:
            continue
        row = {"url": url, "title": _safe_text(title)}
        candidate = candidate_from_row("saucenao", row)
        if candidate:
            results.append(candidate)
    return results[:20]


def parse_json_engine(engine: str, payload: dict[str, Any]) -> list[Candidate]:
    rows = payload.get("result") or payload.get("results") or payload.get("data") or []
    if isinstance(rows, dict):
        rows = [rows]
    output: list[Candidate] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        candidate = candidate_from_row(engine, row)
        if candidate:
            output.append(candidate)
    return output[:20]


def parse_tracemoe(payload: str | bytes) -> list[Candidate]:
    try:
        data = json.loads(payload.decode("utf-8", "replace") if isinstance(payload, bytes) else payload)
    except (TypeError, ValueError):
        return []
    output: list[Candidate] = []
    for row in data.get("result", []) if isinstance(data, dict) else []:
        if not isinstance(row, dict):
            continue
        anilist = row.get("anilist") or {}
        title = anilist.get("title") if isinstance(anilist, dict) else ""
        candidate = Candidate(
            engine="tracemoe",
            platform="trace.moe",
            account=_safe_text(title or row.get("filename") or "动画片段", 160),
            name=_safe_text(row.get("filename") or title, 160),
            source_url=_safe_url(row.get("video") or row.get("image")),
            score=_float(row.get("similarity")),
        )
        output.append(candidate)
    return output[:20]


def parse_iqdb(payload: str | bytes) -> list[Candidate]:
    return parse_saucenao(payload)


async def _request_bytes(
    url: str,
    *,
    image_bytes: bytes,
    mime_type: str,
    timeout: float,
    proxy: str | None,
) -> tuple[int, bytes]:
    if aiohttp is None:
        raise EngineError("HTTP 依赖未安装", code="dependency_missing")
    client_timeout = aiohttp.ClientTimeout(total=max(3.0, float(timeout)))
    form = aiohttp.FormData()
    form.add_field("file", image_bytes, filename="image", content_type=mime_type)
    async with aiohttp.ClientSession(timeout=client_timeout) as session:
        async with session.post(url, data=form, proxy=proxy or None) as response:
            body = await response.content.read(2 * 1024 * 1024)
            return response.status, body


async def search_http_engine(
    engine: str,
    image_bytes: bytes,
    mime_type: str,
    *,
    timeout: float = 45,
    proxy: str | None = None,
) -> EngineResult:
    endpoints = {
        "saucenao": "https://saucenao.com/search.php",
        "tracemoe": "https://api.trace.moe/search",
        "iqdb": "https://iqdb.org/",
    }
    if engine not in endpoints:
        return EngineResult(engine=engine, error="unsupported_engine")
    try:
        status, body = await _request_bytes(
            endpoints[engine],
            image_bytes=image_bytes,
            mime_type=mime_type,
            timeout=timeout,
            proxy=proxy,
        )
        if status < 200 or status >= 300:
            return EngineResult(engine=engine, error=f"http_{status}")
        if engine == "tracemoe":
            candidates = parse_tracemoe(body)
        elif engine == "iqdb":
            candidates = parse_iqdb(body)
        else:
            candidates = parse_saucenao(body)
        return EngineResult(engine=engine, candidates=candidates)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        return EngineResult(engine=engine, error=type(error).__name__)


async def search_engine(
    engine: str,
    image_bytes: bytes,
    mime_type: str,
    *,
    timeout: float = 45,
    proxy: str | None = None,
    browser: Any = None,
) -> EngineResult:
    engine = str(engine or "").strip().lower()
    if engine in HTTP_ENGINES:
        return await search_http_engine(
            engine,
            image_bytes,
            mime_type,
            timeout=timeout,
            proxy=proxy,
        )
    if engine in BROWSER_ENGINES:
        if browser is None:
            return EngineResult(engine=engine, error="browser_unavailable")
        try:
            result = await browser.search(
                engine,
                image_bytes,
                mime_type,
                timeout=timeout,
                proxy=proxy,
            )
            if isinstance(result, EngineResult):
                return result
            rows = result if isinstance(result, list) else []
            return EngineResult(
                engine=engine,
                candidates=[
                    row
                    for row in (
                        candidate_from_row(engine, item)
                        for item in rows
                        if isinstance(item, dict)
                    )
                    if row
                ],
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            return EngineResult(engine=engine, error=type(error).__name__)
    return EngineResult(engine=engine, error="unsupported_engine")
