"""Whirlpool.net.au (AU) + Geekzone.co.nz (NZ) — 抓两大本地论坛收入帖原文。"""
import json, hashlib, re, sys, time, random
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

UA_BROWSER = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

HDR_AU = {
    "User-Agent": UA_BROWSER,
    "Accept-Language": "en-AU,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
HDR_NZ = {
    "User-Agent": UA_BROWSER,
    "Accept-Language": "en-NZ,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

DAY = datetime.now().strftime("%Y%m%d")
OUT_WP = Path(f"data/raw/whirlpool_native_{DAY}.jsonl")
OUT_GZ = Path(f"data/raw/geekzone_native_{DAY}.jsonl")

# Whirlpool forum ids — finance=30, careers=24
WP_FORUMS = [("finance", 30), ("careers", 24)]
# Geekzone forum ids — finance=44, jobs=22
GZ_FORUMS = [("finance", 44), ("jobs", 22)]

PAGES_PER_FORUM = 3

KEYWORDS = [
    "salary", "wage", "earn", "income", "super", "kiwisaver", "pension",
    "fire", "freelance", "tradie", "bonus", "package", "ctc", "take home",
    "take-home", "gross",
]


def md5_16(*p):
    return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def polite():
    time.sleep(random.uniform(1.3, 1.7))


def load_seen(path):
    seen = set()
    if path.exists():
        for line in path.open():
            try:
                seen.add(json.loads(line)["id"])
            except Exception:
                pass
    return seen


def is_cloudflare(html, status):
    if status in (403, 503) and re.search(r"cloudflare|cf-ray|attention required|just a moment", html, re.I):
        return True
    if "cf-chl" in html.lower() or "checking your browser" in html.lower():
        return True
    return False


def matched_kw(text):
    low = text.lower()
    for kw in KEYWORDS:
        if kw in low:
            return kw
    return None


# ---------------- Whirlpool ----------------

def fetch_wp_listing(forum_id, page):
    """Whirlpool list pages: /forum/<id>?p=N (or /forum/<id> for first)."""
    if page == 1:
        url = f"https://forums.whirlpool.net.au/forum/{forum_id}"
    else:
        url = f"https://forums.whirlpool.net.au/forum/{forum_id}?p={page}"
    return url


def parse_wp_thread_links(html):
    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()
    # primary: list under #threadList .thread
    for a in soup.select("#threadList a[href*='/thread/']"):
        href = a.get("href", "")
        if not href:
            continue
        m = re.search(r"/thread/(\d+)", href)
        if not m:
            continue
        tid = m.group(1)
        if tid in seen:
            continue
        seen.add(tid)
        title = a.get_text(" ", strip=True)
        links.append((tid, urljoin("https://forums.whirlpool.net.au", href), title))
    # fallback: all /thread/ anchors
    if not links:
        for a in soup.select("a[href*='/thread/']"):
            href = a.get("href", "")
            m = re.search(r"/thread/(\d+)", href)
            if not m:
                continue
            tid = m.group(1)
            if tid in seen:
                continue
            seen.add(tid)
            title = a.get_text(" ", strip=True)
            if not title:
                continue
            links.append((tid, urljoin("https://forums.whirlpool.net.au", href), title))
    return links


def parse_wp_thread(html):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one("h1")
    title = h1.get_text(" ", strip=True) if h1 else ""
    body_el = soup.select_one(".body") or soup.select_one(".message") or soup.select_one("article")
    body = body_el.get_text(" ", strip=True) if body_el else ""
    # author of OP — first .username / .author / .by
    author = ""
    a_el = soup.select_one(".op .username, .firstpost .username, .username, .author, .by")
    if a_el:
        author = a_el.get_text(" ", strip=True)
    # engagement: replies / views (best effort)
    replies = 0
    views = 0
    txt = soup.get_text(" ", strip=True)
    m = re.search(r"(\d+)\s+repl", txt, re.I)
    if m:
        try:
            replies = int(m.group(1))
        except Exception:
            pass
    m = re.search(r"(\d+)\s+view", txt, re.I)
    if m:
        try:
            views = int(m.group(1))
        except Exception:
            pass
    return title, body, author, replies, views


def crawl_whirlpool():
    seen = load_seen(OUT_WP)
    n_total = 0
    for forum_name, fid in WP_FORUMS:
        for page in range(1, PAGES_PER_FORUM + 1):
            list_url = fetch_wp_listing(fid, page)
            try:
                r = requests.get(list_url, headers=HDR_AU, timeout=25)
            except Exception as e:
                print(f"[whirlpool] {forum_name} p{page} err: {e}")
                polite()
                continue
            if is_cloudflare(r.text, r.status_code):
                print(f"[whirlpool] {forum_name} p{page} CLOUDFLARE — abort site", file=sys.stderr)
                return n_total
            if r.status_code >= 400:
                print(f"[whirlpool] {forum_name} p{page} status={r.status_code} skip")
                polite()
                continue
            links = parse_wp_thread_links(r.text)
            print(f"[whirlpool] forum={forum_name}({fid}) p{page} threads={len(links)}")
            if page == 1 and not links:
                sys.stderr.write(f"[whirlpool] forum={forum_name}({fid}) p1 0 threads — HTML head:\n")
                sys.stderr.write(r.text[:800] + "\n")
                sys.stderr.flush()
            polite()
            added = 0
            for tid, turl, ltitle in links:
                rid = md5_16("whirlpool", tid)
                if rid in seen:
                    continue
                # quick keyword filter using listing title first (cheap)
                kw_listing = matched_kw(ltitle)
                # if listing title has no kw, still fetch — body may contain kw
                try:
                    rt = requests.get(turl, headers=HDR_AU, timeout=25)
                except Exception as e:
                    print(f"[whirlpool] thread {tid} err: {e}")
                    polite()
                    continue
                if is_cloudflare(rt.text, rt.status_code):
                    print(f"[whirlpool] thread {tid} CLOUDFLARE — abort site", file=sys.stderr)
                    return n_total
                if rt.status_code >= 400:
                    polite()
                    continue
                title, body, author, replies, views = parse_wp_thread(rt.text)
                if not title:
                    title = ltitle
                combined = (title + " " + body).lower()
                kw = kw_listing or matched_kw(combined)
                if not kw:
                    polite()
                    continue
                obj = {
                    "id": rid,
                    "raw_id": tid,
                    "platform": "whirlpool",
                    "lang": "en",
                    "title": title,
                    "body": body[:5000],
                    "author": author,
                    "url": turl,
                    "country_hint": "AU",
                    "matched_keyword": kw,
                    "engagement": {"score": 0, "comments": replies, "views": views},
                    "forum": forum_name,
                    "forum_id": fid,
                    "crawled_at": now_iso(),
                }
                append(OUT_WP, obj)
                seen.add(rid)
                n_total += 1
                added += 1
                polite()
            print(f"[whirlpool] forum={forum_name} p{page} +{added} (total {n_total})")
    print(f"[whirlpool] DONE +{n_total}")
    return n_total


# ---------------- Geekzone ----------------

def fetch_gz_listing(forum_id, page):
    """Geekzone list: /forums.asp?forumid=<id>&page=N."""
    if page == 1:
        url = f"https://www.geekzone.co.nz/forums.asp?forumid={forum_id}"
    else:
        url = f"https://www.geekzone.co.nz/forums.asp?forumid={forum_id}&page={page}"
    return url


def parse_gz_thread_links(html, forum_id):
    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()
    for a in soup.select("a[href*='topicid=']"):
        href = a.get("href", "")
        m = re.search(r"topicid=(\d+)", href)
        if not m:
            continue
        tid = m.group(1)
        if tid in seen:
            continue
        seen.add(tid)
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 4:
            continue
        full = urljoin("https://www.geekzone.co.nz/", href)
        links.append((tid, full, title))
    return links


def parse_gz_thread(html):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one("h1.topictitle") or soup.select_one("h1")
    title = h1.get_text(" ", strip=True) if h1 else ""
    body_el = (
        soup.select_one(".firstpost")
        or soup.select_one(".message")
        or soup.select_one(".postbody")
    )
    body = body_el.get_text(" ", strip=True) if body_el else ""
    author = ""
    a_el = soup.select_one(".firstpost .username, .firstpost .author, .username, .author")
    if a_el:
        author = a_el.get_text(" ", strip=True)
    replies = 0
    views = 0
    txt = soup.get_text(" ", strip=True)
    m = re.search(r"(\d+)\s+repl", txt, re.I)
    if m:
        try:
            replies = int(m.group(1))
        except Exception:
            pass
    m = re.search(r"(\d+)\s+view", txt, re.I)
    if m:
        try:
            views = int(m.group(1))
        except Exception:
            pass
    return title, body, author, replies, views


def crawl_geekzone():
    seen = load_seen(OUT_GZ)
    n_total = 0
    for forum_name, fid in GZ_FORUMS:
        for page in range(1, PAGES_PER_FORUM + 1):
            list_url = fetch_gz_listing(fid, page)
            try:
                r = requests.get(list_url, headers=HDR_NZ, timeout=25)
            except Exception as e:
                print(f"[geekzone] {forum_name} p{page} err: {e}")
                polite()
                continue
            if is_cloudflare(r.text, r.status_code):
                print(f"[geekzone] {forum_name} p{page} CLOUDFLARE — abort site", file=sys.stderr)
                return n_total
            if r.status_code >= 400:
                print(f"[geekzone] {forum_name} p{page} status={r.status_code} skip")
                polite()
                continue
            links = parse_gz_thread_links(r.text, fid)
            print(f"[geekzone] forum={forum_name}({fid}) p{page} threads={len(links)}")
            if page == 1 and not links:
                sys.stderr.write(f"[geekzone] forum={forum_name}({fid}) p1 0 threads — HTML head:\n")
                sys.stderr.write(r.text[:800] + "\n")
                sys.stderr.flush()
            polite()
            added = 0
            for tid, turl, ltitle in links:
                rid = md5_16("geekzone", tid)
                if rid in seen:
                    continue
                kw_listing = matched_kw(ltitle)
                try:
                    rt = requests.get(turl, headers=HDR_NZ, timeout=25)
                except Exception as e:
                    print(f"[geekzone] thread {tid} err: {e}")
                    polite()
                    continue
                if is_cloudflare(rt.text, rt.status_code):
                    print(f"[geekzone] thread {tid} CLOUDFLARE — abort site", file=sys.stderr)
                    return n_total
                if rt.status_code >= 400:
                    polite()
                    continue
                title, body, author, replies, views = parse_gz_thread(rt.text)
                if not title:
                    title = ltitle
                combined = (title + " " + body).lower()
                kw = kw_listing or matched_kw(combined)
                if not kw:
                    polite()
                    continue
                obj = {
                    "id": rid,
                    "raw_id": tid,
                    "platform": "geekzone",
                    "lang": "en",
                    "title": title,
                    "body": body[:5000],
                    "author": author,
                    "url": turl,
                    "country_hint": "NZ",
                    "matched_keyword": kw,
                    "engagement": {"score": 0, "comments": replies, "views": views},
                    "forum": forum_name,
                    "forum_id": fid,
                    "crawled_at": now_iso(),
                }
                append(OUT_GZ, obj)
                seen.add(rid)
                n_total += 1
                added += 1
                polite()
            print(f"[geekzone] forum={forum_name} p{page} +{added} (total {n_total})")
    print(f"[geekzone] DONE +{n_total}")
    return n_total


# ---------------- Reporting ----------------

def print_samples(path, label, k=3):
    if not path.exists():
        print(f"[{label}] file missing: {path}")
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    print(f"\n=== {label}: {path} | {len(lines)} lines ===")
    for ln in lines[:k]:
        try:
            o = json.loads(ln)
            t = (o.get("title") or "").replace("\n", " ")[:120]
            b = (o.get("body") or "").replace("\n", " ")[:200]
            print(f"  - kw={o.get('matched_keyword')!r} | forum={o.get('forum')} | {t}")
            print(f"    body: {b}...")
        except Exception as e:
            print(f"  parse err: {e}")
    return len(lines)


if __name__ == "__main__":
    n_wp = crawl_whirlpool()
    n_gz = crawl_geekzone()
    lwp = print_samples(OUT_WP, "whirlpool")
    lgz = print_samples(OUT_GZ, "geekzone")
    print(f"\n=== TOTAL: whirlpool +{n_wp} (file {lwp}), geekzone +{n_gz} (file {lgz}) ===")
