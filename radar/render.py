"""Yayın katmanı: statik site üretir (GitHub Pages).

Sayfa üç işi yapıyor:
  1. Günün listesini gösterir, her maddenin skor kırılımı açılabilir durumda.
  2. Arşiv araması -- tüm günlerin JSON'u tek dosyada, istemci tarafında filtre.
  3. Fayda işaretleme (✓/✗) -- localStorage'da tutulur, üstte yürüyen precision
     sayacına döner. Pilotun ölçüm aracı bu: bir hafta sonra "faydalı oranı"
     gerçek bir sayı olarak elde.

Not: işaretler tarayıcıda kalır, sunucuya gitmez. Statik yayın seçildiği için
bu bilinçli bir sınır -- tek cihazdan okunduğu sürece ölçüm geçerli.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from .models import AXES, Item

AXIS_COLOR = {
    "image": "#c084fc", "video": "#f472b6", "game": "#4ade80",
    "threed": "#38bdf8", "model": "#fbbf24", "infra": "#94a3b8", "people": "#fb923c",
}

TEMPLATE = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Radar — __DATE__</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ccircle cx='8' cy='8' r='7' fill='none' stroke='%232563eb' stroke-width='1.5'/%3E%3Ccircle cx='8' cy='8' r='2.5' fill='%232563eb'/%3E%3C/svg%3E">
<style>
  :root {
    --bg: #ffffff; --surface: #f6f7f9; --border: #e3e6ea;
    --text: #15181c; --muted: #646d78; --accent: #2563eb; --shadow: rgba(15,23,42,.06);
  }
  :root:not([data-theme="light"]) { }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #0d1013; --surface: #161a1f; --border: #262c34;
      --text: #e8ebee; --muted: #8b95a1; --accent: #60a5fa; --shadow: rgba(0,0,0,.4);
    }
  }
  :root[data-theme="dark"] {
    --bg: #0d1013; --surface: #161a1f; --border: #262c34;
    --text: #e8ebee; --muted: #8b95a1; --accent: #60a5fa; --shadow: rgba(0,0,0,.4);
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font: 16px/1.55 ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  .wrap { max-width: 780px; margin: 0 auto; padding: 32px 16px 80px; }
  header { border-bottom: 1px solid var(--border); padding-bottom: 20px; margin-bottom: 8px; }
  h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -.02em; }
  h1 span { color: var(--muted); font-weight: 400; }
  .meta { color: var(--muted); font-size: 13px; display: flex; flex-wrap: wrap; gap: 6px 14px; margin-top: 10px; }
  .meta b { color: var(--text); font-weight: 600; }
  .tools { display: flex; gap: 8px; margin: 18px 0 8px; flex-wrap: wrap; }
  input[type=search], select {
    background: var(--surface); color: var(--text); border: 1px solid var(--border);
    border-radius: 8px; padding: 8px 11px; font: inherit; font-size: 14px;
  }
  input[type=search] { flex: 1; min-width: 180px; }
  ol { list-style: none; padding: 0; margin: 12px 0 0; }
  li.item {
    border: 1px solid var(--border); border-radius: 12px; background: var(--surface);
    padding: 14px 16px; margin-bottom: 10px; box-shadow: 0 1px 2px var(--shadow);
  }
  li.item.marked-yes { border-color: #22c55e55; }
  li.item.marked-no { opacity: .45; }
  .title { font-size: 16px; font-weight: 600; line-height: 1.4; margin: 0 0 6px; }
  .title a { color: var(--text); text-decoration: none; }
  .title a:hover { color: var(--accent); text-decoration: underline; }
  .sub { color: var(--muted); font-size: 12.5px; display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: center; }
  .chip {
    font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 999px;
    border: 1px solid currentColor; letter-spacing: .01em;
  }
  .summary { color: var(--muted); font-size: 13.5px; margin: 8px 0 0; }
  .why { color: var(--text); font-size: 13.5px; margin: 8px 0 0; padding-left: 10px; border-left: 2px solid var(--accent); }
  .row { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-top: 10px; }
  .marks { display: flex; gap: 6px; }
  .marks button {
    background: transparent; border: 1px solid var(--border); color: var(--muted);
    border-radius: 7px; padding: 3px 10px; font: inherit; font-size: 13px; cursor: pointer;
  }
  .marks button:hover { border-color: var(--accent); color: var(--accent); }
  .marks button[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: #fff; }
  details.parts { font-size: 12px; color: var(--muted); }
  details.parts summary { cursor: pointer; list-style: none; }
  details.parts summary::-webkit-details-marker { display: none; }
  details.parts table { border-collapse: collapse; margin-top: 6px; font-variant-numeric: tabular-nums; }
  details.parts td { padding: 1px 12px 1px 0; }
  footer { margin-top: 36px; padding-top: 18px; border-top: 1px solid var(--border); color: var(--muted); font-size: 12.5px; }
  footer a { color: var(--accent); }
  .empty { color: var(--muted); padding: 30px 0; text-align: center; }
  .fails { color: #ef4444; font-size: 12.5px; margin-top: 6px; }
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>AI Radar <span>— __DATE__</span></h1>
  <div class="meta">
    <span><b>__COUNT__</b> madde</span>
    <span><b>__SOURCES_OK__</b>/<b>__SOURCES_TOTAL__</b> kaynak</span>
    <span><b>__COLLECTED__</b> taranan</span>
    <span><b>__DROPPED__</b> tekrar elendi</span>
    <span id="precision"></span>
  </div>
  __FAILS__
</header>

<div class="tools">
  <input type="search" id="q" placeholder="Arşivde ara (başlık, kaynak, eksen)…" autocomplete="off">
  <select id="axis"><option value="">Tüm eksenler</option>__AXIS_OPTIONS__</select>
  <select id="scope"><option value="today">Bugün</option><option value="all">Tüm arşiv</option></select>
</div>

<ol id="list">__ITEMS__</ol>
<div class="empty" id="empty" hidden>Eşleşen madde yok.</div>

<footer>
  <div>__ARCHIVE_LINKS__</div>
  <div style="margin-top:8px">
    Üretim: <b>__GENERATED__</b> · Faydalı/faydasız işaretleri yalnız bu tarayıcıda saklanır.
    <a href="#" id="reset">işaretleri sıfırla</a>
  </div>
</footer>
</div>

<script>
const ARCHIVE_URL = "data/index.json";
const store = {
  read() { try { return JSON.parse(localStorage.getItem("radar.marks") || "{}"); } catch (e) { return {}; } },
  write(v) { try { localStorage.setItem("radar.marks", JSON.stringify(v)); } catch (e) {} }
};

function renderPrecision() {
  const marks = store.read();
  const vals = Object.values(marks);
  const yes = vals.filter(v => v === "yes").length;
  const el = document.getElementById("precision");
  if (!vals.length) { el.textContent = "işaretlenmemiş"; return; }
  el.innerHTML = "faydalı oranı <b>" + Math.round(100 * yes / vals.length) + "%</b> (" + yes + "/" + vals.length + ")";
}

function wireMarks(root) {
  const marks = store.read();
  root.querySelectorAll("li.item").forEach(li => {
    const key = li.dataset.key;
    const current = marks[key];
    if (current) li.classList.add("marked-" + current);
    li.querySelectorAll(".marks button").forEach(btn => {
      const val = btn.dataset.mark;
      btn.setAttribute("aria-pressed", String(current === val));
      btn.onclick = () => {
        const m = store.read();
        if (m[key] === val) { delete m[key]; } else { m[key] = val; }
        store.write(m);
        li.classList.remove("marked-yes", "marked-no");
        if (m[key]) li.classList.add("marked-" + m[key]);
        li.querySelectorAll(".marks button").forEach(b =>
          b.setAttribute("aria-pressed", String(m[key] === b.dataset.mark)));
        renderPrecision();
      };
    });
  });
}

let archive = null;
async function loadArchive() {
  if (archive) return archive;
  try { archive = await (await fetch(ARCHIVE_URL)).json(); } catch (e) { archive = { items: [] }; }
  return archive;
}

function itemHTML(it) {
  const chips = (it.axes || []).map(a =>
    '<span class="chip" style="color:' + (AXIS_COLOR[a] || "#94a3b8") + '">' + (AXIS_LABEL[a] || a) + '</span>').join(" ");
  return '<li class="item" data-key="' + it.key + '">' +
    '<p class="title"><a href="' + it.url + '" target="_blank" rel="noopener">' + it.title + '</a></p>' +
    '<div class="sub">' + chips + '<span>' + it.source + '</span><span>' + (it.date || "") + '</span></div>' +
    '<div class="row"><div class="marks">' +
      '<button data-mark="yes">✓ faydalı</button><button data-mark="no">✗ değil</button>' +
    '</div><span class="sub">skor ' + it.score + '</span></div></li>';
}

const AXIS_COLOR = __AXIS_COLOR_JSON__;
const AXIS_LABEL = __AXIS_LABEL_JSON__;

async function applyFilter() {
  const q = document.getElementById("q").value.trim().toLowerCase();
  const axis = document.getElementById("axis").value;
  const scope = document.getElementById("scope").value;
  const list = document.getElementById("list");
  const empty = document.getElementById("empty");

  if (scope === "today") {
    let shown = 0;
    list.querySelectorAll("li.item").forEach(li => {
      const hay = li.dataset.hay || "";
      const ok = (!q || hay.includes(q)) && (!axis || (li.dataset.axes || "").includes(axis));
      li.hidden = !ok; if (ok) shown++;
    });
    empty.hidden = shown > 0;
    return;
  }

  const data = await loadArchive();
  const rows = data.items.filter(it =>
    (!q || (it.title + " " + it.source + " " + (it.axes || []).join(" ")).toLowerCase().includes(q)) &&
    (!axis || (it.axes || []).includes(axis)));
  list.innerHTML = rows.slice(0, 300).map(itemHTML).join("");
  empty.hidden = rows.length > 0;
  wireMarks(list);
}

document.getElementById("q").addEventListener("input", applyFilter);
document.getElementById("axis").addEventListener("change", applyFilter);
document.getElementById("scope").addEventListener("change", applyFilter);
document.getElementById("reset").addEventListener("click", e => {
  e.preventDefault();
  store.write({});
  document.querySelectorAll("li.item").forEach(li => li.classList.remove("marked-yes", "marked-no"));
  document.querySelectorAll(".marks button").forEach(b => b.setAttribute("aria-pressed", "false"));
  renderPrecision();
});

wireMarks(document);
renderPrecision();
</script>
</body>
</html>
"""


