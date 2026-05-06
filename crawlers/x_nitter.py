"""Twitter/X crawler via Nitter public instances (HTML-rendered, no JS).

Primary path: requests + BeautifulSoup against the instances listed in
`NITTER_INSTANCES`. Falls back to Playwright on x.com search if every
nitter instance is dead.

Iterates keywords across multiple languages — INCOME_KEYWORDS[lang] for
lang in ["en", "es", "pt", "ja", "ko"] — for cross-language diversity.

Set env var X_COOKIE to a raw cookie string (with or without the
"Cookie:" prefix) to run the Playwright fallback logged-in. Guest mode
still works but hits aggressive rate-limits.

Set env var SKIP_NITTER=1 to skip the dead nitter instance probing and
go straight to the Playwright fallback for every keyword.
"""
import os
import re
import time
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

from config import (
    INCOME_KEYWORDS, PER_PLATFORM_LIMIT, RAW_DIR,
)
from crawlers.common import (
    append_jsonl, default_headers, is_on_topic, make_id,
    polite_sleep, preload_seen,
)
from crawlers.state import State

# Nitter public instances — fallback chain (first that works wins).
# If all die we fall back to Playwright against x.com directly.
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
]

# Languages to sweep; each contributes its own INCOME_KEYWORDS list.
X_NITTER_LANGS = ["en", "es", "pt", "ja", "ko"]

PAGES_PER_KEYWORD = 3
DOMAIN_COOKIE = ".x.com"


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


def _parse_int(s: str) -> int:
    if not s:
        return 0
    s = s.strip().replace(",", "").replace(" ", "")
    m = re.match(r"([\d\.]+)\s*([KkMm]?)", s)
    if not m:
        return 0
    try:
        v = float(m.group(1))
    except ValueError:
        return 0
    suf = m.group(2).lower()
    if suf == "k":
        v *= 1_000
    elif suf == "m":
        v *= 1_000_000
    return int(v)


def _fetch(url: str, timeout: int = 20) -> str | None:
    try:
        r = requests.get(url, headers=default_headers(), timeout=timeout)
        if r.status_code in (429, 502, 503, 504):
            print(f"  [x_nitter] status {r.status_code} on {url}")
            return None
        if r.status_code != 200:
            return None
        return r.text
    except Exception as e:
        print(f"  [x_nitter] fetch err {url}: {e}")
        return None


def _parse_nitter(html: str, instance: str):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for card in soup.select(".timeline-item"):
        link = card.select_one("a.tweet-link")
        if not link:
            continue
        href = link.get("href", "")
        m = re.search(r"/([^/]+)/status/(\d+)", href)
        if not m:
            continue
        author, raw_id = m.group(1), m.group(2)

        content_el = card.select_one(".tweet-content")
        text = content_el.get_text(" ", strip=True) if content_el else ""

        username_el = card.select_one(".username")
        username = username_el.get_text(strip=True) if username_el else author

        stats = {"replies": 0, "retweets": 0, "quotes": 0, "likes": 0}
        for stat in card.select(".tweet-stats .tweet-stat"):
            icon = stat.select_one(".icon-container")
            txt = stat.get_text(" ", strip=True)
            num = _parse_int(txt)
            cls = " ".join(icon.get("class", [])) if icon else ""
            raw = " ".join(stat.get("class", [])) + " " + cls
            if "comment" in raw or "reply" in raw:
                stats["replies"] = num
            elif "retweet" in raw:
                stats["retweets"] = num
            elif "quote" in raw:
                stats["quotes"] = num
            elif "heart" in raw or "like" in raw:
                stats["likes"] = num
            else:
                # fall back to order (nitter renders in: replies, retweets, quotes, likes)
                pass

        date_el = card.select_one(".tweet-date a")
        created = date_el.get("title", "") if date_el else ""

        items.append({
            "raw_id": raw_id,
            "author": username,
            "author_handle": author,
            "text": text,
            "stats": stats,
            "created": created,
            "permalink": urljoin(instance, href.split("#")[0]),
        })

    next_href = None
    more = soup.select_one(".show-more a")
    if more and more.get("href"):
        next_href = more["href"]
    return items, next_href


def _normalize(t: dict, lang: str) -> dict | None:
    text = t.get("text", "") or ""
    if not is_on_topic(text, lang=lang):
        return None
    raw_id = t["raw_id"]
    stats = t.get("stats", {})
    return {
        "id": make_id("x_nitter", raw_id),
        "raw_id": raw_id,
        "platform": "x_nitter",
        "lang": lang,
        "country_hint": "??",
        "title": text[:140],
        "author": t.get("author", ""),
        "url": f"https://x.com/{t.get('author_handle','')}/status/{raw_id}",
        "body": text[:5000],
        "engagement": {
            "score": int(stats.get("likes", 0)),
            "comments": int(stats.get("replies", 0)),
            "views": None,
        },
        "created_utc": t.get("created", ""),
    }


def _scrape_nitter(kw: str, lang: str, state, items_added_ref: list[int]) -> int:
    """Try every nitter instance for this keyword. Returns items added."""
    added = 0
    for inst in NITTER_INSTANCES:
        cursor = state.get_cursor(kw, "")
        path = f"/search?f=tweets&q={quote_plus(kw)}"
        if cursor:
            path += f"&{cursor.lstrip('?&')}"
        url = inst + path
        ok_any = False
        for page in range(PAGES_PER_KEYWORD):
            html = _fetch(url)
            if not html:
                break
            ok_any = True
            tweets, next_href = _parse_nitter(html, inst)
            if not tweets:
                break
            for t in tweets:
                item = _normalize(t, lang)
                if not item:
                    continue
                if state.is_seen(item["id"]):
                    continue
                append_jsonl(item, "x_nitter", RAW_DIR)
                state.mark_seen(item["id"])
                added += 1
                items_added_ref[0] += 1
                if items_added_ref[0] >= PER_PLATFORM_LIMIT:
                    return added
            state.maybe_save(every=5)
            if not next_href:
                break
            url = inst + next_href
            state.set_cursor(kw, next_href)
            polite_sleep()
        if ok_any:
            return added
        print(f"  [x_nitter] instance {inst} failed, trying next")
    return added


