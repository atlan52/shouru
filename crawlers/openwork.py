"""OpenWork (openwork.jp) crawler — Japanese Glassdoor.

Strategy:
  - Search by salary-flavored keyword: https://www.openwork.jp/search.php?src_str={kw}
  - Each result card shows: company name, industry, scores (avg, salary,
    work_life_balance), num_reviews, snippet. Public.
  - Full review text is behind login — we ONLY collect the public summary
    cards. Country JP, lang ja.
  - Use Playwright (Vue-rendered) with locale ja-JP.
"""
import os
import re
import time
from urllib.parse import quote_plus

from config import (
    PER_PLATFORM_LIMIT, PER_KEYWORD_LIMIT, RAW_DIR, PLATFORM_TIME_BUDGET_SEC,
)
from crawlers.common import (
    append_jsonl, make_id, preload_seen, polite_sleep, parse_cookie_env,
    TimeBudget,
)
from crawlers.state import State


SEARCH_URL = "https://www.openwork.jp/search.php?src_str={kw}"
COMPANY_LIST_URL = "https://www.openwork.jp/company.php?src_pat=2&src_id={n}"
COMPANY_URL = "https://www.openwork.jp/company.php?m_id={cid}"
DOMAIN_COOKIE = ".openwork.jp"
SCROLL_TIMES = 6
SCROLL_PAUSE = 1.2

# Salary-flavored Japanese keywords. We don't reuse INCOME_KEYWORDS because
# OpenWork's search is geared at company/industry filters; these terms map
# to its review-tag system.
SALARY_KEYWORDS = [
    "年収", "給料", "ボーナス", "残業代", "出来高", "コミッション",
]


def _parse_int(s: str) -> int:
    if not s:
        return 0
    m = re.search(r"([\d,]+)", s)
    if not m:
        return 0
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return 0


def _parse_float(s: str) -> float:
    if not s:
        return 0.0
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if not m:
        return 0.0
    try:
        return float(m.group(1))
    except ValueError:
        return 0.0


def _extract_cid(href: str) -> str:
    if not href:
        return ""
    m = re.search(r"m_id=(\d+)", href)
    if m:
        return m.group(1)
    m = re.search(r"/company/(\d+)", href)
    if m:
        return m.group(1)
    return ""


def _card_data(card) -> dict | None:
    try:
        # Company name + URL
        link_el = card.query_selector(
            "a[href*='m_id='], a[href*='/company.php'], a[href*='/company/']"
        )
        href = link_el.get_attribute("href") if link_el else ""
        if href and href.startswith("//"):
            href = "https:" + href
        elif href and href.startswith("/"):
            href = "https://www.openwork.jp" + href
        cid = _extract_cid(href)
        if not cid:
            return None

        name = ""
        name_el = (
            card.query_selector("h2, h3, .company-name, [class*='CompanyName']")
            or link_el
        )
        if name_el:
            try:
                name = name_el.inner_text().strip()
            except Exception:
                name = ""

        # Industry
        industry = ""
        for sel in (
            ".industry", "[class*='Industry']", "[class*='industry']",
            ".company-industry", ".cmp-industry",
        ):
            el = card.query_selector(sel)
            if el:
                try:
                    industry = el.inner_text().strip()
                except Exception:
                    industry = ""
                if industry:
                    break

        # Scores — average / salary / work-life
        avg_score = 0.0
        salary_score = 0.0
        wlb_score = 0.0
        for el in card.query_selector_all(
            "[class*='score'], [class*='Score'], .rate, .rating"
        ):
            try:
                txt = el.inner_text().strip()
            except Exception:
                continue
            if not txt:
                continue
            v = _parse_float(txt)
            if v <= 0 or v > 5.5:
                continue
            low = txt
            try:
                low_attr = (el.get_attribute("class") or "").lower()
            except Exception:
                low_attr = ""
            blob = (low + " " + low_attr).lower()
            if "salary" in blob or "給与" in blob or "年収" in low:
                if salary_score == 0.0:
                    salary_score = v
            elif "work" in blob or "ワークライフ" in low or "働きやすさ" in low:
                if wlb_score == 0.0:
                    wlb_score = v
            elif avg_score == 0.0:
                avg_score = v

        # Number of reviews
        num_reviews = 0
        for el in card.query_selector_all("*"):
            try:
                txt = el.inner_text().strip()
            except Exception:
                continue
            if not txt:
                continue
            if "件" in txt and ("レビュー" in txt or "口コミ" in txt or "回答" in txt):
                num_reviews = _parse_int(txt)
                if num_reviews:
                    break

        # Snippet (first review excerpt visible without login)
        snippet = ""
        for sel in (
            "[class*='Snippet']", "[class*='snippet']",
            ".review-snippet", ".cmp-review-text", "p",
        ):
            el = card.query_selector(sel)
            if el:
                try:
                    snippet = el.inner_text().strip()
                except Exception:
                    snippet = ""
                if snippet and len(snippet) > 30:
                    break

        return {
            "raw_id": cid,
            "name": name[:200],
            "industry": industry[:120],
            "avg_score": avg_score,
            "salary_score": salary_score,
            "work_life_score": wlb_score,
            "num_reviews": num_reviews,
            "snippet": snippet[:1500],
            "url": href or COMPANY_URL.format(cid=cid),
        }
    except Exception as e:
        print(f"  [openwork] card parse err: {e}")
        return None


