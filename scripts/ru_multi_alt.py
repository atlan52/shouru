"""ru_multi_alt — 多源俄语 RSS 收入帖抓取（VC.ru / Habr / DTF / Banki / RBC / Cnews / Sravni）

Strategy:
  - 每个 feed 拉 RSS 列表 → 解析 <item> 的 title/description/link/pubDate。
  - 用俄语收入关键词过滤（зарплата, доход, заработ, оклад, фриланс …）。
  - 命中后 GET 详情页正文，按域名走站点专属 selector + 通用 <p> fallback。
  - schema 与 r_mexico_native 一致，单文件输出 ru_multi_alt_native_<DAY>.jsonl，
    platform 字段 rss_<source>。
  - polite 1.5s / 4xx-5xx skip / UA: ru-RU。

Don't run this from inside the subagent — main agent will execute via .venv/bin/python.
"""
import hashlib
import html as html_mod
import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HDR = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
}
TIMEOUT = 25
SLEEP_MIN, SLEEP_MAX = 1.2, 1.8

DAY = datetime.now().strftime("%Y%m%d")
OUT_PATH = Path(
    f"/Users/jan/sen/code/spider/shouru/data/raw/ru_multi_alt_native_{DAY}.jsonl"
)

# Feed list — each entry is (platform_tag, feed_url, kind)
# kind = "rss" 现在全是 RSS/Atom；以后扩 HTML 列表加 "html" 即可。
FEEDS: list[tuple[str, str, str]] = [
    ("rss_vc",     "https://vc.ru/rss/all",                                "rss"),
    ("rss_habr",   "https://habr.com/ru/rss/articles/?fl=ru",              "rss"),
    ("rss_dtf",    "https://dtf.ru/rss/all",                               "rss"),
    ("rss_banki",  "https://www.banki.ru/news/rss/",                       "rss"),
    ("rss_rbc",    "https://rssexport.rbc.ru/rbcnews/news/30/full.rss",    "rss"),
    ("rss_cnews",  "https://www.cnews.ru/inc/rss/news.xml",                "rss"),
    ("rss_sravni", "https://www.sravni.ru/text/rss/",                      "rss"),
]

# Russian income / earnings keywords. Stem-style — we substring-match on lowered
# text so "зарплата", "зарплаты", "зарплату" all match "зарплат".
INCOME_KEYWORDS = [
    "зарплат",         # зарплата
    "доход",           # доход / доходы
    "заработ",         # заработок / зарабатывать
    "оклад",
    "получк",          # получка
    "фриланс",
    "подработ",        # подработка
    "ваканс",          # вакансия
    "программист зарплата",
    "инженер зарплата",
    "fire",            # FIRE — financial independence retire early
    "пассивный",       # пассивный доход
    "пенси",           # пенсия / пенсионный
    "накопл",          # накопления
    "инвести",         # инвестиции
]

# Per-domain main-content selectors. First hit wins; if none match we fall
# back to <article> → joined <p>.
ARTICLE_SELECTORS: dict[str, list[str]] = {
    "vc.ru":          ["div.content--article", "article", "div.l-content"],
    "habr.com":       ["div.tm-article-body", "div.article-formatted-body", "article"],
    "dtf.ru":         ["div.content--article", "div.content", "article"],
    "banki.ru":       ["div.text-content", "div.article__text", "div.l-news__content", "article"],
    "rbc.ru":         ["div.article__text", "div.article__content", "article"],
    "cnews.ru":       ["div.news_container", "div.article-text", "article"],
    "sravni.ru":      ["div[data-qa='article-content']", "article", "main"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def md5_16(*parts: str) -> str:
    return hashlib.md5("|".join(map(str, parts)).encode("utf-8")).hexdigest()[:16]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def polite() -> None:
    time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))


def load_seen(path: Path) -> set[str]:
    seen: set[str] = set()
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    seen.add(json.loads(line)["id"])
                except Exception:
                    pass
    return seen


def append(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def fetch(url: str) -> str | None:
    """GET url; return text on 2xx, else None. 4xx/5xx skip silently."""
    try:
        r = requests.get(url, headers=HDR, timeout=TIMEOUT)
    except Exception as e:
        print(f"  [fetch err] {url}: {e}", file=sys.stderr)
        return None
    if r.status_code >= 400:
        print(f"  [skip] status={r.status_code} {url}", file=sys.stderr)
        return None
    # ensure decoded text — RSS feeds sometimes leave encoding empty
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding or "utf-8"
    return r.text


# ---------------------------------------------------------------------------
# RSS parsing
# ---------------------------------------------------------------------------

# Common RSS/Atom namespace map — strip on access.
_NS_RE = re.compile(r"\{[^}]+\}")


def _localname(tag: str) -> str:
    return _NS_RE.sub("", tag)


def _strip_tags(s: str) -> str:
    if not s:
        return ""
    s = html_mod.unescape(s)
    # crude but enough for description fields
    return BeautifulSoup(s, "html.parser").get_text(" ", strip=True)


def parse_rss(xml_text: str) -> list[dict]:
    """Parse an RSS or Atom feed into a list of dicts.

    Returns: [{title, link, description, author, pubDate}]
    """
    items: list[dict] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"  [rss parse err] {e}", file=sys.stderr)
        return items

    # RSS 2.0:  rss > channel > item*
    # Atom:     feed > entry*
    # We accept either, walking by localname.
    item_tag_names = {"item", "entry"}
    for el in root.iter():
        if _localname(el.tag) not in item_tag_names:
            continue
        rec: dict[str, str] = {}
        for child in el:
            ln = _localname(child.tag)
            if ln == "title":
                rec["title"] = (child.text or "").strip()
            elif ln == "link":
                # Atom <link href="..."/> vs RSS <link>...</link>
                href = child.get("href")
                if href:
                    rec.setdefault("link", href.strip())
                elif child.text:
                    rec.setdefault("link", child.text.strip())
            elif ln in ("description", "summary", "content"):
                rec.setdefault("description", _strip_tags(child.text or ""))
            elif ln in ("author", "creator", "dc:creator"):
                # Atom <author><name>X</name></author>
                name_el = next((c for c in child if _localname(c.tag) == "name"), None)
                if name_el is not None and name_el.text:
                    rec.setdefault("author", name_el.text.strip())
                elif child.text:
                    rec.setdefault("author", child.text.strip())
            elif ln in ("pubDate", "published", "updated"):
                rec.setdefault("pubDate", (child.text or "").strip())
            elif ln == "guid":
                rec.setdefault("guid", (child.text or "").strip())
        if rec.get("title") and rec.get("link"):
            items.append(rec)
    return items


