"""Universal multi-country, multi-language search harvester.

For each country in COUNTRIES_40:
  For each lang in COUNTRY_LANGUAGES[country]:
    For each kw in INCOME_KEYWORDS[lang]:
      For each domain in COUNTRY_DOMAINS[country] (skip COVERED_BY_DEDICATED):
        DDG site:<domain> <kw>  -> fetch+extract per URL
      DDG <kw> <demonym>        -> fetch+extract per URL  (free fallback)

Concurrency: 4 country lanes in parallel; serial within a lane.
Politeness: 0.8-1.5s sleep per request -> ~4 req/sec aggregate from DDG.
Caps: total run cap = PER_PLATFORM_LIMIT items (round-robin via lanes).
       Per-(country, lang, kw): 2 DDG pages (~60 URLs) -> tunable below.

This is the P0 crawler for 40-country shallow coverage. It deliberately
SKIPS domains in config.COVERED_BY_DEDICATED so dedicated crawlers stay
the source of truth for those sites.
"""
import threading
import concurrent.futures
import requests
from urllib.parse import urlparse, parse_qs, unquote
from bs4 import BeautifulSoup

try:
    import trafilatura
except Exception:
    trafilatura = None

from config import (
    COUNTRIES_40, COUNTRY_LANGUAGES, COUNTRY_DOMAINS, COVERED_BY_DEDICATED,
    INCOME_KEYWORDS, COUNTRY_NAMES_EN,
    PER_PLATFORM_LIMIT, PAGES_PER_QUERY, RAW_DIR, PLATFORM_TIME_BUDGET_SEC,
)
from crawlers.common import (
    append_jsonl, make_id, is_on_topic, polite_sleep, preload_seen,
    default_headers, TimeBudget,
)
from crawlers.state import State

DDG_HTML = "https://html.duckduckgo.com/html/"
BOT_MARKERS = ("unusual traffic", "captcha", "are you a human", "access denied")

# Per-(country, lang, kw) caps
ANCHORED_HITS_PER_DOMAIN = 20   # how many DDG results per site:<domain> query
FREE_PAGES_PER_KW = 2           # DDG pages for the free fallback (~30/page -> ~60)
MIN_BODY_CHARS = 400            # discard short pages

# Total cap for the whole run (round-robin across countries)
TOTAL_QUERIES_CAP = 5000


# ============================================================================
# Demonyms — country term in each language used in that country.
# Used to scope the free DDG query: `<kw> <demonym>`.
# Falls back to COUNTRY_NAMES_EN when a (country, lang) pair is missing.
# ============================================================================
DEMONYMS = {
    # US
    ("US", "en"): "USA",
    # CN
    ("CN", "zh"): "中国",
    # JP
    ("JP", "ja"): "日本",
    # KR
    ("KR", "ko"): "한국",
    # IN — multilingual
    ("IN", "en"): "India",
    ("IN", "hi"): "भारत",
    # DE
    ("DE", "de"): "Deutschland",
    # GB
    ("GB", "en"): "UK",
    # FR
    ("FR", "fr"): "France",
    # BR
    ("BR", "pt"): "Brasil",
    # RU
    ("RU", "ru"): "Россия",
    # MX
    ("MX", "es"): "México",
    # ES
    ("ES", "es"): "España",
    # IT
    ("IT", "it"): "Italia",
    # CA — bilingual
    ("CA", "en"): "Canada",
    ("CA", "fr"): "Canada",
    # AU
    ("AU", "en"): "Australia",
    # NL
    ("NL", "nl"): "Nederland",
    ("NL", "en"): "Netherlands",
    # CH — trilingual
    ("CH", "de"): "Schweiz",
    ("CH", "fr"): "Suisse",
    ("CH", "it"): "Svizzera",
    # SG
    ("SG", "en"): "Singapore",
    ("SG", "zh"): "新加坡",
    # MY
    ("MY", "en"): "Malaysia",
    ("MY", "ms"): "Malaysia",
    # TH
    ("TH", "th"): "ประเทศไทย",
    ("TH", "en"): "Thailand",
    # ID
    ("ID", "id"): "Indonesia",
    ("ID", "en"): "Indonesia",
    # PH
    ("PH", "en"): "Philippines",
    # VN
    ("VN", "vi"): "Việt Nam",
    # TR
    ("TR", "tr"): "Türkiye",
    # SA
    ("SA", "ar"): "السعودية",
    ("SA", "en"): "Saudi Arabia",
    # AE
    ("AE", "ar"): "الإمارات",
    ("AE", "en"): "UAE",
    # EG
    ("EG", "ar"): "مصر",
    # ZA
    ("ZA", "en"): "South Africa",
    # NG
    ("NG", "en"): "Nigeria",
    # AR
    ("AR", "es"): "Argentina",
    # CO
    ("CO", "es"): "Colombia",
    # CL
    ("CL", "es"): "Chile",
    # IL
    ("IL", "he"): "ישראל",
    ("IL", "en"): "Israel",
    # PL
    ("PL", "pl"): "Polska",
    # SE
    ("SE", "sv"): "Sverige",
    ("SE", "en"): "Sweden",
    # NO
    ("NO", "no"): "Norge",
    ("NO", "en"): "Norway",
    # MA
    ("MA", "ar"): "المغرب",
    ("MA", "fr"): "Maroc",
    # PK
    ("PK", "en"): "Pakistan",
    ("PK", "ur"): "پاکستان",
    # BD
    ("BD", "bn"): "বাংলাদেশ",
    ("BD", "en"): "Bangladesh",
    # UA
    ("UA", "uk"): "Україна",
    ("UA", "ru"): "Украина",
}


