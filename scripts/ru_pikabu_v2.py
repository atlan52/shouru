"""Pikabu (pikabu.ru) — Russian income-related posts scraper, v2.

v1 failure: `https://pikabu.ru/search?q=...` returned 0 stories
(likely modern Pikabu JS-renders search results or blocks the new endpoint).

v2 strategy — two paths:
  1. Legacy `search.php` URL:
       https://pikabu.ru/search.php?q=<kw>&page=<n>   (verified 200)
  2. Community boards (HTML-rendered server-side):
       https://pikabu.ru/community/<slug>

Selectors tried (Pikabu's modern stack uses class names like `story__*`):
  - card:    article.story / article[data-story-id] / div.story
  - title:   a.story__title-link / h2.story__title a
  - body:    .story-block_type_text / .story__content-block
  - rating:  .story__rating-count
  - URL:     /story/<slug>_<id>

If everything yields 0 stories: dump the first 1000 chars of HTML to stderr
plus a `[pikabu] PAGE LOOKS LIKE: <first 100 chars>` line.

Output (overwrites the existing 0-byte file from v1):
  data/raw/pikabu_native_<YYYYMMDD>.jsonl

Schema:
  {"id":..., "raw_id":..., "platform":"pikabu", "lang":"ru",
   "title":..., "body":..., "author":..., "url":...,
   "country_hint":"RU", "matched_keyword":...,
   "engagement":{"score":rating, "comments":n, "views":null}}
"""
import datetime
import hashlib
import json
import os
import re
import sys
import time
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

OUT_DIR = "/Users/jan/sen/code/spider/shouru/data/raw"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
TIMEOUT = 25
SLEEP = 1.5

KEYWORDS = [
    "зарплата",
    "доход",
    "сколько зарабатываю",
    "удаленная работа доход",
    "фриланс",
    "подработка",
    "как заработать",
    "бизнес доход",
]

COMMUNITIES = [
    "Финансы",
    "IT-programmirovanie",
]

PAGES_PER_KW = 3
PAGES_PER_COMMUNITY = 3


def headers():
    return {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
        "Referer": "https://pikabu.ru/",
        "Cache-Control": "no-cache",
    }


def make_id(raw_id: str) -> str:
    return hashlib.md5(("pikabu:" + str(raw_id)).encode("utf-8")).hexdigest()[:16]


def fetch(url: str, params: dict | None = None, label: str = "") -> str | None:
    try:
        r = requests.get(url, headers=headers(), params=params, timeout=TIMEOUT)
    except Exception as e:
        print(f"  [pikabu] fetch err {label}: {e}", file=sys.stderr)
        return None
    if r.status_code != 200:
        print(f"  [pikabu] status {r.status_code} {label} url={r.url}", file=sys.stderr)
        return None
    return r.text


def _first_line(html: str, limit: int = 100) -> str:
    text = re.sub(r"\s+", " ", html).strip()
    return text[:limit]


def _select_stories(soup: BeautifulSoup):
    # Try every selector we know; deduplicate by id().
    candidates = []
    candidates.extend(soup.select("article.story"))
    candidates.extend(soup.select("article[data-story-id]"))
    candidates.extend(soup.select("div.story"))
    candidates.extend(soup.select("[data-story-id]"))
    candidates.extend(soup.select("[class*='story_'][class*='feed']"))
    seen = set()
    uniq = []
    for el in candidates:
        if id(el) in seen:
            continue
        seen.add(id(el))
        uniq.append(el)
    return uniq


