"""Boards.ie (IE) + RedFlagDeals (CA) — 爱尔兰 + 加拿大本地论坛收入帖直接抓取。

两个站都是 SSR HTML，无需登录：
  - boards.ie 是 Vanilla Forums skin（同 MoneySavingExpert），thread URL
    模式 `/discussion/<id>/<slug>`
  - forums.redflagdeals.com 是自家 phpBB-style，thread URL 模式
    `/thread-<id>/` 或 `/<slug>-<id>/`

策略：
  1. 各板块前 3 页列表 → 收 thread 链接。
  2. 进 thread 抓 OP 标题 + 楼主正文。
  3. 关键词过滤（salary / RRSP / TFSA / Dublin salary 等）。
  4. 4xx/5xx 跳过该 url；遇 cloudflare interstitial 直接退出该站。
  5. polite 1.2-1.8s 间隔，UA Chrome/124，Accept-Language 按地区。
  6. 输出两个 JSONL，schema 同 r_mexico_native。
"""
import json, hashlib, re, time, random, sys
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

UA_BROWSER = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

HDR_IE = {
    "User-Agent": UA_BROWSER,
    "Accept-Language": "en-IE,en-GB;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
HDR_CA = {
    "User-Agent": UA_BROWSER,
    "Accept-Language": "en-CA,en;q=0.9,fr-CA;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

DAY = datetime.now().strftime("%Y%m%d")
OUT_BOARDS = Path(f"data/raw/boards_ie_native_{DAY}.jsonl")
OUT_RFD = Path(f"data/raw/rfd_native_{DAY}.jsonl")

KEYWORDS = [
    "salary", "wage", "earn", "earning", "income", "pension",
    "rrsp", "tfsa", "t4", "bonus", "freelance", "fire",
    "ireland tech salary", "dublin salary", "take home",
    "net pay", "gross", "take-home", "payslip",
]
# Regex compiled for case-insensitive substring match
_KW_RE = re.compile("|".join(re.escape(k) for k in KEYWORDS), re.I)

CF_MARKERS = ("cf-browser-verification", "checking your browser",
              "attention required", "cloudflare", "challenge-platform",
              "captcha-delivery")

PAGES = 3            # per board
MAX_PER_BOARD = 60   # safety cap per board per run


# -------- shared utils --------
def md5_16(*p): return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]
def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def polite():
    time.sleep(random.uniform(1.2, 1.8))


def load_seen(path):
    seen = set()
    if path.exists():
        for line in path.open():
            try: seen.add(json.loads(line)["id"])
            except: pass
    return seen


def matches_kw(text):
    if not text: return None
    m = _KW_RE.search(text)
    return m.group(0).lower() if m else None


def is_cloudflare(html):
    if not html: return False
    low = html.lower()
    return any(m in low for m in CF_MARKERS)


def fetch(url, headers, label):
    """Returns (status, html) or (status, None). Raises 'CF' string on cloudflare."""
    try:
        r = requests.get(url, headers=headers, timeout=25, allow_redirects=True)
    except Exception as e:
        print(f"  [{label}] net err {url}: {e}")
        return -1, None
    if r.status_code >= 400:
        print(f"  [{label}] status {r.status_code} {url}")
        return r.status_code, None
    if is_cloudflare(r.text):
        print(f"  [{label}] CLOUDFLARE block {url}")
        return r.status_code, "__CF__"
    return r.status_code, r.text


def dump_html_snippet(html, label, url):
    """Dump 800 chars when listing yields 0 threads — for offline debugging."""
    snippet = (html or "")[:800].replace("\n", " ")
    print(f"  [{label}] DEBUG zero threads at {url}")
    print(f"  [{label}] HTML[:800]: {snippet}")


# =====================================================================
# Boards.ie  (Vanilla Forums skin — same as MoneySavingExpert)
# =====================================================================
BOARDS_BASE = "https://www.boards.ie"
BOARDS_CATEGORIES = [
    ("/categories/work-careers-and-business", "careers"),
    ("/categories/personal-finance", "finance"),
]
_BOARDS_THREAD_RE = re.compile(r"/discussion/(\d+)/([^/?#]+)")


def boards_list_threads(html):
    soup = BeautifulSoup(html, "html.parser")
    seen_ids = set()
    out = []
    # Sweep every anchor pointing at /discussion/<id>/<slug>
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = _BOARDS_THREAD_RE.search(href)
        if not m: continue
        tid = m.group(1)
        slug = m.group(2)
        if tid in seen_ids: continue
        seen_ids.add(tid)
        # Canonicalise, strip query/anchor and the /pX paginator
        canonical = f"{BOARDS_BASE}/discussion/{tid}/{slug}"
        title = a.get_text(" ", strip=True)
        out.append({"thread_id": tid, "slug": slug, "url": canonical, "title": title})
    return out


def boards_parse_thread(html, fallback_title=""):
    soup = BeautifulSoup(html, "html.parser")
    # Title
    title = ""
    for sel in ("h1.PageTitle", "h1.heading-1", "h1[class*='Title']", "h1"):
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            title = el.get_text(" ", strip=True); break
    if not title:
        title = fallback_title

    # OP comment is typically the first .Comment / .ItemComment / .Message block
    op_body = ""
    op_author = ""
    for sel in (
        "li.ItemComment", "div.ItemComment", "li.Comment", "div.Comment",
        "article.Comment", "div.Message", "div[class*='Comment_']",
        "[id^='Discussion_']", "article",
    ):
        nodes = soup.select(sel)
        if not nodes: continue
        first = nodes[0]
        msg_el = (first.select_one(".Message") or first.select_one("[class*='Message']")
                  or first.select_one(".userContent") or first)
        body = msg_el.get_text(" ", strip=True)
        if body:
            op_body = body
            a_el = (first.select_one("a.Username") or first.select_one(".Author a")
                    or first.select_one("[class*='Username']") or first.select_one(".PhotoWrap a"))
            if a_el: op_author = a_el.get_text(" ", strip=True)
            break

    # last-resort body fallback
    if not op_body:
        for sel in (".DiscussionContent .Message", ".Discussion .Message",
                    "div[class*='Message']", "article .userContent", "main"):
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                op_body = el.get_text(" ", strip=True); break

    # rough engagement: count comments
    n_comments = max(0, len(soup.select("li.ItemComment, div.ItemComment, li.Comment, div.Comment")) - 1)
    return {"title": title, "author": op_author, "body": op_body, "comments": n_comments}


def crawl_boards_ie():
    seen = load_seen(OUT_BOARDS)
    n = 0
    for cat_path, cat_label in BOARDS_CATEGORIES:
        if n >= MAX_PER_BOARD * len(BOARDS_CATEGORIES): break
        for page in range(1, PAGES + 1):
            list_url = f"{BOARDS_BASE}{cat_path}" if page == 1 else f"{BOARDS_BASE}{cat_path}/p{page}"
            status, html = fetch(list_url, HDR_IE, "boards.ie")
            if html == "__CF__":
                print("[boards.ie] cloudflare — abort site")
                return n
            if not html:
                polite(); continue
            threads = boards_list_threads(html)
            if not threads:
                dump_html_snippet(html, "boards.ie", list_url)
                polite(); continue
            print(f"[boards.ie] {cat_label} p{page} threads={len(threads)}")
            for meta in threads:
                rid = md5_16("boards_ie", meta["thread_id"])
                if rid in seen: continue
                # quick title-only keyword pre-filter to save fetches; keep all if no match yet
                tkm = matches_kw(meta["title"])
                # We'll fetch then re-check with full body so we don't miss income posts
                status2, thtml = fetch(meta["url"], HDR_IE, "boards.ie")
                polite()
                if thtml == "__CF__":
                    print("[boards.ie] cloudflare — abort site")
                    return n
                if not thtml: continue
                parsed = boards_parse_thread(thtml, fallback_title=meta["title"])
                title = parsed["title"] or meta["title"]
                body = parsed["body"] or ""
                kw = matches_kw(title) or matches_kw(body) or tkm
                if not kw:
                    continue
                obj = {
                    "id": rid,
                    "raw_id": meta["thread_id"],
                    "platform": "boards_ie",
                    "lang": "en",
                    "title": title,
                    "body": body[:5000],
                    "author": parsed["author"],
                    "url": meta["url"],
                    "country_hint": "IE",
                    "matched_keyword": kw,
                    "engagement": {
                        "score": 0,
                        "comments": parsed["comments"],
                    },
                    "category": cat_label,
                    "crawled_at": now_iso(),
                }
                append(OUT_BOARDS, obj); seen.add(rid); n += 1
                if n % 10 == 0:
                    print(f"  [boards.ie] +{n}")
                if n >= MAX_PER_BOARD * len(BOARDS_CATEGORIES): break
            polite()
        polite()
    print(f"[boards.ie] DONE +{n}")
    return n


# =====================================================================
# RedFlagDeals  (phpBB-style)
# =====================================================================
RFD_BASE = "https://forums.redflagdeals.com"
RFD_BOARDS = [
    ("/personal-finance-29/", "personal-finance"),
    ("/careers-employment-37/", "careers-employment"),
]
# Thread URLs come in two shapes:
#   /thread-12345/
#   /<slug-with-dashes>-12345/
_RFD_THREAD_RE = re.compile(r"/(?:[\w\-]+-)?(\d{5,})/?(?:#.*)?$")


def rfd_list_threads(html):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen_ids = set()
    # phpBB: thread anchors have class .topic_title_link / .topictitle
    candidates = []
    candidates += soup.select("a.topic_title_link")
    candidates += soup.select("a.topictitle")
    candidates += soup.select("h3.topictitle a")
    candidates += soup.select("a[href^='/']")  # broad sweep last
    for a in candidates:
        href = a.get("href", "")
        if not href: continue
        # filter junk: must look like thread (digits at end before optional /)
        # canonical thread URL always ends in `-NNNN/` or is `/thread-NNNN/`
        m = re.search(r"/(?:thread-(\d+)|[\w\-]+?-(\d+))/(?:[\?#].*)?$", href)
        if not m: continue
        tid = m.group(1) or m.group(2)
        if not tid or len(tid) < 4: continue
        if tid in seen_ids: continue
        seen_ids.add(tid)
        full = urljoin(RFD_BASE + "/", href.split("#")[0].split("?")[0])
        title = a.get_text(" ", strip=True)
        if not title: continue
        # avoid sub-forum / category links (they don't end in -<digits>/)
        out.append({"thread_id": tid, "url": full, "title": title})
    return out


def rfd_parse_thread(html, fallback_title=""):
    soup = BeautifulSoup(html, "html.parser")
    # Title
    title = ""
    for sel in ("h1.thread_title", "h1[class*='thread']", "h1"):
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            title = el.get_text(" ", strip=True); break
    if not title:
        title = fallback_title

    # OP body — RFD uses `.first_post .post_body` and `.post_message`
    op_body = ""
    op_author = ""
    op = (soup.select_one(".first_post")
          or soup.select_one("li.post.first")
          or soup.select_one("div.post.first")
          or soup.select_one("li.post")
          or soup.select_one("div.post")
          or soup.select_one("article.post"))
    if op:
        body_el = (op.select_one(".post_body")
                   or op.select_one(".post_message")
                   or op.select_one(".content")
                   or op)
        op_body = body_el.get_text(" ", strip=True)
        a_el = (op.select_one(".author a") or op.select_one("a.username")
                or op.select_one(".post_author a") or op.select_one(".username"))
        if a_el: op_author = a_el.get_text(" ", strip=True)

    if not op_body:
        # fallback: grab the first `.post_body` / `.post_message` anywhere
        for sel in (".post_body", ".post_message", "article", "main"):
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                op_body = el.get_text(" ", strip=True); break

    # engagement: count post containers
    posts = soup.select("li.post, div.post, article.post")
    n_replies = max(0, len(posts) - 1)
    return {"title": title, "author": op_author, "body": op_body, "replies": n_replies}


def crawl_rfd():
    seen = load_seen(OUT_RFD)
    n = 0
    for board_path, board_label in RFD_BOARDS:
        if n >= MAX_PER_BOARD * len(RFD_BOARDS): break
        for page in range(1, PAGES + 1):
            list_url = f"{RFD_BASE}{board_path}" if page == 1 else f"{RFD_BASE}{board_path}?p={page}"
            status, html = fetch(list_url, HDR_CA, "rfd")
            if html == "__CF__":
                print("[rfd] cloudflare — abort site")
                return n
            if not html:
                polite(); continue
            threads = rfd_list_threads(html)
            if not threads:
                dump_html_snippet(html, "rfd", list_url)
                polite(); continue
            print(f"[rfd] {board_label} p{page} threads={len(threads)}")
            for meta in threads:
                rid = md5_16("rfd", meta["thread_id"])
                if rid in seen: continue
                tkm = matches_kw(meta["title"])
                status2, thtml = fetch(meta["url"], HDR_CA, "rfd")
                polite()
                if thtml == "__CF__":
                    print("[rfd] cloudflare — abort site")
                    return n
                if not thtml: continue
                parsed = rfd_parse_thread(thtml, fallback_title=meta["title"])
                title = parsed["title"] or meta["title"]
                body = parsed["body"] or ""
                kw = matches_kw(title) or matches_kw(body) or tkm
                if not kw:
                    continue
                obj = {
                    "id": rid,
                    "raw_id": meta["thread_id"],
                    "platform": "rfd",
                    "lang": "en",
                    "title": title,
                    "body": body[:5000],
                    "author": parsed["author"],
                    "url": meta["url"],
                    "country_hint": "CA",
                    "matched_keyword": kw,
                    "engagement": {
                        "score": 0,
                        "comments": parsed["replies"],
                    },
                    "board": board_label,
                    "crawled_at": now_iso(),
                }
                append(OUT_RFD, obj); seen.add(rid); n += 1
                if n % 10 == 0:
                    print(f"  [rfd] +{n}")
                if n >= MAX_PER_BOARD * len(RFD_BOARDS): break
            polite()
        polite()
    print(f"[rfd] DONE +{n}")
    return n


# =====================================================================
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
            print(f"  - kw={o.get('matched_keyword')!r} | {t}")
            print(f"    body: {b}...")
        except Exception as e:
            print(f"  parse err: {e}")
    return len(lines)


if __name__ == "__main__":
    n_b = crawl_boards_ie()
    n_r = crawl_rfd()
    lb = print_samples(OUT_BOARDS, "boards.ie")
    lr = print_samples(OUT_RFD, "rfd")
    print(f"\n=== TOTAL: boards.ie +{n_b} (file {lb}), rfd +{n_r} (file {lr}) ===")
