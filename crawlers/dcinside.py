"""DCInside crawler — gallery.dcinside.com.

Major Korean meta-forum: thousands of "갤러리" (galleries / boards) covering
stocks, sports, programming, motor, startup, etc. Public, no auth.

Strategy:
  1. Search across galleries via:
       https://search.dcinside.com/post/q/{kw}
     (the official site search). Paginate PAGES_PER_QUERY pages per kw.
  2. Also browse a curated list of high-signal galleries' lists pages.
  3. For each candidate post, fetch the view page and extract title / body /
     author / comment_count / view_count / upvotes / downvotes.

Encoding: Modern dcinside serves UTF-8, but a few legacy galleries still
emit EUC-KR. We rely on `response.apparent_encoding` (chardet) when the
declared encoding is wrong.
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


PLATFORM = "dcinside"
BASE = "https://gall.dcinside.com"
SEARCH_URL = "https://search.dcinside.com/post/q/{kw}"

# Curated galleries to browse if search comes up dry — skip adult/politics.
SEED_GALLERIES = [
    "stock_new1",       # 주식
    "baseball_new10",   # 야구
    "football_new7",    # 축구
    "programming",      # 프로그래밍
    "motor",            # 자동차
    "startup",          # 스타트업
]
# Adult/politics galleries excluded by policy (NSFW / off-topic noise).

BOT_MARKERS = (
    "차단되었습니다", "비정상적인 접근", "captcha", "차단",
    "blocked", "access denied",
)


class DCError(Exception):
    pass


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _decode(r: requests.Response) -> str:
    """Decode response, falling back to chardet (apparent_encoding) when
    the declared encoding is missing or clearly wrong."""
    declared = (r.encoding or "").lower()
    if not declared or declared in ("iso-8859-1",):
        # iso-8859-1 is Python's default when no charset header — trust chardet
        try:
            r.encoding = r.apparent_encoding or "utf-8"
        except Exception:
            r.encoding = "utf-8"
    text = r.text or ""
    # Heuristic: if we see lots of replacement glyphs, retry with euc-kr
    if "�" in text and declared not in ("euc-kr", "ks_c_5601-1987", "cp949"):
        try:
            text = r.content.decode("euc-kr", errors="replace")
        except Exception:
            pass
    return text


def fetch_html(url: str, timeout: int = 25, referer: str | None = None) -> str:
    headers = default_headers("ko-KR,ko;q=0.9,en;q=0.6")
    headers["User-Agent"] = random_ua()
    if referer:
        headers["Referer"] = referer
    try:
        r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    except Exception as e:
        raise DCError(f"net err {url}: {e}")
    if r.status_code in (403, 429):
        raise DCError(f"{r.status_code} on {url}")
    if r.status_code != 200:
        raise DCError(f"status {r.status_code} on {url}")
    body = _decode(r)
    low = body.lower()
    if any(m.lower() in low for m in BOT_MARKERS):
        raise DCError("bot-block / captcha")
    return body


def fetch_with_retry(url: str, referer: str | None = None) -> str:
    try:
        return fetch_html(url, referer=referer)
    except DCError as e:
        msg = str(e)
        if "403" in msg or "429" in msg:
            print(f"  [{PLATFORM}] backoff 30s on {url}")
            time.sleep(30)
            return fetch_html(url, referer=referer)
        raise


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
_VIEW_HREF_RE = re.compile(
    r"/board/view/?\?id=([A-Za-z0-9_]+)&[^\"']*?no=(\d+)"
)


def _parse_int(s: str) -> int:
    if not s:
        return 0
    s = s.replace(",", "").strip()
    m = re.search(r"(\d+)", s)
    if not m:
        return 0
    try:
        return int(m.group(1))
    except ValueError:
        return 0


def parse_search_results(html: str) -> list[dict]:
    """Extract post links from search.dcinside.com results."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Search hits link directly to gall.dcinside.com/board/view/?id=...&no=...
        m = _VIEW_HREF_RE.search(href)
        if not m:
            # Some search-result anchors have absolute URLs; normalize.
            parsed = urlparse(href)
            if "dcinside.com" in (parsed.netloc or "") and "view" in (parsed.path or ""):
                qs = parse_qs(parsed.query or "")
                gid = (qs.get("id") or [""])[0]
                no = (qs.get("no") or [""])[0]
                if gid and no:
                    key = f"{gid}/{no}"
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({
                        "gallery": gid,
                        "post_id": no,
                        "url": f"{BASE}/board/view/?id={gid}&no={no}",
                        "title": a.get_text(" ", strip=True),
                    })
            continue
        gid = m.group(1)
        no = m.group(2)
        key = f"{gid}/{no}"
        if key in seen:
            continue
        seen.add(key)
        title = a.get_text(" ", strip=True)
        out.append({
            "gallery": gid,
            "post_id": no,
            "url": f"{BASE}/board/view/?id={gid}&no={no}",
            "title": title,
        })
    return out


