# AI Radar

Görsel üretimi, video üretimi, oyun üretimi, 3D/rigging boru hattı, yeni modeller
ve öncü şirketler ekseninde **günlük bir brief** üreten statik yayın hattı.

Hazır AI bültenleri (TLDR, The Batch) LLM/agent ekseninde yazıyor; bu projenin
varlık sebebi onların dipnot geçtiği eksenleri öne almak.

**Durum: 1 haftalık pilot.** Amaç sistemin "çalışması" değil, *faydalı oranının
ölçülmesi*. Bir hafta sonra sayfadaki ✓/✗ sayacı karar verecek.

---

## Nasıl çalışıyor

```
sources.yaml → collect → dedup → score → select → render → docs/ (GitHub Pages)
   31 kaynak     ~200      ~120     ~120     12       statik sayfa + arşiv
```

| Aşama | Dosya | İş |
|---|---|---|
| Toplama | `radar/collect.py` | 5 kaynak türü (rss, reddit, hn, hf_papers, arxiv), paralel; tek kaynağın ölmesi koşuyu düşürmez |
| Dedup | `radar/normalize.py` | Yaş sınırı (10 gün) → çapraz-kaynak birleştirme → 7 günlük tekrar elemesi |
| Hype | `radar/hype.py` | Yükseliş ölçümü: hız + HN konu eğimi + HF trendingScore/ivme |
| Skorlama | `radar/score.py` | 6 bileşenli açıklanabilir skor; her kırılım sayfada görünür |
| Seçim | `radar/score.py` | Kota ≤12; kategori/eksen başına ≤4, kaynak başına ≤2, puan tabanı 4.5 |
| Yayın | `radar/render.py` | Dört kategoriye ayrılmış statik sayfa + kısa kısa + arşiv + arama |

### Sayfa tasarımı

Dört kaba kategori, madde üstünde ince eksen etiketi:

| Bölüm | Kapsadığı eksenler |
|---|---|
| **Üretim** | görsel, video, 3D / rigging |
| **Oyun** | oyun üretimi |
| **Modeller & Araştırma** | yeni modeller, makaleler |
| **Ekosistem** | araç & altyapı, şirketler, etkinlikler |

Yedi ekseni doğrudan bölüm yapmak 12 maddeyi yedi parçaya bölüp okuma ritmini
kırıyordu; bölümler kaba, hassasiyet etiketlerde. Kategorisi boş kalan bölüm
sayfada görünmez.

En altta **Kısa kısa**: kotanın altında kalan 8 madde tek satır. "Faydalı ama
öncelikli değil" olan şeyler (etkinlik duyuruları, ikincil sürüm notları)
buraya düşer -- elenmezler, sadece yer kaplamazlar.

Kart yığını yerine editoryal düzen (beyaz alan + saç teli ayraç), web yazı tipi
yok (sistem yığını anında boyanır), tek vurgu rengi, açık/koyu tema.

### Skor bileşenleri

| Bileşen | Ne ölçüyor |
|---|---|
| `kaynak` | Kaynağın taban güveni (`sources.yaml` içinde `weight`) |
| `eksen` | En yüksek öncelikli eksen; niş eksenler (görsel/video/oyun/3D) genel olanların önünde |
| `sinyal` | Kaynağın kendi oyu (HN puanı, Reddit upvote) — logaritmik |
| `tazelik` | 30 saat yarılanma ömrüyle üstel sönüm |
| `capraz_kaynak` | Kaç bağımsız kaynak aynı haberi verdi |
| `gurultu_cezasi` | Düşük özlü kalıplar + AI-alaka kapısı |

Skor **tamamen açıklanabilir**: sayfadaki her maddenin sağ altındaki puana
tıklayınca kırılım tablosu açılıyor. Bir madde neden üstte, görülebiliyor.

### Yükseliş (hype) katmanı

Bir maddenin *kendi* özellikleri (kaynak, eksen, tazelik) ile *dünyanın ona
verdiği tepki* farklı şeyler. İkincisi ayrı bir katman ve **toplanarak değil,
ayrı bir kapı olarak** kullanılıyor:

- **İlgi yolu** — çekirdek eksende (oyun/görsel/video/3D) ise sıfır ilgiyle girer.
- **Yükseliş yolu** — yükseliş eşiğini (0.60) geçerse ekseni ne olursa olsun girer,
  puan tabanını atlar.
