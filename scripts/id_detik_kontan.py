"""Scrape detik.com + kontan.co.id — Indonesian salary/income articles.

Outputs:
  data/raw/detik_native_<YYYYMMDD>.jsonl
  data/raw/kontan_native_<YYYYMMDD>.jsonl
"""
import datetime as _dt
import hashlib
import json
import os
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUT_DIR = "/Users/jan/sen/code/spider/shouru/data/raw"
TODAY = _dt.datetime.now().strftime("%Y%m%d")
DETIK_OUT = os.path.join(OUT_DIR, f"detik_native_{TODAY}.jsonl")
KONTAN_OUT = os.path.join(OUT_DIR, f"kontan_native_{TODAY}.jsonl")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.5",
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

POLITE_SEC = 1.5
TARGET_TOTAL = 50

KEYWORDS = [
    "gaji",
    "pendapatan",
    "berapa pendapatan",
    "freelance pendapatan",
    "bisnis pendapatan",
    "penghasilan tambahan",
    "gaji programmer",
    "gaji insinyur",
    "kerja online pendapatan",
    "pensiun dini",
]


def md5_id(*parts) -> str:
    h = hashlib.md5()
    for p in parts:
        h.update(("|" + str(p)).encode("utf-8", errors="replace"))
    return h.hexdigest()


def fetch(url: str, retries: int = 2, timeout: int = 25):
    last = None
    for i in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout,
                             allow_redirects=True)
            if r.status_code == 200 and r.text:
                low = r.text.lower()
                if any(m in low for m in ("captcha", "are you a human",
                                          "access denied",
                                          "unusual traffic")):
                    last = "bot-block"
                    return None
                return r.text
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(2 + i * 2)
    print(f"  [fetch fail] {url}: {last}", file=sys.stderr)
    return None


