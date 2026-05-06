"""英语国家主流财经报 RSS — 收入相关报道（人物访谈 / 薪资调查 / 个税专题）。

UK / US / CA / AU / NZ / IE / IN(英语) / ZA。
单输出文件 data/raw/anglo_news_rss_native_<DAY>.jsonl，
platform=rss_<feedname_short>，country_hint 按域名判断。
"""
import json, hashlib, time, random, re, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

DAY = datetime.now().strftime("%Y%m%d")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
TIMEOUT = 25
SLEEP = (1.0, 1.5)
OUT = Path(f"data/raw/anglo_news_rss_native_{DAY}.jsonl")

# 关键词（whole-word 优先，部分长 token 直接 substring）
KW_RE = re.compile(
    r"\b("
    r"salary|salaries|wage|wages|earn(?:s|ed|ing|ings)?|income|paycheck|"
    r"FIRE|freelance(?:r|rs|ing)?|gig\s+(?:work|economy|worker)|side\s+hustle|"
    r"pension(?:s|er)?|retire(?:d|ment)?|take[-\s]?home|gross\s+(?:pay|income|salary)|"
    r"net\s+pay|bonus(?:es)?|package|CTC|lakh(?:s)?\s+per\s+month|lakh(?:s)?\s+a\s+month|"
    r"raise|pay\s+raise|pay\s+rise|cost[-\s]of[-\s]living|COL\s+adjusted"
    r")\b",
    re.IGNORECASE,
)

# 选 12-15 feed: 跨 8 国, 偏向高产出主流大报
FEEDS = [
    # UK
    ("rss_guardian_money",      "https://www.theguardian.com/uk/money/rss",
        [".article-body-commercial-selector", "[data-component='text-block']", "article", ".content__article-body"]),
    ("rss_guardian_careers",    "https://www.theguardian.com/money/work-careers/rss",
        [".article-body-commercial-selector", "[data-component='text-block']", "article", ".content__article-body"]),
    ("rss_bbc_business",        "https://www.bbc.co.uk/news/business/rss.xml",
        ["article", "[data-component='text-block']", ".ssrcss-11r1m41-RichTextComponentWrapper"]),
    ("rss_thisismoney",         "https://www.thisismoney.co.uk/news/index.rss",
        ["article", "[itemprop='articleBody']", ".article-text"]),

    # US
    ("rss_nyt_yourmoney",       "https://rss.nytimes.com/services/xml/rss/nyt/YourMoney.xml",
        ["article", "section[name='articleBody']", ".StoryBodyCompanionColumn"]),
    ("rss_npr_business",        "https://feeds.npr.org/1006/rss.xml",
        ["#storytext", "article", ".storytext"]),
    ("rss_cnbc_pf",             "https://www.cnbc.com/id/10000664/device/rss/rss.html",
        ["[data-module='ArticleBody']", ".ArticleBody-articleBody", "article", ".group"]),

    # CA
    ("rss_cbc_business",        "https://www.cbc.ca/cmlink/rss-business",
        [".story", "article", ".storyWrapper"]),
    ("rss_financialpost",       "https://financialpost.com/feed",
        ["article", ".article-content", ".story-v2-content"]),

    # AU
    ("rss_abc_business",        "https://www.abc.net.au/news/feed/2942460/rss.xml",
        ["article", "[data-component='Body']", ".comp-rich-text-article-body"]),
    ("rss_smh_business",        "https://www.smh.com.au/rss/business.xml",
        ["article", "[itemprop='articleBody']", ".article__body"]),

    # NZ
    ("rss_nzherald_business",   "https://www.nzherald.co.nz/rss/business/",
        ["article", ".article__body", ".story-content"]),
    ("rss_stuff_business",      "https://www.stuff.co.nz/business/rss",
        ["article", ".article-body", ".sics-component__story"]),

    # IE
    ("rss_thejournal_business", "https://www.thejournal.ie/business/rss/",
        ["article", ".article-body", "#js-articleBody"]),

    # IN
    ("rss_toi_business",        "https://timesofindia.indiatimes.com/rssfeeds/1898055.cms",
        ["article", "._s30J", ".ga-headlines", ".Normal"]),
    ("rss_livemint_money",      "https://www.livemint.com/rss/money",
        ["article", ".storyParagraph", ".mainArea"]),

    # ZA
    ("rss_news24_business",     "https://www.news24.com/news24/Business/rss",
        ["article", ".article__body", ".article-body"]),
    ("rss_mybroadband",         "https://mybroadband.co.za/news/feed/",
        ["article", ".entry-content", ".td-post-content"]),
]


def domain_country(host: str) -> str:
    h = (host or "").lower()
    if h.endswith(".co.uk") or "bbc.co.uk" in h or "thisismoney.co.uk" in h or "theguardian.com" in h:
        return "GB"
    if h.endswith(".com.au") or "abc.net.au" in h or "afr.com" in h:
        return "AU"
    if h.endswith(".co.nz") or "stuff.co.nz" in h or "nzherald.co.nz" in h:
        return "NZ"
    if h.endswith(".ca") or "cbc.ca" in h or "financialpost.com" in h or "theglobeandmail.com" in h:
        return "CA"
    if h.endswith(".ie") or "irishtimes.com" in h or "thejournal.ie" in h:
        return "IE"
    if "indiatimes.com" in h or "livemint.com" in h or "thehindu.com" in h:
        return "IN"
    if "news24.com" in h or "mybroadband.co.za" in h or h.endswith(".co.za"):
        return "ZA"
    return "US"


