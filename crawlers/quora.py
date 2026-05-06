"""Quora multi-language scraper — income disclosure across en/es/pt/ja/hi/it/fr/de.

Quora has rich income discussion in many languages, especially:
  - English (US, IN diaspora) at quora.com
  - Spanish (LatAm/ES) at es.quora.com
  - Portuguese (BR) at pt.quora.com
  - Hindi (IN) at hi.quora.com
  - Japanese (JP) at jp.quora.com
  - Italian / French / German subdomains

Heavy JS + bot detection, so we use the shared Playwright session with stealth
init script. Per-(lang, kw) we hit the search endpoint, scroll a few times to
load more cards, then extract title / top-answer body / author / upvotes.

Env: SMOKE_TEST=1 cuts limits via PER_PLATFORM_LIMIT/PER_KEYWORD_LIMIT.
"""
import re
import time
from urllib.parse import quote

from config import (
    INCOME_KEYWORDS, PER_PLATFORM_LIMIT, PER_KEYWORD_LIMIT, RAW_DIR,
    PLATFORM_TIME_BUDGET_SEC,
)
from crawlers.common import (
    append_jsonl, detect_country, is_on_topic, make_id, polite_sleep,
    preload_seen, random_ua, TimeBudget,
)
from crawlers.state import State


# Languages we cover on Quora; English uses the apex www subdomain.
QUORA_LANGS = ["en", "es", "pt", "ja", "hi", "it", "fr", "de"]

# Per-language Locale + AcceptLang hints for the browser context.
LANG_LOCALE = {
    "en": "en-US",
    "es": "es-ES",
    "pt": "pt-BR",
    "ja": "ja-JP",
    "hi": "hi-IN",
    "it": "it-IT",
    "fr": "fr-FR",
    "de": "de-DE",
}

# Primary country fallback per language. en is multi → fall back to detect_country.
LANG_PRIMARY_COUNTRY = {
    "en": "??",
    "es": "MX",
    "pt": "BR",
    "ja": "JP",
    "hi": "IN",
    "it": "IT",
    "fr": "FR",
    "de": "DE",
}

SCROLL_TIMES = 6
SCROLL_PAUSE = 2.5


def _search_url(lang: str, kw: str) -> str:
    q = quote(kw)
    if lang == "en":
        return f"https://www.quora.com/search?q={q}&type=question"
    return f"https://{lang}.quora.com/search?q={q}&type=question"


def _is_blocked(page) -> bool:
    """Detect Quora captcha / verification interstitial."""
    try:
        title = (page.title() or "").strip().lower()
    except Exception:
        title = ""
    try:
        body_txt = (page.evaluate("document.body && document.body.innerText || ''") or "").lower()
    except Exception:
        body_txt = ""
    # Page title is just "Quora" → likely interstitial / login wall.
    if title in ("quora",) and len(body_txt) < 400:
        return True
    if "captcha" in body_txt or "verification" in body_txt or "are you a human" in body_txt:
        return True
    if "log in to quora" in body_txt and len(body_txt) < 800:
        return True
    return False


def _extract_slug(href: str) -> str:
    """Pull the question slug out of a Quora URL.

    Examples:
      https://www.quora.com/How-much-do-software-engineers-make → 'How-much-do-software-engineers-make'
      https://es.quora.com/Cuanto-ganas → 'Cuanto-ganas'
      /How-much-do-engineers-make → 'How-much-do-engineers-make'
    """
    if not href:
        return ""
    href = href.split("?", 1)[0].split("#", 1)[0]
    # Strip protocol+host
    m = re.match(r"^https?://[^/]+(/.*)$", href)
    path = m.group(1) if m else href
    if not path.startswith("/"):
        path = "/" + path
    parts = [p for p in path.split("/") if p]
    if not parts:
        return ""
    # Skip language prefix segments and 'unanswered', 'topic', etc.
    skip_first = {"unanswered", "topic", "profile", "search", "answer"}
    slug = parts[-1] if parts[-1] not in skip_first else (parts[-2] if len(parts) >= 2 else parts[-1])
    return slug


def _absolute_url(href: str, lang: str) -> str:
    if not href:
        return ""
    if href.startswith("http://") or href.startswith("https://"):
        return href
    host = "www.quora.com" if lang == "en" else f"{lang}.quora.com"
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return f"https://{host}{href}"
    return f"https://{host}/{href}"


