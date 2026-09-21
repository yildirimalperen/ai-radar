"""Boru hattı testleri.

Testlerin çoğu ilk gerçek koşuda ortaya çıkan somut hataları kilitliyor.
Her birinin başında hangi hatayı koruduğu yazıyor.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from radar.models import Item, canonical_url, clean_text, title_fingerprint
from radar.normalize import drop_seen, drop_stale, merge_duplicates, record_seen, load_seen
from radar.score import detect_axes, is_ai_relevant, noise_penalty, score_all, select_daily


def make(title: str, **kwargs) -> Item:
    defaults = {
        "url": f"https://example.test/{abs(hash(title)) % 10**8}",
        "source": "test",
        "published": datetime.now(timezone.utc).isoformat(),
    }
    return Item(title=title, **{**defaults, **kwargs})


# --- url / metin normalizasyonu -------------------------------------------------

def test_canonical_url_takip_parametrelerini_atar():
    a = canonical_url("https://www.OpenAI.com/news/x/?utm_source=t&id=5")
    b = canonical_url("http://openai.com/news/x?id=5")
    assert a == b


def test_clean_text_html_varliklarini_cozer():
    """Regresyon: sayfada ham '&#x2014;' görünüyordu (feed + yayın çift-escape)."""
    assert "—" in clean_text("bir film &#x2014; ve devamı")
    assert "&#x2014;" not in clean_text("bir film &#x2014; ve devamı")


def test_clean_text_kelime_sinirinda_kirpar():
    """Regresyon: özet kelime ortasından kesiliyordu ('...for scalin')."""
    out = clean_text("alpha beta gamma delta epsilon zeta", limit=20)
    assert out.endswith("…")
    assert "epsilo" not in out


# --- dedup ----------------------------------------------------------------------

def test_ayni_haber_tek_maddeye_iner_ve_capraz_kaynak_sayilir():
    items = [
        make("OpenAI ships new image model", source="openai", source_weight=3.0),
        make("OpenAI Ships New Image Model", source="techcrunch", source_weight=0.5),
    ]
    merged = merge_duplicates(items)
    assert len(merged) == 1
    assert merged[0].source == "openai", "temsilci en güvenilir kaynak olmalı"
    assert merged[0].score_parts["corroboration"] == 1.0


def test_bayat_maddeler_elenir():
    """Regresyon: 69 günlük bir blog yazısı günlük listenin 3. sırasına çıktı."""
    old = make("eski", published=(datetime.now(timezone.utc) - timedelta(days=40)).isoformat())
    new = make("yeni")
    kept, dropped = drop_stale([old, new], max_age_days=10)
    assert [i.title for i in kept] == ["yeni"]
    assert dropped == 1


def test_gecmiste_gorulen_madde_tekrar_cikmaz(tmp_path):
    """Kayıt-sonra-eleme döngüsü. Bastırma önceki günler için geçerli olduğundan
    kaydı dün tarihiyle yazıyoruz; aynı gün davranışı ayrı testte."""
    import json
    item = make("tek sefer gosterilecek baslik")
    dun = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    (tmp_path / "seen.jsonl").write_text(
        json.dumps({"key": item.key, "first_seen": dun}) + "\n", encoding="utf-8")
    fresh, dropped = drop_seen([item], load_seen(tmp_path))
    assert fresh == [] and dropped == 1


# --- eksen tespiti --------------------------------------------------------------

def test_niche_eksen_metinden_okunur():
    axes, from_text = detect_axes(make("Tripo ships image-to-3D with auto-rigging"))
    assert from_text and "threed" in axes


def test_eksen_bulunamazsa_kaynak_egilimi_tahmin_sayilir():
    """Regresyon: hf-papers'ın 4 eksenli eğilimi ilgisiz makalelere kesin bilgi
    gibi uygulanınca listenin 5/12'sini araştırma makaleleri aldı."""
    item = make("LimiX-2: A Contextual Mechanism Network for Structured Data",
                source_axes=["model", "image", "video", "threed"])
    axes, from_text = detect_axes(item)
    assert from_text is False, "bu başlıkta niş eksen yok, tahmin olmalı"


