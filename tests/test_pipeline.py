"""Boru hattı testleri.

Testlerin çoğu ilk gerçek koşuda ortaya çıkan somut hataları kilitliyor.
Her birinin başında hangi hatayı koruduğu yazıyor.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from radar.models import Item, canonical_url, clean_text, title_fingerprint
from radar.hype import (
    _is_product_like, canonical_topic, extract_topics, trend_score, velocity_score,
)
from radar.normalize import (
    drop_seen, drop_shown_unless_rising, drop_stale, load_seen, merge_duplicates, record_seen,
)
from radar.score import (
    apply_hype, assign_topics, category_of, detect_axes, group_by_category,
    is_ai_relevant, noise_penalty, score_all, select_daily, select_secondary,
)


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


# --- kategorili tasarım turu ----------------------------------------------------

def test_eksen_eslestirmesi_kelime_siniri_kullanir():
    """Regresyon: 'ipo' terimi 'dipole' içinde eşleşip bir ışık saçılımı
    makalesine 'şirket' ekseni taktı. Düz altdizi araması yetmiyor."""
    item = make("An Elementary Expression for Multiple Scattering in Microflake Media",
                summary="We derive a diffuse-like BRDF using a dipole approximation",
                source_axes=["threed", "game"])
    axes, from_text = detect_axes(item)
    assert "people" not in axes
    assert from_text is False


def test_kelime_siniri_gercek_eslesmeyi_bozmaz():
    """Sınır kuralı '3d' ve 'ipo' gibi kısa terimleri kullanılamaz hale
    getirmemeli."""
    axes, from_text = detect_axes(make("Startup raises Series B after IPO rumors"))
    assert from_text and "people" in axes
    axes, _ = detect_axes(make("New 3D model generator ships today"))
    assert "threed" in axes


def test_kategori_tavani_tek_bolumu_sismekten_korur():
    """Regresyon: görsel+video+3D aynı kategoriye düştüğü için Üretim bölümü
    12 maddenin 7'sini aldı, kategorize etmenin anlamı kalmadı."""
    items = score_all(
        [make(f"New text-to-video model release {n}", source=f"vid{n}") for n in range(8)]
        + [make(f"Unreal engine gamedev AI tool {n}", source=f"game{n}") for n in range(4)]
    )
    chosen = select_daily(items, limit=12, max_per_category=4)
    counts: dict[str, int] = {}
    for item in chosen:
        counts[category_of(item)] = counts.get(category_of(item), 0) + 1
    assert max(counts.values()) <= 4


def test_temsil_garantisi_zayif_maddeyi_listeye_sokmaz():
    """Regresyon: kategori temsili uğruna 2.83 puanlı bir madde, çok daha
    yüksek puanlı maddeler dururken ana listeye girdi."""
    strong = [make(f"New text-to-3D rigging model {n}", source=f"s{n}", source_weight=3.0)
              for n in range(6)]
    weak = make("We are hiring for a webinar coupon deal", source="zayif", source_weight=0.5)
    items = score_all(strong + [weak])
    chosen = select_daily(items, limit=6)
    assert weak not in chosen, "puan tabanının altındaki madde temsil için alınmamalı"


def test_kisa_kisa_ana_listeyle_cakismaz():
    items = score_all([make(f"AI model release {n}", source=f"src{n}") for n in range(20)])
    main = select_daily(items, limit=8)
    brief = select_secondary(items, main, limit=6)
    assert not ({i.key for i in main} & {i.key for i in brief})
    assert len(brief) == 6


def test_gruplama_bos_kategoriyi_dusurur():
    items = score_all([make("New text-to-video model", source="a")])
    groups = group_by_category(items)
    assert len(groups) == 1 and groups[0][0] == "uretim"


# --- hype katmanı ---------------------------------------------------------------

def test_konu_cikarimi_surum_numarasi_ister():
    """Regresyon: 'çok parçalı büyük harfli ad' kuralı 'Reason About' ve
    'LLM Models' gibi jenerik ifadeleri model adı sanıyordu."""
    urun = lambda t: [e for e in extract_topics(t) if _is_product_like(e)]
    assert urun("Pirate Face Rescues LLM Models from Deletion") == []
    assert "Qwen Image 2.1" in urun("Qwen Image 2.1 ships today")


def test_konu_cikarimi_bastaki_durak_kelimeyi_yutmaz():
    """Regresyon: açgözlü eşleşme 'Can MiniMax-H3 Reason' üretiyor, baş token
    durak kelime olduğu için gerçek model adı tamamen kayboluyordu."""
    topics = extract_topics("Can MiniMax-H3 Reason About the Physical World")
    assert any("MiniMax-H3" in t for t in topics)


def test_kanonik_konu_ayni_modeli_birlestirir():
    """Regresyon: aynı model üç farklı dizgeye çıkıp konu tavanını deldi ve
    tek duyuru listenin ilk üç sırasını birden aldı."""
    assert canonical_topic("Minimax H3 Video") == canonical_topic("MiniMax-H3 Reason")
    assert canonical_topic("Qwen Image 2.1") != canonical_topic("Kling 3.0")
    assert canonical_topic("Pirate Face") == ""


def test_trend_puani_kucuk_sayilarda_susar():
    """Ölçümle kalibre edildi: 1→3 hikâye dalga değil, 15→36 dalga."""
    assert trend_score(3, 1) == 0.0
    assert trend_score(36, 15) >= 0.6
    assert trend_score(17, 22) == 0.0, "düşüşte olan konu yükseliş sayılmamalı"


