"""自适应论坛重试 — 死掉的 6 个 200-站，先扫主页找 finance/career 板块 anchor，
再爬 thread。

涵盖站点:
  - forums.redflagdeals.com (CA)
  - forums.whirlpool.net.au (AU)
  - geekzone.co.nz (NZ)
  - tinhte.vn (VN)
  - kaskus.co.id (ID)
  - forum.lowyat.net (MY)
"""
import json, hashlib, time, random, re, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

DAY = datetime.now().strftime("%Y%m%d")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
TIMEOUT = 25
SLEEP = (1.3, 1.8)

# (key, base, lang, country, accept_lang, finance_words, kw_re)
SITES = [
    ("rfd", "https://forums.redflagdeals.com/", "en", "CA", "en-CA,en;q=0.9",
     ["personal-finance", "career", "employment", "money", "investing"],
     re.compile(r"salary|wage|earn|income|tfsa|rrsp|t4|cpp|bonus|raise|freelance|fire", re.I)),
    ("whirlpool", "https://forums.whirlpool.net.au/", "en", "AU", "en-AU,en;q=0.9",
     ["finance", "career", "money", "salary", "tax", "super"],
     re.compile(r"salary|wage|earn|income|super|bonus|raise|freelance|fire|tradie", re.I)),
    ("geekzone", "https://www.geekzone.co.nz/forums.asp", "en", "NZ", "en-NZ,en;q=0.9",
     ["finance", "money", "career", "job", "salary", "tax"],
     re.compile(r"salary|wage|earn|income|kiwisaver|bonus|raise|freelance|fire", re.I)),
    ("tinhte", "https://tinhte.vn/", "vi", "VN", "vi-VN,vi;q=0.9",
     ["công việc", "tài chính", "kinh doanh", "công sở", "lương", "thu nhập"],
     re.compile(r"lương|thu nhập|kiếm tiền|freelance|kỹ sư|lập trình|fire")),
    ("kaskus", "https://www.kaskus.co.id/", "id", "ID", "id-ID,id;q=0.9",
     ["finance", "money", "investasi", "kerja", "karir", "lounge"],
     re.compile(r"gaji|pendapatan|penghasilan|freelance|FIRE|pensiun")),
    ("lowyat", "https://forum.lowyat.net/", "ms", "MY", "ms-MY,ms;q=0.9,en;q=0.5",
     ["money", "finance", "career", "job", "kerjaya", "kewangan", "Bursa", "Sersera"],
     re.compile(r"salary|gaji|income|pendapatan|earn|bonus|EPF|PERKESO|freelance", re.I)),
]


def md5_16(*p): return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]
def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def polite(): time.sleep(random.uniform(*SLEEP))


def hdr(accept_lang: str):
    return {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": accept_lang,
        "Accept-Encoding": "gzip, deflate, br",
    }


def fetch(url: str, accept_lang: str, label: str = "") -> str | None:
    try:
        r = requests.get(url, headers=hdr(accept_lang), timeout=TIMEOUT, allow_redirects=True)
    except Exception as e:
        print(f"  [{label}] err: {e}", file=sys.stderr)
        return None
    if r.status_code != 200:
        print(f"  [{label}] status={r.status_code} url={url}", file=sys.stderr)
        return None
    return r.text


def discover_boards(home_url: str, accept_lang: str, finance_words: list[str], key: str) -> list[str]:
    """Scan home page for anchors whose text contains any finance-related word."""
    html = fetch(home_url, accept_lang, label=f"{key} home")
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    base = home_url
    boards = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        text = a.get_text(" ", strip=True).lower()
        if not text:
            continue
        for fw in finance_words:
            if fw.lower() in text or fw.lower() in href.lower():
                full = urljoin(base, href)
                if not full.startswith("http"):
                    continue
                # skip non-board links
                pu = urlparse(full)
                if pu.netloc not in (urlparse(home_url).netloc,):
                    continue
                if full in seen:
                    continue
                seen.add(full)
                boards.append((text[:80], full))
                break
        if len(boards) >= 30:
            break
    print(f"[{key}] discovered {len(boards)} candidate boards:")
    for t, u in boards[:15]:
        print(f"    {t!r:<40} -> {u}")
    return [u for t, u in boards]