def get_demonym(country: str, lang: str) -> str:
    return DEMONYMS.get((country, lang)) or COUNTRY_NAMES_EN.get(country, country)


# ============================================================================
# DDG helpers — mirror token/crawlers/google_web.py production impl.
# ============================================================================
def fetch_ddg(query: str, page: int = 0) -> str:
    data = {"q": query, "kl": "us-en"}
    if page > 0:
        data["s"] = str(page * 30)
        data["dc"] = str(page * 30 + 1)
    r = requests.post(DDG_HTML, headers=default_headers(), data=data, timeout=20)
    if r.status_code in (403, 429):
        raise RuntimeError(f"DDG {r.status_code}")
    if r.status_code != 200:
        raise RuntimeError(f"DDG status {r.status_code}")
    body = r.text or ""
    low = body.lower()
    if any(m in low for m in BOT_MARKERS):
        raise RuntimeError("DDG bot-block")
    return body


def _clean_ddg_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    try:
        p = urlparse(href)
        if p.path == "/l/" or p.netloc.endswith("duckduckgo.com"):
            qs = parse_qs(p.query)
            if "uddg" in qs and qs["uddg"]:
                return unquote(qs["uddg"][0])
    except Exception:
        pass
    return href


def parse_ddg(html: str):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for res in soup.select(".result"):
        a = res.select_one(".result__a")
        if not a:
            continue
        href = _clean_ddg_url(a.get("href") or "")
        if not href.startswith(("http://", "https://")):
            continue
        title = a.get_text(" ", strip=True)
        snip_el = res.select_one(".result__snippet")
        snippet = snip_el.get_text(" ", strip=True) if snip_el else ""
        out.append({"title": title, "url": href, "snippet": snippet})
    return out


def extract_clean(url: str) -> str:
    try:
        r = requests.get(url, headers=default_headers(), timeout=20)
        if r.status_code != 200:
            return ""
        if not trafilatura:
            return ""
        return trafilatura.extract(
            r.text, include_comments=False, include_tables=False,
        ) or ""
    except Exception:
        return ""


def _domain_in_covered(domain: str) -> bool:
    """Return True if `domain` (or a parent) is in COVERED_BY_DEDICATED."""
    if not domain:
        return False
    domain = domain.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    if domain in COVERED_BY_DEDICATED:
        return True
    # parent-domain match (e.g. forums.hardwarezone.com.sg -> hardwarezone.com.sg)
    parts = domain.split(".")
    for i in range(1, len(parts) - 1):
        if ".".join(parts[i:]) in COVERED_BY_DEDICATED:
            return True
    return False


