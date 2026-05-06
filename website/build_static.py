"""Build static HTML version of the website for GitHub Pages.

Renders every page via Flask test client, rewrites absolute paths to relative,
and writes to dist/. Each country, each record gets its own .html.

Usage:
  cd /Users/jan/sen/code/spider/shouru
  .venv/bin/python -m website.build_static
"""
from __future__ import annotations

import re
import shutil
import sqlite3
from pathlib import Path

from website.app import app, DB_PATH, FIGS_DIR

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "docs"  # GitHub Pages can serve from /docs


def rewrite_html(html: str, depth: int) -> str:
    """Rewrite absolute /paths to relative ../ paths based on file depth."""
    prefix = "../" * depth if depth else ""

    # /static/X → <prefix>static/X
    # /figs/X → <prefix>figs/X
    # /country/CC → <prefix>country/CC.html
    # /record/RID → <prefix>record/RID.html
    # /records → <prefix>records.html
    # /platforms, /mechanisms, /about, /visualizations → <prefix>X.html
    # / → <prefix>index.html

    # Order matters: do specific paths first
    def sub_country(m):
        return f'{m.group(1)}{prefix}country/{m.group(2)}.html'

    def sub_record(m):
        return f'{m.group(1)}{prefix}record/{m.group(2)}.html'

    html = re.sub(r'(href=")\/country\/([A-Z?]{2,})', sub_country, html)
    html = re.sub(r'(href=")\/record\/([A-Za-z0-9]+)', sub_record, html)

    # Pages with possible query strings — rewrite to .html (drop query since static)
    for page in ["records", "platforms", "mechanisms", "about", "visualizations"]:
        # Both bare and with query string
        html = re.sub(
            rf'href="\/{page}(?:\?[^"]*)?"',
            f'href="{prefix}{page}.html"',
            html,
        )

    # /static/, /figs/ — directory-style remain dirs
    html = html.replace('href="/static/', f'href="{prefix}static/')
    html = html.replace('src="/static/', f'src="{prefix}static/')
    html = html.replace('href="/figs/', f'href="{prefix}figs/')
    html = html.replace('src="/figs/', f'src="{prefix}figs/')

    # Plain href="/" (home)
    html = html.replace('href="/"', f'href="{prefix}index.html"')

    # Brand link (already covered above, double-check)
    return html


def write(out: Path, html: str, depth: int):
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rewrite_html(html, depth), encoding="utf-8")
    print(f"  wrote {out.relative_to(ROOT)}")


def main():
    # 1. clean & init dist
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)

    # 2. copy static assets
    static_src = Path(__file__).parent / "static"
    static_dst = DIST / "static"
    shutil.copytree(static_src, static_dst)
    print(f"  copied static/ → {static_dst.relative_to(ROOT)}/")

    # 3. copy figs/
    if FIGS_DIR.exists():
        figs_dst = DIST / "figs"
        shutil.copytree(FIGS_DIR, figs_dst)
        print(f"  copied figs/ → {figs_dst.relative_to(ROOT)}/")

    # 4. render with Flask test client
    client = app.test_client()

    # Top-level pages
    routes = [
        ("/", DIST / "index.html", 0),
        ("/records", DIST / "records.html", 0),
        ("/visualizations", DIST / "visualizations.html", 0),
        ("/platforms", DIST / "platforms.html", 0),
        ("/mechanisms", DIST / "mechanisms.html", 0),
        ("/about", DIST / "about.html", 0),
    ]
    for url, out, depth in routes:
        r = client.get(url)
        if r.status_code != 200:
            print(f"  ERR {url}: status {r.status_code}")
            continue
        write(out, r.data.decode("utf-8"), depth)

    # 5. country pages — all 80
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    countries = [r[0] for r in cur.execute(
        "SELECT DISTINCT country FROM income_records "
        "WHERE country IS NOT NULL ORDER BY 1"
    ).fetchall()]
    print(f"  rendering {len(countries)} country pages...")
    for cc in countries:
        r = client.get(f"/country/{cc}")
        if r.status_code != 200:
            print(f"  WARN /country/{cc}: status {r.status_code}")
            continue
        out = DIST / "country" / f"{cc}.html"
        write(out, r.data.decode("utf-8"), depth=1)

    # 6. record pages — all (3482)
    rids = [r[0] for r in cur.execute(
        "SELECT record_id FROM income_records ORDER BY record_id"
    ).fetchall()]
    print(f"  rendering {len(rids)} record pages...")
    for i, rid in enumerate(rids):
        r = client.get(f"/record/{rid}")
        if r.status_code != 200:
            continue
        out = DIST / "record" / f"{rid}.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rewrite_html(r.data.decode("utf-8"), depth=1), encoding="utf-8")
        if (i + 1) % 500 == 0:
            print(f"    [{i+1}/{len(rids)}]")
    conn.close()

    # 7. additional /records pagination — pages 2-N, base filters
    # We pre-generate first 30 pages of unfiltered for direct linking
    print(f"  rendering /records pages 2-30...")
    for p in range(2, 31):
        r = client.get(f"/records?page={p}")
        if r.status_code != 200:
            continue
        out = DIST / "records" / f"page{p}.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        # depth=1 here
        out.write_text(rewrite_html(r.data.decode("utf-8"), depth=1), encoding="utf-8")

    # 8. CNAME placeholder + .nojekyll (GitHub Pages skip jekyll)
    (DIST / ".nojekyll").write_text("", encoding="utf-8")
    print(f"  wrote .nojekyll")

    print(f"\nDone. Static site at {DIST}")
    print(f"Total HTML files: {sum(1 for _ in DIST.rglob('*.html'))}")


if __name__ == "__main__":
    main()