def parse_stories(html: str, kw: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    stories = _select_stories(soup)
    items: list[dict] = []
    for s in stories:
        # URL & title
        title_el = (
            s.select_one("a.story__title-link")
            or s.select_one("h2.story__title a")
            or s.select_one(".story__title a")
            or s.select_one("h2 a")
            or s.select_one("a.story__title")
        )
        if not title_el:
            continue
        url = (title_el.get("href") or "").strip()
        title = title_el.get_text(" ", strip=True)
        if not url or not title:
            continue
        if not url.startswith("http"):
            url = "https://pikabu.ru" + url

        # Story id from data attr or URL pattern /story/<slug>_<id>
        sid = s.get("data-story-id") or ""
        if not sid:
            m = re.search(r"/story/[^/?#]+_(\d+)", url)
            if m:
                sid = m.group(1)
        if not sid:
            # last fallback: hash of URL
            sid = url
        raw_id = str(sid)

        # Body
        body_el = (
            s.select_one(".story-block_type_text")
            or s.select_one(".story__content-block")
            or s.select_one(".story__content-inner")
            or s.select_one("[class*='text-block']")
        )
        body = body_el.get_text(" ", strip=True) if body_el else ""

        # Author
        author_el = (
            s.select_one(".user__nick")
            or s.select_one(".story__user a")
            or s.select_one("a.user")
        )
        author = author_el.get_text(strip=True) if author_el else ""

        # Rating / score
        rating = 0
        rating_el = (
            s.select_one(".story__rating-count")
            or s.select_one("[class*='rating-count']")
            or s.select_one("[class*='rating']")
        )
        if rating_el:
            mt = re.search(r"-?\d+", rating_el.get_text(" ", strip=True))
            if mt:
                try:
                    rating = int(mt.group(0))
                except ValueError:
                    pass

        # Comments
        comments = 0
        comments_el = (
            s.select_one(".story__comments-link-count")
            or s.select_one("[class*='comments-link-count']")
            or s.select_one("[class*='comments']")
        )
        if comments_el:
            mc = re.search(r"\d+", comments_el.get_text(" ", strip=True))
            if mc:
                try:
                    comments = int(mc.group(0))
                except ValueError:
                    pass

        items.append({
            "id": make_id(raw_id),
            "raw_id": raw_id,
            "platform": "pikabu",
            "lang": "ru",
            "title": title[:300],
            "body": body[:5000],
            "author": author,
            "url": url,
            "country_hint": "RU",
            "matched_keyword": kw,
            "engagement": {
                "score": int(rating),
                "comments": int(comments),
                "views": None,
            },
        })
    return items


def crawl_search_legacy(out, seen_ids: set) -> int:
    """Strategy 1: legacy search.php endpoint."""
    added = 0
    for kw in KEYWORDS:
        kw_added = 0
        for page in range(1, PAGES_PER_KW + 1):
            label = f"search.php kw={kw!r} p{page}"
            print(f"[pikabu] {label}", flush=True)
            html = fetch(
                "https://pikabu.ru/search.php",
                params={"q": kw, "page": page},
                label=label,
            )
            if not html:
                time.sleep(SLEEP)
                continue
            entries = parse_stories(html, kw)
            if not entries and page == 1:
                # Diagnostic dump: page yielded 0 stories
                print(
                    f"  [pikabu] PAGE LOOKS LIKE: {_first_line(html, 100)}",
                    file=sys.stderr,
                )
                sys.stderr.write(
                    "  [pikabu] HTML[:1000]>>>\n" + html[:1000] + "\n<<<\n"
                )
                sys.stderr.flush()
            new_here = 0
            for it in entries:
                if it["id"] in seen_ids:
                    continue
                seen_ids.add(it["id"])
                out.write(json.dumps(it, ensure_ascii=False) + "\n")
                out.flush()
                added += 1
                kw_added += 1
                new_here += 1
            print(
                f"  -> parsed {len(entries)}, new_this_page {new_here}, "
                f"new_for_kw {kw_added}, total {added}",
                flush=True,
            )
            time.sleep(SLEEP)
            if len(entries) == 0 and page >= 1:
                # No point hammering if first page yielded nothing parseable
                if page == 1:
                    break
    return added


def crawl_communities(out, seen_ids: set) -> int:
    """Strategy 2: community boards."""
    added = 0
    for slug in COMMUNITIES:
        # Pikabu community URLs accept Cyrillic; quote them.
        base = "https://pikabu.ru/community/" + quote_plus(slug, safe="-_")
        kw_label = f"community:{slug}"
        for page in range(1, PAGES_PER_COMMUNITY + 1):
            label = f"{kw_label} p{page}"
            print(f"[pikabu] {label}", flush=True)
            html = fetch(base, params={"page": page} if page > 1 else None, label=label)
            if not html:
                time.sleep(SLEEP)
                continue
            entries = parse_stories(html, kw_label)
            if not entries and page == 1:
                print(
                    f"  [pikabu] PAGE LOOKS LIKE: {_first_line(html, 100)}",
                    file=sys.stderr,
                )
                sys.stderr.write(
                    "  [pikabu] HTML[:1000]>>>\n" + html[:1000] + "\n<<<\n"
                )
                sys.stderr.flush()
            new_here = 0
            for it in entries:
                if it["id"] in seen_ids:
                    continue
                seen_ids.add(it["id"])
                out.write(json.dumps(it, ensure_ascii=False) + "\n")
                out.flush()
                added += 1
                new_here += 1
            print(
                f"  -> parsed {len(entries)}, new_this_page {new_here}, total {added}",
                flush=True,
            )
            time.sleep(SLEEP)
            if len(entries) == 0 and page == 1:
                break
    return added


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    today = datetime.datetime.now().strftime("%Y%m%d")
    out_path = os.path.join(OUT_DIR, f"pikabu_native_{today}.jsonl")

    # Per the task: overwrite the prior 0-byte file. Open in 'w' mode.
    seen_ids: set[str] = set()
    total_search = 0
    total_comm = 0
    with open(out_path, "w", encoding="utf-8") as out:
        total_search = crawl_search_legacy(out, seen_ids)
        total_comm = crawl_communities(out, seen_ids)

    total = total_search + total_comm
    print(
        f"[pikabu] DONE total_new={total} "
        f"(search={total_search}, communities={total_comm}) file={out_path}"
    )

    # Final stats: line count + 5 Russian samples
    line_count = 0
    samples: list[dict] = []
    with open(out_path, "r", encoding="utf-8") as f:
        for line in f:
            line_count += 1
            if len(samples) < 5:
                try:
                    samples.append(json.loads(line))
                except Exception:
                    pass
    print(f"[pikabu] LINES IN FILE: {line_count}")
    print("[pikabu] SAMPLES:")
    for s in samples:
        eng = s.get("engagement") or {}
        print(
            f"  - {s.get('title','')[:90]}  "
            f"[score={eng.get('score')}, comments={eng.get('comments')}]  "
            f"{s.get('url','')}"
        )


if __name__ == "__main__":
    main()