# ---------------------------------------------------------------------------
# Article extraction
# ---------------------------------------------------------------------------

def extract_article(html: str, url: str) -> str:
    """Pull main article body text. Site-specific selectors first, then
    <article>, then joined <p> fallback.
    """
    soup = BeautifulSoup(html, "html.parser")

    host = urlparse(url).netloc.lower()
    # match suffix — e.g. "www.banki.ru" matches "banki.ru"
    selectors: list[str] = []
    for domain, sels in ARTICLE_SELECTORS.items():
        if host == domain or host.endswith("." + domain):
            selectors = sels
            break

    for sel in selectors:
        try:
            el = soup.select_one(sel)
        except Exception:
            el = None
        if el is not None:
            txt = el.get_text(" ", strip=True)
            if len(txt) >= 200:
                return txt

    # Generic <article>
    art = soup.find("article")
    if art is not None:
        txt = art.get_text(" ", strip=True)
        if len(txt) >= 200:
            return txt

    # Last-resort: join all <p> tags inside <body>
    paras = soup.find_all("p")
    if paras:
        txt = " ".join(p.get_text(" ", strip=True) for p in paras)
        return txt

    return soup.get_text(" ", strip=True)


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def matched_keyword(blob: str) -> str | None:
    low = blob.lower()
    for kw in INCOME_KEYWORDS:
        if kw in low:
            return kw
    return None


# ---------------------------------------------------------------------------
# Main per-feed crawl
# ---------------------------------------------------------------------------

def crawl_feed(platform: str, feed_url: str, seen: set[str]) -> int:
    """Crawl one RSS feed; append matching records to OUT_PATH. Returns # added."""
    print(f"[{platform}] feed={feed_url}", flush=True)
    xml_text = fetch(feed_url)
    polite()
    if not xml_text:
        print(f"[{platform}] feed unreachable", flush=True)
        return 0

    items = parse_rss(xml_text)
    print(f"[{platform}] items in feed: {len(items)}", flush=True)
    if not items:
        return 0

    added = 0
    for it in items:
        title = it.get("title", "") or ""
        link = it.get("link", "") or ""
        description = it.get("description", "") or ""
        author = it.get("author", "") or ""
        pub_date = it.get("pubDate", "") or ""
        guid = it.get("guid", "") or link

        if not link:
            continue

        # Stage-1 filter on title+description (cheap, no detail fetch).
        kw = matched_keyword(title + " " + description)
        if kw is None:
            continue

        rid = md5_16(platform, guid)
        if rid in seen:
            continue

        # Stage-2: pull full article body
        detail_html = fetch(link)
        polite()
        body = ""
        if detail_html:
            try:
                body = extract_article(detail_html, link)
            except Exception as e:
                print(f"  [{platform}] extract err {link}: {e}", file=sys.stderr)
                body = description
        if not body:
            body = description

        # Stage-3 filter on full body (description sometimes mentions a
        # keyword in a footer; we want the article itself to actually be
        # about income/work).
        kw2 = matched_keyword(title + " " + body)
        if kw2 is None:
            continue

        rec = {
            "id": rid,
            "raw_id": guid,
            "platform": platform,
            "lang": "ru",
            "title": title[:300],
            "body": body[:5000],
            "author": author[:120],
            "url": link,
            "country_hint": "RU",
            "matched_keyword": kw2,
            "engagement": {
                "score": 0,
                "comments": 0,
                "views": 0,
                "pub_date": pub_date,
            },
            "crawled_at": now_iso(),
        }
        append(OUT_PATH, rec)
        seen.add(rid)
        added += 1

    print(f"[{platform}] added {added}", flush=True)
    return added


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    seen = load_seen(OUT_PATH)
    print(f"[ru_multi_alt] start; existing rows in {OUT_PATH.name} = {len(seen)}")

    per_feed: dict[str, int] = {}
    for platform, feed_url, kind in FEEDS:
        if kind != "rss":
            continue
        try:
            added = crawl_feed(platform, feed_url, seen)
        except Exception as e:
            print(f"[{platform}] FATAL {e}", file=sys.stderr)
            added = 0
        per_feed[platform] = added

    # Final summary
    total_lines = 0
    if OUT_PATH.exists():
        with OUT_PATH.open("r", encoding="utf-8") as f:
            for _ in f:
                total_lines += 1

    print()
    print("=" * 50)
    print(f"[ru_multi_alt] DONE file={OUT_PATH}")
    print(f"[ru_multi_alt] total_lines_in_file={total_lines}")
    for plat, n in per_feed.items():
        print(f"  {plat:14s} +{n}")
    print(f"  {'TOTAL_ADDED':14s} +{sum(per_feed.values())}")


if __name__ == "__main__":
    main()
