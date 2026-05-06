"""Glassdoor crawler via DuckDuckGo `site:` search.

Glassdoor heavily gates content behind a login wall, but salary pages get
indexed by search engines and snippet/summary cards include the salary
range. We bypass the login wall by:

  1. Issuing `site:glassdoor.{tld} <income_kw>` queries against DDG's HTML
     endpoint (the same pattern token/crawlers/google_web.py uses).
  2. For each hit, fetch the page and run trafilatura.extract for a clean
     body. Glassdoor's snippet block + structured-data salary range tend
     to survive trafilatura.
  3. Country comes from the TLD; lang is the country's primary language.

DDG aggressively rate-limits — we use a 2.5s sleep between requests and
back off on 403/429.
"""
import time
from urllib.parse import urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup
try:
    import trafilatura
except Exception:
    trafilatura = None

from config import (
    INCOME_KEYWORDS, PER_PLATFORM_LIMIT, GOOGLE_PAGES_PER_QUERY, RAW_DIR,
    PLATFORM_TIME_BUDGET_SEC,
)
from crawlers.common import (
    append_jsonl, make_id, is_on_topic, polite_sleep, preload_seen,
    default_headers, TimeBudget,
)
from crawlers.state import State


PLATFORM = "glassdoor_via_google"
DDG_HTML = "https://html.duckduckgo.com/html/"

BOT_MARKERS = ("unusual traffic", "captcha", "are you a human", "access denied",
               "cf-browser-verification", "checking your browser")

# DDG sleep — DDG is aggressive about rate limiting; the task requires 2.5s.
DDG_SLEEP_LO_MS = 2500
DDG_SLEEP_HI_MS = 3500


# ============================================================================
# (TLD → ISO-2 country, primary language) for Glassdoor's national subdomains.
# Note: lang follows config.INCOME_KEYWORDS keys. The .com TLD is treated as
# US-en. Some subdomains (e.g. CH) get the country's most-common Glassdoor
# search language.
# ============================================================================
GLASSDOOR_TLDS = [
    # tld,         country, lang, accept_lang
    ("com",        "US", "en", "en-US,en;q=0.9"),
    ("com.au",     "AU", "en", "en-AU,en;q=0.9"),
    ("ca",         "CA", "en", "en-CA,en;q=0.9"),
    ("co.uk",      "GB", "en", "en-GB,en;q=0.9"),
    ("co.in",      "IN", "en", "en-IN,en;q=0.9"),
    ("com.sg",     "SG", "en", "en-SG,en;q=0.9"),
    ("fr",         "FR", "fr", "fr-FR,fr;q=0.9"),
    ("de",         "DE", "de", "de-DE,de;q=0.9"),
    ("com.br",     "BR", "pt", "pt-BR,pt;q=0.9"),
    ("com.mx",     "MX", "es", "es-MX,es;q=0.9"),
    ("es",         "ES", "es", "es-ES,es;q=0.9"),
    ("it",         "IT", "it", "it-IT,it;q=0.9"),
    ("nl",         "NL", "nl", "nl-NL,nl;q=0.9"),
    ("ch",         "CH", "de", "de-CH,de;q=0.9"),
    ("com.hk",     "HK", "en", "en-HK,en;q=0.9"),
]


# ============================================================================
# HTTP / DDG plumbing — adapted from token/crawlers/google_web.py
# ============================================================================
class GlassdoorViaGoogleError(Exception):
    pass


def _ddg_headers(accept_lang: str = "en-US,en;q=0.9") -> dict:
    h = default_headers(accept_lang)
    h["Referer"] = "https://duckduckgo.com/"
    return h


def fetch_html(url: str, method: str = "GET", data=None,
               accept_lang: str = "en-US,en;q=0.9", timeout: int = 30) -> str:
    try:
        if method == "POST":
            r = requests.post(url, headers=_ddg_headers(accept_lang),
                              data=data, timeout=timeout)
        else:
            r = requests.get(url, headers=_ddg_headers(accept_lang),
                             params=data, timeout=timeout)
    except Exception as e:
        raise GlassdoorViaGoogleError(f"net err {url}: {e}")
    if r.status_code in (403, 429):
        raise GlassdoorViaGoogleError(f"{r.status_code} on {url}")
    if r.status_code != 200:
        raise GlassdoorViaGoogleError(f"status {r.status_code} on {url}")
    body = r.text or ""
    low = body.lower()
    if any(m in low for m in BOT_MARKERS):
        raise GlassdoorViaGoogleError("bot-block / captcha")
    return body


def extract_clean(html: str) -> str:
    if not html or not trafilatura:
        return ""
    try:
        out = trafilatura.extract(html, include_comments=False, include_tables=False)
        return out or ""
    except Exception:
        return ""


def clean_ddg_url(href: str) -> str:
    """DDG wraps external URLs in `/l/?uddg=<encoded>` — unwrap them."""
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    try:
        parsed = urlparse(href)
        if parsed.path == "/l/" or parsed.netloc.endswith("duckduckgo.com"):
            qs = parse_qs(parsed.query)
            if "uddg" in qs and qs["uddg"]:
                return unquote(qs["uddg"][0])
    except Exception:
        pass
    return href


def parse_search_results(html: str):
    """Parse DDG HTML result list into [{title, url, snippet}, ...]."""
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for res in soup.select(".result"):
        a = res.select_one(".result__a")
        if not a:
            continue
        title = a.get_text(" ", strip=True)
        href = a.get("href") or ""
        url = clean_ddg_url(href)
        if not url or not url.startswith(("http://", "https://")):
            continue
        snip_el = res.select_one(".result__snippet")
        snippet = snip_el.get_text(" ", strip=True) if snip_el else ""
        results.append({"title": title, "url": url, "snippet": snippet})
    return results


