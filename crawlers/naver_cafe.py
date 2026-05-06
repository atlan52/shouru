"""Naver Cafe crawler — cafe.naver.com.

Korea's dominant community platform. Many income/career-focused cafes
(월급쟁이재테크, 재테크모임, 부동산 스터디). Search both via the
cross-cafe article search endpoint and the per-cafe browse view.

Set NAVER_COOKIE (raw "Cookie:" string with NID_AUT + NID_SES at minimum)
to log in. Guest mode mostly works for search, but article bodies may be
truncated or hidden behind member-only walls in some cafes.
"""
import re
import time
from urllib.parse import quote

from config import INCOME_KEYWORDS, PER_PLATFORM_LIMIT, PAGES_PER_QUERY, RAW_DIR, PLATFORM_TIME_BUDGET_SEC
from crawlers.common import (
    append_jsonl, is_on_topic, make_id, polite_sleep, preload_seen,
    parse_cookie_env, TimeBudget,
)
from crawlers.state import State


PLATFORM = "naver_cafe"
DOMAIN_COOKIE = ".naver.com"

# Income-focused cafe seeds (cafeId, friendly name).
SEED_CAFES = [
    ("10050146", "월급쟁이재테크"),
    ("12175294", "재테크 자취방"),
    ("11876032", "직장인 재테크"),
    ("10050143", "부동산 스터디"),
]

# Cross-cafe article search:
#   https://search.naver.com/search.naver?where=articleg&query={kw}&sm=tab_jum
ARTICLE_SEARCH_URL = (
    "https://search.naver.com/search.naver?where=articleg&query={kw}&sm=tab_jum"
)

SCROLL_TIMES = 4
SCROLL_PAUSE = 1.4

# Regex helpers
_ARTICLE_HREF_RE = re.compile(
    r"https?://cafe\.naver\.com/(?:ca-fe/)?(?:cafes/)?([A-Za-z0-9_\-]+)/(?:articles/|ArticleRead\.nhn\?clubid=\d+&articleid=)?(\d+)"
)
_NUM_RE = re.compile(r"([\d,]+)")


def _to_int(s: str) -> int:
    if not s:
        return 0
    m = _NUM_RE.search(s.replace(",", ""))
    if not m:
        return 0
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return 0


def _abs_naver(href: str) -> str:
    if not href:
        return ""
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return "https://cafe.naver.com" + href
    return href


def _extract_article_meta(href: str) -> tuple[str, str] | None:
    """From an arbitrary cafe link, return (cafe_name_or_id, article_id)."""
    if not href:
        return None
    m = _ARTICLE_HREF_RE.search(href)
    if m:
        return (m.group(1), m.group(2))
    # Legacy m.cafe.naver.com / ArticleRead.nhn variants
    m = re.search(r"clubid=(\d+).*?articleid=(\d+)", href)
    if m:
        return (m.group(1), m.group(2))
    return None


def _scrape_search_results(page) -> list[dict]:
    """Extract article cards from a Naver search-articleg results page."""
    out = []
    seen_local = set()
    # Anchors that point at cafe.naver.com articles
    try:
        anchors = page.query_selector_all("a[href*='cafe.naver.com']")
    except Exception:
        anchors = []

    for a in anchors:
        try:
            href = a.get_attribute("href") or ""
        except Exception:
            continue
        meta = _extract_article_meta(href)
        if not meta:
            continue
        cafe_key, article_id = meta
        local_key = f"{cafe_key}/{article_id}"
        if local_key in seen_local:
            continue
        seen_local.add(local_key)

        try:
            title = (a.inner_text() or "").strip()
        except Exception:
            title = ""
        if not title:
            continue

        # Try to walk up to the surrounding card to grab a snippet/desc + author.
        snippet = ""
        author = ""
        try:
            container = a.evaluate_handle(
                "el => el.closest('li, div.total_wrap, div.bx, .total_area') || el.parentElement"
            )
            if container:
                el = container.as_element()
                if el:
                    desc_el = el.query_selector(
                        ".dsc, .api_txt_lines, .total_dsc, .desc, .group_news .dsc_txt"
                    )
                    if desc_el:
                        try:
                            snippet = (desc_el.inner_text() or "").strip()
                        except Exception:
                            snippet = ""
                    auth_el = el.query_selector(
                        ".sub_txt, .name, .source_box .source, .sub_name, .api_txt_lines.sub_txt"
                    )
                    if auth_el:
                        try:
                            author = (auth_el.inner_text() or "").strip()
                        except Exception:
                            author = ""
        except Exception:
            pass

        canonical_url = (
            f"https://cafe.naver.com/{cafe_key}/{article_id}"
        )
        out.append({
            "cafe_key": cafe_key,
            "article_id": article_id,
            "title": title,
            "url": canonical_url,
            "snippet": snippet,
            "author": author,
        })
    return out