def _scroll_and_collect(page, state, kw_label: str,
                        items_added_ref: list[int]) -> int:
    added = 0
    seen_this_round = set()
    for _ in range(SCROLL_TIMES):
        try:
            cards = page.query_selector_all(
                "[class*='CompanyCard'], [class*='company-card'], "
                ".search-result-item, li.search-result, .l-cmp-card"
            )
        except Exception:
            cards = []
        if not cards:
            try:
                cards = page.query_selector_all("a[href*='m_id=']")
            except Exception:
                cards = []
            # Fall back to ancestor card if anchor-only
            cards = [c for c in cards if c]

        for c in cards:
            raw = _card_data(c)
            if not raw:
                continue
            if raw["raw_id"] in seen_this_round:
                continue
            seen_this_round.add(raw["raw_id"])
            item_id = make_id("openwork", raw["raw_id"])
            if state.is_seen(item_id):
                continue
            title = raw["name"] or f"company_{raw['raw_id']}"
            # No strict topic filter — OpenWork is wholly salary/jobs context.
            item = {
                "id": item_id,
                "raw_id": raw["raw_id"],
                "platform": "openwork",
                "lang": "ja",
                "country_hint": "JP",
                "title": title,
                "author": "",
                "url": raw["url"],
                "body": raw["snippet"],
                "industry": raw["industry"],
                "scores": {
                    "average": raw["avg_score"],
                    "salary": raw["salary_score"],
                    "work_life": raw["work_life_score"],
                },
                "num_reviews": raw["num_reviews"],
                "matched_keyword": kw_label,
                "engagement": {
                    "score": int(round(raw["avg_score"] * 100)) if raw["avg_score"] else 0,
                    "comments": raw["num_reviews"],
                    "views": None,
                },
            }
            append_jsonl(item, "openwork", RAW_DIR)
            state.mark_seen(item_id)
            added += 1
            items_added_ref[0] += 1
            if items_added_ref[0] >= PER_PLATFORM_LIMIT:
                return added
            if added >= PER_KEYWORD_LIMIT:
                return added
        state.maybe_save(every=10)

        try:
            page.mouse.wheel(0, 4500)
        except Exception:
            pass
        time.sleep(SCROLL_PAUSE)
    return added


def run():
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from crawlers.playwright_pool import browser_session

    state = State("openwork")
    preload_seen(state, "openwork", key_field="id")
    items_added = [0]
    budget = TimeBudget(PLATFORM_TIME_BUDGET_SEC)

    cookies = parse_cookie_env("OPENWORK_COOKIE", DOMAIN_COOKIE)
    if cookies:
        print("[openwork] logged in via OPENWORK_COOKIE")
    else:
        print("[openwork] guest mode — public summary cards only")

    try:
        with browser_session(headless=True, locale="ja-JP") as sess:
            for kw in SALARY_KEYWORDS:
                if budget.expired():
                    print("[openwork] time budget expired")
                    break
                if state.is_kw_done(kw):
                    continue
                print(f"[openwork] kw={kw!r}")
                url = SEARCH_URL.format(kw=quote_plus(kw))
                page = sess.new_page()
                if cookies:
                    try:
                        page.context.add_cookies(cookies)
                    except Exception as e:
                        print(f"  [openwork] add_cookies err: {e}")
                had_error = False
                try:
                    try:
                        page.goto(url, wait_until="domcontentloaded")
                    except PlaywrightTimeoutError:
                        print(f"  [openwork] timeout on {url}")
                        had_error = True
                        continue
                    try:
                        page.wait_for_selector(
                            "a[href*='m_id='], [class*='CompanyCard'], "
                            ".search-result-item",
                            timeout=10000,
                        )
                    except PlaywrightTimeoutError:
                        # No results / Vue still mounting — best effort.
                        pass
                    _scroll_and_collect(page, state, kw, items_added)
                except Exception as e:
                    print(f"  [openwork] kw={kw!r} err: {e}")
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
                    print(f"[openwork] hit PER_PLATFORM_LIMIT={PER_PLATFORM_LIMIT}")
                    break

            # Pass 2: company list pagination (broad scoop) if we still have budget
            if items_added[0] < PER_PLATFORM_LIMIT and not budget.expired():
                start_n = state.get_cursor("list", 1) or 1
                pages = 5 if PER_PLATFORM_LIMIT >= 200 else 1
                for n in range(start_n, start_n + pages):
                    if budget.expired():
                        break
                    label = f"list:{n}"
                    if state.is_kw_done(label):
                        continue
                    url = COMPANY_LIST_URL.format(n=n)
                    print(f"[openwork] list page {n}")
                    page = sess.new_page()
                    if cookies:
                        try:
                            page.context.add_cookies(cookies)
                        except Exception as e:
                            print(f"  [openwork] add_cookies err: {e}")
                    try:
                        try:
                            page.goto(url, wait_until="domcontentloaded")
                        except PlaywrightTimeoutError:
                            print(f"  [openwork] timeout on {url}")
                            continue
                        try:
                            page.wait_for_selector("a[href*='m_id=']", timeout=10000)
                        except PlaywrightTimeoutError:
                            pass
                        _scroll_and_collect(page, state, label, items_added)
                    except Exception as e:
                        print(f"  [openwork] list n={n} err: {e}")
                    finally:
                        try:
                            page.close()
                        except Exception:
                            pass
                    state.set_cursor("list", n + 1)
                    state.mark_kw_done(label)
                    state.save()
                    polite_sleep()
                    if items_added[0] >= PER_PLATFORM_LIMIT:
                        break
    finally:
        state.save(force=True)

    print(f"[openwork] done, +{items_added[0]} items this run")


if __name__ == "__main__":
    run()
