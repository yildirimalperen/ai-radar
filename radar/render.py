"""Yayın katmanı: statik site üretir (GitHub Pages).

Tasarım kararları:
  * Kart yığını yerine editoryal düzen. Her maddeyi kutuya almak 12 maddede
    görsel gürültü üretiyor; beyaz alan ve saç teli ayraç daha hızlı okunuyor.
  * Dört kaba kategori + madde üstünde ince eksen etiketi. Yedi ekseni doğrudan
    bölüm yapmak 12 maddeyi yedi parçaya bölüp ritmi kırıyordu.
  * Web yazı tipi yok. Sistem yığını anında boyanıyor ve macOS/iOS'ta zaten
    modern duruyor; dış bağımlılık eklemeye değmiyor.
  * Sayfanın işlevi okumak; ✓/✗ ve skor kırılımı ikincil, o yüzden sessiz.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from .models import AXES, Item
from .score import CATEGORIES, group_by_category

# Eksen etiketleri madde üstünde kısa görünür; uzun adlar satırı dağıtıyor.
AXIS_SHORT = {
    "image": "görsel", "video": "video", "game": "oyun", "threed": "3D",
    "model": "model", "infra": "araç", "people": "şirket",
}
AXIS_COLOR = {
    "image": "#a855f7", "video": "#ec4899", "game": "#22c55e", "threed": "#0ea5e9",
    "model": "#f59e0b", "infra": "#64748b", "people": "#f97316",
}
CATEGORY_COLOR = {
    "uretim": "#a855f7", "oyun": "#22c55e",
    "arastirma": "#f59e0b", "ekosistem": "#64748b",
}

AYLAR = ("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
         "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık")


def turkce_tarih(iso_date: str) -> str:
    try:
        when = datetime.strptime(iso_date, "%Y-%m-%d")
    except ValueError:
        return iso_date
    return f"{when.day} {AYLAR[when.month - 1]} {when.year}"


def yas_metni(hours: float) -> str:
    if hours < 1:
        return "az önce"
    if hours < 24:
        return f"{hours:.0f} saat önce"
    return f"{hours / 24:.0f} gün önce"


TEMPLATE = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Radar — __DATE_H__</title>
<meta name="description" content="Görsel üretimi, oyun üretimi, 3D ve yeni modeller ekseninde günlük brief.">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ccircle cx='8' cy='8' r='6.5' fill='none' stroke='%232563eb' stroke-width='1.4'/%3E%3Ccircle cx='8' cy='8' r='2.2' fill='%232563eb'/%3E%3C/svg%3E">
<style>
  :root {
    --bg: #ffffff;
    --text: #101418;
    --muted: #6b7280;
    --faint: #9aa2ad;
    --rule: #ebedf0;
    --rule-strong: #d9dde2;
    --accent: #2563eb;
    --mark-yes: #16a34a;
    --mark-no: #9aa2ad;
    --chip-bg: rgba(16,20,24,.045);
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #0b0d10;
      --text: #e7eaee;
      --muted: #8b93a0;
      --faint: #667080;
      --rule: #1c2127;
      --rule-strong: #2b323a;
      --accent: #7aa7ff;
      --mark-yes: #4ade80;
      --mark-no: #667080;
      --chip-bg: rgba(255,255,255,.06);
    }
  }
  :root[data-theme="dark"] {
    --bg: #0b0d10; --text: #e7eaee; --muted: #8b93a0; --faint: #667080;
    --rule: #1c2127; --rule-strong: #2b323a; --accent: #7aa7ff;
    --mark-yes: #4ade80; --mark-no: #667080; --chip-bg: rgba(255,255,255,.06);
  }

  * { box-sizing: border-box; }
  html { -webkit-text-size-adjust: 100%; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font: 400 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", "Inter",
          ui-sans-serif, Roboto, "Helvetica Neue", Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
    text-rendering: optimizeLegibility;
  }
  .wrap { max-width: 700px; margin: 0 auto; padding: 56px 16px 96px; }

  /* --- başlık --- */
  .mast { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
  .mast h1 {
    font-size: 19px; font-weight: 640; letter-spacing: -.015em; margin: 0;
    display: flex; align-items: center; gap: 9px;
  }
  .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--accent); flex: none; }
  .mast time { color: var(--muted); font-size: 14px; font-variant-numeric: tabular-nums; }
  .stats {
    margin-top: 12px; color: var(--faint); font-size: 12.5px;
    display: flex; flex-wrap: wrap; gap: 4px 16px; font-variant-numeric: tabular-nums;
  }
  .stats b { color: var(--muted); font-weight: 600; }
  .warn { color: #dc2626; }
  @media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) .warn { color: #f87171; } }

  /* --- araç çubuğu --- */
  .tools { display: flex; gap: 8px; margin: 26px 0 8px; flex-wrap: wrap; }
  .tools input, .tools select {
    font: inherit; font-size: 13.5px; color: var(--text);
    background: transparent; border: 1px solid var(--rule-strong);
    border-radius: 9px; padding: 8px 11px; min-width: 0;
    transition: border-color .15s ease;
  }
  .tools input { flex: 1 1 200px; }
  .tools input:focus, .tools select:focus { outline: none; border-color: var(--accent); }
  .tools input::placeholder { color: var(--faint); }

  /* --- kategori bölümü --- */
  section { margin-top: 42px; }
  .cat {
    display: flex; align-items: center; gap: 10px; margin: 0 0 4px;
    font-size: 11.5px; font-weight: 680; letter-spacing: .09em; text-transform: uppercase;
    color: var(--muted);
  }
  .cat::after { content: ""; flex: 1; height: 1px; background: var(--rule); }
  .cat i { width: 6px; height: 6px; border-radius: 50%; flex: none; }
  .cat u { text-decoration: none; color: var(--faint); font-weight: 600; letter-spacing: .04em; }

  /* --- madde --- */
  article { padding: 20px 0; border-bottom: 1px solid var(--rule); }
  article:last-child { border-bottom: none; }
  article.hidden { display: none; }
  article.no { opacity: .38; }
  h2 { margin: 0; font-size: 16.5px; line-height: 1.42; font-weight: 600; letter-spacing: -.008em; }
  article.lead h2 { font-size: 20.5px; line-height: 1.34; letter-spacing: -.017em; }
  h2 a { color: inherit; text-decoration: none; }
  h2 a:hover { color: var(--accent); }
  h2 a:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; border-radius: 3px; }

  .meta {
    margin-top: 7px; display: flex; flex-wrap: wrap; align-items: center;
    gap: 4px 9px; font-size: 12.5px; color: var(--faint);
  }
  .meta .sep { color: var(--rule-strong); }
  .ax { display: inline-flex; align-items: center; gap: 5px; color: var(--muted); }
  .ax i { width: 5px; height: 5px; border-radius: 50%; flex: none; }
  .rise {
    display: inline-flex; align-items: center; gap: 4px; font-weight: 640;
    color: #d97706; background: rgba(217,119,6,.10); border-radius: 999px;
    padding: 2px 8px; font-size: 11.5px; letter-spacing: .01em;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) .rise { color: #fbbf24; background: rgba(251,191,36,.12); }
  }
  .rise-why { color: var(--faint); font-size: 12px; }

  p.sum {
    margin: 9px 0 0; color: var(--muted); font-size: 14px; line-height: 1.58;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
  }
  article.lead p.sum { -webkit-line-clamp: 3; }
  p.why {
    margin: 10px 0 0; font-size: 14px; line-height: 1.55; color: var(--text);
    padding-left: 12px; border-left: 2px solid var(--accent);
  }

  .foot { margin-top: 12px; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .marks { display: flex; gap: 2px; }
  .marks button {
    font: inherit; font-size: 12.5px; line-height: 1; cursor: pointer;
    background: transparent; border: 1px solid transparent; border-radius: 7px;
    padding: 6px 9px; color: var(--faint); transition: all .13s ease;
  }
  .marks button:hover { color: var(--text); background: var(--chip-bg); }
  .marks button[aria-pressed="true"][data-mark="yes"] { color: var(--mark-yes); background: var(--chip-bg); }
  .marks button[aria-pressed="true"][data-mark="no"] { color: var(--mark-no); background: var(--chip-bg); }
  .marks button:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }

  details.parts { font-size: 12px; color: var(--faint); font-variant-numeric: tabular-nums; }
  details.parts summary { cursor: pointer; list-style: none; padding: 4px 0; }
  details.parts summary::-webkit-details-marker { display: none; }
  details.parts summary:hover { color: var(--muted); }
  details.parts table { border-collapse: collapse; margin: 6px 0 2px; font-size: 11.5px; }
  details.parts td { padding: 1px 0; }
  details.parts td:last-child { text-align: right; padding-left: 18px; }

  /* --- kısa kısa --- */
  .brief li { padding: 9px 0; border-bottom: 1px solid var(--rule); font-size: 14px; line-height: 1.5; }
  .brief li:last-child { border-bottom: none; }
  .brief a { color: var(--text); text-decoration: none; }
  .brief a:hover { color: var(--accent); }
  .brief span { color: var(--faint); font-size: 12.5px; }
  ul, ol { list-style: none; margin: 0; padding: 0; }

  .empty { color: var(--faint); font-size: 14px; padding: 36px 0; text-align: center; }

  footer {
    margin-top: 56px; padding-top: 20px; border-top: 1px solid var(--rule);
    color: var(--faint); font-size: 12.5px; line-height: 1.8;
  }
  footer a { color: var(--muted); text-decoration: none; }
  footer a:hover { color: var(--accent); }
  footer nav { display: flex; flex-wrap: wrap; gap: 4px 12px; font-variant-numeric: tabular-nums; }
  footer nav b { color: var(--text); }

  @media (max-width: 480px) {
    .wrap { padding: 36px 16px 72px; }
    article.lead h2 { font-size: 18.5px; }
  }

  /* --- yan panel: liste sola kayar, hedef sayfa sağdan açılır --- */
  .shell {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 0fr;
    transition: grid-template-columns .42s cubic-bezier(.32, .72, 0, 1);
    min-height: 100vh;
  }
  .shell.open { grid-template-columns: minmax(0, 42fr) minmax(0, 58fr); }
  .shell.open .wrap {
    margin-left: max(20px, 3vw); margin-right: 0; padding-top: 40px;
    transition: margin .42s cubic-bezier(.32, .72, 0, 1);
  }
  .wrap { transition: margin .42s cubic-bezier(.32, .72, 0, 1); }

  .pane {
    position: sticky; top: 0; height: 100vh; overflow: hidden;
    border-left: 1px solid var(--rule); background: var(--bg);
    display: flex; flex-direction: column;
    opacity: 0; transform: translateX(28px);
    transition: opacity .3s ease .08s, transform .42s cubic-bezier(.32, .72, 0, 1);
  }
  .shell.open .pane { opacity: 1; transform: none; }
  .pane[hidden] { display: none; }

  .pane-bar {
    display: flex; align-items: center; gap: 8px; padding: 12px 14px;
    border-bottom: 1px solid var(--rule); flex: none; min-height: 54px;
  }
  .pane-bar .who { flex: 1; min-width: 0; }
  .pane-bar .who b { display: block; font-size: 13.5px; font-weight: 600;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .pane-bar .who span { font-size: 11.5px; color: var(--faint); }
  .pane-bar button, .pane-bar a.btn {
    font: inherit; font-size: 13px; line-height: 1; cursor: pointer; text-decoration: none;
    background: transparent; border: 1px solid var(--rule-strong); color: var(--muted);
    border-radius: 8px; padding: 7px 10px; transition: all .13s ease; flex: none;
  }
  .pane-bar button:hover, .pane-bar a.btn:hover { color: var(--accent); border-color: var(--accent); }
  .pane-bar button:disabled { opacity: .35; cursor: default; }
  .pane-bar .marks button { border-color: transparent; }

  .pane-body { flex: 1; position: relative; overflow: auto; background: var(--bg); }
  .pane-body iframe { width: 100%; height: 100%; border: 0; display: block; background: #fff; }

  .preview { max-width: 620px; margin: 0 auto; padding: 48px 28px 64px; }
  .preview h2 { font-size: 24px; line-height: 1.3; letter-spacing: -.02em; margin: 0 0 12px; }
  .preview .pmeta { color: var(--faint); font-size: 13px; margin-bottom: 22px; }
  .preview p { font-size: 15.5px; line-height: 1.7; color: var(--muted); margin: 0 0 16px; }
  .preview .note {
    font-size: 12.5px; color: var(--faint); background: var(--chip-bg);
    border-radius: 9px; padding: 11px 13px; margin-top: 26px; line-height: 1.55;
  }
  .preview .go {
    display: inline-flex; align-items: center; gap: 7px; margin-top: 22px;
    background: var(--accent); color: #fff; text-decoration: none; font-size: 14.5px;
    font-weight: 560; border-radius: 10px; padding: 11px 17px;
  }
  .preview .go:hover { filter: brightness(1.08); }

  article.active { position: relative; }
  article.active::before {
    content: ""; position: absolute; left: -14px; top: 18px; bottom: 18px;
    width: 2px; border-radius: 2px; background: var(--accent);
  }

  /* Dar ekranda bölme yerine tam ekran katman. */
  @media (max-width: 900px) {
    .shell, .shell.open { grid-template-columns: minmax(0, 1fr); }
    .shell.open .wrap { margin: 0 auto; }
    .pane {
      position: fixed; inset: 0; height: 100dvh; z-index: 50; border-left: 0;
      transform: translateY(100%); opacity: 1;
      transition: transform .38s cubic-bezier(.32, .72, 0, 1);
    }
    .shell.open .pane { transform: none; }
    article.active::before { display: none; }
  }
  /* Çok dar ekranda başlığa yer açmak için gezinme oklarını gizle. */
  @media (max-width: 430px) {
    #pane-prev, #pane-next { display: none; }
  }
</style>
</head>
<body>
<div class="shell" id="shell">
<div class="wrap">

<header>
  <div class="mast">
    <h1><span class="dot"></span>AI Radar</h1>
    <time datetime="__DATE__">__DATE_H__</time>
  </div>
  <div class="stats">
    <span><b>__COUNT__</b> madde</span>
    <span><b>__SOURCES_OK__</b>/<b>__SOURCES_TOTAL__</b> kaynak</span>
    <span><b>__COLLECTED__</b> tarandı</span>
    <span id="precision"></span>
  </div>
  __FAILS__
</header>

<div class="tools">
  <input type="search" id="q" placeholder="Ara…" autocomplete="off" aria-label="Ara">
  <select id="axis" aria-label="Eksen"><option value="">Tüm eksenler</option>__AXIS_OPTIONS__</select>
  <select id="scope" aria-label="Kapsam"><option value="today">Bugün</option><option value="all">Tüm arşiv</option></select>
</div>

<main id="content">__SECTIONS__</main>
<div id="flat" hidden></div>
<div class="empty" id="empty" hidden>Eşleşen madde yok.</div>

<footer>
  <nav>__ARCHIVE_LINKS__</nav>
  <div style="margin-top:10px">
    __GENERATED__ · işaretler yalnız bu tarayıcıda saklanır ·
    <a href="#" id="reset">sıfırla</a>
  </div>
</footer>

</div>

<aside class="pane" id="pane" hidden aria-label="Okuma paneli">
  <div class="pane-bar">
    <button id="pane-close" title="Kapat (Esc)" aria-label="Kapat">✕</button>
    <div class="who"><b id="pane-title"></b><span id="pane-source"></span></div>
    <div class="marks" id="pane-marks">
      <button data-mark="yes">✓</button><button data-mark="no">✗</button>
    </div>
    <button id="pane-prev" title="Önceki (←)" aria-label="Önceki">‹</button>
    <button id="pane-next" title="Sonraki (→)" aria-label="Sonraki">›</button>
    <a class="btn" id="pane-open" href="#" target="_blank" rel="noopener" title="Yeni sekmede aç">↗</a>
  </div>
  <div class="pane-body" id="pane-body"></div>
</aside>

</div>

<script>
const AXIS_COLOR = __AXIS_COLOR_JSON__;
const AXIS_SHORT = __AXIS_SHORT_JSON__;

const store = {
  read() { try { return JSON.parse(localStorage.getItem("radar.marks") || "{}"); } catch (e) { return {}; } },
  write(v) { try { localStorage.setItem("radar.marks", JSON.stringify(v)); } catch (e) {} }
};

function renderPrecision() {
  const vals = Object.values(store.read());
  const el = document.getElementById("precision");
  if (!vals.length) { el.textContent = ""; return; }
  const yes = vals.filter(v => v === "yes").length;
  el.innerHTML = "faydalı <b>%" + Math.round(100 * yes / vals.length) + "</b> (" + yes + "/" + vals.length + ")";
}

function wireMarks(root) {
  const marks = store.read();
  root.querySelectorAll("article").forEach(card => {
    const key = card.dataset.key;
    if (marks[key] === "no") card.classList.add("no");
    card.querySelectorAll(".marks button").forEach(btn => {
      btn.setAttribute("aria-pressed", String(marks[key] === btn.dataset.mark));
      btn.onclick = () => {
        const m = store.read();
        const val = btn.dataset.mark;
        if (m[key] === val) { delete m[key]; } else { m[key] = val; }
        store.write(m);
        card.classList.toggle("no", m[key] === "no");
        card.querySelectorAll(".marks button").forEach(b =>
          b.setAttribute("aria-pressed", String(m[key] === b.dataset.mark)));
        renderPrecision();
      };
    });
  });
}

let archive = null;
async function loadArchive() {
  if (!archive) {
    try { archive = await (await fetch("__DATA_PREFIX__data/index.json")).json(); }
    catch (e) { archive = { items: [] }; }
  }
  return archive;
}

function flatRow(it) {
  const ax = (it.axes || []).slice(0, 2).map(a =>
    '<span class="ax"><i style="background:' + (AXIS_COLOR[a] || "#64748b") + '"></i>' +
    (AXIS_SHORT[a] || a) + "</span>").join("");
  return '<article data-key="' + it.key + '">' +
    '<h2><a href="' + it.url + '" target="_blank" rel="noopener">' + it.title + "</a></h2>" +
    '<div class="meta">' + ax + '<span class="sep">·</span><span>' + it.source +
    '</span><span class="sep">·</span><span>' + (it.date || "") + "</span></div>" +
    '<div class="foot"><div class="marks">' +
    '<button data-mark="yes">✓ faydalı</button><button data-mark="no">✗ değil</button>' +
    "</div></div></article>";
}

async function applyFilter() {
  const q = document.getElementById("q").value.trim().toLowerCase();
  const axis = document.getElementById("axis").value;
  const scope = document.getElementById("scope").value;
  const content = document.getElementById("content");
  const flat = document.getElementById("flat");
  const empty = document.getElementById("empty");

  if (scope === "all") {
    const data = await loadArchive();
    const rows = data.items.filter(it =>
      (!q || (it.title + " " + it.source + " " + (it.axes || []).join(" ")).toLowerCase().includes(q)) &&
      (!axis || (it.axes || []).includes(axis)));
    content.hidden = true;
    flat.hidden = false;
    flat.innerHTML = rows.slice(0, 200).map(flatRow).join("");
    wireMarks(flat);
    empty.hidden = rows.length > 0;
    return;
  }

  flat.hidden = true;
  content.hidden = false;
  let shown = 0;
  content.querySelectorAll("article").forEach(card => {
    const ok = (!q || (card.dataset.hay || "").includes(q)) &&
               (!axis || (card.dataset.axes || "").split(",").includes(axis));
    card.classList.toggle("hidden", !ok);
    if (ok) shown++;
  });
  // Tüm maddeleri gizlenen bölüm başlığı ortada kalmasın.
  content.querySelectorAll("section").forEach(sec => {
    const live = sec.querySelectorAll("article:not(.hidden)").length;
    const briefHit = !q && !axis;
    sec.hidden = sec.dataset.kind === "brief" ? !briefHit : live === 0;
  });
  empty.hidden = shown > 0;
}

["q", "axis", "scope"].forEach(id =>
  document.getElementById(id).addEventListener(id === "q" ? "input" : "change", applyFilter));

document.getElementById("reset").addEventListener("click", e => {
  e.preventDefault();
  store.write({});
  document.querySelectorAll("article").forEach(c => c.classList.remove("no"));
  document.querySelectorAll(".marks button").forEach(b => b.setAttribute("aria-pressed", "false"));
  renderPrecision();
});

// --- yan panel -------------------------------------------------------------
const shell = document.getElementById("shell");
const pane = document.getElementById("pane");
const paneBody = document.getElementById("pane-body");
let current = null;

function paneList() {
  const flat = document.getElementById("flat");
  const root = flat.hidden ? document.getElementById("content") : flat;
  return [...root.querySelectorAll("article")].filter(a => !a.classList.contains("hidden"));
}

function esc(t) {
  const d = document.createElement("div"); d.textContent = t || ""; return d.innerHTML;
}

function paneMarkup(card) {
  const url = card.dataset.url;
  if (card.dataset.embed === "1") {
    return '<iframe src="' + esc(url) + '" title="' + esc(card.dataset.title) +
      '" referrerpolicy="no-referrer" sandbox="allow-same-origin allow-scripts allow-popups allow-forms"></iframe>';
  }
  return '<div class="preview">' +
    "<h2>" + esc(card.dataset.title) + "</h2>" +
    '<div class="pmeta">' + esc(card.dataset.source) + "</div>" +
    (card.dataset.extract ? "<p>" + esc(card.dataset.extract) + "</p>" : "") +
    '<a class="go" href="' + esc(url) + '" target="_blank" rel="noopener">Sitede aç ↗</a>' +
    '<div class="note">Bu kaynak, sayfasının başka bir sitede gömülmesine izin vermiyor ' +
    "(X-Frame-Options), bu yüzden burada tam metin gösterilemiyor.</div></div>";
}

function syncPaneMarks(key) {
  const marks = store.read();
  document.querySelectorAll("#pane-marks button").forEach(b =>
    b.setAttribute("aria-pressed", String(marks[key] === b.dataset.mark)));
}

function openPane(card) {
  current = card;
  document.querySelectorAll("article.active").forEach(a => a.classList.remove("active"));
  card.classList.add("active");

  document.getElementById("pane-title").textContent = card.dataset.title;
  document.getElementById("pane-source").textContent =
    card.dataset.source + (card.dataset.embed === "1" ? "" : " · önizleme");
  document.getElementById("pane-open").href = card.dataset.url;
  paneBody.innerHTML = paneMarkup(card);
  paneBody.scrollTop = 0;
  syncPaneMarks(card.dataset.key);

  const list = paneList();
  const at = list.indexOf(card);
  document.getElementById("pane-prev").disabled = at <= 0;
  document.getElementById("pane-next").disabled = at < 0 || at >= list.length - 1;

  pane.hidden = false;
  requestAnimationFrame(() => shell.classList.add("open"));
}

function closePane() {
  shell.classList.remove("open");
  document.querySelectorAll("article.active").forEach(a => a.classList.remove("active"));
  current = null;
  setTimeout(() => {
    if (!shell.classList.contains("open")) { pane.hidden = true; paneBody.innerHTML = ""; }
  }, 420);
}

function step(delta) {
  if (!current) return;
  const list = paneList();
  const next = list[list.indexOf(current) + delta];
  if (next) { openPane(next); next.scrollIntoView({ block: "nearest", behavior: "smooth" }); }
}

// Başlık linkleri panelde açılır; cmd/ctrl/shift/orta tık normal davranışında kalır.
document.addEventListener("click", e => {
  const link = e.target.closest("article h2 a");
  if (!link || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const card = link.closest("article");
  if (!card || !card.dataset.url) return;
  e.preventDefault();
  openPane(card);
});

document.getElementById("pane-close").onclick = closePane;
document.getElementById("pane-prev").onclick = () => step(-1);
document.getElementById("pane-next").onclick = () => step(1);
document.querySelectorAll("#pane-marks button").forEach(btn => {
  btn.onclick = () => {
    if (!current) return;
    const key = current.dataset.key;
    const m = store.read();
    if (m[key] === btn.dataset.mark) { delete m[key]; } else { m[key] = btn.dataset.mark; }
    store.write(m);
    current.classList.toggle("no", m[key] === "no");
    current.querySelectorAll(".marks button").forEach(b =>
      b.setAttribute("aria-pressed", String(m[key] === b.dataset.mark)));
    syncPaneMarks(key);
    renderPrecision();
  };
});

document.addEventListener("keydown", e => {
  if (!current) return;
  if (e.key === "Escape") { closePane(); }
  else if (e.key === "ArrowRight") { e.preventDefault(); step(1); }
  else if (e.key === "ArrowLeft") { e.preventDefault(); step(-1); }
});

wireMarks(document);
renderPrecision();
</script>
</body>
</html>
"""


