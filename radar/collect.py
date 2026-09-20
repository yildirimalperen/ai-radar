"""Toplama katmanı: her kaynak türü için bir fetcher, çıktı tek tip Item listesi.

Tasarım kuralı: tek bir kaynağın ölmesi koşuyu düşürmez. Her fetcher kendi
hatasını yakalar, boş liste döner ve rapora "FAIL" satırı bırakır.
"""

from __future__ import annotations

import base64
import concurrent.futures as futures
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

import feedparser

from .models import Item, clean_text

UA = "ai-radar/0.1 (+https://github.com/yildirimalperen/ai-radar)"
# Reddit kendi RSS'ini bot UA'sına 403'lüyor; tarayıcı benzeri UA ile açılıyor.
UA_BROWSER = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ai-radar/0.1"
TIMEOUT = 25

# Reddit aynı ana bilgisayara paralel giden istekleri 429'luyor. Host başına
# asgari aralık dayatıp isteği sıraya sokuyoruz; diğer hostlar etkilenmiyor.
HOST_MIN_INTERVAL = {"www.reddit.com": 3.0}
MAX_RETRIES = 3

_host_locks: dict[str, threading.Lock] = {}
_host_last_call: dict[str, float] = {}
_registry_lock = threading.Lock()


def _host_gate(host: str) -> tuple[threading.Lock, float]:
    """Host için kilit ve asgari aralığı döner (yoksa oluşturur)."""
    interval = HOST_MIN_INTERVAL.get(host, 0.0)
    if not interval:
        return threading.Lock(), 0.0
    with _registry_lock:
        lock = _host_locks.setdefault(host, threading.Lock())
    return lock, interval


class SourceError(RuntimeError):
    """Tek bir kaynağın çekilememesi. Koşuyu değil yalnız o kaynağı düşürür."""


