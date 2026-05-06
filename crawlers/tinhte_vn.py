"""Tinhte.vn crawler — biggest Vietnamese tech-and-life forum.

Tinh tế runs on XenForo. Two top-level sections we care about:
  - "Tinh tế thảo luận"      (general discussion)
  - "Khoa học công nghệ"     (science & tech)

Strategy:
  1. For each kw in INCOME_KEYWORDS["vi"], hit
       https://tinhte.vn/search.html?keyword=<kw>
     across PAGES_PER_QUERY pages.
  2. For each thread link (/thread/<slug>.<numeric-id>/), fetch the page
     and pull title, OP body+author, reply count.
  3. Filter via is_on_topic(..., lang="vi").
  4. Fallback: walk forums index https://tinhte.vn/forums/index.html
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


PLATFORM = "tinhte_vn"
BASE = "https://tinhte.vn"
SEARCH_URL = BASE + "/search.html?keyword={kw}"

FALLBACK_BOARDS = [
    "/forums/tinh-te-thao-luan.41/",       # General discussion
    "/forums/khoa-hoc-cong-nghe.30/",      # Science & tech
    "/forums/index.html",                  # Forum index (catch-all)
]

BOT_MARKERS = ("captcha", "are you a human", "access denied",
               "cf-browser-verification", "checking your browser",
               "attention required")


class TinhteError(Exception):
    pass


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _headers() -> dict:
    h = default_headers("vi-VN,vi;q=0.9,en;q=0.6")
    h["User-Agent"] = random_ua()
    h["Referer"] = BASE + "/"
    return h


def fetch_html(url: str, timeout: int = 30) -> str:
    try:
        r = requests.get(url, headers=_headers(), timeout=timeout, allow_redirects=True)
    except Exception as e:
        raise TinhteError(f"net err {url}: {e}")
    if r.status_code in (403, 429):
        raise TinhteError(f"{r.status_code} on {url}")
    if r.status_code != 200:
        raise TinhteError(f"status {r.status_code} on {url}")
    if not r.encoding:
        r.encoding = "utf-8"
    body = r.text or ""
    low = body.lower()
    if any(m in low for m in BOT_MARKERS):
        raise TinhteError("bot-block / captcha")
    return body


def fetch_with_retry(url: str) -> str:
    try:
        return fetch_html(url)
    except TinhteError as e:
        msg = str(e)
        if "403" in msg or "429" in msg or "bot-block" in msg:
            print(f"  [{PLATFORM}] backoff 30s on {url}")
            time.sleep(30)
            return fetch_html(url)
        raise


# ---------------------------------------------------------------------------
# Parsing — XenForo
# ---------------------------------------------------------------------------
# Thread URLs on XenForo are /threads/<slug>.<id>/ (or /thread/<slug>.<id>/).
_THREAD_HREF_RE = re.compile(
    r"^/threads?/([\w\-]+)\.(\d+)/?(?:[/?#].*)?$",
    re.IGNORECASE,
)


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
    """Extract /threads/<slug>.<id>/ links + titles from a listing page."""
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        path = href
        if href.startswith("http"):
            p = urlparse(href)
            if "tinhte.vn" not in p.netloc:
                continue
            path = p.path
        path = path.split("?")[0].split("#")[0]
        m = _THREAD_HREF_RE.match(path)
        if not m:
            continue
        slug = m.group(1)
        tid = m.group(2)
        if tid in seen:
            continue
        title = _text_of(a)
        # Skip "Last reply" anchors and short non-titles
        if not title or len(title) < 4:
            continue
        low = title.lower()
        if low in ("trả lời", "xem", "đọc thêm", "chi tiết"):
            continue
        seen.add(tid)
        out.append({
            "thread_id": tid,
            "slug": slug,
            "url": _abs(f"/threads/{slug}.{tid}/"),
            "title": title,
        })
    return out


def parse_thread(html: str, fallback_title: str = "") -> dict:
    """Pull title, OP body+author, reply count from a XenForo thread."""
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title = ""
    for sel in ("h1.p-title-value", "h1[class*='title']",
                "div.titleBar h1", "h1", "title"):
        el = soup.select_one(sel)
        if el:
            title = _text_of(el)
            if title:
                break
    if not title:
        title = fallback_title
    title = re.sub(r"\s*\|\s*Tinh\s*tế\s*$", "", title, flags=re.IGNORECASE)

    # XenForo posts: <article class="message"> or <li id="post-<id>">
    post_selectors = (
        "article.message",
        "li.message",
        "div.message",
        "article[id^='js-post-']",
        "li[id^='post-']",
        "div[id^='post-']",
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
        msg_el = (first.select_one(".bbWrapper")
                  or first.select_one(".message-body")
                  or first.select_one(".messageContent")
                  or first.select_one("[class*='messageContent']")
                  or first.select_one("blockquote.messageText")
                  or first)
        op_body = _text_of(msg_el)
        a_el = (first.select_one("a.username")
                or first.select_one(".message-name a")
                or first.select_one(".username")
                or first.select_one("[class*='username']"))
        op_author = _text_of(a_el)
        # XenForo also exposes data-author
        if not op_author and first.has_attr("data-author"):
            op_author = first["data-author"]

    # Engagement — XenForo usually shows reply count on the listing, not the
    # thread. Inside the thread, count the messages minus the OP.
    reply_count = max(0, len(posts) - 1) if posts else 0
    views = 0
    page_text = soup.get_text(" ", strip=True)
    for pat in (r"lượt xem\s*[:.]?\s*([\d.,]+\s*[kKmM]?)",
                r"views?\s*[:.]?\s*([\d.,]+\s*[kKmM]?)"):
        m = re.search(pat, page_text, re.IGNORECASE)
        if m:
            views = max(views, _parse_int(m.group(1)))
            break
    for pat in (r"trả lời\s*[:.]?\s*([\d.,]+\s*[kKmM]?)",
                r"replies?\s*[:.]?\s*([\d.,]+\s*[kKmM]?)"):
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
        # XenForo board pagination: /<path>page-N
        if board_path.endswith("/"):
            return f"{BASE}{board_path}page-{page}"
        return f"{BASE}{board_path}/page-{page}"
    return f"{BASE}{board_path}"


def process_thread(meta: dict, kw: str, state: State) -> bool:
    rid = meta["thread_id"]
    our_id = make_id(PLATFORM, rid)
    if state.is_seen(our_id):
        return False

    try:
        html = fetch_with_retry(meta["url"])
    except TinhteError as e:
        print(f"  [{PLATFORM}] thread {rid} err: {e}")
        state.mark_seen(our_id)
        return False

    parsed = parse_thread(html, fallback_title=meta.get("title", ""))
    title = parsed["title"] or meta.get("title", "")
    op_body = parsed["op_body"] or ""

    if not is_on_topic(title, op_body, lang="vi"):
        state.mark_seen(our_id)
        return False

    item = {
        "id": our_id,
        "raw_id": rid,
        "platform": PLATFORM,
        "lang": "vi",
        "title": title,
        "body": op_body[:5000],
        "author": parsed["author"],
        "url": meta["url"],
        "country_hint": "VN",
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

    try:
        for kw in INCOME_KEYWORDS.get("vi", []):
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
                except TinhteError as e:
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
                    except TinhteError as e:
                        print(f"  [{PLATFORM}] process err: {e}")
                    state.maybe_save(every=10)
                    polite_sleep()

                state.set_cursor(kw, page + 1)
                polite_sleep()

            if not had_error:
                state.mark_kw_done(kw)
            state.save()
            polite_sleep()

        # Fallback: walk the named boards
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
                    except TinhteError as e:
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
                        except TinhteError as e:
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