# ============================================================================
# Per-country lane
# ============================================================================
def crawl_country(country, state, items_added_ref, query_count_ref, lock, budget):
    """One country lane: iterate languages x keywords x domains, then free."""
    langs = COUNTRY_LANGUAGES.get(country, ["en"])
    domains = COUNTRY_DOMAINS.get(country, [])

    for lang in langs:
        if budget.expired():
            return
        kws = INCOME_KEYWORDS.get(lang, [])
        for kw in kws:
            kw_label = f"{country}|{lang}|{kw}"
            if state.is_kw_done(kw_label):
                continue
            if budget.expired():
                return
            if items_added_ref[0] >= PER_PLATFORM_LIMIT:
                return
            if query_count_ref[0] >= TOTAL_QUERIES_CAP:
                return

            # ---- (1) Anchored: site:<domain> <kw> for each known local domain
            for domain in domains:
                if _domain_in_covered(domain):
                    continue
                if budget.expired():
                    return
                if items_added_ref[0] >= PER_PLATFORM_LIMIT:
                    return
                if query_count_ref[0] >= TOTAL_QUERIES_CAP:
                    return
                query = f"site:{domain} {kw}"
                with lock:
                    query_count_ref[0] += 1
                try:
                    html = fetch_ddg(query, page=0)
                except RuntimeError as e:
                    print(f"  [gu] {country}|{lang}|{kw}|{domain} ddg err: {e}")
                    polite_sleep()
                    continue
                except Exception as e:
                    print(f"  [gu] {country}|{lang}|{kw}|{domain} unexpected: {e}")
                    polite_sleep()
                    continue

                hits = parse_ddg(html)
                for h in hits[:ANCHORED_HITS_PER_DOMAIN]:
                    rid = h["url"]
                    iid = make_id("gu", rid)
                    if state.is_seen(iid):
                        continue
                    body = extract_clean(rid)
                    polite_sleep(800, 1500)
                    if len(body) < MIN_BODY_CHARS or not is_on_topic(
                            h["title"], body, lang=lang):
                        state.mark_seen(iid)
                        continue
                    item = {
                        "id": iid,
                        "raw_id": rid,
                        "platform": "google_universal",
                        "lang": lang,
                        "title": h["title"],
                        "body": body[:8000],
                        "author": urlparse(rid).netloc,
                        "url": rid,
                        "country_hint": country,
                        "snippet": h["snippet"],
                        "matched_keyword": kw,
                        "anchor_domain": domain,
                        "engagement": {
                            "score": None, "comments": None, "views": None,
                        },
                    }
                    with lock:
                        append_jsonl(item, "google_universal", RAW_DIR)
                        state.mark_seen(iid)
                        items_added_ref[0] += 1
                    if items_added_ref[0] >= PER_PLATFORM_LIMIT:
                        return
                state.maybe_save(every=10)
                polite_sleep()

            # ---- (2) Free fallback: <kw> <demonym>, paginate PAGES_PER_QUERY
            if budget.expired():
                return
            if items_added_ref[0] >= PER_PLATFORM_LIMIT:
                return
            demonym = get_demonym(country, lang)
            free_query = f"{kw} {demonym}"
            free_pages = min(FREE_PAGES_PER_KW, PAGES_PER_QUERY)
            for page in range(free_pages):
                if budget.expired():
                    return
                if items_added_ref[0] >= PER_PLATFORM_LIMIT:
                    return
                if query_count_ref[0] >= TOTAL_QUERIES_CAP:
                    return
                with lock:
                    query_count_ref[0] += 1
                try:
                    html = fetch_ddg(free_query, page=page)
                except RuntimeError as e:
                    print(f"  [gu] free {country}|{lang}|{kw} ddg err: {e}")
                    break
                except Exception as e:
                    print(f"  [gu] free {country}|{lang}|{kw} unexpected: {e}")
                    break
                hits = parse_ddg(html)
                if not hits:
                    break
                for h in hits:
                    rid = h["url"]
                    iid = make_id("gu", rid)
                    if state.is_seen(iid):
                        continue
                    host = urlparse(rid).netloc
                    if _domain_in_covered(host):
                        # let dedicated crawlers handle these
                        state.mark_seen(iid)
                        continue
                    body = extract_clean(rid)
                    polite_sleep(800, 1500)
                    if len(body) < MIN_BODY_CHARS or not is_on_topic(
                            h["title"], body, lang=lang):
                        state.mark_seen(iid)
                        continue
                    item = {
                        "id": iid,
                        "raw_id": rid,
                        "platform": "google_universal",
                        "lang": lang,
                        "title": h["title"],
                        "body": body[:8000],
                        "author": host,
                        "url": rid,
                        "country_hint": country,
                        "snippet": h["snippet"],
                        "matched_keyword": kw,
                        "anchor_domain": "FREE",
                        "engagement": {
                            "score": None, "comments": None, "views": None,
                        },
                    }
                    with lock:
                        append_jsonl(item, "google_universal", RAW_DIR)
                        state.mark_seen(iid)
                        items_added_ref[0] += 1
                    if items_added_ref[0] >= PER_PLATFORM_LIMIT:
                        return
                state.maybe_save(every=10)
                polite_sleep()

            state.mark_kw_done(kw_label)
            state.save()


# ============================================================================
# Entry point
# ============================================================================
def run():
    state = State("google_universal")
    preload_seen(state, "google_universal", key_field="id")
    items_added = [0]
    query_count = [0]
    lock = threading.Lock()
    budget = TimeBudget(PLATFORM_TIME_BUDGET_SEC)

    print(f"[gu] starting: {len(COUNTRIES_40)} countries, "
          f"budget={PLATFORM_TIME_BUDGET_SEC}s, cap={PER_PLATFORM_LIMIT}")
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futures = []
            for country in COUNTRIES_40:
                if budget.expired():
                    break
                futures.append(ex.submit(
                    crawl_country, country, state,
                    items_added, query_count, lock, budget,
                ))
            for f in concurrent.futures.as_completed(futures):
                try:
                    f.result()
                except Exception as e:
                    print(f"  [gu] lane err: {e}")
    finally:
        state.save(force=True)

    print(f"[gu] done, +{items_added[0]} items, "
          f"{query_count[0]} DDG queries issued")


if __name__ == "__main__":
    run()
