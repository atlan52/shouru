"""Zhihu crawler — Chinese Q&A platform, Playwright with optional cookie auth.

Search: https://www.zhihu.com/search?type=content&q={kw}
Scrolls 5-10x to load more, extracts answer/question cards, handles the
"查看更多" expander. Filters to topic tokens in Chinese.

Set env var ZHIHU_COOKIE to a raw cookie string (with or without the
"Cookie:" prefix) to run logged-in. Guest mode still works but yields
much less content.
"""
import os
import re
import time
from urllib.parse import quote

from config import INCOME_KEYWORDS, PER_PLATFORM_LIMIT, RAW_DIR
from crawlers.common import (
    append_jsonl, is_on_topic, make_id, polite_sleep, preload_seen,
)
from crawlers.state import State

SEARCH_URL = "https://www.zhihu.com/search?type=content&q={kw}"
SCROLL_TIMES = 7
SCROLL_PAUSE = 1.5
DOMAIN_COOKIE = ".zhihu.com"


def _parse_cookie_env(var_name: str) -> list[dict]:
    """Parse a raw 'Cookie: foo=bar; baz=qux' string (or the value portion
    without the 'Cookie:' prefix) from env var `var_name` into a list of
    Playwright-ready cookie dicts. Returns [] if unset."""
    raw = (os.environ.get(var_name) or "").strip()
    if not raw:
        return []
    if raw.lower().startswith("cookie:"):
        raw = raw[len("cookie:"):].strip()
    cookies = []
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        cookies.append({"name": name.strip(), "value": value.strip(),
                        "domain": DOMAIN_COOKIE, "path": "/"})
    return cookies


def _parse_int_cn(s: str) -> int:
    """Parse '1,234', '1.2 万', '3k' into int."""
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


def _card_data(card) -> dict | None:
    """Extract one Zhihu search card. Returns None if unparseable."""
    try:
        # Title / question stem
        title_el = card.query_selector("h2 a, h2, .ContentItem-title a, .ContentItem-title")
        title = title_el.inner_text().strip() if title_el else ""

        # URL + raw id — prefer anchor on the title.
        link_el = card.query_selector("h2 a") or card.query_selector("a[href*='/answer/']") \
                  or card.query_selector("a[href*='/question/']")
        href = link_el.get_attribute("href") if link_el else ""
        if href and href.startswith("//"):
            href = "https:" + href
        elif href and href.startswith("/"):
            href = "https://www.zhihu.com" + href

        raw_id = ""
        if href:
            m = re.search(r"/answer/(\d+)", href)
            if m:
                raw_id = "a" + m.group(1)
            else:
                m = re.search(r"/question/(\d+)", href)
                if m:
                    raw_id = "q" + m.group(1)
                else:
                    m = re.search(r"/p/(\d+)", href)
                    if m:
                        raw_id = "p" + m.group(1)
        if not raw_id:
            return None

        # Author
        author_el = card.query_selector(".AuthorInfo-name a, .AuthorInfo-name")
        author = author_el.inner_text().strip() if author_el else ""

        # Expand "查看更多" (limited — sometimes collapsed)
        try:
            more = card.query_selector("button.ContentItem-more, .RichContent-inner button")
            if more:
                try:
                    more.click(timeout=1500)
                    time.sleep(0.3)
                except Exception:
                    pass
        except Exception:
            pass

        body_el = card.query_selector(".RichContent-inner, .RichText, .ContentItem-content")
        body = body_el.inner_text().strip() if body_el else ""

        # Upvotes + comments — action bar
        score = 0
        comments = 0
        for btn in card.query_selector_all(".ContentItem-actions button, .ContentItem-actions span, .Button"):
            try:
                txt = btn.inner_text().strip()
            except Exception:
                continue
            if not txt:
                continue
            if "赞同" in txt or "赞" == txt[:1]:
                score = _parse_int_cn(txt)
            elif "评论" in txt:
                comments = _parse_int_cn(txt)

        return {
            "raw_id": raw_id,
            "title": title,
            "author": author,
            "url": href,
            "body": body,
            "score": score,
            "comments": comments,
        }
    except Exception as e:
        print(f"  [zhihu] card parse err: {e}")
        return None


def _scroll_and_collect(page, state, items_added_ref: list[int]) -> int:
    added = 0
    seen_this_round = set()
    stats = {"cards_seen": 0, "parsed": 0, "off_topic": 0, "deduped": 0}
    for i in range(SCROLL_TIMES):
        try:
            cards = page.query_selector_all(".List-item, .SearchResult-Card")
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
            item_id = make_id("zhihu", raw["raw_id"])
            if state.is_seen(item_id):
                continue
            item = {
                "id": item_id,
                "raw_id": raw["raw_id"],
                "platform": "zhihu",
                "lang": "zh",
                "country_hint": "CN",
                "title": title,
                "author": raw["author"],
                "url": raw["url"],
                "body": body[:5000],
                "engagement": {
                    "score": int(raw["score"]),
                    "comments": int(raw["comments"]),
                    "views": None,
                },
            }
            append_jsonl(item, "zhihu", RAW_DIR)
            state.mark_seen(item["id"])
            added += 1
            items_added_ref[0] += 1
            if items_added_ref[0] >= PER_PLATFORM_LIMIT:
                return added
        state.maybe_save(every=5)

        # Scroll
        try:
            page.mouse.wheel(0, 5000)
        except Exception:
            pass
        time.sleep(SCROLL_PAUSE)
    print(f"  [zhihu] stats cards={stats['cards_seen']} parsed={stats['parsed']} "
          f"off_topic={stats['off_topic']} added={added}")
    return added


def run():
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from crawlers.playwright_pool import browser_session

    state = State("zhihu")
    preload_seen(state, "zhihu", key_field="id")
    items_added = [0]

    cookies = _parse_cookie_env("ZHIHU_COOKIE")
    if cookies:
        print("[zhihu] logged in via ZHIHU_COOKIE")
    else:
        print("[zhihu] guest mode — set ZHIHU_COOKIE to log in")
        print("[zhihu] no ZHIHU_COOKIE set, running in guest mode (low yield expected)")

    try:
        with browser_session(headless=True, locale="zh-CN") as sess:
            for kw in INCOME_KEYWORDS["zh"]:
                if state.is_kw_done(kw):
                    continue
                print(f"[zhihu] kw={kw!r}")
                url = SEARCH_URL.format(kw=quote(kw))
                page = sess.new_page()
                if cookies:
                    try:
                        page.context.add_cookies(cookies)
                    except Exception as e:
                        print(f"  [zhihu] add_cookies err: {e}")
                had_error = False
                try:
                    try:
                        page.goto(url, wait_until="domcontentloaded")
                    except PlaywrightTimeoutError:
                        print(f"  [zhihu] timeout on {url}")
                        had_error = True
                        continue
                    # Wait briefly for React to mount list-items.
                    try:
                        page.wait_for_selector(".List-item, .SearchResult-Card", timeout=8000)
                    except PlaywrightTimeoutError:
                        # Still try: maybe logged-out wall interfered.
                        pass
                    _scroll_and_collect(page, state, items_added)
                except Exception as e:
                    print(f"  [zhihu] kw={kw!r} err: {e}")
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
                    print(f"[zhihu] hit PER_PLATFORM_LIMIT={PER_PLATFORM_LIMIT}")
                    break
    finally:
        state.save(force=True)

    print(f"[zhihu] done, +{items_added[0]} items this run")


if __name__ == "__main__":
    run()