- **İkisi birden** ise çarpan alır (×1.35). "Oyun yapan **ve** trend olan Qwen
  kopyası" durumu tam olarak bu.

Üç sinyal:

| Sinyal | Ne | Durum |
|---|---|---|
| **Hız** | oy / yaş, kaynak bazında normalize | Çalışıyor, ama akışın yalnız %16'sı oy taşıyor |
| **HN konu eğimi** | konunun haftalık hikâye sayısındaki büyüme | Çalışıyor ama **nadiren ateşler** (aşağıya bak) |
| **HF trendingScore** | HuggingFace'in bakımlı hype metriği + günlük ivmesi | En güçlü sinyal |

Sayfada yükselen maddede `↑ yükselişte` rozeti ve gerekçesi görünür
(`HF trend 1015`, `32 oy/saat`). Böylece eşiğin doğru olup olmadığını ✓/✗ ile
denetleyebiliyorsun.

**Bastırma artık yükselişi engellemiyor.** Daha önce gösterilen bir madde
eleniyordu; yani bir konu tam dalgaya dönüşürken susuyorduk. Artık havuzda
kalıp skorlanıyor ve yükselişteyse `↑ yükselişte · yeniden` etiketiyle dönüyor.

### Ölçümle ELENEN yaklaşımlar

Bunlar denendi ve veriyle çürütüldü; tekrar denenmesin diye yazılı:

**"Kaç bağımsız kaynak aynı şeyi söyledi" bir hype ölçüsü olamaz.** Gerçek bir
günde 122 maddenin **0'ı** birden fazla kaynakta geçti; varlık seviyesinde de
274 addan yalnız 2'si (ikisi de "Google"/"ChatGPT" gibi jenerik) eşleşti. Kök
neden: 31 kaynağımız birbiriyle örtüşmeyen nişler, aynı gün içinde ölçülecek
artıklık yok.

**HN konu eğimi niş konularımız için yetersiz.** Ayrıca HN Algolia varsayılan
olarak yazım-hatası toleranslı: `rigging` sorgusu "Rising Fuel Prices"i, `veo`
sorgusu "Voodoo"yu eşleştiriyor. Sonuçları kendimiz süzüyoruz, ve süzdükten
sonra gerçek hacim çok küçük: `rigging` ham 53 → gerçek 1, `veo` ham 815 →
gerçek 0. Yalnız ana-akım model adları sayı üretiyor (`qwen` 5→12). Sinyal
tutuldu ama nadiren ateşleyeceği biliniyor.

### Üç koruma kapısı

**AI-alaka kapısı.** 80lv, gamesindustry, Hacker News, Unity, Godot gibi
kaynaklar AI'a özel değil (`ai_native: false`). Oradan gelen bir madde AI ile
ilgili olduğunu kendi metninde göstermek zorunda, yoksa −4.0 ceza alıyor.

**Çıkarımsal eksen sönümü.** Metinden eksen okunamazsa kaynağın ön-eğilimine
düşülür, ama bu bir tahmindir ve 0.5 katsayıyla sönümlenir.

**Puan tabanı (4.5).** 126 adaylık gerçek bir günün dağılımı ölçülerek seçildi:
bu bandın altı neredeyse tamamen dolgu (müşteri referans hikâyeleri, kişisel
blog notları), üstü gerçek haber. Taban oransal değil mutlak -- oransal taban
sakin bir günde gürültünün girmesine izin veriyor. **Sonuç: sakin bir günde
liste kotadan kısa çıkar. Bu bir arıza değil, tasarım.**

Üçü de gerçek koşularda ölçülen somut hatalara karşı eklendi; gerekçeler kodun
içinde yazılı, regresyonları `tests/test_pipeline.py` içinde (28 test).

---

## Kurulum

```bash
uv venv && uv pip install feedparser PyYAML pytest
python -m radar.cli run --dry-run --no-llm     # dosya yazmadan listeyi gör
python -m radar.cli run                        # docs/ altına yayınla
python -m pytest tests/ -q
```

### GitHub Pages

1. Repo → Settings → Pages → Source: **Deploy from a branch**, branch `main`, klasör `/docs`.
2. Actions her gün 03:00 UTC (06:00 TR) koşar, `docs/` ve `archive/` günceller.
3. Elle tetiklemek için: Actions → "Günlük radar" → Run workflow.