def parse_gallery_list(html: str, gallery: str) -> list[dict]:
    """Parse rows from /board/lists/?id={gallery}."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()
    for tr in soup.select("tr.us-post, tr.ub-content"):
        a = tr.select_one("td.gall_tit a, .gall_tit a")
        if not a:
            continue
        href = a.get("href", "")
        m = _VIEW_HREF_RE.search(href)
        if not m:
            continue
        gid = m.group(1)
        no = m.group(2)
        key = f"{gid}/{no}"
        if key in seen:
            continue
        seen.add(key)
        title = a.get_text(" ", strip=True)
        out.append({
            "gallery": gid,
            "post_id": no,
            "url": f"{BASE}/board/view/?id={gid}&no={no}",
            "title": title,
        })
    if not out:
        # Fallback: any anchor matching the view pattern
        for a in soup.find_all("a", href=True):
            m = _VIEW_HREF_RE.search(a["href"])
            if not m:
                continue
            gid = m.group(1)
            no = m.group(2)
            key = f"{gid}/{no}"
            if key in seen:
                continue
            seen.add(key)
            title = a.get_text(" ", strip=True)
            if not title:
                continue
            out.append({
                "gallery": gid,
                "post_id": no,
                "url": f"{BASE}/board/view/?id={gid}&no={no}",
                "title": title,
            })
    return out


def _text_of(el) -> str:
    if not el:
        return ""
    return el.get_text(" ", strip=True)


def parse_post(html: str) -> dict:
    """Extract title, body, author, score, comment_count, view_count from
    a /board/view/ page."""
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    for sel in (".title_subject", ".view_subject", "h3.title", ".gallview_head .title"):
        el = soup.select_one(sel)
        if el:
            title = _text_of(el)
            if title:
                break

    body_el = (soup.select_one(".write_div")
               or soup.select_one(".gallview_contents .inner")
               or soup.select_one(".view_content_wrap"))
    body = _text_of(body_el)

    # Author (often "ㅇㅇ" — anonymous)
    author = ""
    for sel in (".gall_writer", ".nickname", ".user_id", ".gall_writer .nickname"):
        el = soup.select_one(sel)
        if el:
            txt = _text_of(el)
            if txt:
                # First token is the nick; suffixes are IP/level
                author = txt.split()[0] if txt.split() else txt
                break

    # Stats — view + recommend + comment counts
    view_count = 0
    upvotes = 0
    downvotes = 0
    comment_count = 0

    # Modern view page: <div class="fr"><span class="gall_count">조회 1,234</span> ...</div>
    for el in soup.select(".gall_count, .gall_comment, .gall_reply_num, "
                          ".view_count, .recom_count, .nonrecom_count"):
        txt = _text_of(el)
        if not txt:
            continue
        low = txt.replace(" ", "")
        if "조회" in low and not view_count:
            view_count = _parse_int(txt)
        elif "댓글" in low and not comment_count:
            comment_count = _parse_int(txt)
        elif "추천" in low and "비추천" not in low and not upvotes:
            upvotes = _parse_int(txt)
        elif "비추천" in low and not downvotes:
            downvotes = _parse_int(txt)

    # Backup: dedicated up/down spans
    for sel, key in (
        (".up_num", "up"), ("#recommend_view_up", "up"),
        (".down_num", "down"), ("#recommend_view_down", "down"),
    ):
        el = soup.select_one(sel)
        if el:
            v = _parse_int(_text_of(el))
            if key == "up" and not upvotes:
                upvotes = v
            elif key == "down" and not downvotes:
                downvotes = v

    # Comment count fallback: count rendered comment rows
    if not comment_count:
        crows = soup.select(".cmt_list li, ul.cmt_list > li, .cmt_box li.ub-content")
        if crows:
            comment_count = len(crows)

    return {
        "title": title,
        "body": body,
        "author": author,
        "view_count": view_count,
        "comment_count": comment_count,
        "upvotes": upvotes,
        "downvotes": downvotes,
    }


# ---------------------------------------------------------------------------
# Per-post processing
# ---------------------------------------------------------------------------
def _abs(base: str, href: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return urljoin(base + "/", href)


def process_post(meta: dict, kw: str, state: State, referer: str | None = None) -> bool:
    """Fetch + parse one post; emit jsonl item if on-topic and unseen.
    Returns True if a new item was written."""
    rid = f"{meta['gallery']}/{meta['post_id']}"
    our_id = make_id(PLATFORM, rid)
    if state.is_seen(our_id):
        return False

    try:
        html = fetch_with_retry(meta["url"], referer=referer)
    except DCError as e:
        print(f"  [{PLATFORM}] post {rid} err: {e}")
        state.mark_seen(our_id)
        return False

    parsed = parse_post(html)
    title = parsed["title"] or meta.get("title", "")
    body = parsed["body"]

    if not is_on_topic(title, body, lang="ko"):
        state.mark_seen(our_id)
        return False

    item = {
        "id": our_id,
        "raw_id": rid,
        "platform": PLATFORM,
        "lang": "ko",
        "country_hint": "KR",
        "title": title,
        "body": body[:5000],
        "author": parsed["author"],
        "url": meta["url"],
        "gallery": meta["gallery"],
        "post_id": meta["post_id"],
        "engagement": {
            "score": int(parsed["upvotes"]) - int(parsed["downvotes"]),
            "upvotes": int(parsed["upvotes"]),
            "downvotes": int(parsed["downvotes"]),
            "comments": int(parsed["comment_count"]),
            "views": int(parsed["view_count"]),
        },
        "matched_keyword": kw,
    }
    append_jsonl(item, PLATFORM, RAW_DIR)
    state.mark_seen(our_id)
    return True


def search_url(kw: str, page: int) -> str:
    base = SEARCH_URL.format(kw=quote_plus(kw))
    if page > 1:
        return f"{base}/p/{page}"
    return base


def gallery_list_url(gallery: str, page: int) -> str:
    if page > 1:
        return f"{BASE}/board/lists/?id={gallery}&page={page}"
    return f"{BASE}/board/lists/?id={gallery}"


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def run():
    state = State(PLATFORM)
    preload_seen(state, PLATFORM, key_field="id")
    budget = TimeBudget(PLATFORM_TIME_BUDGET_SEC)
    items_added = 0

    try:
        # Phase 1: cross-gallery search by Korean income keywords
        for kw in INCOME_KEYWORDS["ko"]:
            if budget.expired():
                print(f"[{PLATFORM}] time budget expired")
                break
            if items_added >= PER_PLATFORM_LIMIT:
                break
            kw_label = f"search:{kw}"
            if state.is_kw_done(kw_label):
                continue

            print(f"[{PLATFORM}] search kw={kw!r}")
            had_error = False
            start_page = state.get_cursor(kw_label, 1) or 1

            for page in range(start_page, start_page + PAGES_PER_QUERY):
                if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                    break
                url = search_url(kw, page)
                try:
                    html = fetch_with_retry(url)
                except DCError as e:
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
                        if process_post(meta, kw, state, referer=url):
                            items_added += 1
                            if items_added % 25 == 0:
                                print(f"  [{PLATFORM}] +{items_added} so far")
                    except DCError as e:
                        print(f"  [{PLATFORM}] post err: {e}")
                    state.maybe_save(every=10)
                    polite_sleep()

                state.set_cursor(kw_label, page + 1)
                polite_sleep()

            if not had_error:
                state.mark_kw_done(kw_label)
            state.save()
            polite_sleep()

        # Phase 2: browse seed galleries' list pages — take topics that pass
        # the on-topic filter on title alone (saves a fetch); we still fetch
        # body to get full text + counts.
        if items_added < PER_PLATFORM_LIMIT and not budget.expired():
            for gallery in SEED_GALLERIES:
                if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                    break
                gal_label = f"gallery:{gallery}"
                if state.is_kw_done(gal_label):
                    continue

                print(f"[{PLATFORM}] gallery {gallery}")
                start_page = state.get_cursor(gal_label, 1) or 1
                had_error = False
                for page in range(start_page, start_page + PAGES_PER_QUERY):
                    if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                        break
                    url = gallery_list_url(gallery, page)
                    try:
                        html = fetch_with_retry(url)
                    except DCError as e:
                        print(f"  [{PLATFORM}] gallery {gallery} p{page} err: {e}")
                        had_error = True
                        break
                    rows = parse_gallery_list(html, gallery)
                    if not rows:
                        break
                    # Cheap pre-filter on title: skip rows without an income token
                    candidates = [r for r in rows
                                  if is_on_topic(r["title"], lang="ko")]
                    for meta in candidates:
                        if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                            break
                        try:
                            if process_post(meta, gal_label, state, referer=url):
                                items_added += 1
                                if items_added % 25 == 0:
                                    print(f"  [{PLATFORM}] +{items_added} so far")
                        except DCError as e:
                            print(f"  [{PLATFORM}] post err: {e}")
                        state.maybe_save(every=10)
                        polite_sleep()
                    state.set_cursor(gal_label, page + 1)
                    polite_sleep()
                if not had_error:
                    state.mark_kw_done(gal_label)
                state.save()
    finally:
        state.save(force=True)

    print(f"[{PLATFORM}] done, +{items_added} items this run")


if __name__ == "__main__":
    run()
