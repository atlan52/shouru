"""VnExpress native scraper — Vietnamese income / salary articles.

Strategy:
  1. For each Vietnamese keyword, hit the SSR search endpoint
     https://timkiem.vnexpress.net/?q=<kw>&page=<n>
     and collect article links + titles + leads from the result list
     (article.item-news / .list-news article / [class*=item-news]).
  2. Visit each article URL, extract:
       - real title (h1.title-detail)
       - article body (article.fck_detail / .fck_detail; falls back to
         .sidebar-1 fck_detail or any .fck_detail descendant)
       - author byline (p.author / .author_mail strong / footer)
  3. Filter: title or body must contain a Vietnamese on-topic token
     (lương, thu nhập, đồng, lương tháng, kiếm tiền, ...).
  4. Emit JSONL records to data/raw/vnexpress_native_<YYYYMMDD>.jsonl.

Polite: 1.5s sleep between requests, single Chrome/124 UA, vi-VN.
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
BASE = "https://vnexpress.net"
SEARCH_BASE = "https://timkiem.vnexpress.net"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")
TIMEOUT = 25
SLEEP = 1.5

# 10 Vietnamese keywords as per spec
KEYWORDS = [
    "lương",
    "thu nhập",
    "kiếm tiền",
    "freelancer thu nhập",
    "làm thêm thu nhập",
    "nghề nghiệp lương",
    "lương kỹ sư",
    "lương lập trình viên",
    "FIRE Việt Nam",
    "công việc cao lương",
]

PAGES_PER_KEYWORD = 3
MAX_ARTICLES_PER_FEED = 50
TARGET = 25

# On-topic Vietnamese income tokens (no diacritics-only fallback; we keep
# accented forms because the source is properly encoded)
VI_TOPIC_TOKENS = [
    "lương", "thu nhập", "tiền lương", "kiếm tiền", "đồng/tháng",
    "triệu/tháng", "triệu đồng", "tỷ đồng", "thưởng", "freelance",
    "freelancer", "làm thêm", "nghề", "công việc", "kỹ sư",
    "lập trình", "việc làm", "tài chính cá nhân", "tiết kiệm",
    "đầu tư", "FIRE", "nghỉ hưu sớm",
]

BOT_MARKERS = (
    "captcha", "are you a human", "access denied",
    "cf-browser-verification", "checking your browser",
    "attention required",
)

# VnExpress article URLs end with -<digits>.html (the trailing digit run is
# the article id). Examples:
#   /kinh-doanh/.../tang-luong-toi-thieu-2024-4791234.html
ARTICLE_ID_RE = re.compile(r"-(\d{6,9})\.html(?:[?#].*)?$")


def headers(referer: str = BASE + "/") -> dict:
    return {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.5",
        "Referer": referer,
    }


def make_id(raw_id: str) -> str:
    return hashlib.md5(("vnexpress:" + raw_id).encode("utf-8")).hexdigest()[:16]


def fetch(url: str, referer: str = BASE + "/") -> str | None:
    try:
        r = requests.get(url, headers=headers(referer), timeout=TIMEOUT,
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


def extract_search_items(html: str) -> list[dict]:
    """Pull article links from a search result page.

    VnExpress search result items live under article.item-news /
    .list-news article. Each item has h3.title-news a (or h2 a) with
    the article URL, and p.description / .description as a lead.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Try several container selectors; vnexpress varies them across
    # search and list pages.
    candidates: list = []
    for sel in (
        "article.item-news",
        ".list-news article",
        ".search_listing article",
        ".width_common article",
        "[class*=item-news]",
    ):
        found = soup.select(sel)
        if found:
            candidates = found
            break

    seen: set[str] = set()
    out: list[dict] = []

    def push(href: str, title: str, lead: str):
        if not href or not title:
            return
        # normalise to absolute https url
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = urljoin(BASE, href)
        p = urlparse(href)
        if "vnexpress.net" not in p.netloc:
            return
        m = ARTICLE_ID_RE.search(p.path)
        if not m:
            return
        aid = m.group(1)
        if aid in seen:
            return
        seen.add(aid)
        out.append({
            "article_id": aid,
            "url": href.split("?")[0].split("#")[0],
            "title": title.strip(),
            "lead": lead.strip(),
        })

    if candidates:
        for art in candidates:
            a = (art.select_one("h3.title-news a")
                 or art.select_one("h2.title-news a")
                 or art.select_one("h3 a")
                 or art.select_one("h2 a")
                 or art.select_one("a.thumb")
                 or art.select_one("a"))
            if not a or not a.get("href"):
                continue
            title = (a.get("title") or a.get_text(" ", strip=True) or "")
            lead_el = (art.select_one(".description")
                       or art.select_one("p.lead")
                       or art.select_one("p.description"))
            lead = lead_el.get_text(" ", strip=True) if lead_el else ""
            push(a["href"], title, lead)
    else:
        # Fallback: scan all anchors that look like article URLs.
        for a in soup.find_all("a", href=True):
            href = a["href"]
            title = (a.get("title") or a.get_text(" ", strip=True) or "")
            if title and len(title) > 8:
                push(href, title, "")

    return out


