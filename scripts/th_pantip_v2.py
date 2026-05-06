"""Pantip native scraper v2 — Thai income posts via SSR board listings.

Background:
  Earlier attempt used /search which is JS-rendered and yielded 0 records.
  v2 strategy: hit the SSR-rendered forum board listings directly.

Boards (verified 200 OK):
  - https://pantip.com/forum/sinthorn       (สินธร, finance)        pages 1..10
  - https://pantip.com/forum/klaibaan       (ใกล้บ้าน, work/life)   pages 1..10
  - https://pantip.com/forum/jatujak        (jatujak, mixed)        pages 1..5
  - https://pantip.com/forum/klaibaan/topic/list  pages 1..10

For every listing page extract /topic/<id> links, then GET each topic page
and parse OP body. Filter: title or body must contain at least one Thai
income keyword. Write JSONL records.

Output: data/raw/pantip_native_<YYYYMMDD>.jsonl  (overwrites prior 0-byte file)
"""
import datetime
import hashlib
import json
import os
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUT_DIR = "/Users/jan/sen/code/spider/shouru/data/raw"
BASE = "https://pantip.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")
TIMEOUT = 25
SLEEP = 1.5
TARGET = 35

# Thai income keywords used to filter topics (and report matched_keyword).
INCOME_KEYWORDS = [
    "เงินเดือน",      # salary
    "รายได้เสริม",    # side income (check before generic รายได้)
    "รายได้",        # income
    "หาเงิน",        # earn money
    "ค่าจ้าง",       # wage
    "ฟรีแลนซ์",      # freelance
    "อาชีพ",        # occupation
]

# (path, page_count, board_label)
FEEDS = [
    ("/forum/sinthorn", 10, "สินธร"),
    ("/forum/klaibaan", 10, "ใกล้บ้าน"),
    ("/forum/jatujak", 5, "jatujak"),
    ("/forum/klaibaan/topic/list", 10, "klaibaan-list"),
]

BOT_MARKERS = ("captcha", "are you a human", "access denied",
               "cf-browser-verification", "checking your browser",
               "attention required")

TOPIC_HREF_RE = re.compile(r"^/topic/(\d+)(?:[/?#].*)?$")


def headers():
    return {
        "User-Agent": UA,
        "Accept": ("text/html,application/xhtml+xml,application/xml;"
                   "q=0.9,*/*;q=0.8"),
        "Accept-Language": "th-TH,th;q=0.9,en;q=0.5",
        "Referer": BASE + "/",
    }


def make_id(raw_id: str) -> str:
    return hashlib.md5(("pantip:" + raw_id).encode("utf-8")).hexdigest()[:16]


def fetch(url: str) -> str | None:
    try:
        r = requests.get(url, headers=headers(), timeout=TIMEOUT,
                         allow_redirects=True)
    except Exception as e:
        print(f"  [net err] {url}: {e}", file=sys.stderr)
        return None
    if r.status_code != 200:
        print(f"  [HTTP {r.status_code}] {url}", file=sys.stderr)
        return None
    if not r.encoding:
        r.encoding = "utf-8"
    body = r.text or ""
    low = body.lower()
    if any(m in low for m in BOT_MARKERS):
        print(f"  [bot-block] {url}", file=sys.stderr)
        return None
    return body


def parse_int(s: str) -> int:
    if not s:
        return 0
    s = s.replace(",", "").replace(" ", "").lower()
    m = re.match(r"([\d.]+)\s*([km]?)", s)
    if not m:
        return 0
    try:
        v = float(m.group(1))
    except ValueError:
        return 0
    suf = m.group(2)
    if suf == "k":
        v *= 1_000
    elif suf == "m":
        v *= 1_000_000
    return int(v)


