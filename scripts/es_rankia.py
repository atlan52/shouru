"""Scrape rankia.com — Spanish-language financial forum/blog.

Strategy:
  1. For each Spanish keyword, hit
       https://www.rankia.com/buscador/?ord=relevance&q=<kw>&page=<n>
     (multiple pages). Parse search-result cards with several
     fallback selectors because Rankia's markup may vary across
     blog posts vs. forum threads.
  2. For each candidate Rankia URL, GET the article/thread page and
     parse title + body + author. Body selectors also use fallbacks
     (article.post .post-content / [itemprop=articleBody] / main
     #content / .article-body / largest <p> cluster).
  3. Require the candidate to be on rankia.com and to contain at least
     one Spanish income/finance token in the title or body. Limit body
     to 3000 chars.

Output: data/raw/rankia_native_<YYYYMMDD>.jsonl
"""
import datetime as _dt
import hashlib
import json
import os
import re
import sys
import time
from urllib.parse import urljoin, urlparse, quote_plus

import requests
from bs4 import BeautifulSoup

OUT_DIR = "/Users/jan/sen/code/spider/shouru/data/raw"
TODAY = _dt.datetime.now().strftime("%Y%m%d")
OUT_PATH = os.path.join(OUT_DIR, f"rankia_native_{TODAY}.jsonl")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.5",
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.rankia.com/",
}

POLITE_SEC = 1.5
TIMEOUT = 25
TARGET = 35
PAGES_PER_KEYWORD = 3

KEYWORDS = [
    "sueldo",
    "salario",
    "cuánto cobras",
    "ingresos pasivos",
    "ingresos",
    "autónomo ingresos",
    "freelance sueldo",
    "empresario ganancias",
    "jubilación temprana",
    "FIRE España",
]

# Spanish on-topic tokens — at least one must appear in title or body
ES_TOPIC_TOKENS = [
    "sueldo", "salario", "ingreso", "ingresos", "cobr", "gana",
    "ganar", "ganancia", "autónomo", "autonomo", "freelance",
    "jubilación", "jubilacion", "FIRE", "pasivo", "pasivos",
    "renta", "rentas", "nómina", "nomina", "euro", "€", "EUR",
    "empresa", "empresario", "negocio", "trabajo", "empleo",
    "dinero", "millón", "millon", "pensión", "pension",
]

BOT_MARKERS = (
    "captcha",
    "are you a human",
    "access denied",
    "unusual traffic",
    "cf-browser-verification",
    "checking your browser",
    "attention required",
)


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
                low = r.text.lower()
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


