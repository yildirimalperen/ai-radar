"""Hype ölçümü: bir maddenin *yükselişte* olup olmadığını sayıya çevirir.

Neden ayrı bir katman: mevcut skorlayıcı bir maddeyi kendi iç özellikleriyle
(kaynak, eksen, tazelik) puanlıyor. "Yükselişte olmak" ise maddenin kendisinde
değil, dünyanın ona verdiği tepkide ve o tepkinin değişim hızında. Bu iki şey
farklı ve toplanarak değil, ayrı kapılar olarak kullanılmalı.

Ölçümle elenen yaklaşım: "kaç bağımsız kaynak aynı şeyi söyledi". 31 kaynağımız
birbiriyle örtüşmeyen nişler; gerçek bir günde 122 maddenin 0'ı birden fazla
kaynakta geçti, varlık seviyesinde de yalnız 2 jenerik şirket adı eşleşti.
Aynı gün içinde artıklık yok, dolayısıyla ölçülecek bir şey de yok.

Kullanılan üç sinyal (üçü de geçmiş biriktirmeden, bugün ölçülebilir):
  H1 hız       — oy / yaş. Kaynak bazında normalize, çünkü HN'de 30 oy/saat
                 ile HF Papers'ta 3 oy/saat aynı anlama geliyor.
  H2 konu eğimi— HN arşivinde konunun bu haftaki hikâye sayısı / geçen hafta.
                 Tek sorguda iki haftayı çekip yerelde kovalıyoruz.
  H3 dış metrik— HuggingFace trendingScore. Doğrudan, bakımlı bir hype sayısı.

Üçü OR mantığıyla birleşiyor (en güçlüsü belirleyici), birden fazlası
ateşlerse küçük bir pekiştirme var.
"""

from __future__ import annotations

import json
import math
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .models import Item

UA = "ai-radar/0.1 (+https://github.com/yildirimalperen/ai-radar)"
TIMEOUT = 25

HN_SEARCH = "https://hn.algolia.com/api/v1/search"
HF_TRENDING = "https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit=200"

CACHE_FILE = "hype_cache.json"
HF_HISTORY_FILE = "hf_trend_history.jsonl"
HF_DELTA_WINDOW_DAYS = 3
CACHE_TTL_HOURS = 20          # günde bir tazelenir, aynı gün ikinci koşu ağa çıkmaz
MAX_TRACKED_TOPICS = 20       # HN'e atılacak sorgu sayısının üst sınırı
# Haftalık hikâye sayısı bunun altındaysa eğim hesaplanmaz. Gerçek konularla
# kalibre edildi: bu eşiğin altında oran tamamen gürültü.
MIN_WEEKLY_STORIES = 5

# Kabul eşiği: bunu geçen madde ekseni ne olursa olsun listeye girebilir.
PROMOTION_THRESHOLD = 0.60
# Hem çekirdek eksende hem yükselişte olan maddeye uygulanan pekiştirme.
COMBO_MULTIPLIER = 1.35

# Hız normalizasyonu için taban referanslar. Koşu içi dağılım yeterliyse
# onunla ezilir; buradakiler yalnız veri azken kullanılan emniyet değerleri.
VELOCITY_FALLBACK = {"hackernews": 30.0, "hf-papers": 3.0}
VELOCITY_DEFAULT = 15.0


@dataclass
class HypeSignal:
    """Tek bir maddenin yükseliş ölçüsü ve bunun gerekçesi."""

    velocity: float = 0.0
    topic_trend: float = 0.0
    external: float = 0.0
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    @property
    def is_rising(self) -> bool:
        return self.score >= PROMOTION_THRESHOLD

    @property
    def label(self) -> str:
        return " · ".join(self.reasons)


# --- konu çıkarımı --------------------------------------------------------------