def parse_article(html: str, fallback_title: str = "") -> dict:
    soup = BeautifulSoup(html, "html.parser")

    # Title: h1.title-detail is canonical.
    title = ""
    for sel in ("h1.title-detail", "h1.title_news_detail",
                "h1.title", "h1", "title"):
        el = soup.select_one(sel)
        if el:
            title = el.get_text(" ", strip=True)
            if title:
                break
    if not title:
        title = fallback_title
    title = re.sub(r"\s*-\s*VnExpress.*$", "", title)

    # Description / sapo (lead paragraph)
    sapo = ""
    for sel in ("p.description", "h2.description",
                ".description", ".sapo"):
        el = soup.select_one(sel)
        if el:
            sapo = el.get_text(" ", strip=True)
            if sapo:
                break

    # Body: article.fck_detail / .fck_detail. Concatenate all <p> within.
    body = ""
    fck = (soup.select_one("article.fck_detail")
           or soup.select_one(".fck_detail")
           or soup.select_one("[class*=fck_detail]"))
    if fck:
        paras = []
        for p in fck.find_all(["p", "h2"]):
            cls = " ".join(p.get("class") or [])
            # skip caption / author / related boxes
            if "Image" in cls or "author" in cls.lower():
                continue
            text = p.get_text(" ", strip=True)
            if text:
                paras.append(text)
        body = "\n".join(paras)
    if not body:
        # last-ditch: any p inside <article>
        art = soup.find("article")
        if art:
            body = "\n".join(
                p.get_text(" ", strip=True)
                for p in art.find_all("p")
                if p.get_text(strip=True))

    # Compose: prepend sapo if not already part of body
    if sapo and sapo not in body:
        body = (sapo + "\n" + body).strip()

    # Author: VnExpress puts byline at the end of fck_detail in
    # <p style="text-align:right"><strong>Tên Tác Giả</strong></p>
    author = ""
    if fck:
        # Check the last few <p> for a single bold span (typical byline).
        ps = fck.find_all("p")
        for p in reversed(ps[-6:]) if len(ps) > 6 else reversed(ps):
            strong = p.find("strong")
            if strong and len(strong.get_text(strip=True)) <= 60:
                txt = strong.get_text(" ", strip=True)
                # Filter out obvious non-author bold texts
                if txt and not re.search(r"\d", txt) and len(txt.split()) <= 6:
                    author = txt
                    break
    if not author:
        for sel in (".author", "p.author", ".author_mail strong",
                    ".author_news"):
            el = soup.select_one(sel)
            if el:
                txt = el.get_text(" ", strip=True)
                if txt and len(txt) <= 80:
                    author = txt
                    break

    # Engagement: comments count (vnexpress shows total_comment in a
    # data attribute on the comment box) and views (rare; usually absent).
    comments = 0
    cmt_el = soup.select_one("[data-objectid][data-objecttype]")
    if cmt_el:
        for attr in ("data-total", "data-totalcomment",
                     "data-total_comment"):
            v = cmt_el.get(attr)
            if v and v.isdigit():
                comments = int(v)
                break
    if comments == 0:
        m = re.search(r"(\d{1,5})\s*(ý kiến|bình luận|comments?)",
                      soup.get_text(" ", strip=True), re.IGNORECASE)
        if m:
            try:
                comments = int(m.group(1))
            except ValueError:
                pass

    return {
        "title": title,
        "sapo": sapo,
        "body": body,
        "author": author,
        "comments": comments,
    }


