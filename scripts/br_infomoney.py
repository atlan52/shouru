"""Scrape infomoney.com.br — Brazilian Portuguese finance articles.

Strategy:
  1. Hit WordPress search /?s=<pt-kw> for each Portuguese keyword.
  2. Also hit the /carreira/ category page for career-related articles.
  3. From each listing, extract article cards (article.post / [class*=post-]/
     [class*=article-card] / generic <article>) and pull title, URL, excerpt.
  4. For each article URL, fetch and extract `.entry-content` / `article .content`
     full body (Portuguese, capped at 3000 chars).
  5. Filter to in-domain article URLs only; skip /tag/, /author/, /category/.

Output: /Users/jan/sen/code/spider/shouru/data/raw/infomoney_native_<YYYYMMDD>.jsonl
"""
import datetime as _dt
import hashlib
import json
import os
import re
import sys
import time
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUT_DIR = "/Users/jan/sen/code/spider/shouru/data/raw"
TODAY = _dt.datetime.now().strftime("%Y%m%d")
OUT_PATH = os.path.join(OUT_DIR, f"infomoney_native_{TODAY}.jsonl")

BASE = "https://www.infomoney.com.br"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5",
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Referer": BASE + "/",
}

POLITE_SEC = 1.5
TIMEOUT = 25
TARGET = 25
MAX_PER_KEYWORD = 8

# 10 Portuguese keywords as per spec
KEYWORDS = [
    "salário",
    "renda",
    "quanto ganha",
    "MEI faturamento",
    "freelancer renda",
    "aposentadoria",
    "ganhar dinheiro",
    "renda passiva",
    "salário desenvolvedor",
    "salário médico",
]

# Plus a category browse for career articles
CATEGORY_PATHS = [
    "/carreira/",
]

# Non-article path segments to skip
SKIP_SEGMENTS = (
    "/tag/", "/author/", "/category/", "/cotacoes/", "/wp-content/",
    "/wp-login", "/feed", "/page/", "/topico/", "/colunistas/",
    "/newsletter", "/podcast", "/video", "/galeria",
)

BOT_MARKERS = ("captcha", "are you a human", "access denied",
               "unusual traffic", "cf-browser-verification",
               "attention required")


def md5_id(*parts) -> str:
    h = hashlib.md5()
    for p in parts:
        h.update(("|" + str(p)).encode("utf-8", errors="replace"))
    return h.hexdigest()


def fetch(url: str, retries: int = 2):
    last = None
    for i in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT,
                             allow_redirects=True)
            if r.status_code == 200 and r.text:
                low = r.text[:5000].lower()
                if any(m in low for m in BOT_MARKERS):
                    last = "bot-block"
                    return None
                return r.text
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(2 + i * 2)
    print(f"  [fetch fail] {url}: {last}", file=sys.stderr)
    return None


def is_article_url(url: str) -> bool:
    """Keep only canonical infomoney article URLs."""
    if not url:
        return False
    try:
        p = urlparse(url)
    except Exception:
        return False
    if "infomoney.com.br" not in (p.netloc or ""):
        return False
    path = p.path or "/"
    if path in ("/", ""):
        return False
    for seg in SKIP_SEGMENTS:
        if seg in path:
            return False
    # Article slugs typically have hyphens and are reasonably long
    last = path.rstrip("/").rsplit("/", 1)[-1]
    if len(last) < 12 or "-" not in last:
        return False
    return True


def slug_from_url(url: str) -> str:
    p = urlparse(url)
    return (p.path or "/").rstrip("/").rsplit("/", 1)[-1] or url


def extract_listing_cards(html: str):
    """Yield (title, url, excerpt) tuples from a search/category listing."""
    if not html:
        return
    soup = BeautifulSoup(html, "html.parser")
    seen = set()

    # Strategy A: WordPress-style article elements
    cards = soup.find_all("article")
    for art in cards:
        # title link
        a = None
        for tag in ("h2", "h3", "h4"):
            h = art.find(tag)
            if h:
                a = h.find("a", href=True)
                if a:
                    break
        if not a:
            a = art.find("a", href=True)
        if not a:
            continue
        href = a.get("href", "").strip()
        if href.startswith("/"):
            href = urljoin(BASE, href)
        if not is_article_url(href) or href in seen:
            continue
        seen.add(href)
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 8:
            # Fallback to full article-level heading text
            h = art.find(["h1", "h2", "h3", "h4"])
            if h:
                title = h.get_text(" ", strip=True)
        if not title:
            continue
        # excerpt
        excerpt = ""
        for sel in [
            {"class": re.compile(r"(?i)excerpt|summary|description|deck")},
            {"name": "p"},
        ]:
            tag = art.find(attrs=sel) if "class" in sel else art.find("p")
            if tag:
                t = tag.get_text(" ", strip=True)
                if t and len(t) >= 30:
                    excerpt = t
                    break
        yield (title.strip()[:300], href, excerpt[:600])

    # Strategy B: any anchor with article-looking href, when <article> sparse
    if not seen:
        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            if href.startswith("/"):
                href = urljoin(BASE, href)
            if not is_article_url(href) or href in seen:
                continue
            title = a.get_text(" ", strip=True)
            if not title or len(title) < 12:
                continue
            seen.add(href)
            yield (title[:300], href, "")


