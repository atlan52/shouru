"""UK 本地论坛收入帖原文抓取 — MoneySavingExpert + Mumsnet。

两站都是 SSR HTML，cookie/JS 不强依赖。polite 1.5s sleep，UA Chrome/124，
Accept-Language en-GB。关键词过滤后输出 schema 与 r_mexico_native 一致。
"""
import json, hashlib, re, time, random, sys
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HDR = {
    "User-Agent": UA,
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
}

DAY = datetime.now().strftime("%Y%m%d")
OUT_MSE = Path(f"data/raw/mse_native_{DAY}.jsonl")
OUT_MN = Path(f"data/raw/mumsnet_native_{DAY}.jsonl")

# 英文收入相关关键词
KEYWORDS = [
    "salary", "wage", "earn", "income", "pension", "ISA", "bonus",
    "freelance", "tax", "FIRE", "side hustle", "take home", "gross",
    "net pay", "payslip",
]
KW_RE = re.compile("|".join(re.escape(k) for k in KEYWORDS), re.I)

CAPTCHA_HINTS = [
    "cf-chl", "cf-mitigated", "cloudflare", "captcha", "challenge-platform",
    "Just a moment", "Please verify you are a human", "Attention Required",
    "px-captcha", "perimeterx", "datadome",
]


def md5_16(*p): return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]
def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def polite(): time.sleep(random.uniform(1.3, 1.8))