### İsteğe bağlı sırlar (ikisi de olmadan sistem çalışır)

| Sır | Ne kazandırıyor | Yoksa ne olur |
|---|---|---|
| `ANTHROPIC_API_KEY` | Her maddeye tek cümlelik "neden önemli" notu | Notlar üretilmez, sıralama aynı kalır |
| `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` | Reddit'ten güvenilir çekim | Kimliksiz RSS'e düşer, sık sık 429 alır |

LLM katmanı bilinçli olarak dar: **sıralamayı yapmıyor**, yalnız seçilmiş ≤12
maddeye bağlam cümlesi yazıyor. Böylece sıralama deterministik ve test edilebilir
kalıyor, maliyet koşu başına birkaç kuruşta duruyor.

Reddit kimliği için: reddit.com/prefs/apps → "create app" → tür **script**.

---

## Ölçüm protokolü (pilotun asıl işi)

Sayfadaki her maddede **✓ faydalı / ✗ değil** düğmeleri var. Üst bantta yürüyen
bir "faydalı oranı" sayacı tutuluyor.

Bir hafta boyunca her sabah listeyi işaretle. Sonunda:

- **oran ≥ %50** → skorlayıcı işini yapıyor, X katmanını eklemeye değer.
- **oran %30–50** → skorlama ayarı gerekiyor; ✗ işaretlenenlerin ortak kalıbına bak.
- **oran < %30** → kaynak seçimi yanlış, skorlama değil.

İşaretler `localStorage`'da, yani **yalnız o tarayıcıda** tutuluyor. Statik yayın
seçildiği için bu bilinçli bir sınır: tek cihazdan okunduğu sürece ölçüm geçerli,
başka cihazdan bakılırsa sayaç sıfırdan başlar.

---

## Bilinen boşluklar

**RSS yayını olmayan kaynaklar.** Anthropic, Mistral, Meta AI, Runway, Black
Forest Labs (FLUX), Stability, Luma — hiçbirinin çalışan bir feed'i yok
(2026-09-21 itibarıyla ölçüldü). Duyuruları Hacker News, Simon Willison ve genel
basın üzerinden dolaylı yakalanıyor. Doğrudan izlemek HTML fark-takibi gerektirir.

**X (Twitter) yok.** Bilinçli karar. Ücretsiz tier kapandı, resmî pay-per-use bu
hacimde ~$150/ay, Nitter Ağustos 2026'da kapatıldı. Üçüncü-parti okuma API'leri
~$2-5/ay ile mümkün ama ToS-gri. X'in benzersiz katkısı "ne oldu" değil "kim ne
diyor"; pilot çalıştıktan sonra ölçüme dayanarak yeniden değerlendirilecek.

**Eksen tespiti kelime listesine dayalı.** Kelime sınırıyla eşleşiyor (düz
altdizi araması "ipo"yu "dipole" içinde bulup bir saçılım makalesine "şirket"
ekseni takmıştı), ama yine de elle bakımlı bir liste. Yeni bir terim dalgası
(yeni model adları) `AXIS_STRONG` içine eklenmezse o maddeler kaynak eğilimine
düşer.

**Reddit kimliksiz güvenilmez.** Yerel ölçüm: 4 subreddit'lik koşuda 20 saniye
aralıkla bile yalnız 2/4 geçti. GitHub Actions üzerinde de 4'ün 2'si 429 aldı.
OAuth kimliği tek güvenilir yol. `fetch_reddit`'in OAuth dalı **kimlik
olmadığı için henüz canlı doğrulanmadı.**

**Substack CI'da 403 veriyor.** Import AI yerelde sorunsuz çekiliyor ama
GitHub Actions'ın datacenter IP'sinden 403 dönüyor (ilk CI koşusunda ölçüldü).
Substack tabanlı diğer kaynaklar da aynı riski taşıyor.

**İşaretler cihaz-yerel.** Yukarıda açıklandı.

---

## Maliyet

| Kalem | Aylık |
|---|---|
| Kaynaklar (RSS/API) | $0 |
| GitHub Actions + Pages | $0 (public repo) |
| LLM notları (Haiku, ~12 madde/gün) | ~$0.30 |
| **Toplam** | **~$0.30** |
