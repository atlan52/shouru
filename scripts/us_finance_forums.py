"""US three big personal-finance / FIRE / RE forums income posts (English, US):

1. Bogleheads.org forum  (phpBB, SSR)            board f=1 (personal finance), f=2 (investing)
2. Mr Money Mustache forum (forum.mrmoneymustache.com, SMF, SSR)  board=8.0 (Career & income), board=11.0 (Investor Alley)
3. BiggerPockets forum  (SSR-ish)                /forums/311 (investor mindset), /forums/49 (rookie investor)

Subagent must NOT run python — only write the script. Main agent runs:
    .venv/bin/python scripts/us_finance_forums.py
"""
import json, hashlib, re, time, random
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HDR = {
    "User-Agent": UA,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
DAY = datetime.now().strftime("%Y%m%d")
OUT_BH  = Path(f"data/raw/bogleheads_native_{DAY}.jsonl")
OUT_MMM = Path(f"data/raw/mmm_native_{DAY}.jsonl")
OUT_BP  = Path(f"data/raw/biggerpockets_native_{DAY}.jsonl")

# English finance / FIRE / income / investing keywords
KEYWORDS = [
    "salary", "income", "FIRE number", "net worth", "RE income",
    "rental income", "dividend", "401k", "Roth", "NW",
    "Boglehead milestone", "total comp", "TC",
    "compensation", "raise", "promotion", "bonus", "stock comp", "RSU",
    "passive income", "side hustle", "freelance", "consulting income",
    "early retirement", "FI/RE", "FIRE",
    "real estate income", "cash flow", "rental property",
    "saving rate", "savings rate", "expense ratio",
    "milestone", "portfolio",
]
# Lower-case once for matching
KEYWORDS_LC = [k.lower() for k in KEYWORDS]


def md5_16(*p): return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]
def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def append(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
def polite(): time.sleep(random.uniform(1.3, 1.7))


def load_seen(path):
    seen = set()
    if path.exists():
        for line in path.open():
            try: seen.add(json.loads(line)["id"])
            except: pass
    return seen


def keyword_match(text):
    """Return first matched keyword (lowercased) or empty string."""
    t = (text or "").lower()
    for k_lc, k_orig in zip(KEYWORDS_LC, KEYWORDS):
        # Use simple substring match; for 2-3 letter abbrevs require word boundary
        if len(k_lc) <= 3:
            if re.search(rf"\b{re.escape(k_lc)}\b", t):
                return k_orig
        else:
            if k_lc in t:
                return k_orig
    return ""


def detect_cloudflare(html):
    if not html: return False
    h = html.lower()
    return ("cloudflare" in h and ("checking your browser" in h or "attention required" in h or "cf-chl" in h)) \
           or "just a moment" in h


def get(url, label, dump_on_zero=False):
    """GET with polite retry semantics. Returns (status, text). Skips 4xx/5xx; exits cloudflare."""
    try:
        r = requests.get(url, headers=HDR, timeout=25)
    except Exception as e:
        print(f"[{label}] GET err {url}: {e}")
        return -1, ""
    if detect_cloudflare(r.text):
        print(f"[{label}] CLOUDFLARE on {url} — abort site")
        return -2, r.text
    if r.status_code >= 400:
        print(f"[{label}] {r.status_code} {url}")
        return r.status_code, ""
    return r.status_code, r.text


# -------------------- Bogleheads (phpBB) --------------------

def crawl_bogleheads():
    seen = load_seen(OUT_BH)
    n = 0
    boards = [("personal_finance", 1), ("investing", 2)]
    PAGES = 3  # first 3 pages
    PER_PAGE = 50  # phpBB default
    for board_name, fid in boards:
        for page in range(PAGES):
            start = page * PER_PAGE
            list_url = f"https://www.bogleheads.org/forum/viewforum.php?f={fid}&start={start}"
            status, html = get(list_url, "bogleheads")
            if status == -2: return n  # cloudflare → bail entire site
            if status != 200 or not html: continue
            soup = BeautifulSoup(html, "html.parser")
            # phpBB topic links: a.topictitle, href like ./viewtopic.php?f=1&t=12345
            anchors = soup.select("a.topictitle")
            if not anchors:
                # fallback: any viewtopic anchor
                anchors = soup.select("a[href*='viewtopic.php']")
            thread_links = []
            seen_t = set()
            for a in anchors:
                href = a.get("href", "")
                m = re.search(r"[?&]t=(\d+)", href)
                if not m: continue
                tid = m.group(1)
                if tid in seen_t: continue
                seen_t.add(tid)
                if href.startswith("./"):
                    full = "https://www.bogleheads.org/forum/" + href[2:]
                elif href.startswith("/"):
                    full = "https://www.bogleheads.org" + href
                elif href.startswith("http"):
                    full = href
                else:
                    full = "https://www.bogleheads.org/forum/" + href
                thread_links.append((tid, a.get_text(" ", strip=True), full))
            print(f"[bogleheads] {board_name} page={page} threads={len(thread_links)}")
            if not thread_links and page == 0:
                dump = html[:800].replace("\n", " ")
                print(f"[bogleheads] EMPTY page f={fid} HTML[:800]: {dump}")
                continue
            for tid, list_title, url in thread_links:
                rid = md5_16("bogleheads", tid)
                if rid in seen: continue
                # Fetch thread
                t_status, t_html = get(url, "bogleheads")
                polite()
                if t_status == -2: return n
                if t_status != 200 or not t_html: continue
                tsoup = BeautifulSoup(t_html, "html.parser")
                title_el = tsoup.select_one("h2.topic-title") or tsoup.select_one("h2") or tsoup.select_one("h1")
                title = title_el.get_text(" ", strip=True) if title_el else list_title
                # First post: first .post block
                post_el = tsoup.select_one(".post .postbody .content") \
                          or tsoup.select_one(".postbody .content") \
                          or tsoup.select_one(".content") \
                          or tsoup.select_one(".post")
                body = post_el.get_text(" ", strip=True) if post_el else ""
                author_el = tsoup.select_one(".post .author a, .post .author strong, .username, .username-coloured")
                author = author_el.get_text(" ", strip=True) if author_el else ""
                # Keyword filter
                kw = keyword_match(title + " " + body)
                if not kw:
                    continue
                obj = {
                    "id": rid,
                    "raw_id": tid,
                    "platform": "bogleheads",
                    "lang": "en",
                    "title": title,
                    "body": body[:5000],
                    "author": author,
                    "url": url,
                    "country_hint": "US",
                    "matched_keyword": kw,
                    "engagement": {"score": 0, "comments": 0, "views": None},
                    "board": board_name,
                    "crawled_at": now_iso(),
                }
                append(OUT_BH, obj); seen.add(rid); n += 1
            polite()
    print(f"[bogleheads] DONE +{n}")
    return n


# -------------------- Mr Money Mustache (SMF) --------------------

def crawl_mmm():
    seen = load_seen(OUT_MMM)
    n = 0
    # SMF: ?board=8.0 = first page, ?board=8.20 = page 2 (20 per page typical), ?board=8.40
    boards = [("career_and_income", 8), ("investor_alley", 11)]
    PAGES = 3
    PER_PAGE = 20
    for board_name, bid in boards:
        for page in range(PAGES):
            offset = page * PER_PAGE
            list_url = f"https://forum.mrmoneymustache.com/index.php?board={bid}.{offset}"
            status, html = get(list_url, "mmm")
            if status == -2: return n
            if status != 200 or not html: continue
            soup = BeautifulSoup(html, "html.parser")
            # SMF topic links: a[href*='topic=']
            anchors = soup.select("a[href*='topic=']")
            thread_links = []
            seen_t = set()
            for a in anchors:
                href = a.get("href", "")
                m = re.search(r"topic=(\d+)", href)
                if not m: continue
                tid = m.group(1)
                if tid in seen_t: continue
                # skip nav anchors like ".msg" reply jumps; we want topic top
                if "msg" in href and "#" in href:
                    pass  # still keep, we'll normalise
                seen_t.add(tid)
                full = f"https://forum.mrmoneymustache.com/index.php?topic={tid}.0"
                title_text = a.get_text(" ", strip=True)
                if not title_text or len(title_text) < 4: continue
                thread_links.append((tid, title_text, full))
            print(f"[mmm] {board_name} page={page} threads={len(thread_links)}")
            if not thread_links and page == 0:
                dump = html[:800].replace("\n", " ")
                print(f"[mmm] EMPTY page board={bid} HTML[:800]: {dump}")
                continue
            for tid, list_title, url in thread_links:
                rid = md5_16("mmm", tid)
                if rid in seen: continue
                t_status, t_html = get(url, "mmm")
                polite()
                if t_status == -2: return n
                if t_status != 200 or not t_html: continue
                tsoup = BeautifulSoup(t_html, "html.parser")
                # SMF title: h4.windowbg or h3, page <title>
                title_el = tsoup.select_one("h4.windowbg") or tsoup.select_one("h3") or tsoup.select_one("title")
                title = title_el.get_text(" ", strip=True) if title_el else list_title
                # SMF first post: div.post (first one) or div.inner
                post_el = tsoup.select_one("div.post") or tsoup.select_one("div.inner") or tsoup.select_one(".postarea")
                body = post_el.get_text(" ", strip=True) if post_el else ""
                author_el = tsoup.select_one(".poster h4 a") or tsoup.select_one(".poster a")
                author = author_el.get_text(" ", strip=True) if author_el else ""
                kw = keyword_match(title + " " + body)
                if not kw: continue
                obj = {
                    "id": rid,
                    "raw_id": tid,
                    "platform": "mmm",
                    "lang": "en",
                    "title": title,
                    "body": body[:5000],
                    "author": author,
                    "url": url,
                    "country_hint": "US",
                    "matched_keyword": kw,
                    "engagement": {"score": 0, "comments": 0, "views": None},
                    "board": board_name,
                    "crawled_at": now_iso(),
                }
                append(OUT_MMM, obj); seen.add(rid); n += 1
            polite()
    print(f"[mmm] DONE +{n}")
    return n


# -------------------- BiggerPockets --------------------

def crawl_biggerpockets():
    seen = load_seen(OUT_BP)
    n = 0
    boards = [("investor_mindset", 311), ("rookie_investor", 49)]
    PAGES = 3
    for board_name, fid in boards:
        for page in range(1, PAGES + 1):
            list_url = f"https://www.biggerpockets.com/forums/{fid}?page={page}"
            status, html = get(list_url, "biggerpockets")
            if status == -2: return n
            if status != 200 or not html: continue
            soup = BeautifulSoup(html, "html.parser")
            # Topic anchors: /forums/<board>/topics/<id>-<slug>
            anchors = soup.select("a[href*='/forums/'][href*='/topics/']")
            thread_links = []
            seen_t = set()
            for a in anchors:
                href = a.get("href", "")
                m = re.search(r"/forums/\d+/topics/(\d+)(?:-([^?#/]+))?", href)
                if not m: continue
                tid = m.group(1)
                if tid in seen_t: continue
                seen_t.add(tid)
                if href.startswith("/"):
                    full = "https://www.biggerpockets.com" + href
                elif href.startswith("http"):
                    full = href
                else:
                    full = "https://www.biggerpockets.com/" + href
                title_text = a.get_text(" ", strip=True)
                if not title_text or len(title_text) < 4: continue
                thread_links.append((tid, title_text, full))
            print(f"[biggerpockets] {board_name} page={page} threads={len(thread_links)}")
            if not thread_links and page == 1:
                dump = html[:800].replace("\n", " ")
                print(f"[biggerpockets] EMPTY page f={fid} HTML[:800]: {dump}")
                continue
            for tid, list_title, url in thread_links:
                rid = md5_16("biggerpockets", tid)
                if rid in seen: continue
                t_status, t_html = get(url, "biggerpockets")
                polite()
                if t_status == -2: return n
                if t_status != 200 or not t_html: continue
                tsoup = BeautifulSoup(t_html, "html.parser")
                title_el = tsoup.select_one("h1") or tsoup.select_one("h2") or tsoup.select_one("title")
                title = title_el.get_text(" ", strip=True) if title_el else list_title
                post_el = tsoup.select_one(".first-post") \
                          or tsoup.select_one("[class*=first-post]") \
                          or tsoup.select_one("[class*=forum-post]") \
                          or tsoup.select_one("article") \
                          or tsoup.select_one("main")
                body = post_el.get_text(" ", strip=True) if post_el else ""
                author_el = tsoup.select_one("[class*=author]") or tsoup.select_one("[class*=username]")
                author = author_el.get_text(" ", strip=True) if author_el else ""
                kw = keyword_match(title + " " + body)
                if not kw: continue
                obj = {
                    "id": rid,
                    "raw_id": tid,
                    "platform": "biggerpockets",
                    "lang": "en",
                    "title": title,
                    "body": body[:5000],
                    "author": author,
                    "url": url,
                    "country_hint": "US",
                    "matched_keyword": kw,
                    "engagement": {"score": 0, "comments": 0, "views": None},
                    "board": board_name,
                    "crawled_at": now_iso(),
                }
                append(OUT_BP, obj); seen.add(rid); n += 1
            polite()
    print(f"[biggerpockets] DONE +{n}")
    return n


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
            print(f"  - kw={o.get('matched_keyword')!r} board={o.get('board')!r} | {t}")
            print(f"    body: {b}...")
        except Exception as e:
            print(f"  parse err: {e}")
    return len(lines)


if __name__ == "__main__":
    n_bh  = crawl_bogleheads()
    n_mmm = crawl_mmm()
    n_bp  = crawl_biggerpockets()
    l_bh  = print_samples(OUT_BH,  "bogleheads")
    l_mmm = print_samples(OUT_MMM, "mmm")
    l_bp  = print_samples(OUT_BP,  "biggerpockets")
    print(f"\n=== TOTAL: bogleheads +{n_bh} (file {l_bh}), mmm +{n_mmm} (file {l_mmm}), biggerpockets +{n_bp} (file {l_bp}) ===")
