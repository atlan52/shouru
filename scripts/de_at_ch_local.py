"""DE/AT/CH 德语圈本地站收入帖批量抓取（非 Reddit）。

选了 7 个站点：
  1. gehalt.de       — 30 个职业页 (https://www.gehalt.de/beruf/<职业>)
  2. kununu.com      — 公司工资页 (https://www.kununu.com/de/<company>/gehalt)
  3. lohnspiegel.de  — 工资数据库 + 文章页
  4. finanztip.de    — blog 首页 → 文章
  5. karrierebibel.de — RSS feed + /gehalt/ 主题
  6. finanzen.de     — 文章页 + 论坛
  7. wer-weiss-was.de — 老牌 Q&A，beruf-bildung / finanzen-recht-soziales

抓取逻辑：
  - 列表/RSS → 详情链接 → 详情 title + body
  - 关键词过滤（德语收入语义）
  - UA Chrome/124，Accept-Language de-DE，礼貌 1.5s
  - 4xx/5xx 跳过，cloudflare 挑战立即退站
  - 输出每站独立 JSONL；schema 同 r_mexico_native。

注意：subagent python 被 deny —— 主 agent 跑：
    .venv/bin/python scripts/de_at_ch_local.py
"""
import json, hashlib, re, time, random, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HDR = {
    "User-Agent": UA,
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
HDR_RSS = {
    "User-Agent": UA,
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
    "Accept": "application/rss+xml,application/xml;q=0.9,text/xml;q=0.8,*/*;q=0.5",
}

DAY = datetime.now().strftime("%Y%m%d")
RAW_DIR = Path("data/raw")

OUT_GEHALT       = RAW_DIR / f"gehalt_de_alt_native_{DAY}.jsonl"
OUT_KUNUNU       = RAW_DIR / f"kununu_alt_native_{DAY}.jsonl"
OUT_LOHNSPIEGEL  = RAW_DIR / f"lohnspiegel_native_{DAY}.jsonl"
OUT_FINANZTIP    = RAW_DIR / f"finanztip_native_{DAY}.jsonl"
OUT_KARRIEREB    = RAW_DIR / f"karrierebibel_native_{DAY}.jsonl"
OUT_FINANZEN_DE  = RAW_DIR / f"finanzen_de_native_{DAY}.jsonl"
OUT_WERWEISSWAS  = RAW_DIR / f"wer_weiss_was_native_{DAY}.jsonl"

# 德语收入/谋生关键词
KEYWORDS = [
    "gehalt", "einkommen", "lohn", "verdienst", "verdienen", "verdiene",
    "selbstständig", "selbständig", "freelance", "freiberufler", "freiberuflich",
    "rente", "pension", "frührente", "frühe rente", "fire", "finanzielle freiheit",
    "nebenjob", "nebeneinkünfte", "honorar", "bonus", "tantieme", "abfindung",
    "brutto", "netto", "monatslohn", "jahresgehalt", "stundenlohn",
    "mindestlohn", "tarifvertrag", "gehaltserhöhung",
    "elternzeit", "teilzeit", "minijob", "midijob",
    "aktienoptionen", "rsu", "esop", "dividende",
    "vermietung", "mieteinnahmen",
]
KW_RE = re.compile(r"|".join(re.escape(k) for k in KEYWORDS), re.I)


def md5_16(*p):
    return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def polite():
    time.sleep(random.uniform(1.3, 1.8))


def load_seen(path):
    seen = set()
    if path.exists():
        for line in path.open():
            try:
                seen.add(json.loads(line)["id"])
            except Exception:
                pass
    return seen


def looks_like_cloudflare(text, status):
    """Cloudflare challenge / bot detection markers."""
    if status in (403, 503, 429):
        return True
    head = (text or "")[:2000].lower()
    return ("cloudflare" in head and ("challenge" in head or "captcha" in head)) or \
           "checking your browser" in head or \
           "attention required" in head


def fetch(url, headers=None, timeout=22):
    """Returns (status, text) or (-1, '') on exception."""
    try:
        r = requests.get(url, headers=headers or HDR, timeout=timeout)
        return r.status_code, r.text
    except Exception as e:
        return -1, f"__EXC__{e}"


def matches_kw(text):
    if not text:
        return ""
    m = KW_RE.search(text)
    return m.group(0) if m else ""


def main_text(soup, fallback_chars=4500):
    """Pick best main-content node: <article> > <main> > body."""
    el = (soup.select_one("article")
          or soup.select_one("main")
          or soup.select_one("[role=main]")
          or soup.select_one("[itemprop=articleBody]")
          or soup.body)
    if el is None:
        return ""
    # strip nav/footer/aside
    for bad in el.select("nav, footer, aside, script, style, form, .cookie, .newsletter, .ads, .advertisement"):
        bad.decompose()
    return el.get_text(" ", strip=True)[:fallback_chars]


def page_title(soup):
    h = soup.select_one("h1") or soup.select_one("title")
    return h.get_text(" ", strip=True) if h else ""


# ----------------------------------------------------------------------------
# 1. gehalt.de — 30 个职业页
# ----------------------------------------------------------------------------
GEHALT_BERUFE = [
    "softwareentwickler", "softwareingenieur", "data-scientist",
    "lehrer", "grundschullehrer", "erzieher",
    "arzt", "facharzt", "krankenschwester", "krankenpfleger", "altenpfleger",
    "ingenieur", "maschinenbauingenieur", "elektroingenieur", "bauingenieur",
    "jurist", "rechtsanwalt", "steuerberater",
    "bankkaufmann", "versicherungskaufmann", "buchhalter", "controller",
    "marketing-manager", "produktmanager", "projektmanager",
    "verkäufer", "vertriebsmitarbeiter",
    "polizist", "feuerwehrmann", "soldat", "pilot",
]


def crawl_gehalt():
    """gehalt.de/beruf/<beruf>"""
    seen = load_seen(OUT_GEHALT)
    n = 0
    for beruf in GEHALT_BERUFE:
        url = f"https://www.gehalt.de/beruf/{beruf}"
        status, text = fetch(url)
        if status != 200:
            print(f"[gehalt] {beruf} status={status}")
            polite()
            continue
        if looks_like_cloudflare(text, status):
            print(f"[gehalt] cloudflare on {beruf} — abort site")
            return n
        soup = BeautifulSoup(text, "html.parser")
        title = page_title(soup)
        body = main_text(soup, fallback_chars=4500)
        kw = matches_kw(title + " " + body)
        if not kw:
            # gehalt 页面普遍含 Gehalt 字眼；如果没匹配跳过
            print(f"[gehalt] {beruf} no kw match")
            polite()
            continue
        rid = md5_16("gehalt_de_alt", beruf)
        if rid in seen:
            polite(); continue
        obj = {
            "id": rid,
            "raw_id": beruf,
            "platform": "gehalt_de_alt",
            "lang": "de",
            "title": title or f"Gehalt {beruf}",
            "body": body,
            "author": "",
            "url": url,
            "country_hint": "DE",
            "matched_keyword": kw,
            "engagement": {"score": 0, "comments": 0, "views": None},
            "beruf": beruf,
            "crawled_at": now_iso(),
        }
        append(OUT_GEHALT, obj); seen.add(rid); n += 1
        print(f"[gehalt] {beruf} ok len={len(body)} total={n}")
        polite()
    print(f"[gehalt] DONE +{n}")
    return n


# ----------------------------------------------------------------------------
# 2. kununu.com — 50 公司
# ----------------------------------------------------------------------------
KUNUNU_COMPANIES = [
    "siemens", "sap", "bosch", "bmw-group", "daimler", "volkswagen", "audi",
    "porsche", "deutsche-bank", "commerzbank", "allianz", "munich-re",
    "deutsche-telekom", "telefonica-deutschland", "vodafone-deutschland",
    "lufthansa", "deutsche-bahn", "deutsche-post-dhl", "thyssenkrupp",
    "henkel", "beiersdorf", "adidas", "puma", "metro-ag", "rewe-group",
    "edeka", "lidl", "aldi-sued", "aldi-nord", "kaufland", "otto-group",
    "zalando", "hellofresh", "delivery-hero", "n26", "trade-republic",
    "celonis", "personio", "auto1-group", "wirecard", "rocket-internet",
    "sixt", "fielmann", "douglas", "tchibo", "obi", "media-markt",
    "bayer", "basf", "merck-kgaa", "boehringer-ingelheim",
]


def parse_kununu_salaries(soup):
    """Try to extract salary line items from kununu /gehalt page."""
    items = []
    # generic: every list item / row that has '€' + 'Brutto' or 'Jahr'
    for el in soup.select("li, tr, [class*=salary], [class*=Gehalt]"):
        t = el.get_text(" ", strip=True)
        if not t or len(t) > 400:
            continue
        if ("€" in t or "EUR" in t) and ("brutto" in t.lower() or "jahr" in t.lower() or "monat" in t.lower()):
            items.append(t)
    # de-dup preserving order
    out = []
    seen_t = set()
    for t in items:
        if t in seen_t: continue
        seen_t.add(t)
        out.append(t)
    return out[:30]


def crawl_kununu():
    seen = load_seen(OUT_KUNUNU)
    n = 0
    cf_streak = 0
    for company in KUNUNU_COMPANIES:
        url = f"https://www.kununu.com/de/{company}/gehalt"
        status, text = fetch(url)
        if looks_like_cloudflare(text, status):
            cf_streak += 1
            print(f"[kununu] cloudflare/blocked on {company} status={status} streak={cf_streak}")
            if cf_streak >= 3:
                print("[kununu] 3x blocked in a row — abort site")
                return n
            polite(); continue
        cf_streak = 0
        if status != 200:
            print(f"[kununu] {company} status={status}")
            polite(); continue
        soup = BeautifulSoup(text, "html.parser")
        title = page_title(soup)
        body = main_text(soup, fallback_chars=4500)
        salaries = parse_kununu_salaries(soup)
        if salaries:
            body = "\n".join(salaries[:20]) + "\n\n" + body
            body = body[:5000]
        kw = matches_kw(title + " " + body)
        if not kw and not salaries:
            print(f"[kununu] {company} no kw / no salaries")
            polite(); continue
        rid = md5_16("kununu_alt", company)
        if rid in seen:
            polite(); continue
        obj = {
            "id": rid,
            "raw_id": company,
            "platform": "kununu_alt",
            "lang": "de",
            "title": title or f"Gehälter {company}",
            "body": body,
            "author": company,
            "url": url,
            "country_hint": "DE",
            "matched_keyword": kw or "gehalt",
            "engagement": {"score": 0, "comments": 0, "views": None},
            "empresa": company,
            "salaries_extracted": salaries[:10],
            "crawled_at": now_iso(),
        }
        append(OUT_KUNUNU, obj); seen.add(rid); n += 1
        print(f"[kununu] {company} ok len={len(body)} sal={len(salaries)} total={n}")
        polite()
    print(f"[kununu] DONE +{n}")
    return n


# ----------------------------------------------------------------------------
# 3. lohnspiegel.de
# ----------------------------------------------------------------------------
LOHNSPIEGEL_PATHS = [
    "/main/lohncheck",
    "/main/main",
    "/main/lohnspiegel-aktuell",
    "/main/lohn-und-gehalt",
    "/main/sonderzahlungen",
    "/main/arbeitszeit",
    "/main/loehne-und-gehaelter-im-vergleich",
]
# Plus a few discoverable berufs sub-pages
LOHNSPIEGEL_PROFS = [
    "softwareentwickler", "ingenieur", "lehrer", "krankenpfleger",
    "verkaeufer", "buchhalter", "elektriker", "altenpfleger",
]


def crawl_lohnspiegel():
    seen = load_seen(OUT_LOHNSPIEGEL)
    n = 0
    base = "https://www.lohnspiegel.de"
    paths = list(LOHNSPIEGEL_PATHS)
    paths += [f"/main/lohncheck/beruf/{p}" for p in LOHNSPIEGEL_PROFS]
    paths += [f"/main/loehne-und-gehaelter-im-vergleich/{p}" for p in LOHNSPIEGEL_PROFS]
    for p in paths:
        url = base + p
        status, text = fetch(url)
        if looks_like_cloudflare(text, status):
            print(f"[lohnspiegel] cloudflare on {p} — abort site")
            return n
        if status != 200:
            print(f"[lohnspiegel] {p} status={status}")
            polite(); continue
        soup = BeautifulSoup(text, "html.parser")
        title = page_title(soup)
        body = main_text(soup, fallback_chars=4500)
        kw = matches_kw(title + " " + body)
        if not kw:
            print(f"[lohnspiegel] {p} no kw match")
            polite(); continue
        rid = md5_16("lohnspiegel", p)
        if rid in seen:
            polite(); continue
        obj = {
            "id": rid,
            "raw_id": p,
            "platform": "lohnspiegel",
            "lang": "de",
            "title": title or p,
            "body": body,
            "author": "",
            "url": url,
            "country_hint": "DE",
            "matched_keyword": kw,
            "engagement": {"score": 0, "comments": 0, "views": None},
            "crawled_at": now_iso(),
        }
        append(OUT_LOHNSPIEGEL, obj); seen.add(rid); n += 1
        print(f"[lohnspiegel] {p} ok len={len(body)} total={n}")
        polite()
    print(f"[lohnspiegel] DONE +{n}")
    return n


# ----------------------------------------------------------------------------
# 4. finanztip.de — blog index → articles
# ----------------------------------------------------------------------------
def discover_links(html, base, allow_re):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen_u = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("#"): continue
        u = urljoin(base, href)
        if not allow_re.search(u): continue
        # strip fragment
        u = u.split("#")[0]
        if u in seen_u: continue
        seen_u.add(u)
        out.append(u)
    return out


def crawl_finanztip():
    seen = load_seen(OUT_FINANZTIP)
    n = 0
    base = "https://www.finanztip.de"
    seeds = [
        "/blog/",
        "/blog/page/2/",
        "/blog/page/3/",
        "/gehalt/",
        "/altersvorsorge/",
        "/selbststaendigkeit/",
    ]
    article_re = re.compile(r"finanztip\.de/(blog|gehalt|altersvorsorge|selbststaendigkeit|rente|investmentfonds|aktien|geldanlage)/[a-z0-9-]+/?$")
    candidates = []
    for s in seeds:
        url = base + s
        status, text = fetch(url)
        if looks_like_cloudflare(text, status):
            print(f"[finanztip] cloudflare on {s} — abort")
            return n
        if status != 200:
            print(f"[finanztip] index {s} status={status}")
            polite(); continue
        links = discover_links(text, base, article_re)
        candidates += links
        print(f"[finanztip] index {s}: +{len(links)} links")
        polite()
    # de-dup, cap
    uniq = []
    seen_u = set()
    for u in candidates:
        if u in seen_u: continue
        seen_u.add(u)
        uniq.append(u)
    uniq = uniq[:60]
    for url in uniq:
        status, text = fetch(url)
        if looks_like_cloudflare(text, status):
            print("[finanztip] cloudflare mid-crawl — abort")
            return n
        if status != 200:
            polite(); continue
        soup = BeautifulSoup(text, "html.parser")
        title = page_title(soup)
        body = main_text(soup, fallback_chars=4500)
        kw = matches_kw(title + " " + body)
        if not kw:
            polite(); continue
        slug = urlparse(url).path.strip("/")
        rid = md5_16("finanztip", slug)
        if rid in seen:
            polite(); continue
        obj = {
            "id": rid,
            "raw_id": slug,
            "platform": "finanztip",
            "lang": "de",
            "title": title,
            "body": body,
            "author": "",
            "url": url,
            "country_hint": "DE",
            "matched_keyword": kw,
            "engagement": {"score": 0, "comments": 0, "views": None},
            "crawled_at": now_iso(),
        }
        append(OUT_FINANZTIP, obj); seen.add(rid); n += 1
        if n % 5 == 0:
            print(f"[finanztip] running total={n}")
        polite()
    print(f"[finanztip] DONE +{n}")
    return n


# ----------------------------------------------------------------------------
# 5. karrierebibel.de — RSS + /gehalt/ topic listing
# ----------------------------------------------------------------------------
def parse_rss_items(text):
    """Return list of (title, link, description)."""
    out = []
    try:
        root = ET.fromstring(text)
    except Exception:
        return out
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        if link:
            out.append((title, link, desc))
    return out


def crawl_karrierebibel():
    seen = load_seen(OUT_KARRIEREB)
    n = 0
    base = "https://karrierebibel.de"
    # RSS
    feed_url = base + "/feed/"
    status, text = fetch(feed_url, headers=HDR_RSS)
    items = []
    if status == 200 and not looks_like_cloudflare(text, status):
        items = parse_rss_items(text)
        print(f"[karrierebibel] feed items={len(items)}")
    elif looks_like_cloudflare(text, status):
        print("[karrierebibel] feed cloudflare — abort")
        return n
    else:
        print(f"[karrierebibel] feed status={status}")
    polite()
    # /gehalt/ topic listing
    candidates = [(t, l) for (t, l, _) in items]
    for path in ["/gehalt/", "/karriere/", "/beruf/"]:
        u = base + path
        status, text = fetch(u)
        if status == 200 and not looks_like_cloudflare(text, status):
            allow_re = re.compile(r"karrierebibel\.de/[a-z0-9-]+/?$")
            links = discover_links(text, base, allow_re)
            candidates += [("", l) for l in links]
            print(f"[karrierebibel] topic {path}: +{len(links)} links")
        polite()
    # de-dup
    uniq = []
    seen_u = set()
    for t, l in candidates:
        if not l or l in seen_u: continue
        seen_u.add(l)
        uniq.append((t, l))
    uniq = uniq[:80]
    for t0, url in uniq:
        status, text = fetch(url)
        if looks_like_cloudflare(text, status):
            print("[karrierebibel] cloudflare mid — abort")
            return n
        if status != 200:
            polite(); continue
        soup = BeautifulSoup(text, "html.parser")
        title = page_title(soup) or t0
        body = main_text(soup, fallback_chars=4500)
        kw = matches_kw(title + " " + body)
        if not kw:
            polite(); continue
        slug = urlparse(url).path.strip("/")
        rid = md5_16("karrierebibel", slug)
        if rid in seen:
            polite(); continue
        obj = {
            "id": rid,
            "raw_id": slug,
            "platform": "karrierebibel",
            "lang": "de",
            "title": title,
            "body": body,
            "author": "",
            "url": url,
            "country_hint": "DE",
            "matched_keyword": kw,
            "engagement": {"score": 0, "comments": 0, "views": None},
            "crawled_at": now_iso(),
        }
        append(OUT_KARRIEREB, obj); seen.add(rid); n += 1
        if n % 5 == 0:
            print(f"[karrierebibel] running total={n}")
        polite()
    print(f"[karrierebibel] DONE +{n}")
    return n


# ----------------------------------------------------------------------------
# 6. finanzen.de — articles + forum (discover via index)
# ----------------------------------------------------------------------------
def crawl_finanzen_de():
    seen = load_seen(OUT_FINANZEN_DE)
    n = 0
    base = "https://www.finanzen.de"
    seeds = [
        "/news",
        "/forum",
        "/forum/altersvorsorge",
        "/forum/geldanlage",
        "/forum/versicherungen",
        "/altersvorsorge",
        "/geldanlage",
        "/karriere",
    ]
    allow_re = re.compile(r"finanzen\.de/(news|forum|altersvorsorge|geldanlage|karriere|versicherungen|rente)/[a-z0-9-]+", re.I)
    candidates = []
    for s in seeds:
        url = base + s
        status, text = fetch(url)
        if looks_like_cloudflare(text, status):
            print(f"[finanzen.de] cloudflare on {s} — abort")
            return n
        if status != 200:
            print(f"[finanzen.de] index {s} status={status}")
            polite(); continue
        links = discover_links(text, base, allow_re)
        candidates += links
        print(f"[finanzen.de] index {s}: +{len(links)} links")
        polite()
    uniq = []
    seen_u = set()
    for u in candidates:
        if u in seen_u: continue
        seen_u.add(u)
        uniq.append(u)
    uniq = uniq[:60]
    for url in uniq:
        status, text = fetch(url)
        if looks_like_cloudflare(text, status):
            print("[finanzen.de] cloudflare mid — abort")
            return n
        if status != 200:
            polite(); continue
        soup = BeautifulSoup(text, "html.parser")
        title = page_title(soup)
        body = main_text(soup, fallback_chars=4500)
        kw = matches_kw(title + " " + body)
        if not kw:
            polite(); continue
        slug = urlparse(url).path.strip("/")
        rid = md5_16("finanzen_de", slug)
        if rid in seen:
            polite(); continue
        obj = {
            "id": rid,
            "raw_id": slug,
            "platform": "finanzen_de",
            "lang": "de",
            "title": title,
            "body": body,
            "author": "",
            "url": url,
            "country_hint": "DE",
            "matched_keyword": kw,
            "engagement": {"score": 0, "comments": 0, "views": None},
            "crawled_at": now_iso(),
        }
        append(OUT_FINANZEN_DE, obj); seen.add(rid); n += 1
        if n % 5 == 0:
            print(f"[finanzen.de] running total={n}")
        polite()
    print(f"[finanzen.de] DONE +{n}")
    return n


# ----------------------------------------------------------------------------
# 7. wer-weiss-was.de — Q&A
# ----------------------------------------------------------------------------
def crawl_wwwde():
    seen = load_seen(OUT_WERWEISSWAS)
    n = 0
    base = "https://www.wer-weiss-was.de"
    seeds = [
        "/c/finanzen-recht-soziales",
        "/c/finanzen-recht-soziales?page=2",
        "/c/finanzen-recht-soziales?page=3",
        "/c/beruf-bildung",
        "/c/beruf-bildung?page=2",
        "/c/beruf-bildung?page=3",
    ]
    allow_re = re.compile(r"wer-weiss-was\.de/t/[a-z0-9-]+/\d+", re.I)
    candidates = []
    for s in seeds:
        url = base + s
        status, text = fetch(url)
        if looks_like_cloudflare(text, status):
            print(f"[wwwde] cloudflare on {s} — abort")
            return n
        if status != 200:
            print(f"[wwwde] index {s} status={status}")
            polite(); continue
        links = discover_links(text, base, allow_re)
        candidates += links
        print(f"[wwwde] index {s}: +{len(links)} links")
        polite()
    uniq = []
    seen_u = set()
    for u in candidates:
        if u in seen_u: continue
        seen_u.add(u)
        uniq.append(u)
    uniq = uniq[:80]
    for url in uniq:
        status, text = fetch(url)
        if looks_like_cloudflare(text, status):
            print("[wwwde] cloudflare mid — abort")
            return n
        if status != 200:
            polite(); continue
        soup = BeautifulSoup(text, "html.parser")
        title = page_title(soup)
        # Discourse-style: posts under .topic-body / .cooked
        posts = soup.select(".cooked, [itemprop=articleBody], .topic-body")
        if posts:
            body = " \n ".join(p.get_text(" ", strip=True) for p in posts[:5])[:4500]
        else:
            body = main_text(soup, fallback_chars=4500)
        kw = matches_kw(title + " " + body)
        if not kw:
            polite(); continue
        m = re.search(r"/t/([a-z0-9-]+/\d+)", url)
        slug = m.group(1) if m else urlparse(url).path
        rid = md5_16("wer_weiss_was", slug)
        if rid in seen:
            polite(); continue
        obj = {
            "id": rid,
            "raw_id": slug,
            "platform": "wer_weiss_was",
            "lang": "de",
            "title": title,
            "body": body,
            "author": "",
            "url": url,
            "country_hint": "DE",
            "matched_keyword": kw,
            "engagement": {"score": 0, "comments": 0, "views": None},
            "crawled_at": now_iso(),
        }
        append(OUT_WERWEISSWAS, obj); seen.add(rid); n += 1
        if n % 5 == 0:
            print(f"[wwwde] running total={n}")
        polite()
    print(f"[wwwde] DONE +{n}")
    return n


# ----------------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------------
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
    sites = sys.argv[1:] or [
        "gehalt", "kununu", "lohnspiegel", "finanztip",
        "karrierebibel", "finanzen_de", "wwwde",
    ]
    counts = {}
    if "gehalt"        in sites: counts["gehalt"]        = crawl_gehalt()
    if "kununu"        in sites: counts["kununu"]        = crawl_kununu()
    if "lohnspiegel"   in sites: counts["lohnspiegel"]   = crawl_lohnspiegel()
    if "finanztip"     in sites: counts["finanztip"]     = crawl_finanztip()
    if "karrierebibel" in sites: counts["karrierebibel"] = crawl_karrierebibel()
    if "finanzen_de"   in sites: counts["finanzen_de"]   = crawl_finanzen_de()
    if "wwwde"         in sites: counts["wwwde"]         = crawl_wwwde()

    print("\n" + "=" * 60)
    print("SAMPLES")
    print("=" * 60)
    f_lines = {}
    f_lines["gehalt_de_alt"] = print_samples(OUT_GEHALT,      "gehalt_de_alt")
    f_lines["kununu_alt"]    = print_samples(OUT_KUNUNU,      "kununu_alt")
    f_lines["lohnspiegel"]   = print_samples(OUT_LOHNSPIEGEL, "lohnspiegel")
    f_lines["finanztip"]     = print_samples(OUT_FINANZTIP,   "finanztip")
    f_lines["karrierebibel"] = print_samples(OUT_KARRIEREB,   "karrierebibel")
    f_lines["finanzen_de"]   = print_samples(OUT_FINANZEN_DE, "finanzen_de")
    f_lines["wer_weiss_was"] = print_samples(OUT_WERWEISSWAS, "wer_weiss_was")

    print("\n" + "=" * 60)
    print("TOTALS (this run)")
    for k, v in counts.items():
        print(f"  {k:14s}: +{v}")
    print("\nFILE LINE COUNTS")
    for k, v in f_lines.items():
        print(f"  {k:14s}: {v}")
    total_new = sum(counts.values())
    print(f"\n=== TOTAL NEW THIS RUN: +{total_new} ===")