def _scrape_cafe_lists(page) -> list[dict]:
    """Scrape from a per-cafe iframe-based article list (legacy view)."""
    out = []
    seen_local = set()
    try:
        anchors = page.query_selector_all(
            "a.article, a[href*='ArticleRead'], a[href*='/articles/'], a[href*='articleid=']"
        )
    except Exception:
        anchors = []
    for a in anchors:
        try:
            href = a.get_attribute("href") or ""
            title = (a.inner_text() or "").strip()
        except Exception:
            continue
        if not href or not title:
            continue
        meta = _extract_article_meta(_abs_naver(href))
        if not meta:
            continue
        cafe_key, article_id = meta
        local_key = f"{cafe_key}/{article_id}"
        if local_key in seen_local:
            continue
        seen_local.add(local_key)
        out.append({
            "cafe_key": cafe_key,
            "article_id": article_id,
            "title": title,
            "url": f"https://cafe.naver.com/{cafe_key}/{article_id}",
            "snippet": "",
            "author": "",
        })
    return out


def _try_extract_article_body(page, url: str) -> dict:
    """Best-effort: navigate to article and return body/comment_count/view_count.

    Naver Cafe wraps article content in an iframe (#cafe_main on desktop).
    We try the iframe first, then fall back to the top frame.
    """
    out = {"body": "", "comment_count": 0, "view_count": 0, "author": ""}
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
    except Exception:
        return out
    time.sleep(1.0)

    # Try iframe
    frame = None
    try:
        for f in page.frames:
            try:
                if "cafe.naver.com" in (f.url or "") and f != page.main_frame:
                    frame = f
                    break
            except Exception:
                continue
    except Exception:
        frame = None

    target = frame or page.main_frame

    body_text = ""
    for sel in (
        ".se-main-container",
        ".ContentRenderer",
        ".article_viewer",
        "#postViewArea",
        ".se_component_wrap",
        "#tbody",
    ):
        try:
            el = target.query_selector(sel)
        except Exception:
            el = None
        if el:
            try:
                t = (el.inner_text() or "").strip()
            except Exception:
                t = ""
            if t and len(t) > len(body_text):
                body_text = t
    out["body"] = body_text[:5000]

    # View count + comment count — Naver Cafe shows these in metadata bars.
    for sel, key in (
        (".article_info .count", "view_count"),
        (".count_num", "view_count"),
        (".CommentBox__count", "comment_count"),
        (".comment_count", "comment_count"),
        ("a.cmt_link em", "comment_count"),
    ):
        try:
            el = target.query_selector(sel)
        except Exception:
            el = None
        if el:
            try:
                txt = (el.inner_text() or "").strip()
            except Exception:
                txt = ""
            v = _to_int(txt)
            if v and not out[key]:
                out[key] = v

    # Author
    for sel in (".nick_name", ".nickname", ".ArticleWriterProfile__nick", ".p-nick a"):
        try:
            el = target.query_selector(sel)
        except Exception:
            el = None
        if el:
            try:
                a = (el.inner_text() or "").strip()
            except Exception:
                a = ""
            if a:
                out["author"] = a
                break

    return out


