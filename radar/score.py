"""Skorlama: 200 maddeyi okunabilir bir güne indiren karar katmanı.

Tasarım gerekçesi: bu sistemin varlık sebebi hazır AI bültenlerinin kaçırdığı
eksenler -- görsel/video üretimi, oyun üretimi, 3D/rigging/asset boru hattı.
O yüzden eksen önceliği skorun en ağır bileşeni; genel kurumsal AI haberi
yüksek güvenli bir kaynaktan gelse bile niş bir bulgunun önüne geçemiyor.

Skor tamamen açıklanabilir: her bileşen score_parts içinde saklanıyor ve
sayfada maddenin altında gösteriliyor. Bir madde neden üstte, görülebiliyor.
"""

from __future__ import annotations

import math
import re
from functools import lru_cache

from .models import AXES, Item

# Eksen öncelikleri. Niş eksenler genel olanların önünde -- tasarım kararı.
AXIS_PRIORITY: dict[str, float] = {
    "image": 1.6,
    "game": 1.6,
    "video": 1.5,
    "threed": 1.5,
    "model": 1.3,
    "infra": 0.9,
    "people": 0.8,
}

# Eksen tespiti iki katmanlı:
#   STRONG : nerede geçerse geçsin sayılır (başlık veya özet).
#   WEAK   : yalnız BAŞLIKTA geçerse sayılır.
# Gerekçe: ilk sürümde "model", "api", "release" gibi jenerik kelimeler özet
# metinlerinde her yerde geçtiği için maddelerin neredeyse tamamı model+infra
# etiketi aldı ve niş eksen sinyali tamamen silindi. Ölçüm: 12 maddenin 10'u
# aynı iki etiketi taşıyordu, skorlar 6.9-7.1'e sıkıştı.
AXIS_STRONG: dict[str, tuple[str, ...]] = {
    "image": (
        "text-to-image", "image generation", "image model", "image editing",
        "img2img", "inpaint", "outpaint", "stable diffusion", "midjourney",
        "comfyui", "controlnet", "flux.", "nano banana", "upscaler", "lora",
    ),
    "video": (
        "text-to-video", "image-to-video", "video generation", "video model",
        "sora", "veo 3", "veo3", "kling", "hailuo", "runway gen", "seedance",
        "ltx video", "lip sync", "frame interpolation", "world model",
    ),
    "game": (
        "game engine", "gamedev", "game development", "unreal engine", "godot",
        "unity 6", "level design", "procedural generation", "playable", "gameplay",
        "game design", "npc behavior", "video game",
    ),
    "threed": (
        "text-to-3d", "image-to-3d", "3d model", "3d generation", "rigging",
        "auto-rig", "skinning", "retopolog", "gaussian splat", "nerf",
        "mesh generation", "blender", "gltf", "usd scene", "motion capture",
        "animation retarget", "skeleton",
    ),
    "model": (
        "open weights", "open-weight", "state of the art", "benchmark",
        "outperforms", "context window", "fine-tuned", "multimodal",
        "reasoning model", "foundation model", "model card", "parameters",
    ),
    "infra": (
        "inference endpoint", "serverless gpu", "quantiz", "self-host",
        "throughput", "latency", "pricing", "rate limit", "open sourced",
    ),
    "people": (
        "raises", "funding round", "series a", "series b", "acquisition",
        "acquires", "lawsuit", "ipo", "valuation", "steps down", "joins",
        "partnership with",
    ),
}

AXIS_WEAK: dict[str, tuple[str, ...]] = {
    "image": ("diffusion", "sprite", "texture", "render", "visual"),
    "video": ("video", "animate", "motion", "cinematic"),
    "game": ("game", "games", "unity", "steam", "itch.io", "player"),
    "threed": ("3d", "mesh", "rig", "avatar", "character"),
    "model": ("model", "llm", "release", "launches", "introducing", "training", "agent"),
    "infra": ("api", "sdk", "gpu", "library", "framework", "toolkit", "deploy", "runtime"),
    "people": ("ceo", "founder", "startup", "announces", "hires", "interview"),
}

