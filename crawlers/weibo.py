"""Weibo crawler — Chinese microblog, Playwright with optional cookie auth.

Search URL: https://s.weibo.com/weibo?q={kw}&Refer=weibo_weibo
Each '.card-wrap' carries a 'mid' attribute; we extract author / text /
repost-comment-like stats. Click "展开全文" before grabbing full text.

Set env var WEIBO_COOKIE to a raw cookie string (with or without the
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

SEARCH_URL = "https://s.weibo.com/weibo?q={kw}&Refer=weibo_weibo"
SCROLL_TIMES = 4
DOMAIN_COOKIE = ".weibo.com"


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


def _expand(card):
    """Click '展开全文' if present."""
    try:
        btn = card.query_selector("a:has-text('展开')")
        if btn:
            try:
                btn.click(timeout=1500)
                time.sleep(0.3)
            except Exception:
                pass
    except Exception:
        pass


def _card_data(card) -> dict | None:
    try:
        mid = card.get_attribute("mid") or ""
        if not mid:
            # Some cards lack mid (ads, hint rows, "no results"). Skip.
            return None

        # Author
        author_el = card.query_selector(".info .name, a.name, .name")
        author = author_el.inner_text().strip() if author_el else ""

        # Expand full text if possible
        _expand(card)

        text_el = card.query_selector(".txt[node-type='feed_list_content_full']") \
                  or card.query_selector(".txt")
        body = text_el.inner_text().strip() if text_el else ""

        # URL — try the per-card permalink in .from a[href]
        url = ""
        from_el = card.query_selector(".from a[href*='weibo.com']")
        if from_el:
            href = from_el.get_attribute("href") or ""
            if href.startswith("//"):
                href = "https:" + href
            url = href
        if not url:
            url = f"https://weibo.com/detail/{mid}"

        # Stats (.card-act has four <li>: forwards, comments, likes, ...)
        reposts = 0
        comments = 0
        likes = 0
        acts = card.query_selector_all(".card-act li")
        for li in acts:
            try:
                txt = li.inner_text().strip()
            except Exception:
                continue
            if not txt:
                continue
            if "转发" in txt:
                reposts = _parse_int_cn(txt)
            elif "评论" in txt:
                comments = _parse_int_cn(txt)
            elif "赞" in txt or "like" in txt.lower():
                likes = _parse_int_cn(txt)

        return {
            "raw_id": mid,
            "author": author,
            "url": url,
            "body": body,
            "reposts": reposts,
            "comments": comments,
            "likes": likes,
        }
    except Exception as e:
        print(f"  [weibo] card parse err: {e}")
        return None


def _scroll_and_collect(page, state, items_added_ref: list[int]) -> int:
    added = 0
    seen_this_round = set()
    for i in range(SCROLL_TIMES):
        try:
            cards = page.query_selector_all(".card-wrap")
        except Exception:
            cards = []
        for c in cards:
            raw = _card_data(c)
            if not raw:
                continue
            if raw["raw_id"] in seen_this_round:
                continue
            seen_this_round.add(raw["raw_id"])

            body = raw["body"]
            author = raw["author"]
            title = body[:80]
            if not is_on_topic(title, body, author, lang="zh"):
                continue
            item_id = make_id("weibo", raw["raw_id"])
            if state.is_seen(item_id):
                continue
            item = {
                "id": item_id,
                "raw_id": raw["raw_id"],
                "platform": "weibo",
                "lang": "zh",
                "country_hint": "CN",
                "title": title,
                "author": author,
                "url": raw["url"],
                "body": body[:5000],
                "engagement": {
                    "score": int(raw["likes"]),
                    "comments": int(raw["comments"]),
                    "views": None,
                    "reposts": int(raw["reposts"]),
                },
            }
            append_jsonl(item, "weibo", RAW_DIR)
            state.mark_seen(item["id"])
            added += 1
            items_added_ref[0] += 1
            if items_added_ref[0] >= PER_PLATFORM_LIMIT:
                return added
        state.maybe_save(every=5)

        # Weibo rate-limits aggressively → polite scroll pacing.
        try:
            page.mouse.wheel(0, 4000)
        except Exception:
            pass
        polite_sleep()
    return added


def run():
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from crawlers.playwright_pool import browser_session

    state = State("weibo")
    preload_seen(state, "weibo", key_field="id")
    items_added = [0]

    cookies = _parse_cookie_env("WEIBO_COOKIE")
    if cookies:
        print("[weibo] logged in via WEIBO_COOKIE")
    else:
        print("[weibo] guest mode — set WEIBO_COOKIE to log in")
        print("[weibo] no WEIBO_COOKIE set, running in guest mode (low yield expected)")

    try:
        with browser_session(headless=True, locale="zh-CN") as sess:
            for kw in INCOME_KEYWORDS["zh"]:
                if state.is_kw_done(kw):
                    continue
                print(f"[weibo] kw={kw!r}")
                url = SEARCH_URL.format(kw=quote(kw))
                page = sess.new_page()
                if cookies:
                    try:
                        page.context.add_cookies(cookies)
                    except Exception as e:
                        print(f"  [weibo] add_cookies err: {e}")
                had_error = False
                try:
                    try:
                        page.goto(url, wait_until="domcontentloaded")
                    except PlaywrightTimeoutError:
                        print(f"  [weibo] timeout on {url}")
                        had_error = True
                        continue
                    try:
                        page.wait_for_selector(".card-wrap", timeout=8000)
                    except PlaywrightTimeoutError:
                        # Likely login wall or no-results. Keep going best-effort.
                        pass
                    _scroll_and_collect(page, state, items_added)
                except Exception as e:
                    print(f"  [weibo] kw={kw!r} err: {e}")
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
                    print(f"[weibo] hit PER_PLATFORM_LIMIT={PER_PLATFORM_LIMIT}")
                    break
    finally:
        state.save(force=True)

    print(f"[weibo] done, +{items_added[0]} items this run")


if __name__ == "__main__":
    run()
