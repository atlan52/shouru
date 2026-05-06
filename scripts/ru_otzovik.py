"""Otzovik.com (otzovik.com) — 俄语商品/服务评论抓取，过滤包含工资/收入相关词的内容。

Strategy:
  - Search URL: https://otzovik.com/?search_text=<keyword>
  - Search results give cards/links to individual review pages.
  - For each result we follow into the review page and extract title / body / author / rating.
  - Filter: only keep records whose title+body contain at least one income-related Russian
    keyword (зарплата, доход, заработок, фриланс, подработка, etc.). Drop obvious cosmetics /
    pure-product reviews that don't touch on income/employment.

Output: /Users/jan/sen/code/spider/shouru/data/raw/otzovik_native_<YYYYMMDD>.jsonl
"""
import datetime
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
BASE = "https://otzovik.com"
SEARCH_URL = "https://otzovik.com/"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
TIMEOUT = 25
SLEEP = 1.5

KEYWORDS = [
    "зарплата",
    "доход",
    "сколько зарабатываете",
    "фриланс",
    "подработка",
]

# For relevance filtering on individual review pages — the review must mention at least
# one of these income/employment terms. Cast a wider net than the search keywords so that
# a "salary" review under a bank/employer that uses synonyms (заработок, оклад…) is kept.
INCOME_TOKENS = [
    "зарплат",      # зарплата, зарплаты, зарплату...
    "доход",        # доход, доходы
    "заработ",      # заработок, зарабатываю, заработать
    "оклад",
    "получк",       # получка
    "фриланс",
    "подработ",     # подработка, подрабатывать
    "ваканс",       # вакансия
    "работодател",  # работодатель
    "работа",       # very broad — but combined with platform context this is OK
    "карьер",       # карьера, карьерный
    "финанс",       # финансы — bank/income contexts
]

# Hard exclude obvious-irrelevant categories often returned by the search.
EXCLUDE_TOKENS_TITLE = [
    "крем",       # cream
    "шампун",     # shampoo
    "помад",      # lipstick
    "тушь",       # mascara
    "духи",       # perfume
    "пельмен",    # dumplings
    "конфет",     # candy
    "печень",     # cookies
    "колбас",     # sausage
    "йогурт",
    "шоколад",
]

# Pages per keyword for the search listing
PAGES_PER_KW = 2


def headers():
    return {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
        "Referer": "https://otzovik.com/",
        "Cache-Control": "no-cache",
    }


def make_id(raw_id: str) -> str:
    return hashlib.md5(("otzovik:" + str(raw_id)).encode("utf-8")).hexdigest()[:16]


def fetch(url: str, params: dict | None = None) -> str | None:
    try:
        r = requests.get(url, headers=headers(), params=params, timeout=TIMEOUT)
    except Exception as e:
        print(f"  [otzovik] fetch err url={url} params={params}: {e}", file=sys.stderr)
        return None
    if r.status_code != 200:
        print(
            f"  [otzovik] status {r.status_code} url={url} params={params}",
            file=sys.stderr,
        )
        return None
    return r.text