def extract_topic_links(html: str) -> list[dict]:
    """Pull /topic/<id> links + best-effort title from a board listing page.

    The DOM may use .topic-item / [data-topic-id] / article / .post-list-item;
    rather than rely on a single selector, walk every <a href="/topic/..">
    and take the longest anchor text we see for that topic id (titles often
    appear as h2 a or a.title nested in a card).
    """
    soup = BeautifulSoup(html, "html.parser")
    titles: dict[str, str] = {}
    order: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        path = href
        if href.startswith("http"):
            p = urlparse(href)
            if "pantip.com" not in p.netloc:
                continue
            path = p.path
        path = path.split("?")[0].split("#")[0]
        m = TOPIC_HREF_RE.match(path)
        if not m:
            continue
        tid = m.group(1)
        text = a.get_text(" ", strip=True)
        if tid not in titles:
            titles[tid] = text or ""
            order.append(tid)
        else:
            # Keep the longer label – usually the actual title vs. e.g. "comments".
            if len(text) > len(titles[tid]):
                titles[tid] = text
    out = []
    for tid in order:
        title = titles.get(tid, "")
        if len(title) < 4:
            # skip non-title anchors (e.g. comment counts) when no title found
            title = ""
        out.append({
            "topic_id": tid,
            "url": urljoin(BASE + "/", f"topic/{tid}"),
            "title": title,
        })
    return out


def parse_topic(html: str, fallback_title: str = "") -> dict:
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    for sel in ("h2.display-post-title", "h1.display-post-title",
                "h2.title", "h1", "title"):
        el = soup.select_one(sel)
        if el:
            title = el.get_text(" ", strip=True)
            if title:
                break
    if not title:
        title = fallback_title
    title = re.sub(r"\s*-\s*Pantip\s*$", "", title)

    # OP body — try the selectors listed in the spec, then fallbacks.
    op_body = ""
    for sel in (".display-post-story-text", ".display-post-story",
                "[class*=post-story]", ".post-content",
                ".display-post-content", ".main-post-inner", ".post-body"):
        el = soup.select_one(sel)
        if el:
            op_body = el.get_text(" ", strip=True)
            if op_body:
                break

    op_author = ""
    for sel in (".display-post-name a", ".main-post-name a",
                "a.owner-name", "[class*='display-post-name']"):
        el = soup.select_one(sel)
        if el:
            op_author = el.get_text(" ", strip=True)
            if op_author:
                break

    page_text = soup.get_text(" ", strip=True)
    views = 0
    comments = 0
    likes = 0
    for pat in (r"เข้าชม\s*[:.]?\s*([\d.,]+\s*[kKmM]?)",
                r"ผู้เข้าชม\s*[:.]?\s*([\d.,]+\s*[kKmM]?)",
                r"views?\s*[:.]?\s*([\d.,]+\s*[kKmM]?)"):
        m = re.search(pat, page_text, re.IGNORECASE)
        if m:
            views = max(views, parse_int(m.group(1)))
            break
    for pat in (r"ความคิดเห็น\s*[:.]?\s*([\d.,]+\s*[kKmM]?)",
                r"คอมเมนต์\s*[:.]?\s*([\d.,]+\s*[kKmM]?)",
                r"comments?\s*[:.]?\s*([\d.,]+\s*[kKmM]?)"):
        m = re.search(pat, page_text, re.IGNORECASE)
        if m:
            comments = max(comments, parse_int(m.group(1)))
            break
    if comments == 0:
        cmt_els = soup.select(
            ".display-post-wrapper, .comment-wrapper, .display-post.comment")
        if cmt_els:
            comments = max(0, len(cmt_els) - 1)
    for pat in (r"ถูกใจ\s*[:.]?\s*([\d.,]+\s*[kKmM]?)",
                r"คนที่ถูกใจ\s*[:.]?\s*([\d.,]+\s*[kKmM]?)",
                r"likes?\s*[:.]?\s*([\d.,]+\s*[kKmM]?)"):
        m = re.search(pat, page_text, re.IGNORECASE)
        if m:
            likes = max(likes, parse_int(m.group(1)))
            break

    return {
        "title": title,
        "author": op_author,
        "op_body": op_body,
        "views": views,
        "comments": comments,
        "likes": likes,
    }