def is_on_topic_vi(title: str, body: str) -> bool:
    blob = ((title or "") + " " + (body or "")).lower()
    return any(tok.lower() in blob for tok in VI_TOPIC_TOKENS)


def sample_lines(records: list[dict], n: int = 5) -> list[str]:
    out = []
    for rec in records[:n]:
        t = rec.get("title", "")
        b = (rec.get("body", "") or "").replace("\n", " ")[:140]
        out.append(f"  - [{rec.get('matched_keyword', '')}] {t} :: {b}")
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    today = datetime.datetime.now().strftime("%Y%m%d")
    out_path = os.path.join(OUT_DIR, f"vnexpress_native_{today}.jsonl")

    seen_ids: set[str] = set()
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
    new_records: list[dict] = []

    def write_record(meta: dict, parsed: dict, kw_label: str) -> bool:
        nonlocal written
        rid = meta["article_id"]
        if rid in seen_ids:
            return False
        title = parsed["title"] or meta.get("title", "")
        body = parsed["body"] or meta.get("lead", "")
        if not is_on_topic_vi(title, body):
            return False
        item = {
            "id": make_id(rid),
            "raw_id": rid,
            "platform": "vnexpress",
            "lang": "vi",
            "title": title,
            "body": body[:3000],
            "author": parsed["author"],
            "url": meta["url"],
            "country_hint": "VN",
            "matched_keyword": kw_label,
            "engagement": {
                "score": 0,
                "comments": parsed["comments"],
                "views": None,
            },
            "crawled_at": datetime.datetime.now(datetime.timezone.utc)
            .isoformat(timespec="seconds"),
        }
        fout.write(json.dumps(item, ensure_ascii=False) + "\n")
        fout.flush()
        seen_ids.add(rid)
        written += 1
        new_records.append(item)
        return True

    def harvest_search(kw: str, page: int) -> int:
        qs = quote_plus(kw)
        url = f"{SEARCH_BASE}/?q={qs}"
        if page > 1:
            url += f"&page={page}"
        print(f"[search] kw={kw!r} p{page}  {url}")
        html = fetch(url, referer=SEARCH_BASE + "/")
        if not html:
            return 0
        items = extract_search_items(html)
        print(f"    found {len(items)} article links")
        added = 0
        for meta in items[:MAX_ARTICLES_PER_FEED]:
            if written >= TARGET * 2:
                break
            if meta["article_id"] in seen_ids:
                continue
            time.sleep(SLEEP)
            apage = fetch(meta["url"], referer=url)
            if not apage:
                continue
            parsed = parse_article(apage,
                                   fallback_title=meta.get("title", ""))
            if write_record(meta, parsed, kw):
                added += 1
                if written % 5 == 0:
                    print(f"    [+] {written} written so far")
            if written >= TARGET * 2:
                break
        return added

    for kw in KEYWORDS:
        if written >= TARGET:
            break
        for page in range(1, PAGES_PER_KEYWORD + 1):
            if written >= TARGET:
                break
            harvest_search(kw, page)
            time.sleep(SLEEP)

    fout.close()
    print(f"[done] wrote {written} new records to {out_path}")
    print(f"[total] file now has {len(seen_ids)} unique records")
    if new_records:
        print("[samples]")
        for line in sample_lines(new_records, 5):
            print(line)


if __name__ == "__main__":
    main()
