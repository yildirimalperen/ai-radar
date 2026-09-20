"""Dedup katmanı: aynı haberi tek maddeye indirger ve geçmişte görülenleri eler.

İki ayrı iş var:
  1. Koşu içi birleştirme -- aynı duyuruyu veren N kaynak tek madde olur.
     Bu bir kayıp değil kazanç: kaç kaynağın aynı şeyi verdiği (corroboration)
     skorlamada güçlü bir önem sinyali.
  2. Günler arası eleme -- dün gösterilen madde bugün tekrar çıkmaz.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Item, canonical_url, title_fingerprint

SEEN_FILE = "seen.jsonl"
SEEN_WINDOW_DAYS = 7
# Günlük radarda bayat içeriğin yeri yok. Tazelik skoru 96 saatte tabana
# oturduğu için tek başına yetmiyordu: 69 günlük bir blog yazısı listenin
# üçüncü sırasına çıktı. Bu yüzden sert bir yaş sınırı var.
MAX_ITEM_AGE_DAYS = 10


def merge_duplicates(items: list[Item]) -> list[Item]:
    """Koşu içi tekrarları birleştirir, en güvenilir kaynağı temsilci yapar."""
    buckets: dict[str, list[Item]] = {}
    for item in items:
        fingerprint = title_fingerprint(item.title)
        # Başlık parmak izi çok kısaysa (ör. tek kelimelik başlık) URL'ye düş.
        group_key = fingerprint if len(fingerprint) > 12 else item.key
        buckets.setdefault(group_key, []).append(item)

    merged: list[Item] = []
    for group in buckets.values():
        # Temsilci: en güvenilir kaynak, eşitlikte en yüksek ham sinyal.
        group.sort(key=lambda i: (i.source_weight, i.signal), reverse=True)
        lead = group[0]
        others = {i.source for i in group[1:]}
        lead.signal = max(i.signal for i in group)
        lead.score_parts["corroboration"] = float(len(others))
        if others:
            lead.summary = lead.summary or next((i.summary for i in group[1:] if i.summary), "")
            lead.why = ""
        lead.source_axes = sorted({a for i in group for a in i.source_axes})
        lead.score_parts["_also_in"] = 0.0
        lead.__dict__["also_in"] = sorted(others)
        merged.append(lead)
    return merged


def _seen_path(archive_dir: str | Path) -> Path:
    return Path(archive_dir) / SEEN_FILE


def load_seen(archive_dir: str | Path) -> dict[str, str]:
    """Son SEEN_WINDOW_DAYS içinde gösterilmiş madde anahtarları -> ilk görülme."""
    path = _seen_path(archive_dir)
    if not path.exists():
        return {}

    cutoff = datetime.now(timezone.utc) - timedelta(days=SEEN_WINDOW_DAYS)
    seen: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            when = datetime.fromisoformat(row["first_seen"])
        except (ValueError, KeyError, json.JSONDecodeError):
            continue
        if when >= cutoff:
            seen[row["key"]] = row["first_seen"]
    return seen


def drop_seen(items: list[Item], seen: dict[str, str]) -> tuple[list[Item], int]:
    """Daha önce gösterilmiş maddeleri eler. Döner: (kalanlar, elenen_sayısı)."""
    fresh = [i for i in items if i.key not in seen and title_fingerprint(i.title) not in seen]
    return fresh, len(items) - len(fresh)


def record_seen(items: list[Item], archive_dir: str | Path) -> None:
    """Yayına giren maddeleri arşive yazar. Pencere dışı satırlar budanır."""
    path = _seen_path(archive_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    existing = load_seen(archive_dir)
    rows = [{"key": key, "first_seen": when} for key, when in existing.items()]
    for item in items:
        if item.key in existing:
            continue
        rows.append({"key": item.key, "first_seen": now})
        rows.append({"key": title_fingerprint(item.title), "first_seen": now})

    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def drop_stale(items: list[Item], max_age_days: int = MAX_ITEM_AGE_DAYS) -> tuple[list[Item], int]:
    """Yaş sınırını aşan maddeleri eler."""
    limit_hours = max_age_days * 24
    kept = [i for i in items if i.age_hours <= limit_hours]
    return kept, len(items) - len(kept)


def dedup(items: list[Item], archive_dir: str | Path) -> tuple[list[Item], dict[str, int]]:
    """Tam dedup hattı. Döner: (maddeler, sayaçlar)."""
    before = len(items)
    recent, stale = drop_stale(items)
    merged = merge_duplicates(recent)
    seen = load_seen(archive_dir)
    fresh, dropped = drop_seen(merged, seen)
    return fresh, {
        "toplanan": before,
        "bayat_elendi": stale,
        "birlestirme_sonrasi": len(merged),
        "gecmiste_gorulmus": dropped,
        "kalan": len(fresh),
    }
