"""Unified entrypoint with checkpoint resume + parallel execution.

Usage:
  python run.py                          # all P0+P1 platforms in parallel
  python run.py reddit zhihu xiaohongshu # subset
  python run.py --tier P0                # by tier
  python run.py --workers 6 P0           # cap concurrent
  python run.py --serial reddit          # single-process (debug)
  python run.py --fresh                  # wipe all state
  python run.py --status                 # progress per platform
  python run.py --list                   # list known platforms
  python run.py --phase crawl            # crawl only (default)
  python run.py --phase extract          # LLM extract only
  python run.py --phase analyze          # report+viz only

Phase ordering (for --phase all overnight):
  crawl → sample → extract → analyze
"""
from __future__ import annotations

import sys
import os
import json
import signal
import argparse
import traceback
import multiprocessing as mp
from pathlib import Path

from config import STATE_DIR, RAW_DIR, LOGS_DIR, MAX_PLATFORM_WORKERS


# ============================================================================
# Platform inventory — see docs/COUNTRY_PLATFORMS.md for sourcing rationale.
# ============================================================================

# Tier P0 — high yield / large language hubs / must run
PLATFORMS_P0 = [
    "reddit_import",
    "hackernews",
    "zhihu",
    "weibo",
    "xiaohongshu",
    "maimai",
    "ambitionbox",
    "moneysavingexpert",
    "mumsnet",
    "levelsfyi",
    "glassdoor_via_google",
    "govstats",
    "google_universal",
]

# Tier P1 — important local / mid yield
PLATFORMS_P1 = [
    "bilibili",
    "blind",
    "quora",
    "fivech",
    "note_jp",
    "yahoo_chiebukuro",
    "openwork",
    "naver_cafe",
    "kununu",
    "gehalt_de",
    "hh_ru",
    "vk_groups",
    "vagas_br",
    "forocoches",
    "pantip",
    "kaskus",
    "tinhte_vn",
    "hardwarezone_edmw",
    "x_nitter",
    "richlists",
]

# Tier P2 — supplementary / low yield but locally unique
PLATFORMS_P2 = [
    "dcinside",
    "naukri",
    "pikabu",
    "habr",
    "sravni_ru",
    "reclame_aqui",
]

PLATFORMS_BY_TIER = {
    "P0": PLATFORMS_P0,
    "P1": PLATFORMS_P1,
    "P2": PLATFORMS_P2,
}

PLATFORMS = PLATFORMS_P0 + PLATFORMS_P1 + PLATFORMS_P2

# user-facing short name → module name
MODULE_MAP = {
    "reddit": "reddit_import",
    "hn": "hackernews",
    "x": "x_nitter",
    "twitter": "x_nitter",
    "xhs": "xiaohongshu",
    "mm": "maimai",
    "mse": "moneysavingexpert",
    "5ch": "fivech",
    "yahoo": "yahoo_chiebukuro",
    "naver": "naver_cafe",
    "ow": "openwork",
    "ab": "ambitionbox",
    "lf": "levelsfyi",
    "google": "google_universal",
    "gw": "google_universal",
    "gd": "glassdoor_via_google",
    "rich": "richlists",
    "gov": "govstats",
}


def canonical(name: str) -> str:
    return MODULE_MAP.get(name, name)


def show_status():
    print(f"{'platform':<22} {'items':>8} {'seen':>8} {'queue':>8} {'kw_done':>10} {'updated':>20}")
    print("-" * 80)
    for p in PLATFORMS:
        items = 0
        for f in RAW_DIR.glob(f"{p}_*.jsonl"):
            try:
                with f.open(encoding="utf-8") as fh:
                    items += sum(1 for _ in fh)
            except Exception:
                pass
        sf = STATE_DIR / f"{p}.json"
        if sf.exists():
            try:
                d = json.loads(sf.read_text(encoding="utf-8"))
                seen = len(d.get("seen_ids", []))
                q = len(d.get("queue", []))
                kd = len(d.get("kw_done", []))
                upd = d.get("updated_at", "")[:19]
            except Exception:
                seen = q = kd = 0
                upd = ""
        else:
            seen = q = kd = 0
            upd = ""
        print(f"{p:<22} {items:>8} {seen:>8} {q:>8} {kd:>10} {upd:>20}")


def reset_state(platform: str):
    sf = STATE_DIR / f"{platform}.json"
    if sf.exists():
        sf.unlink()
        print(f"[reset] {platform} state cleared")


def _child_sigterm(signum, frame):
    raise KeyboardInterrupt(f"signal {signum}")


