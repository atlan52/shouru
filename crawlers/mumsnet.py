"""Mumsnet.com /Talk forum crawler.

UK parenting + lifestyle community. The /Talk subdomains include:
  - /talk/_aibu                Am I being unreasonable (income/lifestyle vents)
  - /talk/_money_matters       money & saving
  - /talk/_employment_issues   work + pay

Public, no auth — but Mumsnet is known to deploy bot-detection (Cloudflare,
custom UA blocks). We rotate UAs and sleep politely between requests.

Strategy:
  1. For each en income keyword, walk
       https://www.mumsnet.com/search?q=<kw>&product=talk
     across PAGES_PER_QUERY pages.
  2. For each thread link, fetch the thread page; pull title, OP body,
     author and rough engagement numbers (views/replies if present).
  3. Filter via is_on_topic(..., lang="en"). Tag country_hint="GB".
  4. Fallback browsing of the three boards above if search is rate-limited.
  5. Backoff 30s + retry once on 403/429, else mark keyword done.
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


PLATFORM = "mumsnet"
BASE = "https://www.mumsnet.com"
SEARCH_URL = BASE + "/search?q={kw}&product=talk"

FALLBACK_BOARDS = [
    "/talk/_aibu",
    "/talk/_money_matters",
    "/talk/_employment_issues",
]

BOT_MARKERS = ("unusual traffic", "captcha", "are you a human", "access denied",
               "cf-browser-verification", "checking your browser",
               "attention required", "please enable javascript")


class MumsnetError(Exception):
    pass


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _headers() -> dict:
    h = default_headers("en-GB,en;q=0.9")
    h["User-Agent"] = random_ua()
    h["Referer"] = BASE + "/"
    return h


def fetch_html(url: str, timeout: int = 30) -> str:
    try:
        r = requests.get(url, headers=_headers(), timeout=timeout, allow_redirects=True)
    except Exception as e:
        raise MumsnetError(f"net err {url}: {e}")
    if r.status_code in (403, 429):
        raise MumsnetError(f"{r.status_code} on {url}")
    if r.status_code != 200:
        raise MumsnetError(f"status {r.status_code} on {url}")
    body = r.text or ""
    low = body.lower()
    if any(m in low for m in BOT_MARKERS):
        raise MumsnetError("bot-block / captcha")
    return body


def fetch_with_retry(url: str) -> str:
    try:
        return fetch_html(url)
    except MumsnetError as e:
        msg = str(e)
        if "403" in msg or "429" in msg or "bot-block" in msg:
            print(f"  [{PLATFORM}] backoff 30s on {url}")
            time.sleep(30)
            return fetch_html(url)
        raise


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
# Mumsnet thread URLs typically look like /talk/<board>/<numeric-id>-slug
# or /talk/<board>/<slug-with-id>.
_TALK_HREF_RE = re.compile(r"^/talk/([a-z0-9_]+)/([\w\-]+)$", re.IGNORECASE)


def _abs(href: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return urljoin(BASE + "/", href)


def _text_of(el) -> str:
    if not el:
        return ""
    return el.get_text(" ", strip=True)


def _parse_int(s: str) -> int:
    if not s:
        return 0
    s = s.replace(",", "").strip().lower()
    m = re.match(r"([\d.]+)\s*([km]?)", s)
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
    """Extract /talk/<board>/<slug> thread links from search/board HTML."""
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Strip query/fragment for the URL match
        path = urlparse(href).path if href.startswith("http") else href.split("#")[0].split("?")[0]
        m = _TALK_HREF_RE.match(path)
        if not m:
            continue
        board = m.group(1)
        slug = m.group(2)
        # Skip board-index links (slug looks like a numeric page or has no dash)
        if slug.startswith("page") or slug.isdigit():
            continue
        # Skip the board-listing pseudo-slugs that begin with underscore
        if slug.startswith("_"):
            continue
        key = f"{board}/{slug}"
        if key in seen:
            continue
        seen.add(key)
        url = _abs(f"/talk/{board}/{slug}")
        title = _text_of(a)
        if not title or len(title) < 4:
            continue
        out.append({
            "thread_id": key,
            "board": board,
            "slug": slug,
            "url": url,
            "title": title,
        })
    return out


def parse_thread(html: str, fallback_title: str = "") -> dict:
    """Pull title, OP body+author, reply count, view count, first 5 replies."""
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title = ""
    for sel in ("h1.thread-title", "h1[class*='Thread']", "h1.heading-1", "h1"):
        el = soup.select_one(sel)
        if el:
            title = _text_of(el)
            if title:
                break
    if not title:
        title = fallback_title

    # Posts. Mumsnet markup has shifted over years; cover several variants.
    post_selectors = (
        "div.lia-message-view",     # legacy Lithium-style
        "div.thread-message",        # newer Mumsnet
        "article.message",
        "div[class*='Message_']",
        "li.message",
        "div.post",
    )
    posts = []
    for sel in post_selectors:
        posts = soup.select(sel)
        if posts:
            break

    op_body = ""
    op_author = ""
    replies = []
    for i, p in enumerate(posts):
        msg_el = (p.select_one(".message-body") or p.select_one(".post-body")
                  or p.select_one("[class*='MessageBody']")
                  or p.select_one(".lia-message-body-content")
                  or p.select_one("[class*='message-content']")
                  or p)
        text = _text_of(msg_el)
        if not text:
            continue
        a_el = (p.select_one(".author a") or p.select_one(".username")
                or p.select_one("[class*='Username']")
                or p.select_one("[class*='author']"))
        author = _text_of(a_el)
        if i == 0:
            op_body = text
            op_author = author
        else:
            if len(text) >= 30:
                replies.append({"author": author, "body": text[:1500]})
                if len(replies) >= 5:
                    break

    # Fallback OP body
    if not op_body:
        for sel in ("div.thread-original-post", "div.op-body",
                    "div[class*='OriginalPost']", "div.message-body"):
            el = soup.select_one(sel)
            if el:
                op_body = _text_of(el)
                if op_body:
                    break

    # Engagement — Mumsnet often shows "<n> replies" / "<n> views" near header
    views = 0
    reply_count = max(0, len(posts) - 1) if posts else 0
    for el in soup.select(".thread-meta, .thread-stats, [class*='Stats'], .post-count, .views"):
        txt = _text_of(el).lower()
        if not txt:
            continue
        if "view" in txt:
            m = re.search(r"([\d,.]+\s*[kKmM]?)\s*view", txt)
            if m:
                views = max(views, _parse_int(m.group(1)))
        if "repl" in txt or "post" in txt:
            m = re.search(r"([\d,.]+\s*[kKmM]?)\s*(repl|post)", txt)
            if m:
                reply_count = max(reply_count, _parse_int(m.group(1)))

    return {
        "title": title,
        "author": op_author,
        "op_body": op_body,
        "replies": replies,
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
    except MumsnetError as e:
        print(f"  [{PLATFORM}] thread {rid} err: {e}")
        state.mark_seen(our_id)
        return False

    parsed = parse_thread(html, fallback_title=meta.get("title", ""))
    title = parsed["title"] or meta.get("title", "")
    op_body = parsed["op_body"]

    body_parts = [op_body] if op_body else []
    for rep in parsed["replies"]:
        body_parts.append(f"[reply by {rep['author']}]: {rep['body']}")
    body = "\n\n".join(body_parts)[:5000]

    if not is_on_topic(title, body, lang="en"):
        state.mark_seen(our_id)
        return False

    item = {
        "id": our_id,
        "raw_id": rid,
        "platform": PLATFORM,
        "lang": "en",
        "title": title,
        "body": body,
        "author": parsed["author"],
        "url": meta["url"],
        "country_hint": "GB",
        "engagement": {
            "score": parsed["views"],
            "comments": parsed["reply_count"],
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

    try:
        for kw in INCOME_KEYWORDS["en"]:
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
                except MumsnetError as e:
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
                    except MumsnetError as e:
                        print(f"  [{PLATFORM}] process err: {e}")
                    state.maybe_save(every=10)
                    polite_sleep()

                state.set_cursor(kw, page + 1)
                polite_sleep()

            if not had_error:
                state.mark_kw_done(kw)
            state.save()
            polite_sleep()

        # Fallback: walk the three high-signal /talk boards
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
                    except MumsnetError as e:
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
                        except MumsnetError as e:
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
