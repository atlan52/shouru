"""Kaskus.co.id crawler — biggest Indonesian general-discussion forum.

Kaskus runs a custom (vBulletin-derived) engine. Two forums of interest:
  - /forum/118  The Lounge (general chat — many gaji threads)
  - /forum/57   Money & Finance

Strategy:
  1. For each kw in INCOME_KEYWORDS["id"] + Indonesian salary idioms,
     search via https://www.kaskus.co.id/search/posts?q=<kw>
     across PAGES_PER_QUERY pages.
  2. For each thread link (/thread/<id>/<slug> or /show_post/<id>),
     fetch the thread page and pull title, OP body+author, replies, views.
  3. Filter via is_on_topic(..., lang="id").
  4. Fallback: walk /forum/118 and /forum/57.
"""
import re
import time
import requests
from urllib.parse import quote_plus, urljoin, urlparse
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


PLATFORM = "kaskus"
BASE = "https://www.kaskus.co.id"
SEARCH_URL = BASE + "/search/posts?q={kw}"

EXTRA_KEYWORDS_ID = [
    "gaji ideal", "berapa pendapatanmu", "kerja sampingan",
    "gaji UMR", "gaji fresh graduate", "passive income",
]

FALLBACK_BOARDS = [
    "/forum/118",  # The Lounge
    "/forum/57",   # Money & Finance
]

BOT_MARKERS = ("captcha", "are you a human", "access denied",
               "cf-browser-verification", "checking your browser",
               "attention required")


class KaskusError(Exception):
    pass


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _headers() -> dict:
    h = default_headers("id-ID,id;q=0.9,en;q=0.6")
    h["User-Agent"] = random_ua()
    h["Referer"] = BASE + "/"
    return h


def fetch_html(url: str, timeout: int = 30) -> str:
    try:
        r = requests.get(url, headers=_headers(), timeout=timeout, allow_redirects=True)
    except Exception as e:
        raise KaskusError(f"net err {url}: {e}")
    if r.status_code in (403, 429):
        raise KaskusError(f"{r.status_code} on {url}")
    if r.status_code != 200:
        raise KaskusError(f"status {r.status_code} on {url}")
    if not r.encoding:
        r.encoding = "utf-8"
    body = r.text or ""
    low = body.lower()
    if any(m in low for m in BOT_MARKERS):
        raise KaskusError("bot-block / captcha")
    return body


def fetch_with_retry(url: str) -> str:
    try:
        return fetch_html(url)
    except KaskusError as e:
        msg = str(e)
        if "403" in msg or "429" in msg or "bot-block" in msg:
            print(f"  [{PLATFORM}] backoff 30s on {url}")
            time.sleep(30)
            return fetch_html(url)
        raise


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
# Thread URLs on Kaskus look like /thread/<numeric-id>/<slug>
# Sometimes /show_post/<id> for individual posts.
_THREAD_HREF_RE = re.compile(r"^/thread/(\d+)(?:/([^/?#]+))?", re.IGNORECASE)