def _esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def _article(item: Item, *, lead: bool = False) -> str:
    axes = "".join(
        f'<span class="ax"><i style="background:{AXIS_COLOR.get(a, "#64748b")}"></i>'
        f'{_esc(AXIS_SHORT.get(a, a))}</span>'
        for a in item.axes[:3]
    )
    rise = ""
    if item.hype_rising:
        geri = " · yeniden" if item.previously_shown else ""
        rise = f'<span class="rise">↑ yükselişte{geri}</span>'
        if item.hype_label:
            rise += f'<span class="rise-why">{_esc(item.hype_label)}</span>'

    bits = [f"<span>{_esc(item.source)}</span>", f"<span>{yas_metni(item.age_hours)}</span>"]
    if item.signal:
        bits.append(f"<span>{item.signal} oy</span>")
    if getattr(item, "also_in", None):
        bits.append(f'<span>+{len(item.also_in)} kaynak</span>')
    meta = rise + axes + "".join(f'<span class="sep">·</span>{b}' for b in bits)

    rows = "".join(
        f"<tr><td>{_esc(k)}</td><td>{v:+.2f}</td></tr>"
        for k, v in item.score_parts.items()
        if not k.startswith("_") and isinstance(v, (int, float))
    )
    hay = _esc(f"{item.title} {item.source} {' '.join(item.axes)}".lower())

    return (
        f'<article class="{"lead" if lead else ""}" data-key="{item.key}" '
        f'data-axes="{_esc(",".join(item.axes))}" data-hay="{hay}" '
        f'data-url="{_esc(item.url)}" data-title="{_esc(item.title)}" '
        f'data-source="{_esc(item.source)}" data-embed="{int(item.embeddable)}" '
        f'data-extract="{_esc(item.summary)}">'
        f'<h2><a href="{_esc(item.url)}" target="_blank" rel="noopener">{_esc(item.title)}</a></h2>'
        f'<div class="meta">{meta}</div>'
        + (f'<p class="sum">{_esc(item.summary)}</p>' if item.summary else "")
        + (f'<p class="why">{_esc(item.why)}</p>' if item.why else "")
        + '<div class="foot"><div class="marks">'
        '<button data-mark="yes">✓ faydalı</button>'
        '<button data-mark="no">✗ değil</button></div>'
        f'<details class="parts"><summary>{item.score:.2f}</summary>'
        f"<table>{rows}</table></details></div></article>"
    )