def test_tahmin_edilen_eksen_sonumlenir():
    kesin = make("New text-to-3D model with automatic rigging", source_weight=1.0)
    tahmin = make("Bir konu hakkinda genel yazi",
                  source_axes=["threed"], source_weight=1.0)
    a, b = score_all([kesin, tahmin])
    assert a.title.startswith("New text-to-3D"), "metinden okunan eksen öne geçmeli"


# --- gürültü ve alaka -----------------------------------------------------------

@pytest.mark.parametrize("title", [
    "Quoting voxium",                         # alıntı gönderisi
    "llm-keys-ui 0.1",                        # çıplak sürüm notu
    "v0.37.0",                                # çıplak sürüm etiketi
    "Top 10 AI tools for your business",      # liste haberi
    "Still wishing on a local editing model", # dilek gönderisi
    "How Cooley is accelerating IPO work with ChatGPT",  # müşteri referansı
])
def test_dusuk_ozlu_basliklar_cezalandirilir(title):
    """Regresyon: bu altı kalıp ilk gerçek koşuda listenin tepesini işgal etti."""
    assert noise_penalty(make(title)) > 0


def test_ai_disi_haber_ai_olmayan_kaynakta_elenir():
    """Regresyon: 'Twitch CEO Names GTA 6 Release Window' oyun ekseninden girdi."""
    off = make("Twitch CEO Names GTA 6 Multiplayer Release Window",
               source="80lv", ai_native=False, source_axes=["game"])
    on = make("Unity ships AI-assisted level generation",
              source="80lv", ai_native=False, source_axes=["game"])
    assert not is_ai_relevant(off)
    assert is_ai_relevant(on)
    scored = score_all([off, on])
    assert scored[0].title.startswith("Unity")
    assert scored[-1].score_parts["gurultu_cezasi"] <= -4.0


def test_ai_native_kaynak_kapidan_muaf():
    item = make("Introducing our newest release", source="openai", ai_native=True)
    assert noise_penalty(item) == 0


# --- seçim ----------------------------------------------------------------------

def test_tek_kaynak_gunu_ele_geciremez():
    items = score_all([make(f"text-to-3D rigging model number {n}", source="hf-papers")
                       for n in range(10)])
    chosen = select_daily(items, limit=8, max_per_source=2)
    assert sum(1 for i in chosen if i.source == "hf-papers") <= 2


def test_kota_asilmaz():
    items = score_all([make(f"AI model release {n}", source=f"src{n}") for n in range(40)])
    assert len(select_daily(items, limit=12)) <= 12


def test_skorlar_ayrisir():
    """Regresyon: ilk sürümde ilk 10 madde 6.9-7.1'e sıkışmıştı; sıralayıcı
    fiilen ayrım yapmıyordu."""
    items = score_all([
        make("Tripo ships image-to-3D model with automatic rigging", source_weight=2.5),
        make("Top 10 AI tools for your business", source_weight=0.5),
        make("Enterprise announces partnership", source_weight=1.0),
        make("New text-to-video model beats Kling on benchmark", source_weight=2.0),
    ])
    spread = items[0].score - items[-1].score
    assert spread > 2.0, f"skor aralığı çok dar: {spread:.2f}"


def test_gun_ici_ikinci_kosu_ayni_listeyi_uretir(tmp_path):
    """Regresyon: workflow gün içinde ikinci kez koşunca sabahki 12 madde
    'görülmüş' sayılıp eleniyor, sayfa çok daha zayıf maddelerle yeniden
    yazılıyordu. Bastırma yalnız önceki günler için geçerli olmalı."""
    items = [make(f"AI model release number {n}", source=f"src{n}") for n in range(5)]
    record_seen(items, tmp_path)
    fresh, dropped = drop_seen(items, load_seen(tmp_path))
    assert dropped == 0, "bugün kaydedilenler aynı gün bastırılmamalı"
    assert len(fresh) == 5


def test_onceki_gun_gosterilen_madde_bastirilir(tmp_path):
    """Gün içi korumasının önceki gün elemesini bozmadığını doğrular."""
    import json
    from datetime import datetime, timedelta, timezone
    dun = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    item = make("dun gosterilen bir baslik")
    (tmp_path / "seen.jsonl").write_text(
        json.dumps({"key": item.key, "first_seen": dun}) + "\n", encoding="utf-8")
    fresh, dropped = drop_seen([item], load_seen(tmp_path))
    assert dropped == 1 and fresh == []
