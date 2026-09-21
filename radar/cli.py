"""Komut satırı: tek bir `radar run` koşusu boru hattının tamamını yürütür."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

import yaml

from . import hype, llm
from .collect import collect_all
from .normalize import dedup, drop_shown_unless_rising, record_seen
from .render import render_site
from .score import apply_hype, assign_topics, score_all, select_daily, select_secondary


def run(args: argparse.Namespace) -> int:
    started = time.time()
    config = yaml.safe_load(Path(args.sources).read_text(encoding="utf-8"))
    total_sources = len(config["sources"])
    # Bülten yerel güne göre adlandırılır: UTC kullanılırsa Türkiye'de sabah
    # okunan sayfa bir önceki günün tarihini taşıyor.
    date = args.date or datetime.now(ZoneInfo(args.timezone)).strftime("%Y-%m-%d")

    print(f"[1/6] toplama — {total_sources} kaynak")
    items, failures = collect_all(config)
    print(f"      {len(items)} madde, {len(failures)} kaynak düştü")
    for source_id, error in failures:
        print(f"      FAIL {source_id}: {error[:100]}")

    print("[2/6] dedup")
    items, stats = dedup(items, args.archive)
    print(f"      {stats}")

    print("[3/6] skorlama")
    items = score_all(items)

    print("[4/6] hype sinyali")
    items = assign_topics(items)
    signals = hype.compute(items, args.archive, offline=args.no_hype)
    items = apply_hype(items, signals)
    rising = [i for i in items if i.hype_rising]
    print(f"      {len(rising)} madde yükselişte")
    for item in rising[:5]:
        print(f"      ↑ {item.hype_label} — {item.title[:58]}")

    # Daha önce gösterilenler ancak yükselişteyse geri döner.
    items, suppressed = drop_shown_unless_rising(items)
    returning = [i for i in items if i.previously_shown]
    if suppressed or returning:
        print(f"      {suppressed} tekrar elendi, {len(returning)} yükselerek geri döndü")

    selected = select_daily(items, limit=args.limit)
    secondary = select_secondary(items, selected, limit=args.brief)
    print(f"      {len(selected)} madde + {len(secondary)} kısa kısa (kota {args.limit})")

    print("[5/6] LLM notları")
    selected, llm_status = llm.annotate(selected) if not args.no_llm else (selected, "kapalı (--no-llm)")
    print(f"      {llm_status}")

    print("[6/6] yayın")
    if args.dry_run:
        for rank, item in enumerate(selected, 1):
            print(f"  {rank:2}. {item.score:5.2f} [{','.join(item.axes)}] {item.source} — {item.title[:70]}")
        print(f"\nkuru koşu: dosya yazılmadı ({time.time() - started:.1f}s)")
        return 0

    page = render_site(
        selected,
        site_dir=args.site,
        date=date,
        stats=stats,
        failures=failures,
        sources_total=total_sources,
        secondary=secondary,
    )
    # Kısa kısa listesi de gösterilmiş sayılır, yarın tekrar çıkmamalı.
    record_seen(selected + secondary, args.archive)
    print(f"      {page} ({time.time() - started:.1f}s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="radar", description="Günlük AI radarı")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="tam koşu: topla → dedup → skorla → yayınla")
    run_parser.add_argument("--sources", default="sources.yaml")
    run_parser.add_argument("--site", default="docs")
    run_parser.add_argument("--archive", default="archive")
    run_parser.add_argument("--limit", type=int, default=12, help="günlük madde kotası")
    run_parser.add_argument("--brief", type=int, default=8, help="kısa kısa listesi uzunluğu")
    run_parser.add_argument("--date", help="YYYY-MM-DD (varsayılan: bugün)")
    run_parser.add_argument("--timezone", default="Europe/Istanbul", help="gün sınırı için saat dilimi")
    run_parser.add_argument("--no-llm", action="store_true", help="LLM not katmanını atla")
    run_parser.add_argument("--no-hype", action="store_true",
                            help="hype katmanını çevrimdışı çalıştır (ağ sorgusu yok)")
    run_parser.add_argument("--dry-run", action="store_true", help="dosya yazma, listeyi bas")
    run_parser.set_defaults(func=run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
