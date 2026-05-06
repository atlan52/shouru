"""ForoCoches.com crawler — biggest Spanish-language general forum.

Despite the name ("car forum"), ForoCoches has long since become Spain's
largest general-purpose discussion site, with classic vBulletin / Discuz
style markup. The "General" subforum (f=2) hosts an unending stream of
"¿cuánto cobras?" threads where Spaniards trade salary numbers.

Strategy:
  1. For each kw in INCOME_KEYWORDS["es"] + Spanish salary-thread idioms,
     query /foro/search.php?do=process&query=<kw> (forum's vBulletin
     search) across PAGES_PER_QUERY pages.
  2. For each thread link, fetch the thread page; extract title, OP body,
     OP author, reply count, and view count.
  3. Filter via is_on_topic(..., lang="es").
  4. Fallback: walk forumdisplay.php?f=2 (General) when search rate-limits.
  5. ForoCoches output is mixed Latin-1 / UTF-8; rely on requests' built-in
     `apparent_encoding` (chardet) to handle re-decoding.
"""
import re
import time
import requests
from urllib.parse import quote_plus, urljoin, urlparse, parse_qs
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


PLATFORM = "forocoches"
BASE = "https://forocoches.com"
SEARCH_URL = BASE + "/foro/search.php?do=process&showposts=0&starteronly=0&query={kw}"

# Spanish salary-thread idioms — heavy hitters on FC.
EXTRA_KEYWORDS_ES = [
    "sueldo trabajo", "cuánto cobras", "cuánto ganas", "nómina",
    "salario neto", "trabajo bien pagado", "autónomo facturación",
]

FALLBACK_BOARDS = [
    "/foro/forumdisplay.php?f=2",   # General
    "/foro/forumdisplay.php?f=18",  # Tecnología (tech salaries)
]

BOT_MARKERS = ("captcha", "are you a human", "access denied",
               "cf-browser-verification", "checking your browser",
               "attention required", "please enable javascript")


class ForoCochesError(Exception):
    pass


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _headers() -> dict:
    h = default_headers("es-ES,es;q=0.9,en;q=0.6")
    h["User-Agent"] = random_ua()
    h["Referer"] = BASE + "/"
    return h


def fetch_html(url: str, timeout: int = 30) -> str:
    try:
        r = requests.get(url, headers=_headers(), timeout=timeout, allow_redirects=True)
    except Exception as e:
        raise ForoCochesError(f"net err {url}: {e}")
    if r.status_code in (403, 429):
        raise ForoCochesError(f"{r.status_code} on {url}")
    if r.status_code != 200:
        raise ForoCochesError(f"status {r.status_code} on {url}")
    # FC is mixed encoding — let chardet decide.
    if not r.encoding or r.encoding.lower() in ("iso-8859-1", "latin-1"):
        try:
            r.encoding = r.apparent_encoding or r.encoding
        except Exception:
            pass
    body = r.text or ""
    low = body.lower()
    if any(m in low for m in BOT_MARKERS):
        raise ForoCochesError("bot-block / captcha")
    return body


def fetch_with_retry(url: str) -> str:
    try:
        return fetch_html(url)
    except ForoCochesError as e:
        msg = str(e)
        if "403" in msg or "429" in msg or "bot-block" in msg:
            print(f"  [{PLATFORM}] backoff 30s on {url}")
            time.sleep(30)
            return fetch_html(url)
        raise


# ---------------------------------------------------------------------------
# Parsing — vBulletin classic markup
# ---------------------------------------------------------------------------
# Thread URLs look like /foro/showthread.php?t=12345678 or
# /foro/showthread.php?p=400000000  ->  redirects to ?t=
_SHOWTHREAD_RE = re.compile(r"showthread\.php\?(?:[^\"'#]*?)t=(\d+)", re.IGNORECASE)


