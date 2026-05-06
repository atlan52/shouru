"""Xiaohongshu (小红书) crawler — Chinese lifestyle / income-disclosure platform.

XHS is one of the biggest income-disclosure surfaces in China: users post
"月入5万的我", "晒工资", "副业月入" notes constantly. This crawler hits the
notes search feed and harvests cards filtered by INCOME_KEYWORDS["zh"].

Search: https://www.xiaohongshu.com/search_result?keyword={kw}&source=web_search_result_notes&type=51

Set env var XHS_COOKIE to a raw cookie string (with or without the
"Cookie:" prefix) to run logged-in. Without cookies the login wall makes
yield ~0; we still try guest mode but log a warning.
"""
import os
import re
import time
from urllib.parse import quote

from config import (
    INCOME_KEYWORDS, PER_PLATFORM_LIMIT, PAGES_PER_QUERY, RAW_DIR,
    PLATFORM_TIME_BUDGET_SEC,
)
from crawlers.common import (
    append_jsonl, make_id, is_on_topic, polite_sleep, preload_seen,
    parse_cookie_env, TimeBudget,
)
from crawlers.state import State

SEARCH_URL = (
    "https://www.xiaohongshu.com/search_result"
    "?keyword={kw}&source=web_search_result_notes&type=51"
)
NOTE_URL_TPL = "https://www.xiaohongshu.com/explore/{nid}"
SCROLL_TIMES = 6
SCROLL_PAUSE = 1.6
DOMAIN_COOKIE = ".xiaohongshu.com"
REQUIRED_COOKIES = ("web_session", "a1", "webId")


def _parse_int_cn(s: str) -> int:
    """Parse '1,234', '1.2 万', '3k', '百' into int. Empty/unknown -> 0."""
    if not s:
        return 0
    s = s.strip().replace(",", "")
    m = re.search(r"([\d\.]+)\s*([万萬KkMm]?)", s)
    if not m:
        return 0
    try:
        v = float(m.group(1))
    except ValueError:
        return 0
    suf = m.group(2)
    if suf in ("万", "萬"):
        v *= 10_000
    elif suf in ("k", "K"):
        v *= 1_000
    elif suf in ("m", "M"):
        v *= 1_000_000
    return int(v)


def _safe_text(el) -> str:
    if el is None:
        return ""
    try:
        return (el.inner_text() or "").strip()
    except Exception:
        return ""


def _safe_attr(el, attr: str) -> str:
    if el is None:
        return ""
    try:
        return (el.get_attribute(attr) or "").strip()
    except Exception:
        return ""


def _extract_note_id(card) -> str:
    """Try multiple strategies to extract a stable note id from a card."""
    # 1) data-id / data-note-id on the section itself
    for attr in ("data-id", "data-note-id", "data-noteid", "id"):
        nid = _safe_attr(card, attr)
        if nid and re.fullmatch(r"[0-9a-fA-F]{16,40}", nid):
            return nid
    # 2) descendant anchor href like /explore/<id> or /search_result/<id>
    try:
        anchors = card.query_selector_all("a[href]")
    except Exception:
        anchors = []
    for a in anchors:
        href = _safe_attr(a, "href")
        if not href:
            continue
        for pat in (
            r"/explore/([0-9a-fA-F]{16,40})",
            r"/search_result/([0-9a-fA-F]{16,40})",
            r"/discovery/item/([0-9a-fA-F]{16,40})",
            r"/item/([0-9a-fA-F]{16,40})",
        ):
            m = re.search(pat, href)
            if m:
                return m.group(1)
    return ""