# Model/ürün adı adayı: büyük harfle başlayan, rakam veya tire içerebilen adlar.
_ENTITY = re.compile(
    r"\b([A-Z][A-Za-z]*(?:[-–.][A-Za-z0-9]+)*"
    r"(?:\s+[A-Z0-9][A-Za-z0-9.]*(?:[-–.][A-Za-z0-9]+)*){0,2})\b"
)
_STOP = {
    "The", "A", "An", "This", "That", "We", "In", "On", "For", "How", "What", "Why",
    "New", "And", "Our", "Is", "It", "I", "You", "Not", "But", "With", "From", "At",
    "To", "Of", "Introducing", "Can", "Now", "My", "Your", "If", "All", "No", "Some",
    "More", "Most", "Over", "After", "Before", "Here", "There", "When", "Who", "Its",
    "Are", "Was", "Has", "Have", "Will", "Would", "Should", "Could", "Just", "Only",
}


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def extract_topics(title: str) -> list[str]:
    """Başlıktan model/ürün adı adaylarını çıkarır.

    Jenerik şirket adları ("Google", "OpenAI") kasıtlı olarak dışarıda değil --
    eleme, konunun HN'de gerçekten hareketlenip hareketlenmediğine bakılarak
    yapılıyor. Sabit bir kara liste tutmak bakım borcu üretirdi.
    """
    found: list[str] = []
    for match in _ENTITY.finditer(title):
        tokens = match.group(1).strip(" .-").split()
        # Baştaki durak kelimeleri kırp: açgözlü eşleşme "Can MiniMax-H3 Reason"
        # gibi diziler üretiyor ve baş token durak olduğu için gerçek model adı
        # tamamen kayboluyordu.
        while tokens and tokens[0] in _STOP:
            tokens.pop(0)
        while tokens and tokens[-1] in _STOP:
            tokens.pop()
        if not tokens:
            continue
        name = " ".join(tokens).strip(" .-")
        if len(name) < 3:
            continue
        found.append(name)
        # Rakam taşıyan ilk iki token'lık kısa biçim de aday olsun
        # ("MiniMax-H3 Reason" yerine "MiniMax-H3").
        if len(tokens) > 1:
            short = tokens[0].strip(" .-")
            if len(short) >= 3 and short not in found:
                found.append(short)
    return found


def canonical_topic(topic: str) -> str:
    """Konuyu kanonik anahtara indirger: sürüm token'ına kadar kırp + normalize.

    Aynı model başlıklarda farklı kuyruklarla geçiyor ("Minimax H3 Video",
    "MiniMax-H3 Reason"); kanonik biçim olmadan konu tavanı ateşlenmiyor ve
    tek bir duyuru listenin ilk üç sırasını birden alabiliyor.
    """
    tokens = topic.split()
    for index, token in enumerate(tokens):
        if re.search(r"\d", token):
            return _normalize(" ".join(tokens[: index + 1]))
    return ""


def _is_product_like(topic: str) -> bool:
    """Model/ürün adı mı?

    Rakam şartı bilinçli: "çok parçalı büyük harfli ad" kuralı "Reason About"
    ve "LLM Models" gibi jenerik ifadeleri model adı sanıyordu. Sürüm numarası
    taşımak ("Qwen Image 2.1", "Kling 3.0", "MiniMax H3") çok daha kesin.
    """
    return bool(re.search(r"\d", topic))


# --- ağ + önbellek --------------------------------------------------------------


def _get(url: str) -> dict | list | None:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


def _load_cache(archive_dir: Path) -> dict:
    path = archive_dir / CACHE_FILE
    if not path.exists():
        return {}
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    fetched = cache.get("fetched_at", 0)
    if time.time() - fetched > CACHE_TTL_HOURS * 3600:
        return {}
    return cache


def _save_cache(archive_dir: Path, cache: dict) -> None:
    archive_dir.mkdir(parents=True, exist_ok=True)
    cache["fetched_at"] = time.time()
    (archive_dir / CACHE_FILE).write_text(
        json.dumps(cache, ensure_ascii=False), encoding="utf-8"
    )


def fetch_hf_trending() -> dict[str, float]:
    """HuggingFace trending modelleri: normalize edilmiş ad -> trendingScore."""
    payload = _get(HF_TRENDING)
    if not isinstance(payload, list):
        return {}
    out: dict[str, float] = {}
    for model in payload:
        model_id = str(model.get("id", ""))
        short = model_id.split("/")[-1]
        score = float(model.get("trendingScore") or 0)
        if short and score > 0:
            out[_normalize(short)] = max(out.get(_normalize(short), 0.0), score)
    return out