def _esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def _item_html(item: Item) -> str:
    chips = " ".join(
        f'<span class="chip" style="color:{AXIS_COLOR.get(a, "#94a3b8")}">{_esc(AXES.get(a, a))}</span>'
        for a in item.axes
    )
    also = getattr(item, "also_in", []) or []
    also_html = f'<span>+{len(also)} kaynak</span>' if also else ""
    signal_html = f"<span>{item.signal} oy</span>" if item.signal else ""
    summary = _esc(item.summary[:260]) if item.summary else ""
    why = f'<p class="why">{_esc(item.why)}</p>' if item.why else ""

    rows = "".join(
        f"<tr><td>{_esc(k)}</td><td>{v:+.2f}</td></tr>"
        for k, v in item.score_parts.items()
        if not k.startswith("_") and isinstance(v, (int, float))
    )
    haystack = _esc(f"{item.title} {item.source} {' '.join(item.axes)}".lower())

    return (
        f'<li class="item" data-key="{item.key}" data-axes="{_esc(",".join(item.axes))}" data-hay="{haystack}">'
        f'<p class="title"><a href="{_esc(item.url)}" target="_blank" rel="noopener">{_esc(item.title)}</a></p>'
        f'<div class="sub">{chips}<span>{_esc(item.source)}</span>'
        f'<span>{item.age_hours:.0f} saat önce</span>{signal_html}{also_html}</div>'
        + (f'<p class="summary">{summary}</p>' if summary else "")
        + why
        + '<div class="row"><div class="marks">'
        '<button data-mark="yes">✓ faydalı</button><button data-mark="no">✗ değil</button></div>'
        f'<details class="parts"><summary>skor {item.score:.2f}</summary>'
        f"<table>{rows}</table></details></div></li>"
    )