def _clean_text(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_body(html: str, primary_selectors):
    """Try primary selectors first, then fall back to common itemprop/article tags."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    # remove scripts/styles
    for tag in soup(["script", "style", "noscript", "iframe", "form"]):
        tag.decompose()
    node = None
    for sel in primary_selectors:
        node = soup.select_one(sel)
        if node:
            break
    if not node:
        # fallbacks
        node = (soup.select_one("[itemprop=articleBody]")
                or soup.select_one("article")
                or soup.select_one("div.detail__body")
                or soup.select_one("div.detail-content"))
    if not node:
        return ""
    paras = []
    for p in node.find_all(["p", "li"]):
        t = p.get_text(" ", strip=True)
        if not t:
            continue
        # filter nav/related junk
        low = t.lower()
        if any(b in low for b in ("baca juga", "lihat juga", "tonton juga",
                                  "share", "copy link")):
            if len(t) < 80:
                continue
        if len(t) >= 20:
            paras.append(t)
    body = "\n\n".join(paras).strip()
    if not body:
        body = _clean_text(node.get_text(" ", strip=True))
    return body[:8000]


def _extract_title(html: str):
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if h1:
        t = h1.get_text(" ", strip=True)
        if t:
            return t[:300]
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return og["content"].strip()[:300]
    if soup.title and soup.title.string:
        return soup.title.string.strip()[:300]
    return ""


def _extract_author(html: str):
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    m = soup.find("meta", attrs={"name": "author"})
    if m and m.get("content"):
        return m["content"].strip()[:160]
    for sel in (".detail__author", ".author", '[itemprop="author"]',
                ".reporter", ".writer-name"):
        n = soup.select_one(sel)
        if n:
            t = n.get_text(" ", strip=True)
            if t:
                return t[:160]
    return ""


# ---------- detik.com ----------
DETIK_SEARCH = "https://www.detik.com/search/searchall?query={q}"


def _detik_collect_links(html, base="https://www.detik.com"):
    """Return list of (url, title) from a detik search result page."""
    out = []
    if not html:
        return out
    soup = BeautifulSoup(html, "html.parser")
    seen = set()

    # try the documented selectors first
    candidates = []
    candidates.extend(soup.select("article.list-content__item"))
    candidates.extend(soup.select("article.list__title"))
    candidates.extend(soup.select("article"))
    candidates.extend(soup.select(".list-content__item"))

    for art in candidates:
        a = (art.select_one("h2 a") or art.select_one("h3.media__title a")
             or art.select_one("h3 a") or art.select_one("a.media__link")
             or art.select_one("a"))
        if not a:
            continue
        href = a.get("href") or ""
        if not href:
            continue
        href = urljoin(base, href)
        host = urlparse(href).netloc
        if "detik.com" not in host:
            continue
        if href in seen:
            continue
        seen.add(href)
        title = a.get_text(" ", strip=True) or ""
        if not title:
            t = art.find(["h2", "h3"])
            title = t.get_text(" ", strip=True) if t else ""
        out.append((href, title[:300]))

    # fallback: any anchor in the page that points to a detik article
    if not out:
        for a in soup.find_all("a", href=True):
            href = urljoin(base, a["href"])
            host = urlparse(href).netloc
            if "detik.com" not in host:
                continue
            # detik article paths typically contain /d-<id>/ or a long slug
            if not re.search(r"/d-\d+/", href) and not re.search(
                    r"/(berita|finance|news|hot|inet|sport|edu|wolipop|"
                    r"oto|food|health|travel)/", href):
                continue
            if href in seen:
                continue
            seen.add(href)
            title = a.get_text(" ", strip=True)
            if title and len(title) >= 8:
                out.append((href, title[:300]))
            if len(out) >= 40:
                break
    return out


def scrape_detik():
    written = 0
    seen_urls = set()
    with open(DETIK_OUT, "w", encoding="utf-8") as fh:
        for kw in KEYWORDS:
            if written >= TARGET_TOTAL:
                break
            q = requests.utils.quote(kw)
            url = DETIK_SEARCH.format(q=q)
            print(f"[detik] search '{kw}'")
            html = fetch(url)
            time.sleep(POLITE_SEC)
            links = _detik_collect_links(html) if html else []
            print(f"  [detik] {len(links)} candidates")
            for href, sniff_title in links:
                if written >= TARGET_TOTAL:
                    break
                if href in seen_urls:
                    continue
                seen_urls.add(href)
                ahtml = fetch(href)
                time.sleep(POLITE_SEC)
                if not ahtml:
                    continue
                title = _extract_title(ahtml) or sniff_title
                body = _extract_body(
                    ahtml,
                    [".detail__body-text", ".itp_bodycontent",
                     ".detail__body", "[itemprop=articleBody]"],
                )
                author = _extract_author(ahtml)
                if not title or not body or len(body) < 120:
                    continue
                # require keyword presence (Indonesian) for filtering
                hay = (title + "\n" + body).lower()
                if kw.lower() not in hay and "gaji" not in hay and \
                        "pendapatan" not in hay and "penghasilan" not in hay:
                    continue
                rid_raw = href
                rid = md5_id("detik", rid_raw)
                item = {
                    "id": rid,
                    "raw_id": rid_raw,
                    "platform": "detik",
                    "lang": "id",
                    "title": title,
                    "body": body,
                    "author": author or "detik.com",
                    "url": href,
                    "country_hint": "ID",
                    "matched_keyword": kw,
                    "engagement": {"score": 0, "comments": 0, "views": None},
                }
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
                fh.flush()
                written += 1
                print(f"  [detik] +1 ({written}) {title[:80]}")
    return written


# ---------- kontan.co.id ----------
KONTAN_SEARCH = "https://www.kontan.co.id/search?search={q}"


def _kontan_collect_links(html, base="https://www.kontan.co.id"):
    out = []
    if not html:
        return out
    soup = BeautifulSoup(html, "html.parser")
    seen = set()

    candidates = []
    candidates.extend(soup.select("article"))
    candidates.extend(soup.select(".list__item"))
    candidates.extend(soup.select(".list-news"))
    candidates.extend(soup.select("li.list"))
    candidates.extend(soup.select("div.list"))

    for art in candidates:
        a = (art.select_one("h1 a") or art.select_one("h2 a")
             or art.select_one("h3 a") or art.select_one("h4 a")
             or art.select_one(".title a") or art.select_one("a"))
        if not a:
            continue
        href = a.get("href") or ""
        if not href:
            continue
        href = urljoin(base, href)
        host = urlparse(href).netloc
        if "kontan.co.id" not in host:
            continue
        if href in seen:
            continue
        seen.add(href)
        title = a.get_text(" ", strip=True) or ""
        if not title:
            t = art.find(["h1", "h2", "h3", "h4"])
            title = t.get_text(" ", strip=True) if t else ""
        if title:
            out.append((href, title[:300]))

    if not out:
        for a in soup.find_all("a", href=True):
            href = urljoin(base, a["href"])
            host = urlparse(href).netloc
            if "kontan.co.id" not in host:
                continue
            # kontan article paths usually contain /news/ or /berita/
            if not re.search(r"/news/", href) and not re.search(
                    r"\.kontan\.co\.id/news/", href):
                continue
            if href in seen:
                continue
            seen.add(href)
            title = a.get_text(" ", strip=True)
            if title and len(title) >= 10:
                out.append((href, title[:300]))
            if len(out) >= 40:
                break
    return out


def scrape_kontan():
    written = 0
    seen_urls = set()
    with open(KONTAN_OUT, "w", encoding="utf-8") as fh:
        for kw in KEYWORDS:
            if written >= TARGET_TOTAL:
                break
            q = requests.utils.quote(kw)
            url = KONTAN_SEARCH.format(q=q)
            print(f"[kontan] search '{kw}'")
            html = fetch(url)
            time.sleep(POLITE_SEC)
            links = _kontan_collect_links(html) if html else []
            print(f"  [kontan] {len(links)} candidates")
            for href, sniff_title in links:
                if written >= TARGET_TOTAL:
                    break
                if href in seen_urls:
                    continue
                seen_urls.add(href)
                ahtml = fetch(href)
                time.sleep(POLITE_SEC)
                if not ahtml:
                    continue
                title = _extract_title(ahtml) or sniff_title
                body = _extract_body(
                    ahtml,
                    [".detail-content", ".tmpt-desk-kon", ".detail-desk",
                     "[itemprop=articleBody]"],
                )
                author = _extract_author(ahtml)
                if not title or not body or len(body) < 120:
                    continue
                hay = (title + "\n" + body).lower()
                if kw.lower() not in hay and "gaji" not in hay and \
                        "pendapatan" not in hay and "penghasilan" not in hay:
                    continue
                rid_raw = href
                rid = md5_id("kontan", rid_raw)
                item = {
                    "id": rid,
                    "raw_id": rid_raw,
                    "platform": "kontan",
                    "lang": "id",
                    "title": title,
                    "body": body,
                    "author": author or "kontan.co.id",
                    "url": href,
                    "country_hint": "ID",
                    "matched_keyword": kw,
                    "engagement": {"score": 0, "comments": 0, "views": None},
                }
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
                fh.flush()
                written += 1
                print(f"  [kontan] +1 ({written}) {title[:80]}")
    return written


def _print_samples(path, label, n=3):
    if not os.path.exists(path):
        print(f"  ({label}) file missing: {path}")
        return 0
    lines = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                lines.append(line)
    total = len(lines)
    print(f"\n=== {label}: {total} lines @ {path}")
    for i, ln in enumerate(lines[:n], 1):
        try:
            obj = json.loads(ln)
        except Exception:
            print(f"  sample {i}: <unparseable>")
            continue
        title = obj.get("title", "")
        body = obj.get("body", "") or ""
        body_excerpt = body[:240].replace("\n", " ")
        print(f"  --- sample {i} ---")
        print(f"  url:   {obj.get('url','')}")
        print(f"  kw:    {obj.get('matched_keyword','')}")
        print(f"  title: {title}")
        print(f"  body:  {body_excerpt}{'…' if len(body) > 240 else ''}")
    return total


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"== detik.com -> {DETIK_OUT}")
    n_d = scrape_detik()
    print(f"== kontan.co.id -> {KONTAN_OUT}")
    n_k = scrape_kontan()
    print(f"\nDONE: detik={n_d} lines, kontan={n_k} lines, total={n_d + n_k}")
    t_d = _print_samples(DETIK_OUT, "detik", n=3)
    t_k = _print_samples(KONTAN_OUT, "kontan", n=3)
    print(f"\nFINAL: detik={t_d}, kontan={t_k}, combined={t_d + t_k}")


if __name__ == "__main__":
    main()