def _get(url: str, *, browser_ua: bool = False) -> bytes:
    """Tek HTTP GET. Host hız sınırına saygı duyar, 429/5xx'te geri çekilerek yeniden dener."""
    host = urllib.parse.urlsplit(url).netloc.lower()
    lock, interval = _host_gate(host)
    request = urllib.request.Request(
        url, headers={"User-Agent": UA_BROWSER if browser_ua else UA, "Accept": "*/*"}
    )

    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        if interval:
            with lock:
                elapsed = time.monotonic() - _host_last_call.get(host, 0.0)
                if elapsed < interval:
                    time.sleep(interval - elapsed)
                _host_last_call[host] = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in (429, 500, 502, 503, 504):
                break
            time.sleep(2.0 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            time.sleep(1.0 * (attempt + 1))

    raise SourceError(f"{type(last_error).__name__}: {last_error}") from last_error


def _iso(struct_time: Any) -> str:
    """feedparser'ın time.struct_time'ını ISO-8601 UTC'ye çevirir."""
    if not struct_time:
        return datetime.now(timezone.utc).isoformat()
    try:
        return datetime(*struct_time[:6], tzinfo=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).isoformat()


def fetch_rss(spec: dict, *, browser_ua: bool = False) -> list[Item]:
    parsed = feedparser.parse(_get(spec["url"], browser_ua=browser_ua))
    if not parsed.entries:
        raise SourceError("feed ayrıştırıldı ama 0 giriş döndü")

    items: list[Item] = []
    for entry in parsed.entries:
        link = entry.get("link") or ""
        title = clean_text(entry.get("title"), 300)
        if not link or not title:
            continue
        items.append(
            Item(
                title=title,
                url=link,
                source=spec["id"],
                published=_iso(entry.get("published_parsed") or entry.get("updated_parsed")),
                summary=clean_text(entry.get("summary") or entry.get("description")),
                source_axes=list(spec.get("axes", [])),
                source_weight=float(spec.get("weight", 1.0)),
                ai_native=bool(spec.get("ai_native", True)),
            )
        )
    return items


_reddit_token: dict[str, Any] = {"value": None, "expires": 0.0}
_reddit_token_lock = threading.Lock()


def _reddit_oauth_token() -> str | None:
    """Reddit script-app jetonu. Kimlik yoksa None döner ve çağıran RSS'e düşer.

    Ölçüm (2026-09-21): kimliksiz RSS ucu IP itibarına bağlı olarak 429 veriyor --
    4 subreddit'lik bir koşuda 20s aralıkla bile yalnız 2/4 geçti. OAuth ucu
    dakikada 100 isteğe izin verdiği için tek güvenilir yol bu.
    """
    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None

    with _reddit_token_lock:
        if _reddit_token["value"] and time.time() < _reddit_token["expires"]:
            return _reddit_token["value"]

        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        request = urllib.request.Request(
            "https://www.reddit.com/api/v1/access_token",
            data=b"grant_type=client_credentials",
            headers={
                "Authorization": f"Basic {basic}",
                "User-Agent": UA,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                payload = json.loads(response.read())
        except Exception:  # noqa: BLE001 - jeton alınamazsa RSS'e düşeriz
            return None

        token = payload.get("access_token")
        if not token:
            return None
        _reddit_token["value"] = token
        _reddit_token["expires"] = time.time() + int(payload.get("expires_in", 3600)) - 60
        return token


def fetch_reddit(spec: dict) -> list[Item]:
    """Reddit. Kimlik varsa OAuth ucu, yoksa kimliksiz RSS (429'a açık)."""
    token = _reddit_oauth_token()
    if token is None:
        return fetch_rss(spec, browser_ua=True)

    subreddit = spec["url"].split("/r/")[1].split("/")[0]
    request = urllib.request.Request(
        f"https://oauth.reddit.com/r/{subreddit}/top?t=day&limit=25",
        headers={"Authorization": f"Bearer {token}", "User-Agent": UA},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            payload = json.loads(response.read())
    except Exception as exc:  # noqa: BLE001
        raise SourceError(f"oauth: {type(exc).__name__}: {exc}") from exc

    items: list[Item] = []
    for child in payload.get("data", {}).get("children", []):
        post = child.get("data", {})
        title = clean_text(post.get("title"), 300)
        if not title:
            continue
        created = datetime.fromtimestamp(post.get("created_utc", 0), tz=timezone.utc)
        items.append(
            Item(
                title=title,
                url=post.get("url") or f"https://reddit.com{post.get('permalink', '')}",
                source=spec["id"],
                published=created.isoformat(),
                summary=clean_text(post.get("selftext")),
                signal=int(post.get("score") or 0),
                source_axes=list(spec.get("axes", [])),
                source_weight=float(spec.get("weight", 1.0)),
                ai_native=bool(spec.get("ai_native", True)),
            )
        )
    return items


def fetch_hn(spec: dict) -> list[Item]:
    """HN Algolia. Puan gerçek bir insan sinyali, signal alanına taşınıyor."""
    payload = json.loads(_get(spec["url"]))
    items: list[Item] = []
    for hit in payload.get("hits", []):
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        title = clean_text(hit.get("title"), 300)
        if not title:
            continue
        items.append(
            Item(
                title=title,
                url=url,
                source=spec["id"],
                published=hit.get("created_at") or datetime.now(timezone.utc).isoformat(),
                summary="",
                signal=int(hit.get("points") or 0),
                source_axes=list(spec.get("axes", [])),
                source_weight=float(spec.get("weight", 1.0)),
                ai_native=bool(spec.get("ai_native", True)),
            )
        )
    return items


def fetch_hf_papers(spec: dict) -> list[Item]:
    """HuggingFace günlük makaleler. Zaten insan-oylu, upvote sinyal taşıyor."""
    payload = json.loads(_get(spec["url"]))
    items: list[Item] = []
    for row in payload:
        paper = row.get("paper") or {}
        paper_id = paper.get("id") or row.get("paper", {}).get("id")
        title = clean_text(paper.get("title") or row.get("title"), 300)
        if not paper_id or not title:
            continue
        items.append(
            Item(
                title=title,
                url=f"https://huggingface.co/papers/{paper_id}",
                source=spec["id"],
                published=row.get("publishedAt") or paper.get("publishedAt") or "",
                summary=clean_text(paper.get("summary")),
                signal=int(paper.get("upvotes") or 0),
                source_axes=list(spec.get("axes", [])),
                source_weight=float(spec.get("weight", 1.0)),
                ai_native=bool(spec.get("ai_native", True)),
            )
        )
    return items


def fetch_arxiv(spec: dict) -> list[Item]:
    """arXiv Atom ucu. Hacim çok yüksek; asıl eleme skorlama katmanında."""
    return fetch_rss(spec)


FETCHERS: dict[str, Callable[[dict], list[Item]]] = {
    "rss": fetch_rss,
    "reddit": fetch_reddit,
    "hn": fetch_hn,
    "hf_papers": fetch_hf_papers,
    "arxiv": fetch_arxiv,
}


def collect_one(spec: dict, default_cap: int) -> tuple[str, list[Item], str]:
    """Tek kaynağı çeker. Hata durumunda boş liste + sebep döner."""
    fetcher = FETCHERS.get(spec.get("kind", "rss"))
    if fetcher is None:
        return spec["id"], [], f"bilinmeyen kind: {spec.get('kind')}"

    try:
        items = fetcher(spec)
    except SourceError as exc:
        return spec["id"], [], str(exc)
    except Exception as exc:  # noqa: BLE001 - tek kaynak koşuyu düşürmemeli
        return spec["id"], [], f"beklenmeyen {type(exc).__name__}: {exc}"

    cap = int(spec.get("cap", default_cap))
    items.sort(key=lambda i: (i.signal, i.published), reverse=True)
    return spec["id"], items[:cap], ""


def collect_all(config: dict, *, workers: int = 10) -> tuple[list[Item], list[tuple[str, str]]]:
    """Tüm kaynakları paralel çeker.

    Döner: (maddeler, [(kaynak_id, hata)]). Hata listesi boş değilse koşu yine
    tamamlanır -- rapor hangi kaynağın düştüğünü açıkça yazar.
    """
    specs = config["sources"]
    default_cap = int(config.get("defaults", {}).get("cap", 12))

    collected: list[Item] = []
    failures: list[tuple[str, str]] = []
    with futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results = pool.map(lambda s: collect_one(s, default_cap), specs)
        for source_id, items, error in results:
            if error:
                failures.append((source_id, error))
            collected.extend(items)
    return collected, failures
