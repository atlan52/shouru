"""Hatena Bookmark (b.hatena.ne.jp) scraper for Japanese income content.

Strategy:
  - Search URL: https://b.hatena.ne.jp/search/text?q=<keyword>&page=N&safe=on
  - Each result entry typically lives in `.entrylist-contents` / `.bookmark-item`
    or `li.search-result` containers. The page returns HTML.
  - We extract: title, body/excerpt, source URL, bookmark count.

Output: /Users/jan/sen/code/spider/shouru/data/raw/hatena_native_<YYYYMMDD>.jsonl
"""
import hashlib
import json
import os
import sys
import time
import datetime
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

OUT_DIR = "/Users/jan/sen/code/spider/shouru/data/raw"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SEARCH_URL = "https://b.hatena.ne.jp/search/text"
TIMEOUT = 25
SLEEP = 1.5

KEYWORDS = [
    "年収", "月収", "副業 収入", "給料 安い", "不労所得",
    "個人事業主 収入", "フリーランス 年収", "高年収", "手取り", "給料公開",
    "年収アップ", "副収入",
]

PAGES_PER_KW = 2


def headers():
    return {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.5",
        "Referer": "https://b.hatena.ne.jp/",
    }


def make_id(raw_id: str) -> str:
    return hashlib.md5(("hatena:" + raw_id).encode("utf-8")).hexdigest()[:16]


def fetch(kw: str, page: int) -> str | None:
    params = {"q": kw, "safe": "on", "page": page}
    try:
        r = requests.get(SEARCH_URL, headers=headers(), params=params, timeout=TIMEOUT)
    except Exception as e:
        print(f"  [hatena] fetch err kw={kw!r} p{page}: {e}", file=sys.stderr)
        return None
    if r.status_code != 200:
        print(f"  [hatena] status {r.status_code} kw={kw!r} p{page}", file=sys.stderr)
        return None
    return r.text


def parse_entries(html: str, kw: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict] = []

    # Hatena search results most commonly use:
    #   <li class="bookmark-item"> ... </li>  inside <ul class="entrylist-contents">
    #   or  <div class="centerarticle-entry"> .
    # We'll try several selectors and merge.
    candidates = []
    candidates.extend(soup.select("li.bookmark-item"))
    candidates.extend(soup.select("div.centerarticle-entry"))
    candidates.extend(soup.select("li.search-result"))
    candidates.extend(soup.select("div.entrylist-contents-main"))
    # Deduplicate by element id
    seen = set()
    uniq = []
    for el in candidates:
        if id(el) in seen:
            continue
        seen.add(id(el))
        uniq.append(el)

    for el in uniq:
        # Title + URL: usually an <a class="js-keyboard-openable"> or h3 a
        a = (
            el.select_one("a.js-keyboard-openable")
            or el.select_one("h3.centerarticle-entry-title a")
            or el.select_one(".centerarticle-entry-title a")
            or el.select_one("h3 a")
            or el.select_one("a.bookmark-item-link")
            or el.select_one("a")
        )
        if not a:
            continue
        url = a.get("href", "").strip()
        title = (a.get_text(strip=True) or a.get("title") or "").strip()
        if not url or not title:
            continue

        # Body / summary
        body_el = (
            el.select_one(".centerarticle-entry-summary")
            or el.select_one(".bookmark-item-description")
            or el.select_one("p.summary")
            or el.select_one("p")
        )
        body = body_el.get_text(" ", strip=True) if body_el else ""

        # Bookmark count
        cnt_el = (
            el.select_one(".centerarticle-users")
            or el.select_one(".users")
            or el.select_one(".bookmark-count")
            or el.select_one("[class*='users']")
        )
        bookmark_count = 0
        if cnt_el:
            txt = cnt_el.get_text(" ", strip=True)
            digits = "".join(c for c in txt if c.isdigit())
            if digits:
                try:
                    bookmark_count = int(digits)
                except ValueError:
                    pass

        # Author / poster: search results sometimes show a top bookmarker
        author_el = el.select_one(".centerarticle-entry-data .username") or el.select_one(".user")
        author = author_el.get_text(strip=True) if author_el else ""

        raw_id = url
        items.append({
            "id": make_id(raw_id),
            "raw_id": raw_id,
            "platform": "hatena",
            "lang": "ja",
            "title": title[:300],
            "body": body[:5000],
            "author": author,
            "url": url,
            "country_hint": "JP",
            "matched_keyword": kw,
            "engagement": {
                "score": int(bookmark_count),
                "comments": 0,
                "views": None,
            },
        })
    return items


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    today = datetime.datetime.now().strftime("%Y%m%d")
    out_path = os.path.join(OUT_DIR, f"hatena_native_{today}.jsonl")

    seen_ids: set[str] = set()
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    seen_ids.add(json.loads(line)["id"])
                except Exception:
                    pass

    total = 0
    with open(out_path, "a", encoding="utf-8") as out:
        for kw in KEYWORDS:
            for page in range(1, PAGES_PER_KW + 1):
                print(f"[hatena] kw={kw!r} p{page}", flush=True)
                html = fetch(kw, page)
                if not html:
                    time.sleep(SLEEP)
                    continue
                entries = parse_entries(html, kw)
                added_this_page = 0
                for it in entries:
                    if it["id"] in seen_ids:
                        continue
                    seen_ids.add(it["id"])
                    out.write(json.dumps(it, ensure_ascii=False) + "\n")
                    out.flush()
                    total += 1
                    added_this_page += 1
                print(f"  -> parsed {len(entries)}, new {added_this_page}, total {total}",
                      flush=True)
                time.sleep(SLEEP)

    print(f"[hatena] DONE total_new={total} file={out_path}")
    # Print 5 sample titles
    titles = []
    with open(out_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                titles.append(json.loads(line)["title"])
            except Exception:
                pass
            if len(titles) >= 5:
                break
    print("[hatena] SAMPLES:")
    for t in titles:
        print("  -", t)


if __name__ == "__main__":
    main()