def has_topic_token(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(tok.lower() in low for tok in ES_TOPIC_TOKENS)


def normalize_url(href: str, base: str = "https://www.rankia.com/") -> str:
    if not href:
        return ""
    href = href.strip()
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return urljoin(base, href)
    if href.startswith("http"):
        return href
    return urljoin(base, href)


def is_rankia_content(url: str) -> bool:
    """Filter URLs to plausible content pages (blog posts / forum
    threads), skipping search/category/tag/login/help pages."""
    if not url:
        return False
    try:
        p = urlparse(url)
    except Exception:
        return False
    if "rankia.com" not in (p.netloc or ""):
        return False
    path = (p.path or "/").rstrip("/")
    if not path or path == "":
        return False
    # Skip non-content paths
    skip_prefixes = (
        "/buscador", "/login", "/registro", "/help", "/ayuda",
        "/contacto", "/aviso-legal", "/politica", "/cookies",
        "/sobre-nosotros", "/publicidad", "/tags", "/tag",
        "/categorias", "/categoria", "/bloggers", "/usuario",
        "/usuarios", "/comunidad-rankia", "/feed",
    )
    for s in skip_prefixes:
        if path.startswith(s):
            return False
    if path.endswith(".pdf") or path.endswith(".jpg"):
        return False
    # Need at least 2 path segments OR a slug-like path with hyphens
    segs = [s for s in path.split("/") if s]
    if not segs:
        return False
    # Looks like content if has hyphens or numeric id segment
    last = segs[-1]
    if "-" in last or last.isdigit() or len(segs) >= 2:
        return True
    return False


def extract_search_links(html: str) -> list:
    """Extract Rankia content URLs from a search results page,
    using multiple fallback strategies."""
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    found = []
    seen = set()

    def add(href, title="", excerpt="", author=""):
        url = normalize_url(href)
        if not is_rankia_content(url):
            return
        if url in seen:
            return
        seen.add(url)
        found.append({
            "url": url,
            "title": (title or "").strip(),
            "excerpt": (excerpt or "").strip(),
            "author": (author or "").strip(),
        })

    # Strategy 1: known/likely card containers
    card_selectors = [
        ".search-result",
        "article.post-summary",
        "article.search-item",
        "div.search-item",
        "li.search-item",
        ".result-item",
        ".buscador-result",
        "article[class*=result]",
        "div[class*=result-item]",
        "div[class*=search-result]",
        "li[class*=result]",
    ]
    for sel in card_selectors:
        try:
            cards = soup.select(sel)
        except Exception:
            cards = []
        for c in cards:
            a = (c.select_one("h2 a") or c.select_one("h3 a")
                 or c.select_one("a.title") or c.select_one("a[href]"))
            if not a:
                continue
            href = a.get("href", "")
            title = a.get_text(" ", strip=True)
            ex_node = (c.select_one("[class*=excerpt]")
                       or c.select_one("[class*=summary]")
                       or c.select_one("[class*=description]")
                       or c.select_one("p"))
            excerpt = ex_node.get_text(" ", strip=True) if ex_node else ""
            au_node = (c.select_one("[class*=author]")
                       or c.select_one("[rel=author]")
                       or c.select_one(".by"))
            author = au_node.get_text(" ", strip=True) if au_node else ""
            add(href, title, excerpt, author)

    # Strategy 2: <h2>/<h3> headings with anchors anywhere in main
    if not found:
        for h in soup.select("h2 a[href], h3 a[href]"):
            href = h.get("href", "")
            title = h.get_text(" ", strip=True)
            # Try sibling/parent for excerpt
            par = h.find_parent(["article", "li", "div"])
            excerpt = ""
            author = ""
            if par:
                p_tag = par.find("p")
                if p_tag:
                    excerpt = p_tag.get_text(" ", strip=True)
                au = par.select_one("[class*=author], [rel=author]")
                if au:
                    author = au.get_text(" ", strip=True)
            add(href, title, excerpt, author)

    # Strategy 3: any anchor whose href looks like a content URL
    if not found:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            url = normalize_url(href)
            if not is_rankia_content(url):
                continue
            title = a.get_text(" ", strip=True)
            if len(title) < 12:
                continue
            add(href, title, "", "")

    return found


def _strip_boilerplate(soup: BeautifulSoup):
    for tag in soup(["script", "style", "noscript", "iframe", "form",
                     "nav", "aside", "header", "footer"]):
        tag.decompose()


def parse_article(url: str, html: str) -> dict:
    """Extract title, body, author from a Rankia content page."""
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title = ""
    for sel in ("article h1", "h1.post-title", "h1.entry-title",
                "h1[itemprop=headline]", "h1", "title"):
        node = soup.select_one(sel)
        if node:
            t = node.get_text(" ", strip=True)
            if t:
                title = t
                break
    if title.lower().endswith(" - rankia"):
        title = title[: -len(" - rankia")].strip()
    if title.lower().endswith(" | rankia"):
        title = title[: -len(" | rankia")].strip()

    # Author
    author = ""
    for sel in ("[itemprop=author]", "a[rel=author]", ".post-author",
                ".author-name", "[class*=author] a", "[class*=author]",
                'meta[name="author"]'):
        node = soup.select_one(sel)
        if not node:
            continue
        if node.name == "meta":
            v = node.get("content", "")
        else:
            v = node.get_text(" ", strip=True)
        if v:
            author = v.strip()[:120]
            break

    # Body — multiple fallbacks
    body_node = None
    for sel in (
        "article.post .post-content",
        "[itemprop=articleBody]",
        "article .entry-content",
        "article .post-content",
        ".post-content",
        ".entry-content",
        ".article-body",
        ".post-body",
        ".blog-post-content",
        ".content-post",
        "article",
        "main",
        "#content",
    ):
        node = soup.select_one(sel)
        if not node:
            continue
        # Make sure it has substantive text
        tmp = BeautifulSoup(str(node), "html.parser")
        _strip_boilerplate(tmp)
        txt = tmp.get_text(" ", strip=True)
        if len(txt) >= 200:
            body_node = tmp
            break

    body_text = ""
    if body_node:
        # Prefer joined paragraphs for readability
        paras = []
        for p in body_node.find_all(["p", "li"]):
            t = p.get_text(" ", strip=True)
            if len(t) >= 20:
                paras.append(t)
        if paras:
            body_text = "\n".join(paras)
        else:
            body_text = body_node.get_text(" ", strip=True)
    else:
        # Last resort: whole-page paragraphs
        clone = BeautifulSoup(html, "html.parser")
        _strip_boilerplate(clone)
        paras = []
        for p in clone.find_all("p"):
            t = p.get_text(" ", strip=True)
            if len(t) >= 40:
                paras.append(t)
        body_text = "\n".join(paras[:30])

    body_text = re.sub(r"\s+\n", "\n", body_text)
    body_text = re.sub(r"\n{3,}", "\n\n", body_text).strip()
    if len(body_text) > 3000:
        body_text = body_text[:3000].rstrip() + "…"

    # raw_id from URL slug
    p = urlparse(url)
    segs = [s for s in (p.path or "").split("/") if s]
    raw_id = segs[-1] if segs else url

    return {
        "title": title[:300],
        "body": body_text,
        "author": author or "",
        "raw_id": raw_id,
    }


def search_keyword(kw: str) -> list:
    """Search a single keyword across PAGES_PER_KEYWORD pages."""
    results = []
    seen = set()
    encoded = quote_plus(kw)
    for page in range(1, PAGES_PER_KEYWORD + 1):
        if page == 1:
            url = (f"https://www.rankia.com/buscador/"
                   f"?ord=relevance&q={encoded}")
        else:
            url = (f"https://www.rankia.com/buscador/"
                   f"?ord=relevance&q={encoded}&page={page}")
        print(f"[search] kw={kw!r} page={page} -> {url}")
        html = fetch(url)
        time.sleep(POLITE_SEC)
        if not html:
            continue
        items = extract_search_links(html)
        new_n = 0
        for it in items:
            if it["url"] in seen:
                continue
            seen.add(it["url"])
            results.append(it)
            new_n += 1
        print(f"  found {new_n} new (total this kw: {len(results)})")
        if new_n == 0:
            # No new on this page — likely end of results
            break
    return results


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"== rankia.com -> {OUT_PATH}")

    written = 0
    written_urls = set()
    samples = []

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        for kw in KEYWORDS:
            if written >= TARGET + 15:
                # Got plenty; finish current keyword loop and stop adding
                # more from new keywords (still attempt a bit more for
                # robustness — break early to be polite).
                break

            cands = search_keyword(kw)
            for cand in cands:
                if written >= TARGET + 25:
                    break
                url = cand["url"]
                if url in written_urls:
                    continue

                # Quick relevance gate by title/excerpt
                preview = (cand.get("title", "") + " "
                           + cand.get("excerpt", ""))
                if preview and not has_topic_token(preview):
                    # Title doesn't mention finance/income — fetch
                    # anyway only if title is empty (could be valid)
                    if cand.get("title"):
                        continue

                print(f"  [post] {url}")
                phtml = fetch(url)
                time.sleep(POLITE_SEC)
                if not phtml:
                    continue
                art = parse_article(url, phtml)
                title = art.get("title") or cand.get("title", "")
                body = art.get("body") or cand.get("excerpt", "")
                author = art.get("author") or cand.get("author", "")
                raw_id = art.get("raw_id") or url

                if not title and not body:
                    continue
                if len(body) < 80:
                    # not enough text
                    continue
                if not has_topic_token(title + " " + body):
                    continue

                rid = md5_id("rankia", url)
                item = {
                    "id": rid,
                    "raw_id": raw_id,
                    "platform": "rankia",
                    "lang": "es",
                    "title": title,
                    "body": body,
                    "author": author or "rankia.com",
                    "url": url,
                    "country_hint": "ES",
                    "matched_keyword": kw,
                    "engagement": {
                        "score": 0,
                        "comments": 0,
                        "views": None,
                    },
                }
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
                fh.flush()
                written += 1
                written_urls.add(url)
                if len(samples) < 5:
                    samples.append(item)
                print(f"    +1 written={written} title={title[:80]!r}")

            if written >= TARGET:
                # Continue to next keyword once briefly to diversify
                if written >= TARGET + 5:
                    break

    print(f"\nDONE: wrote {written} lines -> {OUT_PATH}")
    print("\n--- 5 Spanish samples ---")
    for s in samples:
        print(f"  • [{s['matched_keyword']}] {s['title']}")
        body_preview = s["body"][:200].replace("\n", " ")
        print(f"      {body_preview}…")
        print(f"      url: {s['url']}")
        print()


if __name__ == "__main__":
    main()
