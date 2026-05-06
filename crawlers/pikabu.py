"""Pikabu crawler — pikabu.ru, the Russian Reddit clone.

Strategy:
  - For each Russian income keyword, walk the search endpoint:
      https://pikabu.ru/search?q=<kw>&t=2 (recent posts)
    paging through PAGES_PER_QUERY pages via &page=N.
  - Each story link looks like /story/<slug>_<postId>. We extract the
    post-id, title, lead body snippet, author, ratings, and comment count
    from the search-result card. For richer text we optionally fetch the
    canonical /story/<slug>_<postId> page.
  - Filter via is_on_topic(..., lang="ru"). Country tag = "RU".
  - Polite: 1.5s minimum between requests (RU sites are mildly aggressive
    about anti-bot).
"""
import re
import time
import requests
from urllib.parse import quote_plus, urljoin
from bs4 import BeautifulSoup

from config import (
    INCOME_KEYWORDS, PER_PLATFORM_LIMIT, PAGES_PER_QUERY, RAW_DIR,
    PLATFORM_TIME_BUDGET_SEC,
)
from crawlers.common import (
    append_jsonl, make_id, is_on_topic, polite_sleep, preload_seen,
    default_headers, random_ua, TimeBudget,
)
from crawlers.state import State


PLATFORM = "pikabu"
BASE = "https://pikabu.ru"
SEARCH_URL = BASE + "/search?q={kw}&t=2"  # t=2 = recent posts

BOT_MARKERS = (
    "captcha", "проверка", "запрос заблокирован", "доступ ограничен",
    "are you a human", "access denied", "cf-browser-verification",
)


class PikabuError(Exception):
    pass


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _headers() -> dict:
    h = default_headers(accept_lang="ru-RU,ru;q=0.9,en;q=0.6")
    h["User-Agent"] = random_ua()
    h["Referer"] = BASE + "/"
    return h


def fetch_html(url: str, timeout: int = 30) -> str:
    try:
        r = requests.get(url, headers=_headers(), timeout=timeout, allow_redirects=True)
    except Exception as e:
        raise PikabuError(f"net err {url}: {e}")
    if r.status_code in (403, 429):
        raise PikabuError(f"{r.status_code} on {url}")
    if r.status_code != 200:
        raise PikabuError(f"status {r.status_code} on {url}")
    body = r.text or ""
    low = body.lower()
    if any(m in low for m in BOT_MARKERS):
        raise PikabuError("bot-block / captcha")
    return body


def fetch_with_retry(url: str) -> str:
    try:
        return fetch_html(url)
    except PikabuError as e:
        msg = str(e)
        if "403" in msg or "429" in msg:
            print(f"  [{PLATFORM}] backoff 30s on {url}")
            time.sleep(30)
            return fetch_html(url)
        raise


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
_STORY_HREF_RE = re.compile(r"/story/([^/?#]+)_(\d+)")


def _text_of(el) -> str:
    if not el:
        return ""
    return el.get_text(" ", strip=True)


def _parse_int(s: str) -> int:
    if not s:
        return 0
    s = s.replace("\xa0", "").replace(",", "").replace(" ", "").strip().lower()
    m = re.match(r"(-?[\d.]+)\s*([kкmм]?)", s)
    if not m:
        return 0
    try:
        v = float(m.group(1))
    except ValueError:
        return 0
    suf = m.group(2)
    if suf in ("k", "к"):
        v *= 1_000
    elif suf in ("m", "м"):
        v *= 1_000_000
    return int(v)


def parse_search_results(html: str):
    """Extract story cards from a Pikabu search page.

    Pikabu wraps each story in an `article.story` element. Within it we
    find the title link `a.story__title-link`, the body lead text inside
    `.story-block_type_text` blocks, the author at `.story__user-link`,
    rating at `.story__rating-count`, and comments at `.story__comments-link-count`.
    Tolerant fallback: any `a[href*='/story/']` whose href matches our regex.
    """
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()

    articles = soup.select("article.story") or soup.select("article")
    for art in articles:
        a = art.select_one("a.story__title-link") or art.select_one("a[href*='/story/']")
        if not a or not a.get("href"):
            continue
        href = a["href"]
        m = _STORY_HREF_RE.search(href)
        if not m:
            continue
        slug = m.group(1)
        post_id = m.group(2)
        if post_id in seen:
            continue
        seen.add(post_id)

        title = _text_of(a) or _text_of(art.select_one(".story__title"))
        if not title:
            continue

        # Body snippet
        body_parts = []
        for blk in art.select(".story-block_type_text, .story__content-inner .story-block"):
            t = _text_of(blk)
            if t and len(t) > 20:
                body_parts.append(t)
        body_snippet = " ".join(body_parts)[:1500]

        # Author
        author = _text_of(art.select_one("a.story__user-link, .story__user a"))

        # Rating
        rating = 0
        rt = art.select_one(".story__rating-count, [class*='rating-count']")
        if rt:
            rating = _parse_int(_text_of(rt))

        # Comments
        comments = 0
        cm = art.select_one(".story__comments-link-count, [class*='comments-link-count']")
        if cm:
            comments = _parse_int(_text_of(cm))

        url = href if href.startswith("http") else urljoin(BASE + "/", href)
        out.append({
            "post_id": post_id,
            "slug": slug,
            "url": url,
            "title": title,
            "body_snippet": body_snippet,
            "author": author,
            "rating": rating,
            "comments": comments,
        })

    # Fallback sweep — generic anchor scan
    if not out:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            m = _STORY_HREF_RE.search(href)
            if not m:
                continue
            slug = m.group(1)
            post_id = m.group(2)
            if post_id in seen:
                continue
            seen.add(post_id)
            title = _text_of(a)
            if not title:
                continue
            url = href if href.startswith("http") else urljoin(BASE + "/", href)
            out.append({
                "post_id": post_id,
                "slug": slug,
                "url": url,
                "title": title,
                "body_snippet": "",
                "author": "",
                "rating": 0,
                "comments": 0,
            })
    return out