def append(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def load_seen(path):
    seen = set()
    if path.exists():
        for line in path.open():
            try:
                seen.add(json.loads(line)["id"])
            except Exception:
                pass
    return seen


def has_captcha(html: str) -> bool:
    if not html: return False
    head = html[:4000].lower()
    for h in CAPTCHA_HINTS:
        if h.lower() in head:
            return True
    return False


def matched_kw(text: str) -> str:
    if not text: return ""
    m = KW_RE.search(text)
    return m.group(0).lower() if m else ""


# =========================================================================
# MoneySavingExpert
# =========================================================================
MSE_BASE = "https://forums.moneysavingexpert.com"
MSE_CATS = [
    "savings-investments",
    "employment-jobseeking",
    "budgeting-bank-accounts",
]


def mse_listing_url(cat: str, page: int) -> str:
    if page <= 1:
        return f"{MSE_BASE}/categories/{cat}"
    return f"{MSE_BASE}/categories/{cat}/p{page}"


def mse_extract_threads(html: str, base_url: str):
    """Return list of (raw_id, slug, abs_url, title_hint) from a MSE category page."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen_href = set()

    # Strategy 1: Vanilla forum list rows
    candidates = (
        soup.select(".MessageList .Message a[href*='/discussion/']")
        + soup.select("[id^='Discussion_'] a[href*='/discussion/']")
        + soup.select("a.Title[href*='/discussion/']")
        + soup.select("a[href*='/discussion/']")
    )

    for a in candidates:
        href = a.get("href", "") or ""
        if "/discussion/" not in href:
            continue
        if "/comment/" in href or "/p2" in href.split("/discussion/")[-1]:
            # skip deep links
            pass
        if href.startswith("/"):
            href = MSE_BASE + href
        elif href.startswith("http") is False:
            continue
        # discussion URL: /discussion/<id>/<slug> or /discussion/<id>/<slug>/p1 etc
        m = re.search(r"/discussion/(\d+)(?:/([^/?#]+))?", href)
        if not m:
            continue
        raw_id = m.group(1)
        slug = m.group(2) or ""
        # canonicalise URL (drop trailing /p2 etc)
        canon = f"{MSE_BASE}/discussion/{raw_id}" + (f"/{slug}" if slug else "")
        if canon in seen_href:
            continue
        seen_href.add(canon)
        title_hint = a.get_text(" ", strip=True)
        out.append((raw_id, slug, canon, title_hint))
    return out


def mse_parse_thread(html: str):
    """Return (title, body, author) from a MSE thread page."""
    soup = BeautifulSoup(html, "html.parser")
    # Title
    t_el = (
        soup.select_one("h1.HomepageTitle")
        or soup.select_one("h1.PageTitle")
        or soup.select_one("h1")
    )
    title = t_el.get_text(" ", strip=True) if t_el else ""

    # First post body — Vanilla forums typically uses .Message .userContent / .Message-body
    body_el = (
        soup.select_one(".Discussion .Message .userContent")
        or soup.select_one(".Discussion .Message-body")
        or soup.select_one(".Message .userContent")
        or soup.select_one(".Message-body")
        or soup.select_one("article .userContent")
        or soup.select_one(".ItemDiscussion .Message")
        or soup.select_one(".CommentBody")
        or soup.select_one("article")
    )
    body = body_el.get_text(" ", strip=True) if body_el else ""

    # Author of first post
    a_el = (
        soup.select_one(".Discussion .Author a, .Discussion .Username")
        or soup.select_one(".ItemDiscussion .Username, .ItemDiscussion .Author a")
        or soup.select_one(".Message .Username, .Message .Author a")
    )
    author = a_el.get_text(" ", strip=True) if a_el else ""
    return title, body, author


def crawl_mse():
    seen = load_seen(OUT_MSE)
    n = 0
    captcha_hit = False
    for cat in MSE_CATS:
        if captcha_hit: break
        for page in range(1, 4):  # 3 pages
            url = mse_listing_url(cat, page)
            try:
                r = requests.get(url, headers=HDR, timeout=25)
                if r.status_code >= 400:
                    print(f"[mse] cat={cat} p={page} status={r.status_code} skip", file=sys.stderr)
                    polite(); continue
                if has_captcha(r.text):
                    print(f"[mse] cat={cat} p={page} CAPTCHA/Cloudflare detected, abort site", file=sys.stderr)
                    captcha_hit = True; break
                threads = mse_extract_threads(r.text, url)
                if not threads and page == 1:
                    print(f"[mse] cat={cat} p1 ZERO threads. HTML head dump:", file=sys.stderr)
                    print(r.text[:1000], file=sys.stderr)
                print(f"[mse] cat={cat} p={page} listing threads={len(threads)}")
                polite()

                for raw_id, slug, t_url, t_hint in threads:
                    rid = md5_16("mse", raw_id)
                    if rid in seen: continue
                    try:
                        rt = requests.get(t_url, headers=HDR, timeout=25)
                        if rt.status_code >= 400:
                            print(f"[mse] thread {raw_id} status={rt.status_code} skip", file=sys.stderr)
                            polite(); continue
                        if has_captcha(rt.text):
                            print(f"[mse] thread {raw_id} CAPTCHA, abort site", file=sys.stderr)
                            captcha_hit = True; break
                        title, body, author = mse_parse_thread(rt.text)
                        if not title:
                            title = t_hint
                        text = (title + " \n " + body)
                        kw = matched_kw(text)
                        if not kw:
                            polite(); continue
                        obj = {
                            "id": rid,
                            "raw_id": raw_id,
                            "platform": "mse",
                            "lang": "en",
                            "title": title,
                            "body": (body or "")[:5000],
                            "author": author,
                            "url": t_url,
                            "country_hint": "GB",
                            "matched_keyword": kw,
                            "engagement": {"score": 0, "comments": 0, "views": None},
                            "category": cat,
                            "crawled_at": now_iso(),
                        }
                        append(OUT_MSE, obj); seen.add(rid); n += 1
                    except Exception as e:
                        print(f"[mse] thread {raw_id} err: {e}", file=sys.stderr)
                    polite()
            except Exception as e:
                print(f"[mse] cat={cat} p={page} err: {e}", file=sys.stderr)
                polite()
    print(f"[mse] DONE +{n}")
    return n


# =========================================================================
# Mumsnet
# =========================================================================
MN_BASE = "https://www.mumsnet.com"
MN_BOARDS = [
    "am_i_being_unreasonable",
    "work",
    "money_matters",
]


def mn_listing_url(board: str, page: int) -> str:
    if page <= 1:
        return f"{MN_BASE}/talk/{board}"
    return f"{MN_BASE}/talk/{board}?page={page}"


def mn_extract_threads(html: str, board: str):
    """Return list of (raw_id, slug, abs_url, title_hint)."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen_href = set()
    candidates = (
        soup.select(f"a[href*='/talk/{board}/']")
        + soup.select("a[href*='/talk/']")
    )
    for a in candidates:
        href = a.get("href", "") or ""
        if "/talk/" not in href:
            continue
        # only thread URLs: /talk/<board>/<digits>-<slug>
        m = re.search(r"/talk/([^/?#]+)/(\d+)-([^/?#]+)", href)
        if not m:
            continue
        b = m.group(1); raw_id = m.group(2); slug = m.group(3)
        if href.startswith("/"):
            abs_url = MN_BASE + href
        elif href.startswith("http"):
            abs_url = href
        else:
            continue
        # canonicalise (strip query/fragment)
        canon = re.sub(r"[?#].*$", "", abs_url)
        if canon in seen_href: continue
        seen_href.add(canon)
        title_hint = a.get_text(" ", strip=True)
        out.append((raw_id, slug, canon, title_hint, b))
    return out


def mn_parse_thread(html: str):
    soup = BeautifulSoup(html, "html.parser")
    t_el = (
        soup.select_one("h1.thread__title")
        or soup.select_one("h1[class*=thread]")
        or soup.select_one("h1")
    )
    title = t_el.get_text(" ", strip=True) if t_el else ""
    # First post body
    body_el = (
        soup.select_one(".thread__post-message")
        or soup.select_one(".lia-message-body-content")
        or soup.select_one("[class*=post-message]")
        or soup.select_one("[class*=message-body]")
        or soup.select_one("article")
    )
    body = body_el.get_text(" ", strip=True) if body_el else ""
    a_el = (
        soup.select_one(".thread__post-author")
        or soup.select_one("[class*=post-author]")
        or soup.select_one("[class*=username]")
    )
    author = a_el.get_text(" ", strip=True) if a_el else ""
    return title, body, author


def crawl_mumsnet():
    seen = load_seen(OUT_MN)
    n = 0
    captcha_hit = False
    for board in MN_BOARDS:
        if captcha_hit: break
        for page in range(1, 4):
            url = mn_listing_url(board, page)
            try:
                r = requests.get(url, headers=HDR, timeout=25)
                if r.status_code >= 400:
                    print(f"[mn] board={board} p={page} status={r.status_code} skip", file=sys.stderr)
                    polite(); continue
                if has_captcha(r.text):
                    print(f"[mn] board={board} p={page} CAPTCHA detected, abort site", file=sys.stderr)
                    captcha_hit = True; break
                threads = mn_extract_threads(r.text, board)
                if not threads and page == 1:
                    print(f"[mn] board={board} p1 ZERO threads. HTML head dump:", file=sys.stderr)
                    print(r.text[:1000], file=sys.stderr)
                print(f"[mn] board={board} p={page} listing threads={len(threads)}")
                polite()

                for raw_id, slug, t_url, t_hint, b in threads:
                    rid = md5_16("mumsnet", raw_id)
                    if rid in seen: continue
                    try:
                        rt = requests.get(t_url, headers=HDR, timeout=25)
                        if rt.status_code >= 400:
                            print(f"[mn] thread {raw_id} status={rt.status_code} skip", file=sys.stderr)
                            polite(); continue
                        if has_captcha(rt.text):
                            print(f"[mn] thread {raw_id} CAPTCHA, abort site", file=sys.stderr)
                            captcha_hit = True; break
                        title, body, author = mn_parse_thread(rt.text)
                        if not title:
                            title = t_hint
                        text = (title + " \n " + body)
                        kw = matched_kw(text)
                        if not kw:
                            polite(); continue
                        obj = {
                            "id": rid,
                            "raw_id": raw_id,
                            "platform": "mumsnet",
                            "lang": "en",
                            "title": title,
                            "body": (body or "")[:5000],
                            "author": author,
                            "url": t_url,
                            "country_hint": "GB",
                            "matched_keyword": kw,
                            "engagement": {"score": 0, "comments": 0, "views": None},
                            "board": b,
                            "crawled_at": now_iso(),
                        }
                        append(OUT_MN, obj); seen.add(rid); n += 1
                    except Exception as e:
                        print(f"[mn] thread {raw_id} err: {e}", file=sys.stderr)
                    polite()
            except Exception as e:
                print(f"[mn] board={board} p={page} err: {e}", file=sys.stderr)
                polite()
    print(f"[mn] DONE +{n}")
    return n


# =========================================================================
# Output samples
# =========================================================================
def print_samples(path: Path, label: str, k: int = 5):
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
    n_mse = crawl_mse()
    n_mn = crawl_mumsnet()
    l_mse = print_samples(OUT_MSE, "MSE", k=5)
    l_mn = print_samples(OUT_MN, "Mumsnet", k=5)
    print(f"\n=== TOTAL: mse +{n_mse} (file {l_mse}), mumsnet +{n_mn} (file {l_mn}) ===")