def _abs(href: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return urljoin(BASE + "/", href.lstrip("/"))
    # vBulletin returns relative-to-/foro/ links most of the time
    return urljoin(BASE + "/foro/", href)


def _text_of(el) -> str:
    if not el:
        return ""
    return el.get_text(" ", strip=True)


def _parse_int(s: str) -> int:
    if not s:
        return 0
    s = s.replace(",", "").replace(".", "").strip().lower()
    m = re.match(r"([\d]+)", s)
    if not m:
        return 0
    try:
        return int(m.group(1))
    except ValueError:
        return 0


def _extract_thread_id(href: str) -> str | None:
    if not href:
        return None
    try:
        parsed = urlparse(href)
        qs = parse_qs(parsed.query)
        if "t" in qs and qs["t"]:
            return qs["t"][0]
    except Exception:
        pass
    m = _SHOWTHREAD_RE.search(href)
    return m.group(1) if m else None


def parse_search_results(html: str):
    """Extract showthread.php?t=<id> links + titles from a search/board page."""
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        tid = _extract_thread_id(href)
        if not tid:
            continue
        if tid in seen:
            continue
        title = _text_of(a)
        if not title or len(title) < 4:
            continue
        # Skip "Last post" / "Reply" anchors that link to the same thread
        low = title.lower()
        if low in ("ir al último mensaje", "último", "responder", "ir"):
            continue
        seen.add(tid)
        # vBulletin classic search uses showthread.php?t=, normalize
        url = _abs(f"/foro/showthread.php?t={tid}")
        out.append({
            "thread_id": tid,
            "url": url,
            "title": title,
        })
    return out


def parse_thread(html: str, fallback_title: str = "") -> dict:
    """Pull title, OP body+author, view/reply counts from a vBulletin thread."""
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title = ""
    # vBulletin: <td class="navbar"> last bold cell; or <title>
    for sel in ("span.threadtitle", "h1", "td.navbar strong", "title"):
        el = soup.select_one(sel)
        if el:
            title = _text_of(el)
            if title:
                break
    if not title:
        title = fallback_title

    # vBulletin posts: <table id="post12345"> or <div id="post_message_12345">
    posts = soup.select("table[id^='post']") or soup.select("div[id^='post_message_']")

    op_body = ""
    op_author = ""
    if posts:
        first = posts[0]
        msg_el = (first.select_one("div[id^='post_message_']")
                  or first.select_one(".postbody")
                  or first.select_one("td.alt1 div")
                  or first)
        op_body = _text_of(msg_el)
        a_el = (first.select_one("a.bigusername")
                or first.select_one(".username")
                or first.select_one("[class*='username']"))
        op_author = _text_of(a_el)

    # Engagement — vBulletin shows "Vistas: <n>" and reply count near header
    views = 0
    reply_count = max(0, len(posts) - 1) if posts else 0
    page_text = soup.get_text(" ", strip=True)
    for pat in (r"vistas?\s*[:.]?\s*([\d.,]+)",
                r"views?\s*[:.]?\s*([\d.,]+)",
                r"hits?\s*[:.]?\s*([\d.,]+)"):
        m = re.search(pat, page_text, re.IGNORECASE)
        if m:
            views = max(views, _parse_int(m.group(1)))
            break
    for pat in (r"respuestas?\s*[:.]?\s*([\d.,]+)",
                r"replies?\s*[:.]?\s*([\d.,]+)"):
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
        sep = "&" if "?" in board_path else "?"
        return f"{BASE}{board_path}{sep}page={page}"
    return f"{BASE}{board_path}"


def process_thread(meta: dict, kw: str, state: State) -> bool:
    rid = meta["thread_id"]
    our_id = make_id(PLATFORM, rid)
    if state.is_seen(our_id):
        return False

    try:
        html = fetch_with_retry(meta["url"])
    except ForoCochesError as e:
        print(f"  [{PLATFORM}] thread {rid} err: {e}")
        state.mark_seen(our_id)
        return False

    parsed = parse_thread(html, fallback_title=meta.get("title", ""))
    title = parsed["title"] or meta.get("title", "")
    op_body = parsed["op_body"] or ""

    if not is_on_topic(title, op_body, lang="es"):
        state.mark_seen(our_id)
        return False

    item = {
        "id": our_id,
        "raw_id": rid,
        "platform": PLATFORM,
        "lang": "es",
        "title": title,
        "body": op_body[:5000],
        "author": parsed["author"],
        "url": meta["url"],
        "country_hint": "ES",
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

    keywords = list(INCOME_KEYWORDS.get("es", [])) + EXTRA_KEYWORDS_ES

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
                except ForoCochesError as e:
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
                    except ForoCochesError as e:
                        print(f"  [{PLATFORM}] process err: {e}")
                    state.maybe_save(every=10)
                    polite_sleep()

                state.set_cursor(kw, page + 1)
                polite_sleep()

            if not had_error:
                state.mark_kw_done(kw)
            state.save()
            polite_sleep()

        # Fallback: walk the General + Tecnología boards if budget left
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
                    except ForoCochesError as e:
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
                        except ForoCochesError as e:
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