def _sections(items: list[Item], secondary: list[Item]) -> str:
    out: list[str] = []
    first = True
    for key, label, members in group_by_category(items):
        color = CATEGORY_COLOR.get(key, "#64748b")
        cards = "".join(
            _article(m, lead=(first and idx == 0)) for idx, m in enumerate(members)
        )
        first = False
        out.append(
            f'<section data-kind="cat"><h3 class="cat"><i style="background:{color}"></i>'
            f"{_esc(label)}<u>{len(members)}</u></h3>{cards}</section>"
        )

    if secondary:
        rows = "".join(
            f'<li><a href="{_esc(i.url)}" target="_blank" rel="noopener">{_esc(i.title)}</a> '
            f"<span>· {_esc(i.source)}</span></li>"
            for i in secondary
        )
        out.append(
            '<section data-kind="brief"><h3 class="cat">'
            '<i style="background:var(--rule-strong)"></i>Kısa kısa'
            f"<u>{len(secondary)}</u></h3><ul class=\"brief\">{rows}</ul></section>"
        )
    return "".join(out)


def render_site(
    items: list[Item],
    *,
    site_dir: str | Path,
    date: str,
    stats: dict[str, int],
    failures: list[tuple[str, str]],
    sources_total: int,
    secondary: list[Item] | None = None,
) -> Path:
    """Günün sayfasını, arşiv kopyasını ve arama verisini yazar."""
    secondary = secondary or []
    site = Path(site_dir)
    (site / "data").mkdir(parents=True, exist_ok=True)
    (site / "archive").mkdir(parents=True, exist_ok=True)

    day_rows = [
        {"key": i.key, "title": i.title, "url": i.url, "source": i.source,
         "axes": i.axes, "score": round(i.score, 2), "date": date}
        for i in items + secondary
    ]
    (site / "data" / f"{date}.json").write_text(
        json.dumps(day_rows, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    index_path = site / "data" / "index.json"
    previous = []
    if index_path.exists():
        try:
            previous = json.loads(index_path.read_text(encoding="utf-8")).get("items", [])
        except json.JSONDecodeError:
            previous = []
    combined = day_rows + [r for r in previous if r.get("date") != date]
    index_path.write_text(
        json.dumps({"items": combined[:3000]}, ensure_ascii=False), encoding="utf-8"
    )

    days = sorted({r["date"] for r in combined}, reverse=True)[:10]
    links = " ".join(
        f"<b>{turkce_tarih(d)}</b>" if d == date
        else f'<a href="archive/{d}.html">{turkce_tarih(d)}</a>'
        for d in days
    )

    fails_html = ""
    if failures:
        names = ", ".join(sid for sid, _ in failures)
        fails_html = f'<div class="stats"><span class="warn">düşen kaynak: {_esc(names)}</span></div>'

    def build(data_prefix: str, archive_prefix: str) -> str:
        return (
            TEMPLATE.replace("__SECTIONS__", _sections(items, secondary))
            .replace("__DATE_H__", turkce_tarih(date))
            .replace("__DATE__", date)
            .replace("__COUNT__", str(len(items)))
            .replace("__SOURCES_OK__", str(sources_total - len(failures)))
            .replace("__SOURCES_TOTAL__", str(sources_total))
            .replace("__COLLECTED__", str(stats.get("toplanan", 0)))
            .replace("__FAILS__", fails_html)
            .replace("__AXIS_OPTIONS__", "".join(
                f'<option value="{k}">{v}</option>' for k, v in AXES.items()))
            .replace("__AXIS_COLOR_JSON__", json.dumps(AXIS_COLOR))
            .replace("__AXIS_SHORT_JSON__", json.dumps(AXIS_SHORT, ensure_ascii=False))
            .replace("__ARCHIVE_LINKS__", links.replace('href="archive/', f'href="{archive_prefix}'))
            .replace("__DATA_PREFIX__", data_prefix)
            .replace("__GENERATED__", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
        )

    (site / "index.html").write_text(build("", "archive/"), encoding="utf-8")
    (site / "archive" / f"{date}.html").write_text(build("../", ""), encoding="utf-8")
    return site / "index.html"
