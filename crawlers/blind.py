"""Blind (teamblind.com) crawler — anonymous workplace gossip.

Heavy in US tech (Google/Meta/Amazon comp threads) and KR tech (네이버,
카카오, 삼성, 쿠팡). Behind an employer-email gate; only logged-in
sessions can read past the first card on most posts.

Set BLIND_COOKIE (raw "Cookie:" string from a logged-in browser) to
unlock content. Without it the crawler will WARN and proceed in guest
mode, where most search hits return only headlines.

Endpoints:
  - Global  : https://www.teamblind.com/search/{kw}
  - Korean  : https://www.teamblind.com/kr/search/{kw}
"""
import re
import time
from urllib.parse import quote

from config import (
    INCOME_KEYWORDS, PER_PLATFORM_LIMIT, PAGES_PER_QUERY, RAW_DIR,
    PLATFORM_TIME_BUDGET_SEC,
)
from crawlers.common import (
    append_jsonl, is_on_topic, make_id, polite_sleep, preload_seen,
    parse_cookie_env, detect_country, TimeBudget,
)
from crawlers.state import State


PLATFORM = "blind"
DOMAIN_COOKIE = ".teamblind.com"
BASE = "https://www.teamblind.com"

GLOBAL_SEARCH_URL = "https://www.teamblind.com/search/{kw}"
KR_SEARCH_URL = "https://www.teamblind.com/kr/search/{kw}"

SCROLL_TIMES = 6
SCROLL_PAUSE = 1.4

# Post URL pattern: /post/{slug}-{postId} or /kr/post/{slug}-{postId}
_POST_HREF_RE = re.compile(
    r"/(?:kr/)?post/([A-Za-z0-9\-_%.]+)-([A-Za-z0-9]{6,})/?(?:\?|$|#)"
)


def _to_int(s: str) -> int:
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


def _abs(href: str) -> str:
    if not href:
        return ""
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return BASE + href
    return href


def _scrape_search_results(page, kr_subpath: bool) -> list[dict]:
    """Extract post cards from a Blind search results page."""
    out = []
    seen_local = set()
    try:
        anchors = page.query_selector_all("a[href*='/post/']")
    except Exception:
        anchors = []

    for a in anchors:
        try:
            href = a.get_attribute("href") or ""
        except Exception:
            continue
        if not href:
            continue
        full = _abs(href)
        m = _POST_HREF_RE.search(full)
        if not m:
            continue
        slug = m.group(1)
        post_id = m.group(2)
        # Filter by subpath: kr search anchors should point at /kr/post/...
        if kr_subpath and "/kr/post/" not in full:
            continue
        if (not kr_subpath) and "/kr/post/" in full:
            # Skip KR posts when we're on the global endpoint
            continue
        if post_id in seen_local:
            continue
        seen_local.add(post_id)

        try:
            title = (a.inner_text() or "").strip()
        except Exception:
            title = ""

        # Walk to the card to grab body excerpt + company tag
        body = ""
        company = ""
        like_count = 0
        comment_count = 0
        try:
            container = a.evaluate_handle(
                "el => el.closest('article, li, .article, [class*=\"feed_card\"], [class*=\"post-card\"]') || el.parentElement"
            )
            if container:
                el = container.as_element()
                if el:
                    desc_el = el.query_selector(
                        ".article_body, .body, .preview, p, [class*='content']"
                    )
                    if desc_el:
                        try:
                            body = (desc_el.inner_text() or "").strip()
                        except Exception:
                            body = ""
                    comp_el = el.query_selector(
                        ".company, .article_info .company, [class*='Company'], [class*='company_name']"
                    )
                    if comp_el:
                        try:
                            company = (comp_el.inner_text() or "").strip()
                        except Exception:
                            company = ""

                    # Engagement counts (like / comment) are tiny <span>s in
                    # the action bar.
                    for s_el in el.query_selector_all(
                        "[class*='like'], [class*='Like'], [class*='comment'], [class*='Comment']"
                    ):
                        try:
                            txt = (s_el.inner_text() or "").strip()
                        except Exception:
                            continue
                        if not txt:
                            continue
                        cls = ""
                        try:
                            cls = (s_el.get_attribute("class") or "").lower()
                        except Exception:
                            pass
                        v = _to_int(txt)
                        if v:
                            if "comment" in cls and not comment_count:
                                comment_count = v
                            elif "like" in cls and not like_count:
                                like_count = v
        except Exception:
            pass

        # Canonical URL
        if kr_subpath:
            url = f"{BASE}/kr/post/{slug}-{post_id}"
        else:
            url = f"{BASE}/post/{slug}-{post_id}"

        if not title:
            continue

        out.append({
            "post_id": post_id,
            "slug": slug,
            "title": title,
            "body": body,
            "company": company,
            "url": url,
            "kr": kr_subpath,
            "like_count": like_count,
            "comment_count": comment_count,
        })
    return out


