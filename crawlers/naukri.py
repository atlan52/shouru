"""Naukri crawler — India's largest job board (P2 priority).

Strategy:
  - Naukri renders results dynamically via Angular → Playwright required.
  - Search URL: https://www.naukri.com/{kw}-jobs-in-{city}
  - Per listing: jobId, title, company, location, salary range,
    experience range, description body. Skip listings tagged "Not Disclosed".
  - Country: IN, lang: en, locale: en-IN.
"""
import re
import time
from urllib.parse import urljoin

from config import (
    PER_PLATFORM_LIMIT, RAW_DIR, PLATFORM_TIME_BUDGET_SEC,
)
from crawlers.common import (
    append_jsonl, make_id, polite_sleep, preload_seen, TimeBudget,
)
from crawlers.state import State

BASE = "https://www.naukri.com"
SEARCH_URL = BASE + "/{kw}-jobs-in-{city}"

KEYWORDS = [
    "software-engineer", "data-scientist", "marketing-manager",
    "sales-executive", "doctor", "teacher", "accountant",
    "lawyer", "designer", "product-manager",
]
CITIES = ["bangalore", "mumbai", "delhi-ncr", "pune", "hyderabad", "chennai"]

SCROLL_TIMES = 6
SCROLL_PAUSE = 1.5
PER_PAGE_PAGES = 2  # how many listing pages per (kw,city) tuple


# ============================================================================
# Card parsing
# ============================================================================
def _card_data(card) -> dict | None:
    """Extract one job-listing tile from the search result page."""
    try:
        # Card root carries data-job-id on Naukri
        job_id = (
            card.get_attribute("data-job-id")
            or card.get_attribute("data-jobid")
            or ""
        )
        # Title + URL
        title_el = (
            card.query_selector("a.title, a.jobTitle, a.title.fw500, .title a")
            or card.query_selector("a[href*='job-listings-']")
        )
        title = (title_el.inner_text().strip() if title_el else "")[:300]
        href = title_el.get_attribute("href") if title_el else ""
        if href and href.startswith("/"):
            href = urljoin(BASE, href)
        # Recover jobId from the URL if attribute was missing
        if not job_id and href:
            m = re.search(r"job-listings-[\w\-]+-(\d+)", href)
            if m:
                job_id = m.group(1)
        if not job_id:
            return None

        # Company
        comp_el = card.query_selector(
            "a.subTitle, .companyInfo a, .comp-name, .companyName"
        )
        company = comp_el.inner_text().strip() if comp_el else ""

        # Location
        loc_el = card.query_selector(
            ".locWdth, .location, .loc, span.location, li.location, .locationsContainer"
        )
        location = loc_el.inner_text().strip() if loc_el else ""

        # Experience
        exp_el = card.query_selector(
            ".expwdth, .experience, .exp, span.experience, li.experience"
        )
        experience = exp_el.inner_text().strip() if exp_el else ""

        # Salary
        sal_el = card.query_selector(
            ".sal, .salary, span.salary, li.salary, .salaryWrap"
        )
        salary = sal_el.inner_text().strip() if sal_el else ""

        # Snippet/description
        desc_el = card.query_selector(
            ".job-description, .jobDescription, .desc, .jd, .jobDesc"
        )
        body = desc_el.inner_text().strip() if desc_el else ""

        return {
            "raw_id": str(job_id),
            "title": title,
            "company": company,
            "location": location,
            "experience": experience,
            "salary": salary,
            "body": body,
            "url": href or f"{BASE}/job-listings-{job_id}",
        }
    except Exception as e:
        print(f"  [naukri] card parse err: {e}")
        return None


_NOT_DISCLOSED_RE = re.compile(r"not\s*disclosed|not\s*specified|^-$", re.I)


def _has_real_salary(s: str) -> bool:
    if not s:
        return False
    if _NOT_DISCLOSED_RE.search(s.strip()):
        return False
    # Accept any string with a digit + Lakh/LPA/Cr/PA hint or a range dash.
    if re.search(r"\d", s) and re.search(r"(lakh|lpa|crore|cr|pa|per\s*annum|/yr|₹|-)", s, re.I):
        return True
    return False