def parse_search_listing(html: str) -> list[dict]:
    """Return list of {title, url} candidates from a search results page.

    Otzovik's search returns a mix of products / services / employers, each with
    a card linking to a category page or to a specific review. We try a few
    targeted selectors first, then fall back to a very broad div/article scan.
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    seen_urls: set[str] = set()

    # Targeted selectors first — Otzovik historically uses div.product-row,
    # div.search-results, div.item-product, etc.
    targeted = []
    targeted.extend(soup.select("div.product-row"))
    targeted.extend(soup.select("div.item-product"))
    targeted.extend(soup.select("div.product"))
    targeted.extend(soup.select("div.search-results .item"))
    targeted.extend(soup.select("li.search-result"))
    targeted.extend(soup.select("article"))

    # Broad fallback: any container whose class hints at product / item /
    # review / search-result.
    fallback = soup.find_all(
        ["div", "article", "li"],
        class_=re.compile(r"(product|item|review|search-result|card)", re.I),
    )

    candidates = list(targeted) + list(fallback)
    seen_ids: set[int] = set()
    for el in candidates:
        if id(el) in seen_ids:
            continue
        seen_ids.add(id(el))

        # Title: first h2/h3/a text
        title_el = (
            el.select_one("h2 a")
            or el.select_one("h3 a")
            or el.select_one("h2")
            or el.select_one("h3")
            or el.select_one("a.product-name")
            or el.select_one("a.item-name")
        )
        if title_el is not None:
            title = title_el.get_text(" ", strip=True)
        else:
            title = ""

        # URL: first a[href] pointing into otzovik.com (or relative)
        url = ""
        for a in el.find_all("a", href=True):
            href = a.get("href", "").strip()
            if not href:
                continue
            if href.startswith("#") or href.startswith("javascript:"):
                continue
            absolute = urljoin(BASE, href)
            if "otzovik.com" not in urlparse(absolute).netloc:
                continue
            url = absolute
            if not title:
                # use the link text as title fallback
                title = a.get_text(" ", strip=True)
            break

        if not title or not url:
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)

        out.append({"title": title[:300], "url": url})

    return out


_RATING_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
_INT_RE = re.compile(r"\d+")


def parse_review_page(html: str, url: str) -> dict | None:
    """Extract title / body / author / rating / counts from an Otzovik page.

    The same parser is used for individual review pages and for category /
    product pages (which are essentially aggregations of reviews — we just
    grab the first review block we see, or the main product description).
    """
    soup = BeautifulSoup(html, "html.parser")

    # --- Title ---------------------------------------------------------
    title_el = (
        soup.select_one("h1.review-title")
        or soup.select_one("h1.product-title")
        or soup.select_one("h1")
        or soup.select_one("title")
    )
    title = title_el.get_text(" ", strip=True) if title_el else ""

    # --- Body ----------------------------------------------------------
    body_el = (
        soup.select_one("div.review-body")
        or soup.select_one("div.review-body-wrap")
        or soup.select_one("div.review-text")
        or soup.select_one("div.product-description")
        or soup.select_one("article")
    )
    if body_el is None:
        # Broad fallback: every div whose class hints review/text and pick the
        # one with the most text.
        candidates = soup.find_all(
            "div", class_=re.compile(r"(review|description|content|text)", re.I)
        )
        if candidates:
            body_el = max(candidates, key=lambda el: len(el.get_text(strip=True)))

    if body_el is not None:
        body = body_el.get_text(" ", strip=True)
    else:
        # absolute last resort — full page text
        body = soup.get_text(" ", strip=True)

    body = body[:3000]

    # --- Author --------------------------------------------------------
    author_el = (
        soup.select_one("div.user-name a")
        or soup.select_one("a.user-login")
        or soup.select_one("span.user-login")
        or soup.select_one("a[href*='/profile/']")
        or soup.select_one("[class*=user-name]")
        or soup.select_one("[class*=username]")
    )
    author = author_el.get_text(" ", strip=True) if author_el else ""

    # --- Rating --------------------------------------------------------
    rating = 0
    rating_el = (
        soup.select_one("div.product-rating")
        or soup.select_one("div.rating-score")
        or soup.select_one("[class*=rating-value]")
        or soup.select_one("[class*=rating]")
    )
    if rating_el is not None:
        # Many Otzovik widgets put the numeric rating in a `title` attr or in
        # the inner text.
        cand = rating_el.get("title") or rating_el.get_text(" ", strip=True)
        m = _RATING_RE.search(cand or "")
        if m:
            try:
                rating = float(m.group(0).replace(",", "."))
                # store as int when whole, else keep float in JSON via cast
                rating = int(rating) if rating == int(rating) else rating
            except ValueError:
                rating = 0

    # --- Comments ------------------------------------------------------
    comments = 0
    comments_el = (
        soup.select_one("a.comments-count")
        or soup.select_one("[class*=comments-count]")
        or soup.select_one("[class*=comment-count]")
    )
    if comments_el is not None:
        m = _INT_RE.search(comments_el.get_text(" ", strip=True))
        if m:
            try:
                comments = int(m.group(0))
            except ValueError:
                pass

    # --- Views ---------------------------------------------------------
    views = 0
    views_el = (
        soup.select_one("div.review-info span.views")
        or soup.select_one("[class*=views-count]")
        or soup.select_one("[class*=view-count]")
        or soup.select_one("[class*=views]")
    )
    if views_el is not None:
        m = _INT_RE.search(views_el.get_text(" ", strip=True))
        if m:
            try:
                views = int(m.group(0))
            except ValueError:
                pass

    # --- raw_id --------------------------------------------------------
    # Otzovik review URLs look like /review_NNNNNNN.html
    raw_id = ""
    m = re.search(r"review_(\d+)", url)
    if m:
        raw_id = m.group(1)
    else:
        # fallback: last path segment
        path = urlparse(url).path.rstrip("/")
        raw_id = path.rsplit("/", 1)[-1] or url

    if not title and not body:
        return None

    return {
        "raw_id": raw_id,
        "title": title[:300],
        "body": body,
        "author": author[:120],
        "rating": rating,
        "comments": int(comments) if isinstance(comments, (int, float)) else 0,
        "views": int(views) if isinstance(views, (int, float)) else 0,
    }


def is_relevant(title: str, body: str) -> bool:
    """Keep only reviews that touch on income/work/employment."""
    blob = (title + " \n " + body).lower()
    if not any(tok in blob for tok in INCOME_TOKENS):
        return False
    # Title-level hard excludes for clearly off-topic cosmetics/food
    tlow = title.lower()
    if any(tok in tlow for tok in EXCLUDE_TOKENS_TITLE):
        # ...unless the body still makes it about income context
        # (rare; safer to drop)
        return False
    return True


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    today = datetime.datetime.now().strftime("%Y%m%d")
    out_path = os.path.join(OUT_DIR, f"otzovik_native_{today}.jsonl")

    seen_ids: set[str] = set()
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    seen_ids.add(json.loads(line)["id"])
                except Exception:
                    pass

    total = 0
    with open(out_path, "a", encoding="utf-8") as out:
        for kw in KEYWORDS:
            for page in range(1, PAGES_PER_KW + 1):
                params = {"search_text": kw}
                if page > 1:
                    params["page"] = page
                print(f"[otzovik] search kw={kw!r} p{page}", flush=True)
                html = fetch(SEARCH_URL, params=params)
                time.sleep(SLEEP)
                if not html:
                    continue
                listings = parse_search_listing(html)
                print(
                    f"  -> listings parsed: {len(listings)}",
                    flush=True,
                )
                added_this_kw_page = 0
                for item in listings:
                    title0 = item["title"]
                    url = item["url"]

                    # Quick title filter — drop blatantly off-topic cosmetics /
                    # food before spending an HTTP round-trip on it.
                    tlow = title0.lower()
                    if any(tok in tlow for tok in EXCLUDE_TOKENS_TITLE):
                        continue

                    raw_id_guess = ""
                    m = re.search(r"review_(\d+)", url)
                    if m:
                        raw_id_guess = m.group(1)
                    else:
                        raw_id_guess = url
                    rid = make_id(raw_id_guess)
                    if rid in seen_ids:
                        continue

                    detail_html = fetch(url)
                    time.sleep(SLEEP)
                    if not detail_html:
                        continue
                    parsed = parse_review_page(detail_html, url)
                    if parsed is None:
                        continue

                    title = parsed["title"] or title0
                    body = parsed["body"]
                    if not is_relevant(title, body):
                        continue

                    rec = {
                        "id": rid,
                        "raw_id": parsed["raw_id"] or raw_id_guess,
                        "platform": "otzovik",
                        "lang": "ru",
                        "title": title,
                        "body": body,
                        "author": parsed["author"],
                        "url": url,
                        "country_hint": "RU",
                        "matched_keyword": kw,
                        "engagement": {
                            "score": parsed["rating"],
                            "comments": parsed["comments"],
                            "views": parsed["views"],
                        },
                    }
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    out.flush()
                    seen_ids.add(rid)
                    total += 1
                    added_this_kw_page += 1

                print(
                    f"  -> kept {added_this_kw_page}, total {total}",
                    flush=True,
                )

    # Count + sample
    line_count = 0
    titles: list[str] = []
    with open(out_path, "r", encoding="utf-8") as f:
        for line in f:
            line_count += 1
            try:
                t = json.loads(line).get("title", "")
                if t:
                    titles.append(t)
            except Exception:
                pass

    print(f"[otzovik] DONE total_lines={line_count} new_added={total} file={out_path}")
    print("[otzovik] SAMPLES:")
    for t in titles[:5]:
        print("  -", t)


if __name__ == "__main__":
    main()
