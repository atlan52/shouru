"""Pantip native scraper — Thai income posts from sinthorn + klaibaan boards.

Strategy:
  1. Try SSR search at /search?q=<th-kw>. If the SSR page yields topic links,
     use it.
  2. Fallback to forum board listings:
       https://pantip.com/forum/sinthorn   (สินธร — finance)
       https://pantip.com/forum/klaibaan   (ใกล้บ้าน — work / jobs)
     Pages 1..PAGES_PER_BOARD; board pages are SSR-friendly.
  3. For each /topic/<id>, GET the topic page and parse:
       title, OP body, OP author, view + comment counts.
  4. Filter: title or body must contain a Thai income token.

Output: /Users/jan/sen/code/spider/shouru/data/raw/pantip_native_<YYYYMMDD>.jsonl
"""
import datetime
import hashlib
import json
import os
import re
import sys
import time
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUT_DIR = "/Users/jan/sen/code/spider/shouru/data/raw"
BASE = "https://pantip.com"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
TIMEOUT = 25
SLEEP = 1.2

# 8 Thai keywords as per spec
KEYWORDS = [
    "เงินเดือน",        # salary
    "รายได้",          # income
    "หาเงิน",           # earning money
    "รายได้เสริม",      # side income
    "ฟรีแลนซ์",        # freelance
    "อาชีพ เงินเดือน",  # occupation salary
    "รายได้พิเศษ",      # extra income
    "ทำงานที่บ้าน รายได้",  # work-from-home income
]

BOARDS = [
    ("/forum/sinthorn", "สินธร"),
    ("/forum/klaibaan", "ใกล้บ้าน"),
]

PAGES_PER_BOARD = 6
PAGES_PER_SEARCH = 2
TARGET = 35
MAX_TOPICS_PER_FEED = 60

# On-topic Thai income tokens
TH_TOPIC_TOKENS = [
    "เงินเดือน", "รายได้", "บาท", "฿", "หาเงิน", "ฟรีแลนซ์",
    "ทำงาน", "อาชีพ", "เงิน", "ค่าจ้าง", "โบนัส", "ลงทุน",
    "ค่าตอบแทน", "เก็บเงิน", "ออม",
]

BOT_MARKERS = ("captcha", "are you a human", "access denied",
               "cf-browser-verification", "checking your browser",
               "attention required")

TOPIC_HREF_RE = re.compile(r"^/topic/(\d+)(?:[/?#].*)?$")


def headers():
    return {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
    """Pull /topic/<id> links from a board listing or search result page."""
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    out: list[dict] = []
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
        if tid in seen:
            continue
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 4:
            continue
        seen.add(tid)
        out.append({
            "topic_id": tid,
            "url": urljoin(BASE + "/", f"topic/{tid}"),
            "title": title,
        })
    return out


def parse_topic(html: str, fallback_title: str = "") -> dict:
    soup = BeautifulSoup(html, "html.parser")

    # title
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

    # OP body
    op_body = ""
    for sel in (".display-post-story", ".display-post-content",
                ".post-content", "[class*='display-post-story']",
                ".main-post-inner", ".post-body"):
        el = soup.select_one(sel)
        if el:
            op_body = el.get_text(" ", strip=True)
            if op_body:
                break

    # OP author
    op_author = ""
    for sel in (".display-post-name a", ".main-post-name a",
                "a.owner-name", "[class*='display-post-name']"):
        el = soup.select_one(sel)
        if el:
            op_author = el.get_text(" ", strip=True)
            if op_author:
                break

    # views & comments
    page_text = soup.get_text(" ", strip=True)
    views = 0
    comments = 0
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

    # likes / score: try to capture "ถูกใจ" or emo count
    likes = 0
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


def is_on_topic_th(title: str, body: str) -> bool:
    blob = (title or "") + " " + (body or "")
    return any(tok in blob for tok in TH_TOPIC_TOKENS)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    today = datetime.datetime.now().strftime("%Y%m%d")
    out_path = os.path.join(OUT_DIR, f"pantip_native_{today}.jsonl")

    seen_ids: set[str] = set()
    # Resume support: skip ids already in the file
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    seen_ids.add(obj.get("raw_id") or "")
                except Exception:
                    pass
        print(f"[resume] {len(seen_ids)} existing items in {out_path}")

    fout = open(out_path, "a", encoding="utf-8")
    written = 0

    def write_record(meta: dict, parsed: dict, kw_label: str):
        nonlocal written
        rid = meta["topic_id"]
        if rid in seen_ids:
            return False
        title = parsed["title"] or meta.get("title", "")
        body = parsed["op_body"] or ""
        if not is_on_topic_th(title, body):
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
            "matched_keyword": kw_label,
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
        return True

    def harvest_feed(feed_url: str, kw_label: str, max_topics: int):
        print(f"  [feed] {feed_url}")
        html = fetch(feed_url)
        if not html:
            return 0
        topics = extract_topic_links(html)
        print(f"    found {len(topics)} topic links")
        added = 0
        for meta in topics[:max_topics]:
            if written >= TARGET * 2:  # cap; don't overcollect
                break
            if meta["topic_id"] in seen_ids:
                continue
            time.sleep(SLEEP)
            tpage = fetch(meta["url"])
            if not tpage:
                continue
            parsed = parse_topic(tpage, fallback_title=meta.get("title", ""))
            if write_record(meta, parsed, kw_label):
                added += 1
                if written % 5 == 0:
                    print(f"    [+] {written} written so far")
            if written >= TARGET * 2:
                break
        return added

    # Phase 1: SSR search per keyword
    for kw in KEYWORDS:
        if written >= TARGET:
            break
        for page in range(1, PAGES_PER_SEARCH + 1):
            if written >= TARGET:
                break
            qs = quote_plus(kw)
            url = f"{BASE}/search?q={qs}&type=topic"
            if page > 1:
                url += f"&page={page}"
            print(f"[search] kw={kw!r} p{page}")
            harvest_feed(url, kw, MAX_TOPICS_PER_FEED)
            time.sleep(SLEEP)

    # Phase 2: fall back to board pages
    if written < TARGET:
        for board, board_th in BOARDS:
            if written >= TARGET:
                break
            for page in range(1, PAGES_PER_BOARD + 1):
                if written >= TARGET:
                    break
                url = f"{BASE}{board}"
                if page > 1:
                    url += f"?page={page}"
                print(f"[board] {board_th} p{page}")
                harvest_feed(url, f"board:{board}", MAX_TOPICS_PER_FEED)
                time.sleep(SLEEP)

    fout.close()
    print(f"[done] wrote {written} new records to {out_path}")
    print(f"[total] file now has {len(seen_ids)} unique records")


if __name__ == "__main__":
    main()