def record_hf_snapshot(archive_dir: Path, hf_map: dict[str, float]) -> None:
    """Günün HF trend tablosunu arşive yazar (günde bir satır)."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / HF_HISTORY_FILE
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("date") != today:
                rows.append(row)
    rows.append({"date": today, "scores": hf_map})
    rows = rows[-30:]
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )


def hf_deltas(archive_dir: Path, hf_map: dict[str, float]) -> dict[str, float]:
    """Model başına trendingScore değişimi (bugün - N gün önce).

    Asıl alan-içi dalga ölçüsü bu: "bu Qwen kopyası hype yapıyor mu" sorusunun
    doğrudan karşılığı, mutlak skor değil skorun ARTIŞI. Geçmiş biriktirmeden
    çalışmaz -- ilk birkaç gün boş döner, bu beklenen davranış.
    """
    path = archive_dir / HF_HISTORY_FILE
    if not path.exists():
        return {}
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    if len(rows) < 2:
        return {}
    baseline = rows[max(0, len(rows) - 1 - HF_DELTA_WINDOW_DAYS)].get("scores", {})
    return {
        name: score - baseline.get(name, 0.0)
        for name, score in hf_map.items()
        if score - baseline.get(name, 0.0) > 0
    }


def fetch_topic_trend(topic: str) -> tuple[int, int]:
    """Konunun HN'de bu hafta ve geçen haftaki hikâye sayısı.

    Algolia'nın döndürdüğü adaylar KENDİMİZ süzülüyor. Varsayılan arama
    yazım-hatası toleranslı: "rigging" sorgusu "Rising Fuel Prices"i,
    "veo" sorgusu "Voodoo" ve "Verus"u eşleştiriyor. Süzgeçsiz sayılar
    tamamen gürültü (ölçüldü: rigging ham 53 → gerçek 1).

    Süzgeçten sonra gerçek hacim çok küçük çıkıyor: niş konular HN'de
    fiilen yok, yalnız ana-akım model adları (qwen: 5→12) sayı üretiyor.
    Bu sinyal bu yüzden NADİREN ateşler; asıl yük H3/H4'te.
    """
    now = int(time.time())
    two_weeks = now - 14 * 86400
    one_week = now - 7 * 86400
    url = (
        f"{HN_SEARCH}?query={urllib.parse.quote(topic)}&tags=story"
        f"&numericFilters=created_at_i%3E{two_weeks}&hitsPerPage=200"
    )
    payload = _get(url)
    if not isinstance(payload, dict):
        return 0, 0

    pattern = re.compile(rf"(?<![a-z0-9]){re.escape(topic.lower())}(?![a-z0-9])")
    this_week = previous = 0
    for hit in payload.get("hits", []):
        haystack = f"{hit.get('title') or ''} {hit.get('url') or ''}".lower()
        if not pattern.search(haystack):
            continue
        if (hit.get("created_at_i") or 0) >= one_week:
            this_week += 1
        else:
            previous += 1
    return this_week, previous


# --- sinyaller ------------------------------------------------------------------


def _velocity_references(items: list[Item]) -> dict[str, float]:
    """Kaynak başına hız referansı: o kaynağın bu koşudaki üst çeyreği.

    Sabit eşik yerine koşu içi dağılımdan türetiliyor; sakin bir günde eşik
    kendiliğinden düşüyor, hareketli günde yükseliyor.
    """
    by_source: dict[str, list[float]] = {}
    for item in items:
        if item.signal > 0:
            by_source.setdefault(item.source, []).append(
                item.signal / max(item.age_hours, 1.0)
            )

    references: dict[str, float] = {}
    for source, values in by_source.items():
        if len(values) >= 4:
            reference = statistics.quantiles(values, n=4)[-1]   # üst çeyrek
        else:
            reference = max(values)
        references[source] = max(reference, 1.0)
    return references


def velocity_score(item: Item, references: dict[str, float]) -> float:
    """İlgi hızı: oy / yaş, kaynak referansına göre 0-1'e ölçeklenir."""
    if item.signal <= 0:
        return 0.0
    reference = references.get(
        item.source, VELOCITY_FALLBACK.get(item.source, VELOCITY_DEFAULT)
    )
    return min(1.0, (item.signal / max(item.age_hours, 1.0)) / reference)


def trend_score(this_week: int, previous: int) -> float:
    """Konu eğimi: haftalık hikâye sayısındaki büyüme.

    Tek haneli sayılarda oran çok oynak olduğu için hem oran hem mutlak hacim
    dikkate alınıyor: 1 → 3 yükseliş sayılmıyor, 7 → 36 sayılıyor.
    """
    if this_week < MIN_WEEKLY_STORIES:
        return 0.0
    ratio = this_week / max(previous, 1)
    if ratio <= 1.0:
        return 0.0
    volume = min(1.0, math.log1p(this_week) / math.log(40))
    growth = min(1.0, math.log(ratio) / math.log(4))
    # Hacim ve büyüme eşit ağırlıkta: yalnız orana bakmak düşük sayılarda
    # gürültü üretiyor (1 → 3 hikâye "dalga" sayılmamalı).
    return round(min(1.0, growth * 0.5 + volume * 0.5), 3)