def _process_search_kw(
    sess, kw: str, state: State, items_added_ref: list[int],
    cookies: list[dict], budget: TimeBudget,
) -> int:
    """Run cross-cafe search for one keyword across PAGES_PER_QUERY pages."""
    added = 0
    start_page = state.get_cursor(f"search:{kw}", 1) or 1

    for page_num in range(start_page, start_page + PAGES_PER_QUERY):
        if budget.expired() or items_added_ref[0] >= PER_PLATFORM_LIMIT:
            break

        url = ARTICLE_SEARCH_URL.format(kw=quote(kw))
        if page_num > 1:
            # search.naver.com paginates with &start=
            start = (page_num - 1) * 10 + 1
            url = url + f"&start={start}"

        page = sess.new_page()
        if cookies:
            try:
                page.context.add_cookies(cookies)
            except Exception as e:
                print(f"  [{PLATFORM}] add_cookies err: {e}")

        try:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
            except Exception as e:
                print(f"  [{PLATFORM}] search goto err {kw} p{page_num}: {e}")
                break

            # Light scroll to render lazy-loaded results
            for _ in range(SCROLL_TIMES):
                try:
                    page.mouse.wheel(0, 4000)
                except Exception:
                    pass
                time.sleep(SCROLL_PAUSE)

            hits = _scrape_search_results(page)
        except Exception as e:
            print(f"  [{PLATFORM}] search {kw} p{page_num} err: {e}")
            hits = []
        finally:
            try:
                page.close()
            except Exception:
                pass

        if not hits:
            break

        for meta in hits:
            if budget.expired() or items_added_ref[0] >= PER_PLATFORM_LIMIT:
                break
            our_id = make_id(PLATFORM, meta["cafe_key"], meta["article_id"])
            if state.is_seen(our_id):
                continue

            title = meta["title"]
            snippet = meta.get("snippet", "")
            # First-cut topic gate using title + snippet (cheap)
            if not is_on_topic(title, snippet, lang="ko"):
                state.mark_seen(our_id)
                continue

            # Try to fetch full article body for richer content
            body = snippet
            comment_count = 0
            view_count = 0
            author = meta.get("author", "")
            article_page = sess.new_page()
            if cookies:
                try:
                    article_page.context.add_cookies(cookies)
                except Exception:
                    pass
            try:
                detail = _try_extract_article_body(article_page, meta["url"])
                if detail["body"]:
                    body = detail["body"]
                if detail["comment_count"]:
                    comment_count = detail["comment_count"]
                if detail["view_count"]:
                    view_count = detail["view_count"]
                if detail["author"]:
                    author = detail["author"]
            except Exception as e:
                print(f"  [{PLATFORM}] article fetch err {meta['url']}: {e}")
            finally:
                try:
                    article_page.close()
                except Exception:
                    pass

            # Final on-topic gate including body
            if not is_on_topic(title, body, lang="ko"):
                state.mark_seen(our_id)
                continue

            item = {
                "id": our_id,
                "raw_id": f"{meta['cafe_key']}/{meta['article_id']}",
                "platform": PLATFORM,
                "lang": "ko",
                "country_hint": "KR",
                "title": title,
                "author": author,
                "url": meta["url"],
                "body": body[:5000],
                "cafe_key": meta["cafe_key"],
                "article_id": meta["article_id"],
                "engagement": {
                    "score": None,
                    "comments": int(comment_count),
                    "views": int(view_count),
                },
                "matched_keyword": kw,
            }
            append_jsonl(item, PLATFORM, RAW_DIR)
            state.mark_seen(our_id)
            added += 1
            items_added_ref[0] += 1
            state.maybe_save(every=10)
            polite_sleep()

        state.set_cursor(f"search:{kw}", page_num + 1)
        state.maybe_save(every=10)
        polite_sleep()

    return added


def run():
    state = State(PLATFORM)
    preload_seen(state, PLATFORM, key_field="id")
    items_added = [0]
    budget = TimeBudget(PLATFORM_TIME_BUDGET_SEC)

    cookies = parse_cookie_env("NAVER_COOKIE", DOMAIN_COOKIE)
    if cookies:
        names = {c["name"] for c in cookies}
        missing = [n for n in ("NID_AUT", "NID_SES") if n not in names]
        if missing:
            print(f"[{PLATFORM}] WARN: NAVER_COOKIE missing {missing}; partial auth")
        else:
            print(f"[{PLATFORM}] logged in via NAVER_COOKIE")
    else:
        print(f"[{PLATFORM}] WARN: NAVER_COOKIE not set — guest mode "
              "(article bodies may be truncated)")

    try:
        from crawlers.playwright_pool import browser_session
        with browser_session(headless=True, locale="ko-KR") as sess:
            for kw in INCOME_KEYWORDS["ko"]:
                if budget.expired():
                    print(f"[{PLATFORM}] time budget expired")
                    break
                if items_added[0] >= PER_PLATFORM_LIMIT:
                    break
                kw_label = f"search:{kw}"
                if state.is_kw_done(kw_label):
                    continue

                print(f"[{PLATFORM}] kw={kw!r}")
                had_error = False
                try:
                    _process_search_kw(sess, kw, state, items_added, cookies, budget)
                except Exception as e:
                    print(f"  [{PLATFORM}] kw={kw!r} err: {e}")
                    had_error = True

                if not had_error:
                    state.mark_kw_done(kw_label)
                state.save()
                polite_sleep()
                if items_added[0] >= PER_PLATFORM_LIMIT:
                    print(f"[{PLATFORM}] hit PER_PLATFORM_LIMIT={PER_PLATFORM_LIMIT}")
                    break
    finally:
        state.save(force=True)

    print(f"[{PLATFORM}] done, +{items_added[0]} items this run")


if __name__ == "__main__":
    run()