def _parse_int_loose(s: str) -> int:
    """Parse '12', '1,234', '1.2K', '3.4M' from an upvote button label."""
    if not s:
        return 0
    s = s.strip().replace(",", "").replace(" ", " ")
    m = re.search(r"([\d\.]+)\s*([KkMm]?)", s)
    if not m:
        return 0
    try:
        v = float(m.group(1))
    except ValueError:
        return 0
    suf = (m.group(2) or "").lower()
    if suf == "k":
        v *= 1_000
    elif suf == "m":
        v *= 1_000_000
    return int(v)


def _card_data(card, lang: str) -> dict | None:
    """Extract one search-result question card."""
    try:
        # Title — try several broad selectors. Quora classes are obfuscated.
        title_el = (
            card.query_selector("span.q-text--strong")
            or card.query_selector("[class*=title]")
            or card.query_selector("h1")
            or card.query_selector("h2")
            or card.query_selector("a[href*='quora.com/']")
            or card.query_selector("a[href^='/']")
        )
        title = ""
        if title_el:
            try:
                title = (title_el.inner_text() or "").strip()
            except Exception:
                title = ""

        # Link / slug
        link_el = (
            card.query_selector("a.question_link")
            or card.query_selector("a[href*='quora.com/']")
            or card.query_selector("a[href^='/']")
        )
        href = ""
        if link_el:
            try:
                href = link_el.get_attribute("href") or ""
            except Exception:
                href = ""
        url = _absolute_url(href, lang)
        slug = _extract_slug(url)
        if not slug:
            return None

        # Top answer body
        body = ""
        body_el = (
            card.query_selector(".q-relative.q-bg--white.spacing_log_answer_content")
            or card.query_selector("[class*=AnswerContent]")
            or card.query_selector("[class*=Answer] [class*=text]")
            or card.query_selector(".q-text")
        )
        if body_el:
            try:
                body = (body_el.inner_text() or "").strip()
            except Exception:
                body = ""

        # Author
        author = ""
        author_el = (
            card.query_selector("a[class*=user]")
            or card.query_selector("[class*=author] a")
            or card.query_selector("[class*=author]")
            or card.query_selector("a[href*='/profile/']")
        )
        if author_el:
            try:
                author = (author_el.inner_text() or "").strip()
            except Exception:
                author = ""

        # Upvotes — Quora "Upvote · 123" style buttons
        upvotes = 0
        try:
            btns = card.query_selector_all("button, [role=button], [class*=upvote], [class*=Upvote]")
        except Exception:
            btns = []
        for b in btns:
            try:
                txt = (b.inner_text() or "").strip()
            except Exception:
                continue
            if not txt:
                continue
            tl = txt.lower()
            if any(kw in tl for kw in ("upvote", "votar", "votos", "いいね", "支持",
                                       "stimme", "vote", "उभार")):
                m = re.search(r"([\d\.,]+\s*[KkMm]?)", txt)
                if m:
                    upvotes = max(upvotes, _parse_int_loose(m.group(1)))

        return {
            "slug": slug,
            "title": title,
            "url": url,
            "body": body,
            "author": author,
            "upvotes": upvotes,
        }
    except Exception as e:
        print(f"  [quora] card parse err: {e}")
        return None


