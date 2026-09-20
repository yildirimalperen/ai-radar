"""Boru hattının her aşamasının konuştuğu tek veri tipi."""

from __future__ import annotations

import hashlib
import html as html_lib
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

# Eksenler: bültenin ilgi alanları. Sıralama ve gruplama bunlara göre.
AXES: dict[str, str] = {
    "model": "Yeni modeller",
    "image": "Görsel üretim",
    "video": "Video üretim",
    "game": "Oyun üretimi",
    "threed": "3D / rigging / asset",
    "infra": "Araç & altyapı",
    "people": "Kişiler & şirketler",
}

_WS = re.compile(r"\s+")
_TAGS = re.compile(r"<[^>]+>")


def clean_text(raw: str | None, limit: int = 600) -> str:
    """HTML etiketlerini/varlıklarını temizler ve kelime sınırında kırpar.

    Varlık çözümlemesi şart: feed'ler içeriği zaten kaçırılmış veriyor, biz
    yayında bir kez daha kaçırdığımız için sayfada ham "&#x2014;" görünüyordu.
    """
    if not raw:
        return ""
    text = _WS.sub(" ", _TAGS.sub(" ", html_lib.unescape(raw))).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit * 0.6 else cut).rstrip(" ,.;:-") + "…"


@dataclass
class Item:
    """Tek bir radar maddesi. Toplama → dedup → skorlama → yayın boyunca taşınır."""

    title: str
    url: str
    source: str
    published: str                      # ISO-8601 UTC
    summary: str = ""
    signal: int = 0                     # kaynağın kendi oyu (HN puanı, reddit upvote)
    source_axes: list[str] = field(default_factory=list)
    source_weight: float = 1.0
    ai_native: bool = True   # kaynak AI'a özel mi; değilse madde alakasını kanıtlamalı

    # skorlama aşamasında doldurulur
    axes: list[str] = field(default_factory=list)
    score: float = 0.0
    score_parts: dict[str, float] = field(default_factory=dict)
    why: str = ""                       # LLM katmanı açıksa: neden önemli

    @property
    def key(self) -> str:
        """Kaynaklar arası dedup anahtarı: kanonik URL'nin hash'i."""
        return hashlib.sha1(canonical_url(self.url).encode()).hexdigest()[:16]

    @property
    def age_hours(self) -> float:
        try:
            when = datetime.fromisoformat(self.published)
        except ValueError:
            return 999.0
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - when).total_seconds() / 3600)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Item:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


_TRACKING = re.compile(r"^(utm_|ref_?$|ref_src|fbclid|gclid|mc_cid|mc_eid|s=\d)")


def canonical_url(url: str) -> str:
    """Aynı içeriğin farklı link biçimlerini tek forma indirir.

    Takip parametrelerini, şemayı, www'yi ve sondaki eğik çizgiyi atar; böylece
    üç ayrı kaynaktan gelen aynı duyuru tek madde olarak sayılır.
    """
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()

    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/") or "/"
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING.match(k)])
    return urlunsplit(("", host, path, query, ""))


_NORM = re.compile(r"[^a-z0-9ğüşıöç ]+")


def title_fingerprint(title: str) -> str:
    """Başlık parmak izi: aynı haberi farklı URL'lerle veren kaynakları eşler."""
    words = _NORM.sub(" ", title.lower()).split()
    stop = {"the", "a", "an", "and", "for", "with", "new", "ai", "to", "of", "in", "is"}
    keep = sorted({w for w in words if len(w) > 2 and w not in stop})[:8]
    return " ".join(keep)
