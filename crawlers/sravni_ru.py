"""Sravni.ru forum crawler — Russian financial-comparison site with a
sizable user forum (mostly banking, credit, investment, mortgages).

Strategy:
  - Search endpoint:
      https://www.sravni.ru/forum/search/?query=<kw>&search_type=posts
    paginated 2-3 pages per keyword.
  - For each topic card we extract topicId, title, OP body, author,
    view_count, reply_count, URL.
  - Filter via is_on_topic(..., lang="ru"). Country tag = "RU".

No auth. Polite ≥1.5s between requests.
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


PLATFORM = "sravni_ru"
BASE = "https://www.sravni.ru"
FORUM_BASE = BASE + "/forum"
SEARCH_URL = FORUM_BASE + "/search/?query={kw}&search_type=posts"

EXTRA_KEYWORDS = ["банк", "кредит", "инвестиции", "ипотека"]

BOT_MARKERS = (
    "captcha", "проверка", "запрос заблокирован", "доступ ограничен",
    "are you a human", "access denied", "cf-browser-verification",
)


class SravniError(Exception):
    pass


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _headers() -> dict:
    h = default_headers(accept_lang="ru-RU,ru;q=0.9,en;q=0.6")
    h["User-Agent"] = random_ua()
    h["Referer"] = FORUM_BASE + "/"
    return h


def fetch_html(url: str, timeout: int = 30) -> str:
    try:
        r = requests.get(url, headers=_headers(), timeout=timeout, allow_redirects=True)
    except Exception as e:
        raise SravniError(f"net err {url}: {e}")
    if r.status_code in (403, 429):
        raise SravniError(f"{r.status_code} on {url}")
    if r.status_code != 200:
        raise SravniError(f"status {r.status_code} on {url}")
    body = r.text or ""
    low = body.lower()
    if any(m in low for m in BOT_MARKERS):
        raise SravniError("bot-block / captcha")
    return body


def fetch_with_retry(url: str) -> str:
    try:
        return fetch_html(url)
    except SravniError as e:
        msg = str(e)
        if "403" in msg or "429" in msg:
            print(f"  [{PLATFORM}] backoff 30s on {url}")
            time.sleep(30)
            return fetch_html(url)
        raise


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
_TOPIC_HREF_RE = re.compile(r"/forum/(?:topic|tema|posts)/([A-Za-z0-9_\-]+)")


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
    """Extract topic links from a sravni.ru forum search page.

    Sravni's forum HTML structure varies; we sweep generic anchor patterns
    pointing at /forum/topic/<id> or /forum/posts/<id> and dedupe on id.
    """
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = _TOPIC_HREF_RE.search(href)
        if not m:
            continue
        rid = m.group(1)
        if rid in seen:
            continue
        seen.add(rid)
        title = _text_of(a)
        if not title or len(title) < 4:
            continue
        url = href if href.startswith("http") else urljoin(BASE, href)
        # Try to find a parent card container for richer metadata
        parent = a.find_parent(["article", "div", "li"]) or a
        snippet = ""
        for sel in ("[class*='snippet']", "[class*='preview']", "[class*='text']", "p"):
            el = parent.select_one(sel)
            if el and el is not a:
                t = _text_of(el)
                if t and len(t) > 30:
                    snippet = t
                    break
        out.append({
            "topic_id": rid,
            "url": url,
            "title": title,
            "snippet": snippet,
        })
    return out


def parse_topic_page(html: str):
    """Extract OP body, author, view/reply counts from a topic page."""
    soup = BeautifulSoup(html, "html.parser")
    title = _text_of(soup.select_one("h1"))

    # OP block — heuristic: first .post / .message / [class*='Post_'] block
    op_body = ""
    op_author = ""
    posts = soup.select(
        ".post, .message, [class*='Post_'], [class*='message'], [class*='Message_'], "
        "article[class*='post'], div[class*='topic-post']"
    )
    if posts:
        first = posts[0]
        body_el = (first.select_one("[class*='body'], [class*='content'], .text, p")
                   or first)
        op_body = _text_of(body_el)
        author_el = first.select_one("[class*='author'], [class*='user'], a[href*='/users/']")
        op_author = _text_of(author_el)

    if not op_body:
        # Fallback: pick the largest <p>/<div> blob in the article body
        candidates = soup.select("article p, .topic p, .topic__body, [class*='topic'] p")
        if candidates:
            best = max(candidates, key=lambda el: len(_text_of(el)))
            op_body = _text_of(best)

    # View / reply counts
    view_count = 0
    reply_count = 0
    for el in soup.select("[class*='views'], [class*='view-count'], [class*='counter']"):
        t = _text_of(el).lower()
        if not t:
            continue
        if "просмотр" in t or "view" in t:
            m = re.search(r"([\d\s.,kкmм]+)", t)
            if m:
                view_count = max(view_count, _parse_int(m.group(1)))
        elif "ответ" in t or "коммент" in t or "reply" in t:
            m = re.search(r"([\d\s.,kкmм]+)", t)
            if m:
                reply_count = max(reply_count, _parse_int(m.group(1)))

    if reply_count == 0 and posts:
        reply_count = max(0, len(posts) - 1)

    return {
        "title": title,
        "op_body": op_body,
        "op_author": op_author,
        "view_count": view_count,
        "reply_count": reply_count,
    }


# ---------------------------------------------------------------------------
# Per-keyword runner
# ---------------------------------------------------------------------------
def search_url(kw: str, page: int) -> str:
    base = SEARCH_URL.format(kw=quote_plus(kw))
    if page > 1:
        return f"{base}&page={page}"
    return base


def process_topic(meta: dict, kw: str, state: State) -> bool:
    rid = meta["topic_id"]
    our_id = make_id(PLATFORM, rid)
    if state.is_seen(our_id):
        return False

    title = meta.get("title", "")
    body = meta.get("snippet", "")
    author = ""
    view_count = 0
    reply_count = 0

    if len(body) < 200:
        try:
            html = fetch_with_retry(meta["url"])
            parsed = parse_topic_page(html)
            if parsed["title"]:
                title = parsed["title"]
            if parsed["op_body"]:
                body = parsed["op_body"]
            author = parsed["op_author"]
            view_count = parsed["view_count"]
            reply_count = parsed["reply_count"]
        except SravniError as e:
            print(f"  [{PLATFORM}] topic {rid} err: {e}")
            # fall through with what we have

    if not is_on_topic(title, body, lang="ru"):
        state.mark_seen(our_id)
        return False

    item = {
        "id": our_id,
        "raw_id": rid,
        "platform": PLATFORM,
        "subtype": "forum_topic",
        "lang": "ru",
        "country_hint": "RU",
        "title": title,
        "body": body[:5000],
        "author": author,
        "url": meta["url"],
        "engagement": {
            "score": view_count,
            "comments": reply_count,
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
    keywords = list(INCOME_KEYWORDS["ru"]) + EXTRA_KEYWORDS
    seen_kw = set()
    keywords = [k for k in keywords if not (k in seen_kw or seen_kw.add(k))]

    try:
        for kw in keywords:
            if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                break
            if state.is_kw_done(kw):
                continue

            print(f"[{PLATFORM}] kw {kw}")
            start_page = state.get_cursor(kw, 1) or 1
            had_error = False

            for page in range(start_page, start_page + pages_to_walk):
                if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                    break
                url = search_url(kw, page)
                try:
                    html = fetch_with_retry(url)
                except SravniError as e:
                    print(f"  [{PLATFORM}] search {kw} p{page} err: {e}")
                    had_error = True
                    break

                hits = parse_search_results(html)
                if not hits:
                    break

                for meta in hits:
                    if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                        break
                    try:
                        if process_topic(meta, kw, state):
                            items_added += 1
                            if items_added % 25 == 0:
                                print(f"  [{PLATFORM}] +{items_added} so far")
                    except SravniError as e:
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