def _scroll_and_collect(
    page, kw: str, state: State, items_added_ref: list[int],
    kr_subpath: bool, lang: str, country_default: str,
) -> int:
    added = 0
    seen_round = set()
    for i in range(SCROLL_TIMES):
        hits = _scrape_search_results(page, kr_subpath=kr_subpath)
        for meta in hits:
            if meta["post_id"] in seen_round:
                continue
            seen_round.add(meta["post_id"])

            our_id = make_id(PLATFORM, meta["post_id"])
            if state.is_seen(our_id):
                continue

            title = meta["title"]
            body = meta["body"]
            if not is_on_topic(title, body, lang=lang):
                # Try the broader (any-lang) gate too — Blind /search/ mixes
                # many languages on global queries.
                if not is_on_topic(title, body):
                    state.mark_seen(our_id)
                    continue

            # Country detection: if Korean subpath, KR. Else infer from
            # company tag + body, fall back to country_default ("US").
            if kr_subpath:
                country_hint = "KR"
            else:
                country_hint = detect_country(
                    f"{meta.get('company', '')} {body}", hint=country_default
                )

            item = {
                "id": our_id,
                "raw_id": meta["post_id"],
                "platform": PLATFORM,
                "lang": lang,
                "country_hint": country_hint,
                "title": title,
                "body": body[:5000],
                "url": meta["url"],
                "anonymized_company": meta.get("company", ""),
                "post_id": meta["post_id"],
                "slug": meta["slug"],
                "engagement": {
                    "score": int(meta.get("like_count", 0)),
                    "comments": int(meta.get("comment_count", 0)),
                },
                "matched_keyword": kw,
            }
            append_jsonl(item, PLATFORM, RAW_DIR)
            state.mark_seen(our_id)
            added += 1
            items_added_ref[0] += 1
            if items_added_ref[0] >= PER_PLATFORM_LIMIT:
                return added

        state.maybe_save(every=10)
        try:
            page.mouse.wheel(0, 5000)
        except Exception:
            pass
        time.sleep(SCROLL_PAUSE)
    return added


def _run_search(
    sess, cookies, kw: str, state: State, items_added_ref: list[int],
    kr_subpath: bool, lang: str, country_default: str, budget: TimeBudget,
):
    if budget.expired() or items_added_ref[0] >= PER_PLATFORM_LIMIT:
        return False
    label_prefix = "kr" if kr_subpath else "global"
    kw_label = f"{label_prefix}:{kw}"
    if state.is_kw_done(kw_label):
        return False

    template = KR_SEARCH_URL if kr_subpath else GLOBAL_SEARCH_URL
    url = template.format(kw=quote(kw))
    print(f"[{PLATFORM}] {label_prefix} kw={kw!r}")

    page = sess.new_page()
    if cookies:
        try:
            page.context.add_cookies(cookies)
        except Exception as e:
            print(f"  [{PLATFORM}] add_cookies err: {e}")

    had_error = False
    try:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
        except Exception as e:
            print(f"  [{PLATFORM}] goto err {url}: {e}")
            had_error = True
            return False

        # Wait briefly for cards to render
        try:
            page.wait_for_selector("a[href*='/post/']", timeout=8000)
        except Exception:
            pass

        # Page-by-page: Blind uses infinite scroll. We do PAGES_PER_QUERY
        # batches of SCROLL_TIMES scrolls each.
        for page_idx in range(PAGES_PER_QUERY):
            if budget.expired() or items_added_ref[0] >= PER_PLATFORM_LIMIT:
                break
            _scroll_and_collect(
                page, kw, state, items_added_ref,
                kr_subpath=kr_subpath, lang=lang,
                country_default=country_default,
            )
    except Exception as e:
        print(f"  [{PLATFORM}] kw={kw!r} err: {e}")
        had_error = True
    finally:
        try:
            page.close()
        except Exception:
            pass

    if not had_error:
        state.mark_kw_done(kw_label)
    state.save()
    polite_sleep()
    return True


def run():
    state = State(PLATFORM)
    preload_seen(state, PLATFORM, key_field="id")
    items_added = [0]
    budget = TimeBudget(PLATFORM_TIME_BUDGET_SEC)

    cookies = parse_cookie_env("BLIND_COOKIE", DOMAIN_COOKIE)
    if cookies:
        print(f"[{PLATFORM}] logged in via BLIND_COOKIE")
    else:
        print(f"[{PLATFORM}] WARN: BLIND_COOKIE not set — guest mode "
              "(most posts will be paywalled; search may return empty)")

    try:
        from crawlers.playwright_pool import browser_session

        # Phase 1: global /search/ — English locale
        with browser_session(headless=True, locale="en-US") as sess:
            for kw in INCOME_KEYWORDS["en"]:
                if budget.expired() or items_added[0] >= PER_PLATFORM_LIMIT:
                    break
                _run_search(
                    sess, cookies, kw, state, items_added,
                    kr_subpath=False, lang="en",
                    country_default="US", budget=budget,
                )

        if budget.expired() or items_added[0] >= PER_PLATFORM_LIMIT:
            print(f"[{PLATFORM}] stopping after global phase: "
                  f"+{items_added[0]} items")
        else:
            # Phase 2: /kr/search/ — Korean locale
            with browser_session(headless=True, locale="ko-KR") as sess:
                for kw in INCOME_KEYWORDS["ko"]:
                    if budget.expired() or items_added[0] >= PER_PLATFORM_LIMIT:
                        break
                    _run_search(
                        sess, cookies, kw, state, items_added,
                        kr_subpath=True, lang="ko",
                        country_default="KR", budget=budget,
                    )
    finally:
        state.save(force=True)

    print(f"[{PLATFORM}] done, +{items_added[0]} items this run")


if __name__ == "__main__":
    run()