def _card_data(card) -> dict | None:
    """Extract one XHS note card. Returns None if we can't get a stable id."""
    try:
        nid = _extract_note_id(card)
        if not nid:
            return None

        # Title — try a few selectors. The XHS DOM uses class names like
        # ".title", "span.title", and sometimes obfuscated hashes containing
        # 'title' as a substring; fall back broadly.
        title_el = (
            card.query_selector("a.title span")
            or card.query_selector("a.title")
            or card.query_selector("span.title")
            or card.query_selector(".title")
            or card.query_selector("[class*=title]")
        )
        title = _safe_text(title_el)

        # Body / description — usually empty in search list, but try.
        body_el = (
            card.query_selector(".desc")
            or card.query_selector("[class*=desc]")
            or card.query_selector(".content")
        )
        body = _safe_text(body_el)

        # Fallback: first image alt as a body-ish hint.
        if not body:
            try:
                img = card.query_selector("img[alt]")
                if img:
                    alt = _safe_attr(img, "alt")
                    if alt:
                        body = alt
            except Exception:
                pass

        # Author / user-name
        author_el = (
            card.query_selector(".author .name")
            or card.query_selector(".author")
            or card.query_selector(".user-name")
            or card.query_selector("[class*=user-name]")
            or card.query_selector("[class*=author]")
        )
        author = _safe_text(author_el)

        # Likes — XHS shows a heart icon next to count. Look at known classes
        # plus any "like-wrapper" / "count" descendants.
        like_el = (
            card.query_selector(".like-wrapper .count")
            or card.query_selector(".like .count")
            or card.query_selector("[class*=like] [class*=count]")
            or card.query_selector(".like-wrapper")
            or card.query_selector("[class*=like-wrapper]")
        )
        likes = _parse_int_cn(_safe_text(like_el))

        # Comments / engagement counts (rare on cards but try)
        comments = 0
        try:
            for el in card.query_selector_all("[class*=comment] [class*=count], [class*=comment-count]"):
                txt = _safe_text(el)
                if txt:
                    comments = _parse_int_cn(txt)
                    break
        except Exception:
            pass

        # Image count — image carousels.
        image_count = 0
        try:
            imgs = card.query_selector_all("img")
            image_count = len(imgs) if imgs else 0
        except Exception:
            image_count = 0

        url = NOTE_URL_TPL.format(nid=nid)
        return {
            "raw_id": nid,
            "title": title,
            "body": body,
            "author": author,
            "url": url,
            "likes": likes,
            "comments": comments,
            "image_count": image_count,
        }
    except Exception as e:
        print(f"  [xiaohongshu] card parse err: {e}")
        return None


def _looks_like_login_wall(page) -> bool:
    """Detect XHS login / verify wall — text-based sniff, cheap."""
    try:
        body_text = page.evaluate("() => document.body && document.body.innerText || ''")
    except Exception:
        return False
    if not body_text:
        return False
    needles = ("登录后查看", "请登录", "登录后", "verify", "captcha", "滑动验证", "扫码登录")
    low = body_text.lower()
    for n in needles:
        if n.lower() in low:
            return True
    return False