def _scroll_and_collect(page, state, lang: str, kw: str,
                        items_added_ref: list[int], budget: TimeBudget) -> int:
    added = 0
    seen_slugs = set()
    stats = {"cards_seen": 0, "parsed": 0, "off_topic": 0}
    for i in range(SCROLL_TIMES):
        if budget.expired():
            break
        try:
            cards = page.query_selector_all(
                "[class*=QuestionPage], [class*=q-box][class*=puppeteer_test_question_main], "
                ".q-box.spacing_log_answer, [role=article], div[class*=AnswerListItem]"
            )
        except Exception:
            cards = []
        if not cards:
            # Fallback: each search result row links to a question — grab top-level boxes.
            try:
                cards = page.query_selector_all(".q-box.qu-borderBottom, .q-box[class*=Result]")
            except Exception:
                cards = []
        stats["cards_seen"] = max(stats["cards_seen"], len(cards))

        for c in cards:
            raw = _card_data(c, lang)
            if not raw:
                continue
            stats["parsed"] += 1
            if raw["slug"] in seen_slugs:
                continue
            seen_slugs.add(raw["slug"])

            title = raw["title"]
            body = raw["body"]
            if not title and not body:
                continue
            if not is_on_topic(title, body, lang=lang):
                stats["off_topic"] += 1
                continue

            item_id = make_id("quora", lang, raw["slug"])
            if state.is_seen(item_id):
                continue

            # Country: per-lang primary, else detect from text.
            primary = LANG_PRIMARY_COUNTRY.get(lang, "??")
            if primary == "??":
                country_hint = detect_country(f"{title}\n{body}", hint="??")
            else:
                detected = detect_country(f"{title}\n{body}", hint=primary)
                country_hint = detected or primary

            item = {
                "id": item_id,
                "raw_id": raw["slug"],
                "platform": "quora",
                "lang": lang,
                "title": title[:500],
                "body": body[:5000],
                "author": raw["author"],
                "url": raw["url"],
                "country_hint": country_hint,
                "engagement": {
                    "score": int(raw["upvotes"]),
                    "comments": 0,
                    "views": None,
                },
                "matched_keyword": kw,
            }
            append_jsonl(item, "quora", RAW_DIR)
            state.mark_seen(item_id)
            added += 1
            items_added_ref[0] += 1
            if added >= PER_KEYWORD_LIMIT:
                break
            if items_added_ref[0] >= PER_PLATFORM_LIMIT:
                break

        state.maybe_save(every=5)
        if added >= PER_KEYWORD_LIMIT or items_added_ref[0] >= PER_PLATFORM_LIMIT:
            break

        # Scroll down to fetch more cards
        try:
            page.mouse.wheel(0, 6000)
        except Exception:
            try:
                page.evaluate("window.scrollBy(0, 6000)")
            except Exception:
                pass
        time.sleep(SCROLL_PAUSE)

    print(f"  [quora] lang={lang} kw={kw!r} cards={stats['cards_seen']} "
          f"parsed={stats['parsed']} off_topic={stats['off_topic']} added={added}")
    return added


def run():
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from crawlers.playwright_pool import browser_session

    state = State("quora")
    preload_seen(state, "quora", key_field="id")
    items_added = [0]
    budget = TimeBudget(PLATFORM_TIME_BUDGET_SEC)

    try:
        for lang in QUORA_LANGS:
            if budget.expired():
                print("[quora] time budget expired")
                break
            kws = INCOME_KEYWORDS.get(lang, [])
            if not kws:
                continue
            locale = LANG_LOCALE.get(lang, "en-US")
            print(f"[quora] === lang={lang} locale={locale} kws={len(kws)} ===")

            try:
                with browser_session(headless=True, locale=locale,
                                     user_agent=random_ua()) as sess:
                    for kw in kws:
                        if budget.expired():
                            break
                        kw_key = f"{lang}::{kw}"
                        if state.is_kw_done(kw_key):
                            continue
                        if items_added[0] >= PER_PLATFORM_LIMIT:
                            break

                        url = _search_url(lang, kw)
                        print(f"[quora] lang={lang} kw={kw!r}")
                        page = sess.new_page()
                        had_error = False
                        try:
                            try:
                                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                            except PlaywrightTimeoutError:
                                print(f"  [quora] timeout on {url}")
                                had_error = True
                                continue

                            polite_sleep(2000, 3000)

                            if _is_blocked(page):
                                print(f"  [quora] captcha/wall on lang={lang} kw={kw!r}, skipping")
                                had_error = True
                                continue

                            # Wait briefly for results to mount.
                            try:
                                page.wait_for_selector(
                                    "[class*=QuestionPage], [role=article], "
                                    ".q-box.qu-borderBottom, [class*=AnswerListItem]",
                                    timeout=8000,
                                )
                            except PlaywrightTimeoutError:
                                pass

                            _scroll_and_collect(page, state, lang, kw, items_added, budget)
                        except Exception as e:
                            print(f"  [quora] lang={lang} kw={kw!r} err: {e}")
                            had_error = True
                        finally:
                            try:
                                page.close()
                            except Exception:
                                pass

                        if not had_error:
                            state.mark_kw_done(kw_key)
                        state.save()
                        polite_sleep(2000, 3000)

                        if items_added[0] >= PER_PLATFORM_LIMIT:
                            print(f"[quora] hit PER_PLATFORM_LIMIT={PER_PLATFORM_LIMIT}")
                            break
            except Exception as e:
                print(f"[quora] session err lang={lang}: {e}")

            if items_added[0] >= PER_PLATFORM_LIMIT:
                break
    finally:
        state.save(force=True)

    print(f"[quora] done, +{items_added[0]} items this run")


if __name__ == "__main__":
    run()