def external_score(raw: float) -> float:
    """HF trendingScore'u 0-1'e indirger. 1000 civarı tavana yakın."""
    if raw <= 0:
        return 0.0
    return round(min(1.0, math.log1p(raw) / math.log(1200)), 3)


# --- orkestrasyon ---------------------------------------------------------------


def compute(
    items: list[Item], archive_dir: str | Path, *, offline: bool = False
) -> dict[str, HypeSignal]:
    """Her madde için hype sinyali üretir. Döner: madde anahtarı -> HypeSignal.

    Ağ erişimi başarısız olursa sinyal sessizce hızla sınırlı kalır; koşu
    düşmez, yalnız hype katmanı zayıflar.
    """
    archive = Path(archive_dir)
    references = _velocity_references(items)

    cache = {} if offline else _load_cache(archive)
    hf_map: dict[str, float] = cache.get("hf", {})
    topic_cache: dict[str, list[int]] = cache.get("topics", {})

    if not offline and not hf_map:
        hf_map = fetch_hf_trending()
    if not offline and hf_map:
        record_hf_snapshot(archive, hf_map)
    deltas = hf_deltas(archive, hf_map) if not offline else {}

    # İzlenecek konular: en yüksek puanlı maddelerin ürün benzeri adları.
    candidates: list[str] = []
    for item in sorted(items, key=lambda i: i.score, reverse=True):
        for topic in extract_topics(item.title):
            if _is_product_like(topic) and topic not in candidates:
                candidates.append(topic)
        if len(candidates) >= MAX_TRACKED_TOPICS:
            break
    tracked = candidates[:MAX_TRACKED_TOPICS]

    if not offline:
        for topic in tracked:
            if topic not in topic_cache:
                this_week, previous = fetch_topic_trend(topic)
                topic_cache[topic] = [this_week, previous]
        _save_cache(archive, {"hf": hf_map, "topics": topic_cache})

    signals: dict[str, HypeSignal] = {}
    for item in items:
        signal = HypeSignal()
        signal.velocity = round(velocity_score(item, references), 3)
        if signal.velocity >= 0.5:
            rate = item.signal / max(item.age_hours, 1.0)
            signal.reasons.append(f"{rate:.0f} oy/saat")

        title_norm = _normalize(item.title)
        for topic in (t for t in extract_topics(item.title) if _is_product_like(t)):
            counts = topic_cache.get(topic)
            if counts:
                value = trend_score(counts[0], counts[1])
                if value > signal.topic_trend:
                    signal.topic_trend = value
                    if value >= 0.4:
                        signal.reasons = [
                            r for r in signal.reasons if "HN'de" not in r
                        ] + [f"HN'de {topic} {counts[1]}→{counts[0]} hikâye"]

            key = _normalize(topic)
            if key and key in hf_map:
                value = external_score(hf_map[key])
                delta = deltas.get(key, 0.0)
                if delta > 0:
                    # Artış varsa o belirleyici: mutlak popülerlik değil ivme.
                    value = min(1.0, value * 0.5 + external_score(delta * 3) * 0.7)
                    signal.reasons.append(f"HF trend +{delta:.0f} ({hf_map[key]:.0f})")
                elif value > signal.external:
                    signal.reasons.append(f"HF trend {hf_map[key]:.0f}")
                signal.external = max(signal.external, value)

        # Başlıkta model adı geçmese bile HF listesindeki bir adla eşleşebilir.
        if not signal.external:
            for name, raw in hf_map.items():
                if len(name) >= 8 and name in title_norm:
                    signal.external = external_score(raw)
                    signal.reasons.append(f"HF trend {raw:.0f}")
                    break

        parts = sorted((signal.velocity, signal.topic_trend, signal.external), reverse=True)
        # OR mantığı: en güçlü sinyal belirleyici, ikincisi küçük pekiştirme.
        signal.score = round(min(1.0, parts[0] + 0.25 * parts[1]), 3)
        signals[item.key] = signal

    return signals