def _scroll_and_collect(page, state, kw: str, items_added_ref: list[int]) -> int:
    added = 0
    seen_this_round: set[str] = set()
    stats = {"cards_seen": 0, "parsed": 0, "off_topic": 0}
    scroll_n = SCROLL_TIMES
    # PAGES_PER_QUERY is 1 in smoke mode — keep scrolling cheap there.
    if PAGES_PER_QUERY <= 1:
        scroll_n = max(2, SCROLL_TIMES // 2)

    for i in range(scroll_n):
        try:
            cards = page.query_selector_all(
                "section.note-item, a.cover.mask, div.note-item, [class*=note-item]"
            )
        except Exception:
            cards = []
        stats["cards_seen"] = max(stats["cards_seen"], len(cards))

        for c in cards:
            raw = _card_data(c)
            if not raw:
                continue
            stats["parsed"] += 1
            if raw["raw_id"] in seen_this_round:
                continue
            seen_this_round.add(raw["raw_id"])

            title = raw["title"]
            body = raw["body"]
            if not is_on_topic(title, body, lang="zh"):
                stats["off_topic"] += 1
                continue

            item_id = make_id("xiaohongshu", raw["raw_id"])
            if state.is_seen(item_id):
                continue

            item = {
                "id": item_id,
                "raw_id": raw["raw_id"],
                "platform": "xiaohongshu",
                "lang": "zh",
                "title": title,
                "body": body[:5000],
                "author": raw["author"],
                "url": raw["url"],
                "country_hint": "CN",
                "engagement": {
                    "score": int(raw["likes"]),
                    "comments": int(raw["comments"]),
                    "views": None,
                },
                "matched_keyword": kw,
                "image_count": int(raw["image_count"]),
            }
            append_jsonl(item, "xiaohongshu", RAW_DIR)
            state.mark_seen(item["id"])
            added += 1
            items_added_ref[0] += 1
            if items_added_ref[0] >= PER_PLATFORM_LIMIT:
                return added

        state.maybe_save(every=5)

        # Scroll for next batch.
        try:
            page.mouse.wheel(0, 5000)
        except Exception:
            try:
                page.evaluate("window.scrollBy(0, 5000)")
            except Exception:
                pass
        time.sleep(SCROLL_PAUSE)

    print(
        f"  [xiaohongshu] kw={kw!r} stats cards={stats['cards_seen']} "
        f"parsed={stats['parsed']} off_topic={stats['off_topic']} added={added}"
    )
    return added


def run():
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from crawlers.playwright_pool import browser_session

    state = State("xiaohongshu")
    preload_seen(state, "xiaohongshu", key_field="id")
    items_added = [0]
    budget = TimeBudget(PLATFORM_TIME_BUDGET_SEC)

    cookies = parse_cookie_env("XHS_COOKIE", DOMAIN_COOKIE)
    if cookies:
        names = {c["name"] for c in cookies}
        missing = [n for n in REQUIRED_COOKIES if n not in names]
        if missing:
            print(
                f"[xiaohongshu] WARNING: XHS_COOKIE missing required cookies: "
                f"{missing} — login may not stick"
            )
        else:
            print("[xiaohongshu] logged in via XHS_COOKIE")
    else:
        print(
            "[xiaohongshu] WARNING: no XHS_COOKIE set — login wall blocks most "
            "results, expect ~0 yield. Set XHS_COOKIE to fix."
        )

    keywords = list(INCOME_KEYWORDS.get("zh", []))

    try:
        with browser_session(headless=True, locale="zh-CN") as sess:
            for kw in keywords:
                if budget.expired():
                    print(f"[xiaohongshu] time budget expired ({PLATFORM_TIME_BUDGET_SEC}s)")
                    break
                if state.is_kw_done(kw):
                    continue
                print(f"[xiaohongshu] kw={kw!r}")
                url = SEARCH_URL.format(kw=quote(kw))
                page = sess.new_page()
                if cookies:
                    try:
                        page.context.add_cookies(cookies)
                    except Exception as e:
                        print(f"  [xiaohongshu] add_cookies err: {e}")
                had_error = False
                try:
                    try:
                        page.goto(url, wait_until="domcontentloaded")
                    except PlaywrightTimeoutError:
                        print(f"  [xiaohongshu] timeout on {url}")
                        had_error = True
                        continue

                    # Wait briefly for note cards to mount.
                    try:
                        page.wait_for_selector(
                            "section.note-item, a.cover.mask, [class*=note-item]",
                            timeout=8000,
                        )
                    except PlaywrightTimeoutError:
                        # May still scroll-collect: maybe wall, maybe slow JS.
                        pass

                    if _looks_like_login_wall(page):
                        print(
                            f"  [xiaohongshu] login/verify wall on kw={kw!r} — "
                            "skipping"
                        )
                        state.mark_kw_done(kw)
                        state.save()
                        polite_sleep()
                        continue

                    _scroll_and_collect(page, state, kw, items_added)
                except Exception as e:
                    print(f"  [xiaohongshu] kw={kw!r} err: {e}")
                    had_error = True
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass

                if not had_error:
                    state.mark_kw_done(kw)
                state.save()
                polite_sleep()
                if items_added[0] >= PER_PLATFORM_LIMIT:
                    print(f"[xiaohongshu] hit PER_PLATFORM_LIMIT={PER_PLATFORM_LIMIT}")
                    break
    finally:
        state.save(force=True)

    print(f"[xiaohongshu] done, +{items_added[0]} items this run")


if __name__ == "__main__":
    run()