def render_site(
    items: list[Item],
    *,
    site_dir: str | Path,
    date: str,
    stats: dict[str, int],
    failures: list[tuple[str, str]],
    sources_total: int,
) -> Path:
    """Günün sayfasını, arşiv kopyasını ve arama verisini yazar."""
    site = Path(site_dir)
    (site / "data").mkdir(parents=True, exist_ok=True)
    (site / "archive").mkdir(parents=True, exist_ok=True)

    # Günün JSON'u + birleşik arşiv indeksi (istemci araması bunu okuyor).
    day_rows = [
        {
            "key": i.key, "title": i.title, "url": i.url, "source": i.source,
            "axes": i.axes, "score": round(i.score, 2), "date": date,
        }
        for i in items
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

    days = sorted({r["date"] for r in combined}, reverse=True)[:14]
    archive_links = "Arşiv: " + " · ".join(
        f'<a href="archive/{d}.html">{d}</a>' if d != date else f"<b>{d}</b>" for d in days
    )

    fails_html = ""
    if failures:
        names = ", ".join(f"{sid} ({err.split(':')[0]})" for sid, err in failures)
        fails_html = f'<div class="fails">Düşen kaynak: {_esc(names)}</div>'

    body = "".join(_item_html(i) for i in items) or ""
    page = (
        TEMPLATE.replace("__DATE__", date)
        .replace("__COUNT__", str(len(items)))
        .replace("__SOURCES_OK__", str(sources_total - len(failures)))
        .replace("__SOURCES_TOTAL__", str(sources_total))
        .replace("__COLLECTED__", str(stats.get("toplanan", 0)))
        .replace("__DROPPED__", str(stats.get("gecmiste_gorulmus", 0)))
        .replace("__FAILS__", fails_html)
        .replace("__ITEMS__", body)
        .replace("__AXIS_OPTIONS__", "".join(f'<option value="{k}">{v}</option>' for k, v in AXES.items()))
        .replace("__AXIS_COLOR_JSON__", json.dumps(AXIS_COLOR))
        .replace("__AXIS_LABEL_JSON__", json.dumps(AXES, ensure_ascii=False))
        .replace("__ARCHIVE_LINKS__", archive_links)
        .replace("__GENERATED__", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    )

    (site / "index.html").write_text(page, encoding="utf-8")
    # Arşiv kopyası bir dizin altında; göreli yollar bir seviye yukarı bakmalı.
    archived = page.replace('"data/index.json"', '"../data/index.json"').replace(
        'href="archive/', 'href="'
    )
    (site / "archive" / f"{date}.html").write_text(archived, encoding="utf-8")
    return site / "index.html"
