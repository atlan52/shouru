"""Maimai (脉脉) crawler — China's LinkedIn + Blind hybrid.

The 职言 (anonymous gossip) section is full of tech salary leaks like
"我在字节月薪5万+股票" or "腾讯T9一年200万". Maimai uniquely shows the
poster's company affiliation even on anonymous posts — captured via
`company_hint` for the LLM extraction pipeline.

Search:
  https://maimai.cn/search/feeds?query={kw}
  (fallback) https://maimai.cn/web/search_center?type=feed&query={kw}

Set MAIMAI_COOKIE to a raw cookie string (with or without the "Cookie:"
prefix) — the entire site is gated, so without a cookie ~0 yield. Required
cookies typically: uid, AccessToken, csrfToken, u.
"""
import re
import time
from urllib.parse import quote

from config import INCOME_KEYWORDS, PER_PLATFORM_LIMIT, RAW_DIR
from crawlers.common import (
    append_jsonl, is_on_topic_zh, make_id, parse_cookie_env, polite_sleep,
    preload_seen,
)
from crawlers.state import State

PRIMARY_SEARCH_URL = "https://maimai.cn/search/feeds?query={kw}"
FALLBACK_SEARCH_URL = "https://maimai.cn/web/search_center?type=feed&query={kw}"
FEED_DETAIL_URL = "https://maimai.cn/web/feed_detail?fid={fid}"
SCROLL_TIMES = 5
SCROLL_PAUSE = 1.6
DOMAIN_COOKIE = ".maimai.cn"
REQUIRED_COOKIES = ("uid", "AccessToken", "csrfToken", "u")


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


def _looks_like_login_wall(page) -> bool:
    """Detect Maimai's login modal / 'please log in first' interstitials."""
    try:
        if page.query_selector(".login-modal, .login-wrap, .login-dialog"):
            return True
    except Exception:
        pass
    try:
        body_txt = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
    except Exception:
        body_txt = ""
    for marker in ("请先登录", "请登录", "登录后查看", "需要登录"):
        if marker in body_txt:
            return True
    return False


def _extract_feed_id(card) -> str:
    """Try several strategies to pull a stable feed id from a card."""
    for attr in ("data-feed-id", "data-id", "data-fid", "data-feedid"):
        try:
            v = card.get_attribute(attr)
        except Exception:
            v = None
        if v:
            return v.strip()
    # Look for a link to feed_detail
    try:
        link = card.query_selector("a[href*='feed_detail'], a[href*='/feed/']")
        if link:
            href = link.get_attribute("href") or ""
            m = re.search(r"(?:fid=|/feed/)(\d+)", href)
            if m:
                return m.group(1)
    except Exception:
        pass
    return ""


def _card_data(card) -> dict | None:
    """Extract one Maimai feed card. Returns None if unparseable."""
    try:
        raw_id = _extract_feed_id(card)
        if not raw_id:
            return None

        # Body — main post content. Try several selectors.
        body = ""
        for sel in (".feed-content", ".content", ".feed-text",
                    "[class*=feed-content]", "[class*=content-text]",
                    "[class*=text]"):
            try:
                el = card.query_selector(sel)
            except Exception:
                el = None
            if el:
                try:
                    txt = el.inner_text().strip()
                except Exception:
                    txt = ""
                if txt and len(txt) > len(body):
                    body = txt
                    if len(body) > 30:
                        break

        # Title — Maimai posts often have no title; use first line as proxy.
        title = ""
        try:
            t_el = card.query_selector(".feed-title, h2, h3, [class*=title]")
            if t_el:
                title = (t_el.inner_text() or "").strip()
        except Exception:
            pass
        if not title and body:
            title = body.splitlines()[0][:120]

        # Author — often "匿名" on 职言 posts.
        author = ""
        for sel in (".feed-author", ".user-name", ".author-name",
                    "[class*=author]", "[class*=username]"):
            try:
                el = card.query_selector(sel)
            except Exception:
                el = None
            if el:
                try:
                    author = (el.inner_text() or "").strip()
                except Exception:
                    author = ""
                if author:
                    break

        # Company hint — Maimai's signature feature: shows poster's company
        # even on anonymous posts.
        company = ""
        for sel in (".feed-company", ".company-name", ".user-company",
                    "[class*=company]"):
            try:
                el = card.query_selector(sel)
            except Exception:
                el = None
            if el:
                try:
                    company = (el.inner_text() or "").strip()
                except Exception:
                    company = ""
                if company:
                    break

        # Upvotes / comments — action bar
        upvotes = 0
        comments = 0
        try:
            like_el = card.query_selector(".feed-praise, [class*=like], [class*=praise], [class*=zan]")
            if like_el:
                upvotes = _parse_int_cn(like_el.inner_text() or "")
        except Exception:
            pass
        try:
            cmt_el = card.query_selector(".feed-comment, [class*=comment]")
            if cmt_el:
                comments = _parse_int_cn(cmt_el.inner_text() or "")
        except Exception:
            pass

        return {
            "raw_id": raw_id,
            "title": title,
            "body": body,
            "author": author,
            "company": company,
            "upvotes": upvotes,
            "comments": comments,
        }
    except Exception as e:
        print(f"  [maimai] card parse err: {e}")
        return None