def extract_article(html: str):
    """Return (title, body, author) from a single article page."""
    if not html:
        return None, "", ""
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(" ", strip=True)
    if not title:
        og = soup.find("meta", attrs={"property": "og:title"})
        if og and og.get("content"):
            title = og["content"].strip()

    # Body
    body_parts = []
    body_root = (
        soup.find(class_=re.compile(r"(?i)entry-content"))
        or soup.find(class_=re.compile(r"(?i)post-content|article-content|content-area"))
        or soup.find("article")
    )
    if body_root:
        # Drop scripts, styles, and embed widgets
        for bad in body_root.find_all(["script", "style", "iframe", "form"]):
            bad.decompose()
        # Drop newsletter/related blocks
        for bad in body_root.find_all(
            class_=re.compile(r"(?i)newsletter|related|share|social|tags?|"
                              r"author-box|comments|sidebar|advert|banner|"
                              r"recommend")):
            bad.decompose()
        for p in body_root.find_all(["p", "h2", "h3", "li"]):
            t = p.get_text(" ", strip=True)
            if not t or len(t) < 25:
                continue
            body_parts.append(t)
            if sum(len(x) for x in body_parts) > 3500:
                break
    body = "\n\n".join(body_parts).strip()
    if len(body) > 3000:
        body = body[:3000].rstrip() + "…"

    # Author
    author = ""
    for sel in [
        {"name": "meta", "attrs": {"name": "author"}},
        {"name": "meta", "attrs": {"property": "article:author"}},
    ]:
        m = soup.find(**sel)
        if m and m.get("content"):
            author = m["content"].strip()
            break
    if not author:
        a = soup.find(class_=re.compile(r"(?i)author-name|byline|by-author"))
        if a:
            author = a.get_text(" ", strip=True)
    author = (author or "infomoney.com.br")[:120]

    return title.strip()[:300], body, author


def gather_article_urls():
    """Collect (article_url, matched_keyword, listing_title, excerpt) tuples."""
    found = []
    seen_urls = set()

    # Search listings
    for kw in KEYWORDS:
        url = f"{BASE}/?s={quote(kw)}"
        print(f"[search] kw={kw!r}")
        html = fetch(url)
        time.sleep(POLITE_SEC)
        if not html:
            continue
        cnt = 0
        for title, art_url, excerpt in extract_listing_cards(html):
            if art_url in seen_urls:
                continue
            seen_urls.add(art_url)
            found.append((art_url, kw, title, excerpt))
            cnt += 1
            if cnt >= MAX_PER_KEYWORD:
                break
        print(f"  [search] {kw!r}: +{cnt} new urls (running total {len(found)})")

    # Category browse
    for cpath in CATEGORY_PATHS:
        url = urljoin(BASE, cpath)
        print(f"[cat] {cpath}")
        html = fetch(url)
        time.sleep(POLITE_SEC)
        if not html:
            continue
        cnt = 0
        for title, art_url, excerpt in extract_listing_cards(html):
            if art_url in seen_urls:
                continue
            seen_urls.add(art_url)
            # tag with a generic keyword for the category path
            found.append((art_url, "carreira", title, excerpt))
            cnt += 1
            if cnt >= 12:
                break
        print(f"  [cat] {cpath}: +{cnt} new urls (running total {len(found)})")

    return found


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"== infomoney.com.br -> {OUT_PATH}")

    urls = gather_article_urls()
    print(f"\n[gather] total candidate articles: {len(urls)}")

    written = 0
    pt_samples = []
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        for art_url, kw, listing_title, excerpt in urls:
            if written >= TARGET * 3:
                # plenty captured; cap to avoid runaway
                break
            print(f"[article] {art_url}")
            html = fetch(art_url)
            time.sleep(POLITE_SEC)
            if not html:
                continue
            title, body, author = extract_article(html)
            if not title:
                title = listing_title
            # Compose body — use excerpt as fallback if extraction thin
            if len(body) < 200 and excerpt:
                body = (excerpt + ("\n\n" + body if body else "")).strip()
            if len(body) < 80:
                print(f"  [skip] body too short ({len(body)} chars)")
                continue

            slug = slug_from_url(art_url)
            rid = md5_id("infomoney", slug)
            item = {
                "id": rid,
                "raw_id": slug,
                "platform": "infomoney",
                "lang": "pt",
                "title": title,
                "body": body,
                "author": author,
                "url": art_url,
                "country_hint": "BR",
                "matched_keyword": kw,
                "engagement": {"score": 0, "comments": 0, "views": None},
            }
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
            fh.flush()
            written += 1
            if len(pt_samples) < 5:
                pt_samples.append((title, body[:240]))
            print(f"  [+1] kw={kw!r} title={title[:80]!r} "
                  f"body_len={len(body)} author={author[:40]!r}")

    print(f"\nDONE: {written} lines written to {OUT_PATH}")
    print("\n--- 5 Portuguese samples ---")
    for i, (t, b) in enumerate(pt_samples, 1):
        print(f"\n[{i}] {t}")
        print(f"    {b}")


if __name__ == "__main__":
    main()