def parse_story_page(html: str) -> dict:
    """Extract richer body + counts from a /story/<slug>_<id> page."""
    soup = BeautifulSoup(html, "html.parser")
    title = _text_of(soup.select_one("h1.story__title, h1"))
    body_parts = []
    for blk in soup.select(".story-block_type_text, .story__content-inner .story-block, article .story__main"):
        t = _text_of(blk)
        if t and len(t) > 20:
            body_parts.append(t)
    body = "\n\n".join(body_parts)[:5000]

    author = _text_of(soup.select_one("a.story__user-link, .story__user a"))

    rating = 0
    rt = soup.select_one(".story__rating-count, [class*='rating-count']")
    if rt:
        rating = _parse_int(_text_of(rt))

    comments = 0
    cm = soup.select_one(".story__comments-link-count, [class*='comments-link-count']")
    if cm:
        comments = _parse_int(_text_of(cm))

    return {
        "title": title,
        "body": body,
        "author": author,
        "rating": rating,
        "comments": comments,
    }


# ---------------------------------------------------------------------------
# Per-keyword runner
# ---------------------------------------------------------------------------
def search_url(kw: str, page: int) -> str:
    base = SEARCH_URL.format(kw=quote_plus(kw))
    if page > 1:
        return f"{base}&page={page}"
    return base


def process_card(card: dict, kw: str, state: State) -> bool:
    rid = card["post_id"]
    our_id = make_id(PLATFORM, rid)
    if state.is_seen(our_id):
        return False

    title = card.get("title", "")
    body = card.get("body_snippet", "")
    author = card.get("author", "")
    rating = card.get("rating", 0)
    comments = card.get("comments", 0)

    # If snippet is thin, attempt full /story page for richer body.
    if len(body) < 200:
        try:
            html = fetch_with_retry(card["url"])
            parsed = parse_story_page(html)
            if parsed["body"]:
                body = parsed["body"]
            if parsed["title"]:
                title = parsed["title"]
            if parsed["author"]:
                author = parsed["author"]
            if parsed["rating"]:
                rating = parsed["rating"]
            if parsed["comments"]:
                comments = parsed["comments"]
        except PikabuError as e:
            print(f"  [{PLATFORM}] story {rid} fetch err: {e}")
            # fall through with snippet-only data

    if not is_on_topic(title, body, lang="ru"):
        state.mark_seen(our_id)
        return False

    item = {
        "id": our_id,
        "raw_id": rid,
        "platform": PLATFORM,
        "lang": "ru",
        "country_hint": "RU",
        "title": title,
        "body": body[:5000],
        "author": author,
        "url": card["url"],
        "engagement": {
            "score": rating,
            "comments": comments,
        },
        "matched_keyword": kw,
    }
    append_jsonl(item, PLATFORM, RAW_DIR)
    state.mark_seen(our_id)
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run():
    state = State(PLATFORM)
    preload_seen(state, PLATFORM, key_field="id")
    budget = TimeBudget(PLATFORM_TIME_BUDGET_SEC)
    items_added = 0

    pages_to_walk = max(1, min(PAGES_PER_QUERY, 3))

    try:
        for kw in INCOME_KEYWORDS["ru"]:
            if budget.expired():
                print(f"[{PLATFORM}] time budget expired")
                break
            if state.is_kw_done(kw):
                continue
            if items_added >= PER_PLATFORM_LIMIT:
                break

            print(f"[{PLATFORM}] kw {kw}")
            start_page = state.get_cursor(kw, 1) or 1
            had_error = False

            for page in range(start_page, start_page + pages_to_walk):
                if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                    break
                url = search_url(kw, page)
                try:
                    html = fetch_with_retry(url)
                except PikabuError as e:
                    print(f"  [{PLATFORM}] search {kw} p{page} err: {e}")
                    had_error = True
                    break

                cards = parse_search_results(html)
                if not cards:
                    break

                for card in cards:
                    if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                        break
                    try:
                        if process_card(card, kw, state):
                            items_added += 1
                            if items_added % 25 == 0:
                                print(f"  [{PLATFORM}] +{items_added} so far")
                    except PikabuError as e:
                        print(f"  [{PLATFORM}] process err: {e}")
                    state.maybe_save(every=10)
                    polite_sleep(1500, 2500)

                state.set_cursor(kw, page + 1)
                polite_sleep(1500, 2500)

            if not had_error:
                state.mark_kw_done(kw)
            state.save()
            polite_sleep(1500, 2500)
    finally:
        state.save(force=True)

    print(f"[{PLATFORM}] done, +{items_added} items this run")


if __name__ == "__main__":
    run()