def _scroll_and_collect(page, state, kw: str, items_added_ref: list[int]) -> int:
    added = 0
    seen_this_round = set()
    stats = {"cards_seen": 0, "parsed": 0, "off_topic": 0, "deduped": 0}
    for i in range(SCROLL_TIMES):
        try:
            cards = page.query_selector_all(
                ".feed-card, [data-feed-id], [data-id], article, "
                "[class*=feed-item], [class*=FeedCard]"
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
                stats["deduped"] += 1
                continue
            seen_this_round.add(raw["raw_id"])

            title = raw["title"]
            body = raw["body"]
            if not is_on_topic_zh(title, body):
                stats["off_topic"] += 1
                continue
            item_id = make_id("maimai", raw["raw_id"])
            if state.is_seen(item_id):
                continue
            url = FEED_DETAIL_URL.format(fid=raw["raw_id"])
            item = {
                "id": item_id,
                "raw_id": raw["raw_id"],
                "platform": "maimai",
                "lang": "zh",
                "title": title,
                "body": body[:5000],
                "author": raw["author"] or "匿名",
                "url": url,
                "country_hint": "CN",
                "engagement": {
                    "score": int(raw["upvotes"]),
                    "comments": int(raw["comments"]),
                    "views": None,
                },
                "company_hint": raw["company"],
                "matched_keyword": kw,
            }
            append_jsonl(item, "maimai", RAW_DIR)
            state.mark_seen(item["id"])
            added += 1
            items_added_ref[0] += 1
            if items_added_ref[0] >= PER_PLATFORM_LIMIT:
                return added
        state.maybe_save(every=5)

        # Scroll for more
        try:
            page.mouse.wheel(0, 5000)
        except Exception:
            try:
                page.evaluate("window.scrollBy(0, 5000)")
            except Exception:
                pass
        time.sleep(SCROLL_PAUSE)
    print(f"  [maimai] kw={kw!r} cards={stats['cards_seen']} parsed={stats['parsed']} "
          f"off_topic={stats['off_topic']} added={added}")
    return added


def run():
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from crawlers.playwright_pool import browser_session

    state = State("maimai")
    preload_seen(state, "maimai", key_field="id")
    items_added = [0]

    cookies = parse_cookie_env("MAIMAI_COOKIE", DOMAIN_COOKIE)
    if cookies:
        names = {c["name"] for c in cookies}
        missing = [n for n in REQUIRED_COOKIES if n not in names]
        if missing:
            print(f"[maimai] WARN: MAIMAI_COOKIE missing required cookies: {missing} "
                  f"— site may still gate content")
        else:
            print("[maimai] logged in via MAIMAI_COOKIE")
    else:
        print("[maimai] WARN: MAIMAI_COOKIE not set — entire site is gated, "
              "expect ~0 yield. Set MAIMAI_COOKIE to a raw cookie string.")

    keywords = list(INCOME_KEYWORDS.get("zh", []))

    try:
        with browser_session(headless=True, locale="zh-CN") as sess:
            for kw in keywords:
                if state.is_kw_done(kw):
                    continue
                print(f"[maimai] kw={kw!r}")
                page = sess.new_page()
                if cookies:
                    try:
                        page.context.add_cookies(cookies)
                    except Exception as e:
                        print(f"  [maimai] add_cookies err: {e}")

                had_error = False
                login_walled = False
                try:
                    primary = PRIMARY_SEARCH_URL.format(kw=quote(kw))
                    fallback = FALLBACK_SEARCH_URL.format(kw=quote(kw))
                    try:
                        page.goto(primary, wait_until="domcontentloaded")
                    except PlaywrightTimeoutError:
                        print(f"  [maimai] timeout on {primary}, trying fallback")
                        try:
                            page.goto(fallback, wait_until="domcontentloaded")
                        except PlaywrightTimeoutError:
                            print(f"  [maimai] timeout on fallback {fallback}")
                            had_error = True
                            continue

                    # Brief pause for React/Vue list mount
                    try:
                        page.wait_for_selector(
                            ".feed-card, [data-feed-id], [data-id], article, "
                            "[class*=feed-item]",
                            timeout=8000,
                        )
                    except PlaywrightTimeoutError:
                        pass

                    if _looks_like_login_wall(page):
                        print(f"  [maimai] WARN: login wall on kw={kw!r}, skipping")
                        login_walled = True
                        # Mark done so we don't keep retrying same blocked kw.
                        state.mark_kw_done(kw)
                        continue

                    _scroll_and_collect(page, state, kw, items_added)
                except Exception as e:
                    print(f"  [maimai] kw={kw!r} err: {e}")
                    had_error = True
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass

                if not had_error and not login_walled:
                    state.mark_kw_done(kw)
                state.save()
                polite_sleep()
                if items_added[0] >= PER_PLATFORM_LIMIT:
                    print(f"[maimai] hit PER_PLATFORM_LIMIT={PER_PLATFORM_LIMIT}")
                    break
    finally:
        state.save(force=True)

    print(f"[maimai] done, +{items_added[0]} items this run")


if __name__ == "__main__":
    run()