# ============================================================================
# Scroll + collect
# ============================================================================
def _scroll_and_collect(page, state, items_added_ref: list[int],
                        kw: str, city: str) -> int:
    added = 0
    seen_this_round = set()
    stats = {"cards": 0, "parsed": 0, "no_salary": 0}

    for _ in range(SCROLL_TIMES):
        try:
            cards = page.query_selector_all(
                "article.jobTuple, .jobTuple, .srp-jobtuple-wrapper, "
                ".srp-tuple, [data-job-id]"
            )
        except Exception:
            cards = []
        stats["cards"] = max(stats["cards"], len(cards))

        for c in cards:
            raw = _card_data(c)
            if not raw:
                continue
            stats["parsed"] += 1
            if raw["raw_id"] in seen_this_round:
                continue
            seen_this_round.add(raw["raw_id"])

            if not _has_real_salary(raw["salary"]):
                stats["no_salary"] += 1
                continue

            item_id = make_id("naukri", raw["raw_id"])
            if state.is_seen(item_id):
                continue

            full_body_parts = [raw["body"], raw["experience"], raw["location"], raw["salary"]]
            full_body = " | ".join(p for p in full_body_parts if p)[:5000]

            item = {
                "id": item_id,
                "raw_id": raw["raw_id"],
                "platform": "naukri",
                "lang": "en",
                "country_hint": "IN",
                "kind": "job_listing",
                "title": raw["title"],
                "company": raw["company"],
                "location": raw["location"],
                "experience_required": raw["experience"],
                "salary_range": raw["salary"],
                "body": full_body,
                "url": raw["url"],
                "matched_keyword": f"{kw}@{city}",
                "engagement": {"score": 0, "comments": 0, "views": None},
            }
            append_jsonl(item, "naukri", RAW_DIR)
            state.mark_seen(item["id"])
            added += 1
            items_added_ref[0] += 1
            if items_added_ref[0] >= PER_PLATFORM_LIMIT:
                return added

        state.maybe_save(every=5)
        try:
            page.mouse.wheel(0, 4500)
        except Exception:
            pass
        time.sleep(SCROLL_PAUSE)

    print(f"  [naukri] kw={kw}@{city} cards={stats['cards']} parsed={stats['parsed']} "
          f"no_salary={stats['no_salary']} added={added}")
    return added


# ============================================================================
# run()
# ============================================================================
def run():
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from crawlers.playwright_pool import browser_session

    state = State("naukri")
    preload_seen(state, "naukri", key_field="id")
    items_added = [0]
    budget = TimeBudget(PLATFORM_TIME_BUDGET_SEC)

    try:
        with browser_session(headless=True, locale="en-IN") as sess:
            for kw in KEYWORDS:
                if budget.expired():
                    print("[naukri] time budget expired")
                    break
                for city in CITIES:
                    if budget.expired():
                        break
                    label = f"{kw}@{city}"
                    if state.is_kw_done(label):
                        continue
                    print(f"[naukri] kw={kw} city={city}")
                    had_error = False

                    for page_num in range(1, PER_PAGE_PAGES + 1):
                        url = SEARCH_URL.format(kw=kw, city=city)
                        if page_num > 1:
                            url = f"{url}-{page_num}"
                        page = sess.new_page()
                        try:
                            try:
                                page.goto(url, wait_until="domcontentloaded")
                            except PlaywrightTimeoutError:
                                print(f"  [naukri] timeout on {url}")
                                had_error = True
                                continue
                            try:
                                page.wait_for_selector(
                                    "article.jobTuple, .jobTuple, "
                                    ".srp-jobtuple-wrapper, [data-job-id]",
                                    timeout=10000,
                                )
                            except PlaywrightTimeoutError:
                                # Likely no results / regional redirect; still try.
                                pass
                            _scroll_and_collect(page, state, items_added, kw, city)
                        except Exception as e:
                            print(f"  [naukri] {label} p{page_num} err: {e}")
                            had_error = True
                        finally:
                            try:
                                page.close()
                            except Exception:
                                pass
                        polite_sleep()
                        if items_added[0] >= PER_PLATFORM_LIMIT:
                            break

                    if not had_error:
                        state.mark_kw_done(label)
                    state.save()
                    polite_sleep()
                    if items_added[0] >= PER_PLATFORM_LIMIT:
                        print(f"[naukri] hit PER_PLATFORM_LIMIT={PER_PLATFORM_LIMIT}")
                        break
                if items_added[0] >= PER_PLATFORM_LIMIT:
                    break
    finally:
        state.save(force=True)

    print(f"[naukri] done, +{items_added[0]} items this run")


if __name__ == "__main__":
    run()