COUNTRY_LANG = {
    "GB": "en-GB,en;q=0.9",
    "US": "en-US,en;q=0.9",
    "CA": "en-CA,en;q=0.9,fr-CA;q=0.5",
    "AU": "en-AU,en;q=0.9",
    "NZ": "en-NZ,en;q=0.9",
    "IE": "en-IE,en-GB;q=0.9,en;q=0.8",
    "IN": "en-IN,en;q=0.9,hi;q=0.5",
    "ZA": "en-ZA,en;q=0.9",
}


def md5_16(*p): return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]
def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def polite(): time.sleep(random.uniform(*SLEEP))


def hdr(country: str) -> dict:
    return {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": COUNTRY_LANG.get(country, "en-US,en;q=0.9"),
    }


def fetch(url: str, country: str, label: str = "") -> str | None:
    try:
        r = requests.get(url, headers=hdr(country), timeout=TIMEOUT, allow_redirects=True)
    except requests.exceptions.SSLError as e:
        print(f"  [{label}] SSL err: {e}", file=sys.stderr); return None
    except Exception as e:
        print(f"  [{label}] err: {e}", file=sys.stderr); return None
    if r.status_code >= 400:
        print(f"  [{label}] status={r.status_code}", file=sys.stderr); return None
    return r.text


def parse_rss(xml: str):
    """try lxml-xml first, fallback to html.parser."""
    soup = None
    for parser in ("xml", "lxml-xml", "html.parser"):
        try:
            soup = BeautifulSoup(xml, parser)
            if soup.find("item") or soup.find("entry"):
                break
        except Exception:
            continue
    if soup is None:
        return []
    items = soup.find_all("item") or soup.find_all("entry")
    out = []
    for it in items:
        t = it.find("title")
        l = it.find("link")
        g = it.find("guid") or it.find("id")
        d = it.find("description") or it.find("summary") or it.find("content")
        a = it.find("author") or it.find("dc:creator")
        p = it.find("pubDate") or it.find("published") or it.find("dc:date")
        title = t.get_text(strip=True) if t else ""
        # link can be element with href (atom) or text (rss)
        link = ""
        if l:
            link = (l.get("href") or "").strip()
            if not link:
                link = l.get_text(strip=True)
        guid = (g.get_text(strip=True) if g else "") or link
        desc = d.get_text(" ", strip=True) if d else ""
        author = a.get_text(strip=True) if a else ""
        pub = p.get_text(strip=True) if p else ""
        if title and link:
            out.append({
                "raw_id": guid, "title": title, "summary": desc,
                "link": link, "author": author, "pub": pub,
            })
    return out


def fetch_body(url: str, sel: list[str], country: str) -> str:
    html = fetch(url, country, label=f"body {urlparse(url).netloc}")
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "aside", "header", "footer", "form", "iframe"]):
        tag.decompose()
    for s in sel:
        try:
            el = soup.select_one(s)
        except Exception:
            el = None
        if el:
            txt = el.get_text(" ", strip=True)
            if len(txt) > 100:
                return txt[:5000]
    # fallback: collect <p> with ≥30 chars
    ps = [p.get_text(" ", strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) >= 30]
    return " ".join(ps)[:5000]


def append(obj: dict):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def load_seen() -> set:
    seen = set()
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            try: seen.add(json.loads(line)["id"])
            except Exception: pass
    return seen


def crawl():
    seen = load_seen()
    summary = []
    grand_items = grand_matched = grand_written = 0

    for name, feed_url, sel in FEEDS:
        host = urlparse(feed_url).netloc
        country = domain_country(host)
        print(f"\n--- {name} | {host} | {country} ---")
        xml = fetch(feed_url, country, label=name)
        if not xml:
            summary.append((name, country, 0, 0, 0))
            continue
        items = parse_rss(xml)
        print(f"  items={len(items)}")
        matched = 0
        written = 0
        for it in items:
            text = (it["title"] or "") + " " + (it["summary"] or "")
            m = KW_RE.search(text)
            if not m:
                continue
            matched += 1
            article_host = urlparse(it["link"]).netloc or host
            article_country = domain_country(article_host)
            rid = md5_16(name, it["raw_id"])
            if rid in seen:
                continue
            body = fetch_body(it["link"], sel, article_country) or it["summary"]
            if not body or len(body) < 80:
                polite()
                continue
            obj = {
                "id": rid,
                "raw_id": it["raw_id"],
                "platform": name,
                "lang": "en",
                "title": it["title"][:300],
                "body": body[:5000],
                "author": it["author"],
                "url": it["link"],
                "country_hint": article_country,
                "matched_keyword": m.group(0),
                "engagement": {"score": 0, "comments": 0, "views": None},
                "crawled_at": now_iso(),
                "pub": it.get("pub", ""),
            }
            append(obj)
            seen.add(rid)
            written += 1
            polite()
        print(f"  matched={matched} written={written}")
        summary.append((name, country, len(items), matched, written))
        grand_items += len(items)
        grand_matched += matched
        grand_written += written
        polite()

    final = sum(1 for _ in OUT.open(encoding="utf-8")) if OUT.exists() else 0
    print("\n========== SUMMARY ==========")
    print(f"{'feed':<30}{'cc':<5}{'items':>7}{'matched':>9}{'written':>9}")
    for n, c, i, m, w in summary:
        print(f"{n:<30}{c:<5}{i:>7}{m:>9}{w:>9}")
    print(f"\nGRAND items={grand_items} matched={grand_matched} written={grand_written}")
    print(f"FILE: {OUT} TOTAL_LINES={final}")


if __name__ == "__main__":
    crawl()