# Değer taşımayan kalıplar. Bunlar bültende yer kaplarsa sistem güven kaybeder.
NOISE_PATTERNS: tuple[tuple[str, float], ...] = (
    (r"\btop \d+\b", 1.5),
    (r"\bbest .{0,30}\b(of|in) 20\d\d\b", 1.5),
    (r"\b(how to|tutorial|guide|tips)\b", 0.8),
    (r"\b(webinar|sponsored|deal|discount|sale|coupon)\b", 2.5),
    (r"\b(we.re hiring|job opening|career)\b", 2.5),
    (r"\b(weekly roundup|newsletter|digest)\b", 0.6),
    # --- ilk gerçek koşudan sonra eklendi: listenin tepesini bunlar kirletti ---
    (r"^quoting\b", 3.0),                       # alıntı-link gönderileri
    (r"^\S+[-\w]* \d+\.\d+(\.\d+)?$", 2.5),  # çıplak sürüm notu: "llm-keys-ui 0.1"
    (r"^v?\d+\.\d+(\.\d+)?$", 2.5),            # çıplak sürüm etiketi: "v0.37.0"
    (r"\?\s*$", 1.8),                           # soru gönderisi (çoğunlukla reddit)
    (r"\b(wishing|anyone else|am i the only|help me|looking for|recommend)\b", 2.2),
    (r"\bhow \w+ is (using|accelerating|building)\b", 2.0),  # müşteri referans hikâyesi
    (r"\b(is expected to|reportedly|rumou?r)\b", 1.0),
)

# AI-alaka kapısı. Bazı kaynaklar (oyun sektörü basını, HN, motor sürümleri)
# AI'a özel değil; oradan gelen bir madde AI ile ilgili olduğunu kendi metninde
# göstermek zorunda. Ölçüm: bu kapı olmadan "Twitch CEO Names GTA 6 Release
# Window" oyun ekseninden günün listesine girdi.
AI_TERMS: tuple[str, ...] = (
    "ai", "a.i.", "artificial intelligence", "genai", "generative", "llm",
    "diffusion", "neural", "machine learning", "deep learning", "transformer",
    "gpt", "claude", "gemini", "llama", "qwen", "mistral", "midjourney",
    "stable diffusion", "copilot", "agent", "prompt", "inference", "model",
    "openai", "anthropic", "hugging face", "nvidia", "training",
)
OFF_TOPIC_PENALTY = 4.0

# Skor bileşenlerinin ağırlıkları.
W_SOURCE = 1.0
W_AXIS = 2.2
W_SIGNAL = 1.1
W_RECENCY = 1.4
W_CORROBORATION = 1.2

RECENCY_HALFLIFE_HOURS = 30.0
MAX_AGE_HOURS = 96.0


# Metinden eksen çıkmayınca kaynağın ön-eğilimine düşüyoruz, ama bu bir tahmin.
# Ölçüm: hf-papers'ın [model,image,video,threed] eğilimi, konuyla ilgisiz
# yapısal-veri makalelerine dört eksen birden takıp listenin 5/12'sini onlara
# verdi. Çıkarımsal eksen artık bu katsayıyla sönümleniyor.
INFERRED_AXIS_CONFIDENCE = 0.5


@lru_cache(maxsize=2048)
def _term_pattern(term: str) -> re.Pattern[str]:
    """Terimi kelime sınırıyla arayan desen.

    Düz altdizi araması sessiz yanlış-pozitif üretiyordu: "ipo" terimi
    "dipole" içinde eşleşip bir ışık saçılımı makalesine "şirket" ekseni
    taktı. Sınır sınıfı harf/rakam; "3d" ve "rig " gibi terimler bozulmasın
    diye kenarlarda yalnız harf-rakam engelleniyor.
    """
    return re.compile(rf"(?<![a-z0-9]){re.escape(term.strip())}(?![a-z0-9])")


def _matches(text: str, words: tuple[str, ...]) -> bool:
    return any(_term_pattern(w).search(text) for w in words)