def _scrape_x_playwright(kw: str, lang: str, state, items_added_ref: list[int]) -> int:
    """Fallback: render x.com search via Playwright; scroll 3x."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from crawlers.playwright_pool import browser_session

    added = 0
    url = f"https://x.com/search?q={quote_plus(kw)}&src=typed_query&f=live"
    cookies = _parse_cookie_env("X_COOKIE")
    try:
        with browser_session(headless=True) as sess:
            page = sess.new_page()
            if cookies:
                try:
                    page.context.add_cookies(cookies)
                except Exception as e:
                    print(f"  [x_nitter/pw] add_cookies err: {e}")
            try:
                page.goto(url, wait_until="domcontentloaded")
            except PlaywrightTimeoutError:
                print(f"  [x_nitter/pw] timeout on {url}")
                page.close()
                return added

            # Tweet cards only appear after client-side render. Wait for
            # at least one tweet to exist before scrolling/collecting.
            try:
                page.wait_for_selector('[data-testid="tweet"]', timeout=15000)
            except PlaywrightTimeoutError:
                # Could be a login prompt, empty result set, or rate-limit.
                body = (page.locator("body").inner_text() or "")[:200]
                print(f"  [x_nitter/pw] no tweets rendered for {kw!r}: {body!r}")
                page.close()
                return added

            for _ in range(3):
                try:
                    page.mouse.wheel(0, 4000)
                except Exception:
                    pass
                time.sleep(2)

            try:
                cards = page.query_selector_all('[data-testid="tweet"]')
            except Exception:
                cards = []
            print(f"  [x_nitter/pw] {kw!r}: {len(cards)} card(s) rendered")
            for c in cards:
                try:
                    text_el = c.query_selector('[data-testid="tweetText"]')
                    text = text_el.inner_text() if text_el else ""
                    link_el = c.query_selector('a[href*="/status/"]')
                    href = link_el.get_attribute("href") if link_el else ""
                    m = re.search(r"/([^/]+)/status/(\d+)", href or "")
                    if not m:
                        continue
                    author, raw_id = m.group(1), m.group(2)
                    if not is_on_topic(text, lang=lang):
                        continue
                    item = {
                        "id": make_id("x_nitter", raw_id),
                        "raw_id": raw_id,
                        "platform": "x_nitter",
                        "lang": lang,
                        "country_hint": "??",
                        "title": text[:140],
                        "author": author,
                        "url": f"https://x.com{href}",
                        "body": text[:5000],
                        "engagement": {"score": 0, "comments": 0, "views": None},
                    }
                    if state.is_seen(item["id"]):
                        continue
                    append_jsonl(item, "x_nitter", RAW_DIR)
                    state.mark_seen(item["id"])
                    added += 1
                    items_added_ref[0] += 1
                    if items_added_ref[0] >= PER_PLATFORM_LIMIT:
                        break
                except Exception as e:
                    print(f"  [x_nitter/pw] card err: {e}")
            page.close()
    except Exception as e:
        print(f"  [x_nitter/pw] session err: {e}")
    return added


def run():
    state = State("x_nitter")
    preload_seen(state, "x_nitter", key_field="id")
    items_added = [0]

    cookies = _parse_cookie_env("X_COOKIE")
    if cookies:
        print("[x_nitter] logged in via X_COOKIE")
    else:
        print("[x_nitter] guest mode — set X_COOKIE to log in")
        print("[x_nitter] no X_COOKIE set, running in guest mode (low yield expected)")

    skip_nitter = (os.environ.get("SKIP_NITTER") or "").strip() == "1"
    if skip_nitter:
        print("[x_nitter] SKIP_NITTER=1 — bypassing nitter instances, Playwright only")

    try:
        done = False
        for lang in X_NITTER_LANGS:
            if done:
                break
            kws = INCOME_KEYWORDS.get(lang) or []
            if not kws:
                continue
            print(f"[x_nitter] lang={lang} ({len(kws)} keywords)")
            for kw in kws:
                # Namespace the keyword in state so the same word in two
                # languages doesn't collide on kw_done / cursor.
                kw_key = f"{lang}:{kw}"
                if state.is_kw_done(kw_key):
                    continue
                print(f"[x_nitter] kw={kw!r} (lang={lang})")
                had_error = False
                if skip_nitter:
                    added = 0
                else:
                    added = _scrape_nitter(kw, lang, state, items_added)
                if added == 0:
                    # Nitter-wide failure (or skipped); try Playwright fallback.
                    if not skip_nitter:
                        print(f"  [x_nitter] nitter empty for {kw!r}, falling back to Playwright")
                    try:
                        added = _scrape_x_playwright(kw, lang, state, items_added)
                    except Exception as e:
                        print(f"  [x_nitter] playwright fallback err: {e}")
                        had_error = True
                if not had_error:
                    state.mark_kw_done(kw_key)
                state.maybe_save(every=5)
                polite_sleep()
                if items_added[0] >= PER_PLATFORM_LIMIT:
                    print(f"[x_nitter] hit PER_PLATFORM_LIMIT={PER_PLATFORM_LIMIT}")
                    done = True
                    break
    finally:
        state.save(force=True)

    print(f"[x_nitter] done, +{items_added[0]} items this run")


if __name__ == "__main__":
    run()
