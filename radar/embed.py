"""Gömülebilirlik yoklaması: bir linkin iframe'de açılıp açılamayacağını ölçer.

Neden inşa zamanında: `X-Frame-Options` veya CSP `frame-ancestors` ile engellenen
bir sayfa, iframe'e konduğunda tarayıcıda sessizce boş kalır ve JS bunu güvenilir
biçimde yakalayamaz (engellenen yükleme `error` olayı üretmez, `load` üretir).
Yani çalışma zamanında öğrenmek mümkün değil; önceden bilmek zorundayız.

Ölçüm (2026-09-21, gerçek günün 18 linki): yalnız 6'sı gömülebiliyor.
HuggingFace DENY, Reddit/OpenAI/TechCrunch SAMEORIGIN veya frame-ancestors 'none'.
Bu yüzden yan panel iki kipli: gömülebilende canlı sayfa, gömülemeyende
okuma önizlemesi.
"""

from __future__ import annotations

import concurrent.futures as futures
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

CACHE_FILE = "embed_cache.json"
CACHE_TTL_DAYS = 14          # alan adlarının politikası nadiren değişir
TIMEOUT = 15

# Tarayıcı benzeri UA: bazı siteler bot UA'sına farklı başlık döndürüyor.
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ai-radar/0.1"


def host_of(url: str) -> str:
    try:
        return urlsplit(url).netloc.lower().removeprefix("www.")
    except ValueError:
        return ""


def _blocks_framing(x_frame_options: str, csp: str) -> bool:
    if x_frame_options.strip().upper() in ("DENY", "SAMEORIGIN"):
        return True
    for directive in csp.split(";"):
        directive = directive.strip()
        if directive.startswith("frame-ancestors"):
            # Yalnız joker izin veren politika bizi kabul eder.
            return "*" not in directive
    return False


def probe(url: str) -> bool:
    """Tek bir adresin gömülebilirliği. Ulaşılamazsa güvenli taraf: False."""
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            headers = response.headers
    except urllib.error.HTTPError as exc:
        headers = exc.headers
        if headers is None:
            return False
    except Exception:  # noqa: BLE001 - yoklama koşuyu düşürmemeli
        return False

    return not _blocks_framing(
        headers.get("X-Frame-Options") or "",
        headers.get("Content-Security-Policy") or "",
    )


def _load_cache(archive_dir: Path) -> dict[str, bool]:
    path = archive_dir / CACHE_FILE
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if time.time() - payload.get("fetched_at", 0) > CACHE_TTL_DAYS * 86400:
        return {}
    return payload.get("hosts", {})


def annotate(items, archive_dir: str | Path, *, offline: bool = False) -> int:
    """Maddelere `embeddable` bayrağını yazar. Döner: gömülebilir madde sayısı.

    Yoklama alan adı başına yapılır ve 14 gün önbelleklenir; günlük koşuda
    genellikle birkaç yeni alan adı kalır.
    """
    archive = Path(archive_dir)
    cache = {} if offline else _load_cache(archive)

    unknown = sorted({host_of(i.url) for i in items} - set(cache) - {""})
    if unknown and not offline:
        # Alan adı başına bir temsilci adres yokla.
        sample = {host_of(i.url): i.url for i in reversed(items)}
        with futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = pool.map(lambda h: (h, probe(sample[h])), unknown)
            cache.update(dict(results))
        archive.mkdir(parents=True, exist_ok=True)
        (archive / CACHE_FILE).write_text(
            json.dumps({"fetched_at": time.time(), "hosts": cache}, ensure_ascii=False),
            encoding="utf-8",
        )

    count = 0
    for item in items:
        item.embeddable = bool(cache.get(host_of(item.url), False))
        count += item.embeddable
    return count