def _run_one(platform: str, log_to_file: bool = False) -> tuple[str, bool, str]:
    """Child-process entry point. Import the crawler module and call run().

    Returns (platform, success, message).
    """
    signal.signal(signal.SIGTERM, _child_sigterm)
    mod_name = canonical(platform)

    if log_to_file:
        log_path = LOGS_DIR / f"{platform}.log"
        fh = log_path.open("a", buffering=1, encoding="utf-8")
        sys.stdout = fh
        sys.stderr = fh
        print(f"\n===== {platform.upper()} (pid={os.getpid()}) =====", flush=True)

    try:
        mod = __import__(f"crawlers.{mod_name}", fromlist=["run"])
        mod.run()
        return (platform, True, "ok")
    except KeyboardInterrupt:
        return (platform, False, "interrupted (state saved)")
    except Exception as e:
        traceback.print_exc()
        return (platform, False, f"FAILED: {e}")


def run_parallel(targets: list[str], workers: int):
    workers = max(1, min(workers, len(targets)))
    print(f"[dispatcher] launching {len(targets)} platform(s) across {workers} worker(s)")
    print(f"[dispatcher] logs: {LOGS_DIR}/<platform>.log")

    ctx = mp.get_context("spawn")
    pool = ctx.Pool(processes=workers)

    def _parent_term(signum, frame):
        print(f"\n[dispatcher] received signal {signum}, terminating workers…")
        pool.terminate()
        pool.join()
        sys.exit(130)

    signal.signal(signal.SIGINT, _parent_term)
    signal.signal(signal.SIGTERM, _parent_term)

    results = []
    try:
        async_res = [pool.apply_async(_run_one, (p, True)) for p in targets]
        pool.close()
        for r in async_res:
            results.append(r.get())
    except KeyboardInterrupt:
        pool.terminate()
    finally:
        pool.join()

    print("\n[dispatcher] summary:")
    for p, ok, msg in results:
        status = "OK " if ok else "ERR"
        print(f"  [{status}] {p:<22} {msg}")


def run_serial(targets: list[str]):
    signal.signal(signal.SIGTERM, _child_sigterm)
    for name in targets:
        print(f"\n===== {name.upper()} =====")
        try:
            mod = __import__(f"crawlers.{canonical(name)}", fromlist=["run"])
            mod.run()
        except KeyboardInterrupt:
            print(f"\n[{name}] interrupted — state saved, resume by re-running")
            return
        except Exception as e:
            print(f"[{name}] FAILED: {e}")
            traceback.print_exc()


def run_extract():
    """Phase 3: LLM extraction. Imports extract.batch_runner."""
    from extract import batch_runner
    batch_runner.run()


def run_analyze():
    """Phase 4: load_sqlite → aggregate → visualize → report."""
    from analyze import load_sqlite, aggregate, visualize, report
    load_sqlite.run()
    aggregate.run()
    visualize.run()
    report.run()


def main(argv):
    ap = argparse.ArgumentParser(description="shouru crawler dispatcher")
    ap.add_argument("platforms", nargs="*", help="platform names or tier (P0/P1/P2)")
    ap.add_argument("--tier", choices=["P0", "P1", "P2"], help="run a tier")
    ap.add_argument("--phase", choices=["crawl", "extract", "analyze", "all"],
                    default="crawl")
    ap.add_argument("--fresh", action="store_true", help="wipe state before running")
    ap.add_argument("--status", "-s", action="store_true", help="show progress and exit")
    ap.add_argument("--list", action="store_true", help="list known platforms and exit")
    ap.add_argument("--serial", action="store_true", help="run sequentially (debug)")
    ap.add_argument("--workers", type=int, default=MAX_PLATFORM_WORKERS,
                    help=f"max parallel platforms (default: {MAX_PLATFORM_WORKERS})")
    args = ap.parse_args(argv)

    if args.list:
        for tier, plats in PLATFORMS_BY_TIER.items():
            print(f"--- {tier} ---")
            for p in plats:
                print(f"  {p}")
        return
    if args.status:
        show_status()
        return

    if args.phase == "extract":
        run_extract()
        return
    if args.phase == "analyze":
        run_analyze()
        return

    # Resolve platforms
    targets: list[str] = []
    if args.tier:
        targets = list(PLATFORMS_BY_TIER[args.tier])
    elif args.platforms:
        for p in args.platforms:
            if p in PLATFORMS_BY_TIER:
                targets.extend(PLATFORMS_BY_TIER[p])
                continue
            cp = canonical(p)
            if cp not in PLATFORMS:
                print(f"[dispatcher] unknown platform: {p}  (try --list)")
                sys.exit(2)
            if cp not in targets:
                targets.append(cp)
    else:
        # Default: P0 + P1
        targets = list(PLATFORMS_P0) + list(PLATFORMS_P1)

    if args.fresh:
        for p in targets:
            reset_state(p)

    if args.serial or len(targets) == 1:
        run_serial(targets)
    else:
        run_parallel(targets, args.workers)

    if args.phase == "all":
        print("\n===== EXTRACT =====")
        run_extract()
        print("\n===== ANALYZE =====")
        run_analyze()


if __name__ == "__main__":
    main(sys.argv[1:])