def detect_axes(item: Item) -> tuple[list[str], bool]:
    """Eksenleri çıkarır. Döner: (eksenler, metinden_mi_bulundu)."""
    title = item.title.lower()
    full = f"{item.title} {item.summary}".lower()

    found = {axis for axis, words in AXIS_STRONG.items() if _matches(full, words)}
    found |= {axis for axis, words in AXIS_WEAK.items() if _matches(title, words)}
    if found:
        return sorted(found), True
    return sorted(set(item.source_axes) or {"model"}), False


def noise_penalty(item: Item) -> float:
    title = item.title.lower()
    return sum(weight for pattern, weight in NOISE_PATTERNS if re.search(pattern, title))


def is_ai_relevant(item: Item) -> bool:
    """Metin AI ile ilgili olduğunu gösteriyor mu? Kelime sınırıyla aranır."""
    return _matches(f"{item.title} {item.summary}".lower(), AI_TERMS)


def score_item(item: Item) -> Item:
    """Tek maddeyi puanlar ve her bileşeni score_parts'a yazar (açıklanabilirlik)."""
    item.axes, from_text = detect_axes(item)

    axis_component = max((AXIS_PRIORITY.get(a, 0.5) for a in item.axes), default=0.5)
    # İkinci eksen küçük bir bonus: kesişimde duran madde (ör. 3D + oyun) değerli.
    # Yalnız gerçekten metinden okunmuş eksenlerde geçerli.
    if from_text and len(item.axes) > 1:
        ranked = sorted((AXIS_PRIORITY.get(a, 0.5) for a in item.axes), reverse=True)
        axis_component += 0.25 * ranked[1]
    if not from_text:
        axis_component *= INFERRED_AXIS_CONFIDENCE

    age = min(item.age_hours, MAX_AGE_HOURS)
    recency = math.exp(-age / RECENCY_HALFLIFE_HOURS)
    signal = math.log1p(max(0, item.signal)) / math.log(500)
    corroboration = item.score_parts.get("corroboration", 0.0)
    penalty = noise_penalty(item)
    if not item.ai_native and not is_ai_relevant(item):
        penalty += OFF_TOPIC_PENALTY

    parts = {
        "kaynak": round(W_SOURCE * item.source_weight, 3),
        "eksen": round(W_AXIS * axis_component, 3),
        "sinyal": round(W_SIGNAL * signal, 3),
        "tazelik": round(W_RECENCY * recency, 3),
        "capraz_kaynak": round(W_CORROBORATION * min(corroboration, 3.0), 3),
        "gurultu_cezasi": round(-penalty, 3),
    }
    item.score_parts["_eksen_metinden"] = 1.0 if from_text else 0.0
    item.score_parts = {**item.score_parts, **parts}
    item.score = round(sum(parts.values()), 3)
    return item


def score_all(items: list[Item]) -> list[Item]:
    scored = [score_item(i) for i in items]
    scored.sort(key=lambda i: i.score, reverse=True)
    return scored


# Puan tabanı. 126 adaylık gerçek bir günün dağılımı ölçülerek seçildi:
# 4.5 altındaki bant neredeyse tamamen dolgu (müşteri referans hikâyeleri,
# kişisel blog notları), 4.5 üstü gerçek haber. Taban oran değil mutlak,
# çünkü oransal taban sakin bir günde gürültünün girmesine izin veriyor.
# Sonuç: sakin günde liste kotadan kısa çıkar -- bu doğru davranış.
SCORE_FLOOR = 4.5
BRIEF_SCORE_FLOOR = 3.0   # etkinlik duyuruları gibi "faydalı ama öncelikli değil" maddeler burada kalsın