def test_hiz_kaynak_bazinda_normalize_edilir():
    """HN'de 30 oy/saat ile HF Papers'ta 3 oy/saat aynı anlama geliyor."""
    refs = {"hackernews": 30.0, "hf-papers": 3.0}
    hizli_hn = make("a", source="hackernews", signal=300,
                    published=(datetime.now(timezone.utc) - timedelta(hours=10)).isoformat())
    hizli_hf = make("b", source="hf-papers", signal=30,
                    published=(datetime.now(timezone.utc) - timedelta(hours=10)).isoformat())
    assert velocity_score(hizli_hn, refs) == pytest.approx(velocity_score(hizli_hf, refs))
    assert velocity_score(hizli_hn, refs) == pytest.approx(1.0)


class _Sinyal:
    def __init__(self, score, rising=True, label="test"):
        self.score, self.label = score, label
        self.is_rising = rising


def test_yukselisteki_madde_puan_tabanini_atlar():
    """Kullanıcı kuralı bir OR: hype yapmışsa ekseni ne olursa olsun girer."""
    dusuk = make("Some offbeat corporate note", source="techcrunch-ai", source_weight=0.5)
    items = score_all([dusuk])
    assert items[0].score < 4.5, "önce taban altında olduğunu doğrula"
    apply_hype(items, {dusuk.key: _Sinyal(0.9)})
    assert select_daily(items, limit=5) == [dusuk]


def test_cekirdek_eksen_ve_yukselis_birlikte_carpan_alir():
    """'Oyun yapan VE trend olan Qwen kopyası' senaryosu."""
    oyun = make("New text-to-3D rigging model for games", source="fal", source_weight=2.0)
    genel = make("Some corporate reorg announcement", source="fal", source_weight=2.0)
    items = score_all([oyun, genel])
    taban = {i.key: i.score for i in items}
    apply_hype(items, {oyun.key: _Sinyal(0.8), genel.key: _Sinyal(0.8)})
    artis_oyun = oyun.score - taban[oyun.key]
    artis_genel = genel.score - taban[genel.key]
    assert artis_oyun > artis_genel, "çekirdek eksen + yükseliş kombosu çarpan almalı"


def test_gosterilmis_madde_ancak_yukselisteyse_geri_doner():
    """Bastırma bir konu tam dalgaya dönüşürken susmamıza yol açıyordu."""
    yukselen = make("rising topic"); yukselen.previously_shown = True; yukselen.hype_rising = True
    sonen = make("quiet topic"); sonen.previously_shown = True
    kept, dropped = drop_shown_unless_rising([yukselen, sonen])
    assert kept == [yukselen] and dropped == 1


def test_ayni_konu_listeyi_ele_geciremez():
    items = score_all([make(f"Minimax H3 update number {n}", source=f"s{n}") for n in range(5)])
    assign_topics(items)
    for i in items:
        i.topic_key = "minimaxh3"
    chosen = select_daily(items, limit=5, max_per_topic=2)
    assert len(chosen) <= 2


def test_yavas_kaynak_tam_hiz_sayilmaz():
    """Regresyon: az örnekli kaynakta referans kendi maksimumuna inip saatte
    1 oy alan makaleyi 'tam hızlı' yapıyor, gerekçeye '1 oy/saat' yazıyordu."""
    from radar.hype import _velocity_references
    yavas = [
        make(f"paper {n}", source="hf-papers", signal=s,
             published=(datetime.now(timezone.utc) - timedelta(hours=100)).isoformat())
        for n, s in enumerate((90, 100, 110, 140))
    ]
    refs = _velocity_references(yavas)
    assert refs["hf-papers"] >= 6.0, "referans tabanın altına inmemeli"
    assert max(velocity_score(i, refs) for i in yavas) < 0.5


def test_dis_metrik_orta_siradaki_modeli_yukselis_saymaz():
    """Regresyon: logaritmik eğri orta sıradaki modeli (213) tek başına
    yükseliş sayıyordu; 120 maddenin 14'ü 'yükselişte' çıkmıştı."""
    from radar.hype import PROMOTION_THRESHOLD, external_score
    assert external_score(213) < PROMOTION_THRESHOLD
    assert external_score(1013) > PROMOTION_THRESHOLD
    assert external_score(0) == 0.0


# --- yan panel / gömülebilirlik -------------------------------------------------

@pytest.mark.parametrize("xfo,csp,engelli", [
    ("DENY", "", True),
    ("SAMEORIGIN", "", True),
    ("", "default-src 'self'; frame-ancestors 'none'", True),
    ("", "frame-ancestors 'self' https://x.test", True),
    ("", "frame-ancestors *", False),
    ("", "", False),
    ("", "default-src 'self'", False),
])
def test_gomulebilirlik_basliklari_dogru_okunur(xfo, csp, engelli):
    """Ölçüm (gerçek günün 18 linki): 6'sı gömülebiliyor. HuggingFace DENY,
    Reddit/OpenAI/TechCrunch SAMEORIGIN veya frame-ancestors 'none'."""
    from radar.embed import _blocks_framing
    assert _blocks_framing(xfo, csp) is engelli


def test_host_normalize_edilir():
    from radar.embed import host_of
    assert host_of("https://www.Reddit.com/r/x") == host_of("https://reddit.com/r/y")


def test_gomulemeyen_maddede_bayrak_kapali(tmp_path):
    """Yoklama çevrimdışıyken hiçbir link gömülebilir sayılmamalı: panel boş
    iframe göstermektense önizlemeye düşsün."""
    from radar.embed import annotate
    items = [make("x", url="https://reddit.com/a"), make("y", url="https://80.lv/b")]
    count = annotate(items, tmp_path, offline=True)
    assert count == 0 and all(not i.embeddable for i in items)
