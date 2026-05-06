"""MoneySavingExpert.com forum crawler.

The biggest UK personal-finance community. Vanilla-Forums-style HTML —
discussions, OPs, and replies are public; no auth required.

Strategy:
  1. For each English income keyword, walk the search endpoint:
       https://forums.moneysavingexpert.com/search?query=<kw>
     paging through PAGES_PER_QUERY pages.
  2. Each search hit links to a discussion under
       /discussion/<threadId>/<slug>
     We fetch the thread, parse OP body, view + reply counts, and the
     first 5 replies (≥30 chars) for richer context.
  3. Filter via is_on_topic(..., lang="en"). Country tag = "GB".
  4. Backoff on 403/429: sleep 30s, retry once, else mark keyword done
     and move on.
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


PLATFORM = "moneysavingexpert"
BASE = "https://forums.moneysavingexpert.com"
SEARCH_URL = BASE + "/search?query={kw}&search_type=advanced"

# Highest-signal categories — fallback browsing if search rate-limits us
FALLBACK_CATEGORIES = [
    "/categories/employment-jobs-and-careers",
    "/categories/marriage-relationships-families",
    "/categories/budgeting-bank-accounts",
    "/categories/savings-investments",
]

BOT_MARKERS = ("unusual traffic", "captcha", "are you a human", "access denied",
               "cf-browser-verification", "checking your browser")


class MSEError(Exception):
    pass


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def fetch_html(url: str, timeout: int = 30) -> str:
    headers = default_headers("en-GB,en;q=0.9")
    headers["User-Agent"] = random_ua()
    try:
        r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    except Exception as e:
        raise MSEError(f"net err {url}: {e}")
    if r.status_code in (403, 429):
        raise MSEError(f"{r.status_code} on {url}")
    if r.status_code != 200:
        raise MSEError(f"status {r.status_code} on {url}")
    body = r.text or ""
    low = body.lower()
    if any(m in low for m in BOT_MARKERS):
        raise MSEError("bot-block / captcha")
    return body


def fetch_with_retry(url: str) -> str:
    """One retry with 30s backoff on 403/429."""
    try:
        return fetch_html(url)
    except MSEError as e:
        msg = str(e)
        if "403" in msg or "429" in msg:
            print(f"  [{PLATFORM}] backoff 30s on {url}")
            time.sleep(30)
            return fetch_html(url)
        raise


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
_THREAD_HREF_RE = re.compile(r"/discussion/(\d+)/([^/?#]+)")


def _abs(href: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return urljoin(BASE + "/", href)


def parse_search_results(html: str):
    """Extract discussion links from a search results page.

    Vanilla Forums renders results inside .Item.Discussion / .Item.Result
    blocks; titles live in .Title a. We're tolerant: we sweep every anchor
    pointing at /discussion/<id>/<slug> and dedupe.
    """
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = _THREAD_HREF_RE.search(href)
        if not m:
            continue
        thread_id = m.group(1)
        slug = m.group(2)
        if thread_id in seen:
            continue
        seen.add(thread_id)
        url = _abs(href.split("#")[0].split("?")[0])
        # Truncate URL to canonical /discussion/<id>/<slug>
        canonical = f"{BASE}/discussion/{thread_id}/{slug}"
        title = a.get_text(" ", strip=True)
        if not title:
            continue
        out.append({
            "thread_id": thread_id,
            "slug": slug,
            "url": canonical,
            "title": title,
        })
    return out


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


def parse_thread(html: str, fallback_title: str = "") -> dict:
    """Pull title, OP body, author, view/reply counts, first 5 replies."""
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title = ""
    for sel in ("h1.PageTitle", "h1.heading-1", "h1[class*='Title']", "h1"):
        el = soup.select_one(sel)
        if el:
            title = _text_of(el)
            if title:
                break
    if not title:
        title = fallback_title

    # All comments (OP is typically the first .Comment or .ItemComment)
    comments = soup.select("li.ItemComment, div.ItemComment, li.Comment, div.Comment, article.Comment")
    if not comments:
        # Newer Vanilla skin uses .Message blocks inside discussion
        comments = soup.select("div.Message, div[class*='Comment_']")

    op_body = ""
    op_author = ""
    replies = []

    for i, c in enumerate(comments):
        # Body
        msg_el = (c.select_one(".Message") or c.select_one("[class*='Message']")
                  or c.select_one(".userContent") or c)
        body_text = _text_of(msg_el)
        if not body_text:
            continue
        # Author
        a_el = (c.select_one("a.Username") or c.select_one(".Author a")
                or c.select_one("[class*='Username']") or c.select_one(".PhotoWrap a"))
        author = _text_of(a_el)
        if i == 0:
            op_body = body_text
            op_author = author
        else:
            if len(body_text) >= 30:
                replies.append({"author": author, "body": body_text[:1500]})
                if len(replies) >= 5:
                    break

    # Fallback OP body extraction if no .Comment blocks were detected
    if not op_body:
        for sel in (".DiscussionContent .Message", ".Discussion .Message",
                    "div[class*='Message']", "article .userContent"):
            el = soup.select_one(sel)
            if el:
                op_body = _text_of(el)
                if op_body:
                    break

    # Views + replies counts — usually in a .DataList / .DiscussionMeta block
    views = 0
    reply_count = max(0, len(comments) - 1) if comments else 0
    for el in soup.select(".MItem, .Stats span, [class*='ViewsCount'], [class*='CommentsCount']"):
        txt = _text_of(el).lower()
        if not txt:
            continue
        if "view" in txt:
            m = re.search(r"([\d,.]+\s*[kKmM]?)", txt)
            if m:
                views = max(views, _parse_int(m.group(1)))
        elif "comment" in txt or "repl" in txt:
            m = re.search(r"([\d,.]+\s*[kKmM]?)", txt)
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
# Per-keyword runner
# ---------------------------------------------------------------------------
def search_url(kw: str, page: int) -> str:
    base = SEARCH_URL.format(kw=quote_plus(kw))
    if page > 1:
        return f"{base}&page={page}"
    return base


def process_thread(meta: dict, kw: str, state: State) -> bool:
    """Fetch + parse one thread; emit jsonl item if on-topic and unseen.

    Returns True if a new item was written.
    """
    rid = meta["thread_id"]
    our_id = make_id(PLATFORM, rid)
    if state.is_seen(our_id):
        return False

    try:
        html = fetch_with_retry(meta["url"])
    except MSEError as e:
        print(f"  [{PLATFORM}] thread {rid} err: {e}")
        # Mark as seen so we don't retry every run
        state.mark_seen(our_id)
        return False

    parsed = parse_thread(html, fallback_title=meta.get("title", ""))
    title = parsed["title"] or meta.get("title", "")
    op_body = parsed["op_body"]

    # Compose a body that includes the OP and the first 5 substantive replies
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
                except MSEError as e:
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
                    except MSEError as e:
                        print(f"  [{PLATFORM}] process err: {e}")
                    state.maybe_save(every=10)
                    polite_sleep()

                state.set_cursor(kw, page + 1)
                polite_sleep()

            if not had_error:
                state.mark_kw_done(kw)
            state.save()
            polite_sleep()

        # Optional fallback: browse high-signal categories if we're under quota
        if items_added < PER_PLATFORM_LIMIT and not budget.expired():
            for cat in FALLBACK_CATEGORIES:
                if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                    break
                cat_label = f"cat:{cat}"
                if state.is_kw_done(cat_label):
                    continue
                print(f"[{PLATFORM}] category {cat}")
                start_page = state.get_cursor(cat_label, 1) or 1
                had_error = False
                for page in range(start_page, start_page + PAGES_PER_QUERY):
                    if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                        break
                    url = f"{BASE}{cat}/p{page}" if page > 1 else f"{BASE}{cat}"
                    try:
                        html = fetch_with_retry(url)
                    except MSEError as e:
                        print(f"  [{PLATFORM}] cat {cat} p{page} err: {e}")
                        had_error = True
                        break
                    hits = parse_search_results(html)
                    if not hits:
                        break
                    for meta in hits:
                        if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                            break
                        try:
                            if process_thread(meta, cat_label, state):
                                items_added += 1
                                if items_added % 25 == 0:
                                    print(f"  [{PLATFORM}] +{items_added} so far")
                        except MSEError as e:
                            print(f"  [{PLATFORM}] process err: {e}")
                        state.maybe_save(every=10)
                        polite_sleep()
                    state.set_cursor(cat_label, page + 1)
                    polite_sleep()
                if not had_error:
                    state.mark_kw_done(cat_label)
                state.save()
    finally:
        state.save(force=True)

    print(f"[{PLATFORM}] done, +{items_added} items this run")


if __name__ == "__main__":
    run()