def select_daily(
    items: list[Item],
    limit: int = 12,
    max_per_axis: int = 4,
    max_per_source: int = 2,
    max_per_category: int = 4,
) -> list[Item]:
    """Günün listesini seçer: sabit kota + kategori/eksen/kaynak çeşitliliği.

    Ham sıralamayı olduğu gibi kesmek listeyi tek konuya boğuyor. İki turlu
    seçim var: önce her kategorinin en iyisi (puan tabanını geçiyorsa), sonra
    kalan yerler ham skora göre, üç tavana saygıyla.
    """
    if not items:
        return []

    eligible = [i for i in items if i.score >= SCORE_FLOOR]
    chosen: list[Item] = []
    per_axis: dict[str, int] = {}
    per_source: dict[str, int] = {}
    per_category: dict[str, int] = {}

    def take(item: Item) -> None:
        chosen.append(item)
        per_axis[primary_axis(item)] = per_axis.get(primary_axis(item), 0) + 1
        per_source[item.source] = per_source.get(item.source, 0) + 1
        per_category[category_of(item)] = per_category.get(category_of(item), 0) + 1

    def fits(item: Item) -> bool:
        return (
            per_axis.get(primary_axis(item), 0) < max_per_axis
            and per_source.get(item.source, 0) < max_per_source
            and per_category.get(category_of(item), 0) < max_per_category
        )

    seen_keys: set[str] = set()

    # 1. tur: her kategorinin en iyisi (puan tabanının üstündeyse).
    for key, _, _ in CATEGORIES:
        if len(chosen) >= limit:
            break
        best = next(
            (i for i in eligible if category_of(i) == key and i.key not in seen_keys),
            None,
        )
        if best is not None:
            take(best)
            seen_keys.add(best.key)

    # 2. tur: kalan yerler ham skora göre (taban yine geçerli).
    for item in eligible:
        if len(chosen) >= limit:
            break
        if item.key in seen_keys or not fits(item):
            continue
        take(item)
        seen_keys.add(item.key)

    chosen.sort(key=lambda i: i.score, reverse=True)
    return chosen


# --- kategoriler ---------------------------------------------------------------
# Yedi eksen doğrudan bölüm yapılırsa 12 madde yedi parçaya dağılıyor ve okuma
# ritmi kırılıyor. Bölümler kaba tutuluyor, hassasiyet madde üstündeki eksen
# etiketinde korunuyor.
CATEGORIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("uretim", "Üretim", ("image", "video", "threed")),
    ("oyun", "Oyun", ("game",)),
    ("arastirma", "Modeller & Araştırma", ("model",)),
    ("ekosistem", "Ekosistem", ("infra", "people")),
)

CATEGORY_OF_AXIS: dict[str, str] = {
    axis: key for key, _, axes in CATEGORIES for axis in axes
}


def primary_axis(item: Item) -> str:
    """Maddenin baskın ekseni: en yüksek öncelikli olan."""
    return max(item.axes, key=lambda a: AXIS_PRIORITY.get(a, 0.5), default="model")


def category_of(item: Item) -> str:
    return CATEGORY_OF_AXIS.get(primary_axis(item), "ekosistem")


def group_by_category(items: list[Item]) -> list[tuple[str, str, list[Item]]]:
    """Maddeleri sabit kategori sırasına göre gruplar. Boş kategoriler düşer."""
    grouped: list[tuple[str, str, list[Item]]] = []
    for key, label, _ in CATEGORIES:
        members = [i for i in items if category_of(i) == key]
        if members:
            grouped.append((key, label, members))
    return grouped


def select_secondary(items: list[Item], chosen: list[Item], limit: int = 8) -> list[Item]:
    """Kotanın altında kalan maddelerden kısa liste.

    Ana listeye girmeyen ama tamamen atılması yazık olan maddeler (ör. etkinlik
    duyuruları, ikincil sürüm notları) burada tek satır olarak görünür. Sayfayı
    şişirmeden kapsamı genişletir.
    """
    taken = {i.key for i in chosen}
    rest = [i for i in items if i.key not in taken and i.score >= BRIEF_SCORE_FLOOR]
    per_source: dict[str, int] = {}
    out: list[Item] = []
    for item in rest:
        if len(out) >= limit:
            break
        if per_source.get(item.source, 0) >= 2:
            continue
        out.append(item)
        per_source[item.source] = per_source.get(item.source, 0) + 1
    return out