def matched_income_keyword(title: str, body: str) -> str | None:
    blob = (title or "") + " " + (body or "")
    for kw in INCOME_KEYWORDS:
        if kw in blob:
            return kw
    return None


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    today = datetime.datetime.now().strftime("%Y%m%d")
    out_path = os.path.join(OUT_DIR, f"pantip_native_{today}.jsonl")

    # Overwrite the prior 0-byte file (and resume any non-empty content).
    seen_ids: set[str] = set()
    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    rid = obj.get("raw_id") or ""
                    if rid:
                        seen_ids.add(rid)
                except Exception:
                    pass
        print(f"[resume] {len(seen_ids)} existing items in {out_path}")
        fout = open(out_path, "a", encoding="utf-8")
    else:
        fout = open(out_path, "w", encoding="utf-8")

    written = 0
    samples: list[dict] = []

    def write_record(meta: dict, parsed: dict) -> bool:
        nonlocal written
        rid = meta["topic_id"]
        if rid in seen_ids:
            return False
        title = parsed["title"] or meta.get("title", "")
        body = parsed["op_body"] or ""
        kw = matched_income_keyword(title, body)
        if not kw:
            return False
        item = {
            "id": make_id(rid),
            "raw_id": rid,
            "platform": "pantip",
            "lang": "th",
            "title": title,
            "body": body[:3000],
            "author": parsed["author"],
            "url": meta["url"],
            "country_hint": "TH",
            "matched_keyword": kw,
            "engagement": {
                "score": parsed["likes"] or parsed["views"],
                "comments": parsed["comments"],
                "views": parsed["views"],
            },
            "crawled_at": datetime.datetime.now(datetime.timezone.utc)
            .isoformat(timespec="seconds"),
        }
        fout.write(json.dumps(item, ensure_ascii=False) + "\n")
        fout.flush()
        seen_ids.add(rid)
        written += 1
        if len(samples) < 5:
            samples.append(item)
        return True

    def harvest_feed(feed_url: str) -> int:
        print(f"  [feed] {feed_url}")
        html = fetch(feed_url)
        if not html:
            return 0
        topics = extract_topic_links(html)
        if not topics:
            # SSR shell with no topics — dump first 500 chars to stderr
            # so we can diagnose.
            print(f"  [empty-list] {feed_url} dump-500:", file=sys.stderr)
            print(html[:500], file=sys.stderr)
            return 0
        print(f"    found {len(topics)} topic links")
        added = 0
        for meta in topics:
            if written >= TARGET * 2:
                break
            if meta["topic_id"] in seen_ids:
                continue
            time.sleep(SLEEP)
            tpage = fetch(meta["url"])
            if not tpage:
                continue
            parsed = parse_topic(tpage, fallback_title=meta.get("title", ""))
            if write_record(meta, parsed):
                added += 1
                if written % 5 == 0:
                    print(f"    [+] {written} written so far")
            if written >= TARGET * 2:
                break
        return added

    for path, page_count, label in FEEDS:
        if written >= TARGET:
            break
        for page in range(1, page_count + 1):
            if written >= TARGET:
                break
            url = f"{BASE}{path}"
            if page > 1:
                url += f"?page={page}"
            print(f"[board] {label} p{page}")
            harvest_feed(url)
            time.sleep(SLEEP)

    fout.close()
    print(f"[done] wrote {written} new records to {out_path}")
    print(f"[total] file now has {len(seen_ids)} unique records")
    print("[samples]")
    for s in samples:
        snippet = (s.get("body") or "")[:160].replace("\n", " ")
        print(f"  - {s['url']}  kw={s['matched_keyword']}")
        print(f"    title: {s['title']}")
        if snippet:
            print(f"    body : {snippet}")


if __name__ == "__main__":
    main()