def fetch_ddg_search(query: str, page: int, accept_lang: str) -> str:
    """Fetch one DDG HTML search page (POST). page 0 = first; offset 30/page."""
    data = {"q": query, "b": "", "kl": "us-en"}
    if page > 0:
        data["s"] = str(page * 30)
        data["dc"] = str(page * 30 + 1)
    return fetch_html(DDG_HTML, method="POST", data=data, accept_lang=accept_lang)


# ============================================================================
# Per-(country, kw) loop
# ============================================================================
def _is_glassdoor_url(url: str, tld: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    if not host:
        return False
    # Allow exact host or any subdomain (www, careers, ...).
    return host == f"glassdoor.{tld}" or host.endswith(f".glassdoor.{tld}")


def process_query(query: str, country: str, lang: str, accept_lang: str,
                  tld: str, kw: str, state: State,
                  budget: TimeBudget) -> int:
    """Run one (tld, kw) DDG search; emit jsonl per Glassdoor hit."""
    added = 0
    start_page = state.get_cursor(query, 0) or 0
    for page in range(start_page, start_page + GOOGLE_PAGES_PER_QUERY):
        if budget.expired():
            break
        try:
            html = fetch_ddg_search(query, page, accept_lang)
        except GlassdoorViaGoogleError as e:
            msg = str(e)
            print(f"  [{PLATFORM}] DDG p{page} {query!r} err: {msg}")
            if "403" in msg or "429" in msg:
                time.sleep(30)
            break
        hits = parse_search_results(html)
        if not hits:
            break
        for hit in hits:
            if budget.expired():
                break
            url = hit["url"]
            if not _is_glassdoor_url(url, tld):
                # DDG site: bias is strong but not absolute — drop off-target hits.
                continue
            title = hit["title"]
            snippet = hit["snippet"]
            our_id = make_id(PLATFORM, url)
            if state.is_seen(our_id):
                continue
            # Pre-filter on title + snippet before we spend a full fetch.
            if not is_on_topic(title, snippet, lang=lang) \
               and not is_on_topic(title, snippet, lang="en"):
                state.mark_seen(our_id)
                continue
            # Fetch the actual page for a clean body.
            body = ""
            try:
                page_html = fetch_html(url, accept_lang=accept_lang)
                body = extract_clean(page_html)
            except GlassdoorViaGoogleError as e:
                print(f"  [{PLATFORM}] fetch {url} err: {e}")
            polite_sleep(DDG_SLEEP_LO_MS, DDG_SLEEP_HI_MS)
            if not body:
                body = snippet
            if not body:
                state.mark_seen(our_id)
                continue
            # Final on-topic check on title + body.
            if not is_on_topic(title, body, lang=lang) \
               and not is_on_topic(title, body, lang="en"):
                state.mark_seen(our_id)
                continue
            try:
                source_domain = urlparse(url).netloc
            except Exception:
                source_domain = f"glassdoor.{tld}"
            item = {
                "id": our_id,
                "raw_id": url,
                "platform": PLATFORM,
                "lang": lang,
                "country_hint": country,
                "title": title,
                "body": (body or "")[:5000],
                "snippet": snippet,
                "source_domain": source_domain,
                "url": url,
                "matched_keyword": kw,
                "engagement": {"score": 0, "comments": 0},
            }
            append_jsonl(item, PLATFORM, RAW_DIR)
            state.mark_seen(our_id)
            added += 1
            if added % 25 == 0:
                print(f"  [{PLATFORM}] +{added} so far for {country}/{kw!r}")
            state.maybe_save(every=10)
        state.set_cursor(query, page + 1)
        polite_sleep(DDG_SLEEP_LO_MS, DDG_SLEEP_HI_MS)
    return added


def run():
    state = State(PLATFORM)
    preload_seen(state, PLATFORM, key_field="id")
    budget = TimeBudget(PLATFORM_TIME_BUDGET_SEC)
    items_added = 0

    try:
        for tld, country, lang, accept_lang in GLASSDOOR_TLDS:
            if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                break
            kws = INCOME_KEYWORDS.get(lang) or INCOME_KEYWORDS["en"]
            for kw in kws:
                if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                    break
                query = f"site:glassdoor.{tld} {kw}"
                if state.is_kw_done(query):
                    continue
                print(f"[{PLATFORM}] {country} ({tld}) kw={kw!r}")
                try:
                    got = process_query(query, country, lang, accept_lang,
                                        tld, kw, state, budget)
                except Exception as e:
                    print(f"  [{PLATFORM}] query {query!r} fatal: {e}")
                    state.save()
                    polite_sleep(DDG_SLEEP_LO_MS, DDG_SLEEP_HI_MS)
                    continue
                items_added += got
                if got:
                    print(f"  [{PLATFORM}] +{got} (total {items_added})")
                state.mark_kw_done(query)
                state.save()
                polite_sleep(DDG_SLEEP_LO_MS, DDG_SLEEP_HI_MS)
            polite_sleep(DDG_SLEEP_LO_MS, DDG_SLEEP_HI_MS)
            if items_added >= PER_PLATFORM_LIMIT:
                print(f"[{PLATFORM}] hit PER_PLATFORM_LIMIT={PER_PLATFORM_LIMIT}")
                break
    finally:
        state.save(force=True)

    print(f"[{PLATFORM}] done, +{items_added} items this run")


if __name__ == "__main__":
    run()
