"""Pantip.com crawler — biggest Thai general-discussion forum.

Pantip is a Discuz-style forum that has dominated Thai online conversation
since the early 2000s. Two boards we care about:
  - /forum/sinthorn   (สินธร — finance / 財經)
  - /forum/klaibaan   (ใกล้บ้าน — work / job-related; informal salary chat)

Strategy:
  1. For each kw in INCOME_KEYWORDS["th"], hit
       https://pantip.com/search?q=<kw>&type=topic
     across PAGES_PER_QUERY pages.
  2. For each topic link, fetch the topic page and pull title, OP body,
     author, comment count, view count.
  3. Filter via is_on_topic(..., lang="th").
  4. Fallback: walk /forum/sinthorn and /forum/klaibaan.

Pantip pages are heavily JS-driven on modern URLs, but fall back to
server-rendered HTML for /topic/<id> and /forum/<board>?page=N — both of
which we can scrape with requests + BeautifulSoup.
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


PLATFORM = "pantip"
BASE = "https://pantip.com"
SEARCH_URL = BASE + "/search?q={kw}&type=topic"

FALLBACK_BOARDS = [
    "/forum/sinthorn",   # finance
    "/forum/klaibaan",   # work / jobs
]

BOT_MARKERS = ("captcha", "are you a human", "access denied",
               "cf-browser-verification", "checking your browser",
               "attention required")


class PantipError(Exception):
    pass


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _headers() -> dict:
    h = default_headers("th-TH,th;q=0.9,en;q=0.6")
    h["User-Agent"] = random_ua()
    h["Referer"] = BASE + "/"
    return h


def fetch_html(url: str, timeout: int = 30) -> str:
    try:
        r = requests.get(url, headers=_headers(), timeout=timeout, allow_redirects=True)
    except Exception as e:
        raise PantipError(f"net err {url}: {e}")
    if r.status_code in (403, 429):
        raise PantipError(f"{r.status_code} on {url}")
    if r.status_code != 200:
        raise PantipError(f"status {r.status_code} on {url}")
    # Pantip is UTF-8 throughout
    if not r.encoding:
        r.encoding = "utf-8"
    body = r.text or ""
    low = body.lower()
    if any(m in low for m in BOT_MARKERS):
        raise PantipError("bot-block / captcha")
    return body


def fetch_with_retry(url: str) -> str:
    try:
        return fetch_html(url)
    except PantipError as e:
        msg = str(e)
        if "403" in msg or "429" in msg or "bot-block" in msg:
            print(f"  [{PLATFORM}] backoff 30s on {url}")
            time.sleep(30)
            return fetch_html(url)
        raise


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
# Topic URLs: /topic/<numeric-id>
_TOPIC_HREF_RE = re.compile(r"^/topic/(\d+)(?:[/?#].*)?$")


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
    """Extract /topic/<id> links + titles from a search or board listing."""
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Strip query/fragment if any
        path = href.split("?")[0].split("#")[0]
        if href.startswith("http"):
            # absolute → only accept pantip.com
            from urllib.parse import urlparse as _up
            p = _up(href)
            if "pantip.com" not in p.netloc:
                continue
            path = p.path
        m = _TOPIC_HREF_RE.match(path)
        if not m:
            continue
        tid = m.group(1)
        if tid in seen:
            continue
        title = _text_of(a)
        if not title or len(title) < 4:
            continue
        seen.add(tid)
        out.append({
            "topic_id": tid,
            "url": _abs(f"/topic/{tid}"),
            "title": title,
        })
    return out


def parse_topic(html: str, fallback_title: str = "") -> dict:
    """Pull title, OP body+author, comment count, views from a topic page."""
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title = ""
    for sel in ("h2.display-post-title", "h1.display-post-title", "h2.title",
                "h1", "title"):
        el = soup.select_one(sel)
        if el:
            title = _text_of(el)
            if title:
                break
    if not title:
        title = fallback_title
    # Trim "- Pantip" suffix often present in <title>
    title = re.sub(r"\s*-\s*Pantip\s*$", "", title)

    # OP body — Pantip wraps the first post in .display-post-story
    # or .post-content / .display-post-wrapper-inner
    op_body = ""
    for sel in (".display-post-story", ".display-post-content",
                ".post-content", "[class*='display-post-story']",
                ".main-post-inner", ".post-body"):
        el = soup.select_one(sel)
        if el:
            op_body = _text_of(el)
            if op_body:
                break

    # OP author
    op_author = ""
    for sel in (".display-post-name a", ".main-post-name a",
                "a.owner-name", "[class*='display-post-name']"):
        el = soup.select_one(sel)
        if el:
            op_author = _text_of(el)
            if op_author:
                break

    # Engagement: views often shown as "เข้าชม X" / comments as "ความคิดเห็น Y"
    views = 0
    comments = 0
    page_text = soup.get_text(" ", strip=True)
    for pat in (r"เข้าชม\s*[:.]?\s*([\d.,]+\s*[kKmM]?)",
                r"ผู้เข้าชม\s*[:.]?\s*([\d.,]+\s*[kKmM]?)",
                r"views?\s*[:.]?\s*([\d.,]+\s*[kKmM]?)"):
        m = re.search(pat, page_text, re.IGNORECASE)
        if m:
            views = max(views, _parse_int(m.group(1)))
            break
    for pat in (r"ความคิดเห็น\s*[:.]?\s*([\d.,]+\s*[kKmM]?)",
                r"คอมเมนต์\s*[:.]?\s*([\d.,]+\s*[kKmM]?)",
                r"comments?\s*[:.]?\s*([\d.,]+\s*[kKmM]?)"):
        m = re.search(pat, page_text, re.IGNORECASE)
        if m:
            comments = max(comments, _parse_int(m.group(1)))
            break
    # Fallback comment count: count .display-post-wrapper after the first
    if comments == 0:
        cmt_els = soup.select(".display-post-wrapper, .comment-wrapper, .display-post.comment")
        if cmt_els:
            comments = max(0, len(cmt_els) - 1)

    return {
        "title": title,
        "author": op_author,
        "op_body": op_body,
        "views": views,
        "comments": comments,
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


def process_topic(meta: dict, kw: str, state: State) -> bool:
    rid = meta["topic_id"]
    our_id = make_id(PLATFORM, rid)
    if state.is_seen(our_id):
        return False

    try:
        html = fetch_with_retry(meta["url"])
    except PantipError as e:
        print(f"  [{PLATFORM}] topic {rid} err: {e}")
        state.mark_seen(our_id)
        return False

    parsed = parse_topic(html, fallback_title=meta.get("title", ""))
    title = parsed["title"] or meta.get("title", "")
    op_body = parsed["op_body"] or ""

    if not is_on_topic(title, op_body, lang="th"):
        state.mark_seen(our_id)
        return False

    item = {
        "id": our_id,
        "raw_id": rid,
        "platform": PLATFORM,
        "lang": "th",
        "title": title,
        "body": op_body[:5000],
        "author": parsed["author"],
        "url": meta["url"],
        "country_hint": "TH",
        "engagement": {
            "score": parsed["views"],
            "comments": parsed["comments"],
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

    try:
        for kw in INCOME_KEYWORDS.get("th", []):
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
                except PantipError as e:
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
                    except PantipError as e:
                        print(f"  [{PLATFORM}] process err: {e}")
                    state.maybe_save(every=10)
                    polite_sleep()

                state.set_cursor(kw, page + 1)
                polite_sleep()

            if not had_error:
                state.mark_kw_done(kw)
            state.save()
            polite_sleep()

        # Fallback: walk the sinthorn + klaibaan boards
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
                    except PantipError as e:
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
                            if process_topic(meta, board_label, state):
                                items_added += 1
                                if items_added % 25 == 0:
                                    print(f"  [{PLATFORM}] +{items_added} so far")
                        except PantipError as e:
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