def _abs(href: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return urljoin(BASE + "/", href.lstrip("/"))


def _text_of(el) -> str:
    if not el:
        return ""
    return el.get_text(" ", strip=True)


def _parse_int(s: str) -> int:
    if not s:
        return 0
    s = s.replace(",", "").replace(".", "").strip().lower()
    m = re.match(r"([\d]+)\s*([km]?)", s)
    if not m:
        return 0
    try:
        v = float(m.group(1))
    except ValueError:
        return 0
    suf = m.group(2)
    if suf == "k":
        v *= 1_000
    elif suf == "m":
        v *= 1_000_000
    return int(v)


def parse_search_results(html: str):
    """Extract /thread/<id> links + titles from a search/board listing."""
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        path = href
        if href.startswith("http"):
            p = urlparse(href)
            if "kaskus.co.id" not in p.netloc:
                continue
            path = p.path
        path = path.split("?")[0].split("#")[0]
        m = _THREAD_HREF_RE.match(path)
        if not m:
            continue
        tid = m.group(1)
        slug = m.group(2) or ""
        if tid in seen:
            continue
        title = _text_of(a)
        if not title or len(title) < 4:
            continue
        seen.add(tid)
        out.append({
            "thread_id": tid,
            "slug": slug,
            "url": _abs(f"/thread/{tid}" + (f"/{slug}" if slug else "")),
            "title": title,
        })
    return out


def parse_thread(html: str, fallback_title: str = "") -> dict:
    """Pull title, OP body+author, reply/view counts from a thread page."""
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title = ""
    for sel in ("h1.thread-title", "h1.title-thread", "h1.title", "h1",
                "div.thread-title", "title"):
        el = soup.select_one(sel)
        if el:
            title = _text_of(el)
            if title:
                break
    if not title:
        title = fallback_title
    title = re.sub(r"\s*-\s*KASKUS\s*$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*\|\s*KASKUS\s*$", "", title, flags=re.IGNORECASE)

    # Posts. Kaskus uses .thread-content-post / .post-detail wrappers.
    post_selectors = (
        "div.post-list .post-list-item",
        "article.post",
        "div.post-detail",
        "div.thread-content-post",
        "li.post",
        "div.entry-content",
    )
    posts = []
    for sel in post_selectors:
        posts = soup.select(sel)
        if posts:
            break

    op_body = ""
    op_author = ""
    if posts:
        first = posts[0]
        msg_el = (first.select_one(".post-content")
                  or first.select_one(".entry")
                  or first.select_one("[class*='post-body']")
                  or first.select_one(".message")
                  or first)
        op_body = _text_of(msg_el)
        a_el = (first.select_one(".username a")
                or first.select_one("a.username")
                or first.select_one(".author a")
                or first.select_one("[class*='username']"))
        op_author = _text_of(a_el)

    # Engagement — Kaskus shows "Replies: N" / "Views: N" style indicators.
    views = 0
    reply_count = max(0, len(posts) - 1) if posts else 0
    page_text = soup.get_text(" ", strip=True)
    for pat in (r"views?\s*[:.]?\s*([\d.,]+\s*[kKmM]?)",
                r"dilihat\s*[:.]?\s*([\d.,]+\s*[kKmM]?)",
                r"tayangan\s*[:.]?\s*([\d.,]+\s*[kKmM]?)"):
        m = re.search(pat, page_text, re.IGNORECASE)
        if m:
            views = max(views, _parse_int(m.group(1)))
            break
    for pat in (r"repl(?:ies|y)\s*[:.]?\s*([\d.,]+\s*[kKmM]?)",
                r"balasan\s*[:.]?\s*([\d.,]+\s*[kKmM]?)",
                r"komentar\s*[:.]?\s*([\d.,]+\s*[kKmM]?)"):
        m = re.search(pat, page_text, re.IGNORECASE)
        if m:
            reply_count = max(reply_count, _parse_int(m.group(1)))
            break

    return {
        "title": title,
        "author": op_author,
        "op_body": op_body,
        "views": views,
        "reply_count": reply_count,
    }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def search_url(kw: str, page: int) -> str:
    base = SEARCH_URL.format(kw=quote_plus(kw))
    if page > 1:
        return f"{base}&page={page}"
    return base


def board_url(board_path: str, page: int) -> str:
    if page > 1:
        return f"{BASE}{board_path}?page={page}"
    return f"{BASE}{board_path}"


def process_thread(meta: dict, kw: str, state: State) -> bool:
    rid = meta["thread_id"]
    our_id = make_id(PLATFORM, rid)
    if state.is_seen(our_id):
        return False

    try:
        html = fetch_with_retry(meta["url"])
    except KaskusError as e:
        print(f"  [{PLATFORM}] thread {rid} err: {e}")
        state.mark_seen(our_id)
        return False

    parsed = parse_thread(html, fallback_title=meta.get("title", ""))
    title = parsed["title"] or meta.get("title", "")
    op_body = parsed["op_body"] or ""

    if not is_on_topic(title, op_body, lang="id"):
        state.mark_seen(our_id)
        return False

    item = {
        "id": our_id,
        "raw_id": rid,
        "platform": PLATFORM,
        "lang": "id",
        "title": title,
        "body": op_body[:5000],
        "author": parsed["author"],
        "url": meta["url"],
        "country_hint": "ID",
        "engagement": {
            "score": parsed["views"],
            "comments": parsed["reply_count"],
            "views": parsed["views"],
        },
        "matched_keyword": kw,
    }
    append_jsonl(item, PLATFORM, RAW_DIR)
    state.mark_seen(our_id)
    return True


def run():
    state = State(PLATFORM)
    preload_seen(state, PLATFORM, key_field="id")
    budget = TimeBudget(PLATFORM_TIME_BUDGET_SEC)
    items_added = 0

    keywords = list(INCOME_KEYWORDS.get("id", [])) + EXTRA_KEYWORDS_ID

    try:
        for kw in keywords:
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

            for page in range(start_page, start_page + PAGES_PER_QUERY):
                if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                    break
                url = search_url(kw, page)
                try:
                    html = fetch_with_retry(url)
                except KaskusError as e:
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
                        if process_thread(meta, kw, state):
                            items_added += 1
                            if items_added % 25 == 0:
                                print(f"  [{PLATFORM}] +{items_added} so far")
                    except KaskusError as e:
                        print(f"  [{PLATFORM}] process err: {e}")
                    state.maybe_save(every=10)
                    polite_sleep()

                state.set_cursor(kw, page + 1)
                polite_sleep()

            if not had_error:
                state.mark_kw_done(kw)
            state.save()
            polite_sleep()

        # Fallback: walk the-lounge + money-finance
        if items_added < PER_PLATFORM_LIMIT and not budget.expired():
            for board in FALLBACK_BOARDS:
                if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                    break
                board_label = f"board:{board}"
                if state.is_kw_done(board_label):
                    continue
                print(f"[{PLATFORM}] board {board}")
                start_page = state.get_cursor(board_label, 1) or 1
                had_error = False
                for page in range(start_page, start_page + PAGES_PER_QUERY):
                    if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                        break
                    url = board_url(board, page)
                    try:
                        html = fetch_with_retry(url)
                    except KaskusError as e:
                        print(f"  [{PLATFORM}] board {board} p{page} err: {e}")
                        had_error = True
                        break
                    hits = parse_search_results(html)
                    if not hits:
                        break
                    for meta in hits:
                        if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                            break
                        try:
                            if process_thread(meta, board_label, state):
                                items_added += 1
                                if items_added % 25 == 0:
                                    print(f"  [{PLATFORM}] +{items_added} so far")
                        except KaskusError as e:
                            print(f"  [{PLATFORM}] process err: {e}")
                        state.maybe_save(every=10)
                        polite_sleep()
                    state.set_cursor(board_label, page + 1)
                    polite_sleep()
                if not had_error:
                    state.mark_kw_done(board_label)
                state.save()
    finally:
        state.save(force=True)

    print(f"[{PLATFORM}] done, +{items_added} items this run")


if __name__ == "__main__":
    run()