def extract_threads(html: str, base: str, key: str) -> list[tuple[str, str]]:
    """Extract (title, thread_url) candidates from a board page."""
    soup = BeautifulSoup(html, "html.parser")
    threads = []
    seen = set()
    # Common thread link selectors
    selectors = [
        "a.title", "a.subject", "a.topictitle", "h2 a", "h3 a", "h4 a",
        ".thread a", ".topic a", ".structItem-title a",
        "tr td a[href*='/topic/']", "tr td a[href*='/thread/']",
        "a[href*='topic=']", "a[href*='topicid=']", "a[href*='/t/']",
        "a[href*='/thread-']", "a[href*='/showthread']",
    ]
    for sel in selectors:
        for a in soup.select(sel):
            url = a.get("href", "")
            text = a.get_text(" ", strip=True)
            if not url or not text or len(text) < 10:
                continue
            full = urljoin(base, url)
            if full in seen:
                continue
            # heuristic: thread URLs usually contain digits
            if not re.search(r"\d", full):
                continue
            seen.add(full)
            threads.append((text, full))
    return threads[:40]


def extract_body(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "aside", "header", "footer"]):
        tag.decompose()
    selectors = [
        ".bbWrapper", ".message-body", ".message-content",
        ".post_body", ".post-message", ".postbody", ".content",
        ".body", ".thread-body", ".firstpost", ".topicbody",
        ".message", ".cont", ".article-body", "article",
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            txt = el.get_text(" ", strip=True)
            if len(txt) > 80:
                return txt[:5000]
    ps = [p.get_text(" ", strip=True) for p in soup.find_all("p")
          if len(p.get_text(strip=True)) > 30]
    return " ".join(ps)[:5000]


def crawl_site(key, base, lang, country, accept_lang, finance_words, kw_re):
    print(f"\n========== {key.upper()} ({country}, {lang}) ==========")
    out = Path(f"data/raw/{key}_native_retry_{DAY}.jsonl")
    seen = set()
    if out.exists():
        for line in out.open(encoding="utf-8"):
            try: seen.add(json.loads(line)["id"])
            except Exception: pass

    boards = discover_boards(base, accept_lang, finance_words, key)
    if not boards:
        print(f"[{key}] no boards discovered -> skip")
        return 0

    written = 0
    for board_url in boards[:8]:  # cap 8 boards
        polite()
        print(f"\n  --- board: {board_url} ---")
        html = fetch(board_url, accept_lang, label=f"{key} board")
        if not html:
            continue
        threads = extract_threads(html, board_url, key)
        print(f"    threads found: {len(threads)}")
        for title, thread_url in threads[:25]:  # cap per board
            polite()
            thtml = fetch(thread_url, accept_lang, label=f"{key} thread")
            if not thtml:
                continue
            body = extract_body(thtml)
            text = title + " " + body
            if not kw_re.search(text):
                continue
            rid = md5_16(key, thread_url)
            if rid in seen:
                continue
            obj = {
                "id": rid, "raw_id": thread_url, "platform": key, "lang": lang,
                "title": title[:300], "body": body[:5000], "author": "",
                "url": thread_url, "country_hint": country,
                "matched_keyword": kw_re.search(text).group(0),
                "engagement": {"score": 0, "comments": 0, "views": None},
                "crawled_at": now_iso(),
            }
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
            seen.add(rid)
            written += 1
            print(f"      +1 ({title[:60]})")
    print(f"\n[{key}] DONE +{written}")
    return written


def main():
    grand = 0
    for site in SITES:
        try:
            grand += crawl_site(*site)
        except Exception as e:
            print(f"[{site[0]}] crawl err: {e}", file=sys.stderr)
    print(f"\n=== GRAND TOTAL: +{grand} new lines ===")


if __name__ == "__main__":
    main()
