"""Kununu crawler — major DACH (DE/AT/CH) employer-review + salary platform.

Strategy:
  - Public, no auth. Pure requests + BeautifulSoup.
  - URL pattern: https://www.kununu.com/de/{slug}/gehalt   (salary tab)
                 https://www.kununu.com/de/{slug}/kommentare (review tab)
  - Optional country path /at/ or /ch/ flags Austria/Switzerland.
  - Per company /gehalt: scrape role × salary range (€ per year × num samples).
  - Per company /kommentare: top 10 reviews with body (employee narratives).
  - Country hint: detect via URL path (/at/, /ch/) — default DE.
  - lang: "de"

Honors SMOKE_TEST (limit to ~15 companies when smoke).
"""
import json
import os
import re
import time

import requests
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from config import (
    PER_PLATFORM_LIMIT, RAW_DIR, PLATFORM_TIME_BUDGET_SEC,
)
from crawlers.common import (
    append_jsonl, make_id, polite_sleep, preload_seen,
    default_headers, TimeBudget,
)
from crawlers.state import State

BASE = "https://www.kununu.com"
# (slug, country_path) — country_path is "" for DE (default), "at" for AT, "ch" for CH.
# Most major employers exist under the /de/ path even if AT/CH-headquartered;
# the tag here is a hint for the country_hint field, not necessarily the host
# country. Override per company where the canonical URL uses /at/ or /ch/.
COMPANIES: list[tuple[str, str]] = [
    # DE - DAX/MDAX heavyweights
    ("siemens", ""), ("sap", ""), ("allianz", ""), ("bmw", ""),
    ("mercedes-benz-group", ""), ("volkswagen", ""), ("audi", ""),
    ("deutsche-bank", ""), ("commerzbank", ""), ("deutsche-telekom", ""),
    ("vodafone-deutschland", ""), ("microsoft-deutschland", ""),
    ("lufthansa", ""), ("ikea-deutschland", ""), ("edeka", ""),
    ("rewe", ""), ("aldi-sued", ""), ("lidl", ""),
    ("dm-drogerie-markt", ""), ("otto", ""), ("henkel", ""),
    ("bayer", ""), ("basf", ""), ("eon", ""), ("rwe", ""),
    ("post", ""), ("daimler", ""), ("fraport", ""), ("bosch", ""),
    ("continental", ""), ("mahle", ""), ("zf-friedrichshafen", ""),
    ("schaeffler", ""), ("salzgitter", ""), ("thyssenkrupp", ""),
    ("eberspaecher", ""), ("deutsche-bahn", ""),
    # Consulting / Big-4 / IT services (DE)
    ("t-systems", ""), ("deloitte-deutschland", ""),
    ("kpmg-deutschland", ""), ("pwc-deutschland", ""),
    ("ey-deutschland", ""), ("mckinsey-company", ""),
    ("bcg-the-boston-consulting-group", ""),
    ("accenture-deutschland", ""), ("ibm-deutschland", ""),
    ("oracle-deutschland", ""),
    ("capgemini-deutschland-gmbh", ""),
    # Consumer brands / fashion / sport
    ("hugo-boss", ""), ("adidas", ""), ("puma", ""), ("fielmann", ""),
    ("zalando", ""), ("otto-group", ""), ("hellofresh", ""),
    ("delivery-hero", ""), ("sixt-se", ""), ("leonardo-hotels", ""),
    # AT
    ("swarovski", "at"), ("voith", ""), ("tcg-unitech", "at"),
]

BOT_MARKERS = ("captcha", "are you a human", "access denied", "unusual traffic", "bot detection")


class KununuError(Exception):
    pass


def _country_for(country_path: str) -> str:
    cp = (country_path or "").lower()
    if cp == "at":
        return "AT"
    if cp == "ch":
        return "CH"
    return "DE"


def _build_url(slug: str, country_path: str, tab: str) -> str:
    cp = (country_path or "").lower()
    if cp in ("at", "ch"):
        return f"{BASE}/{cp}/{slug}/{tab}"
    return f"{BASE}/de/{slug}/{tab}"


def _kununu_headers() -> dict:
    h = default_headers(accept_lang="de-DE,de;q=0.9,en;q=0.5")
    h["Referer"] = BASE + "/"
    return h


def fetch_html(url: str, timeout: int = 25) -> str:
    try:
        r = requests.get(url, headers=_kununu_headers(), timeout=timeout, allow_redirects=True)
        if r.status_code in (403, 429):
            raise KununuError(f"{r.status_code} on {url}")
        if r.status_code == 404:
            raise KununuError(f"404 on {url}")
        if r.status_code != 200:
            raise KununuError(f"status {r.status_code} on {url}")
        body = r.text or ""
        low = body.lower()
        if any(m in low for m in BOT_MARKERS):
            raise KununuError("bot-block / captcha on page")
        return body
    except KununuError:
        raise
    except Exception as e:
        raise KununuError(str(e))


# ============================================================================
# Number / salary parsing — kununu shows EUR amounts like:
#   "€ 65.000", "65.000 €", "55.000 - 75.000 €", "Ø 60.000 €", "12 Gehälter"
# German uses "." as thousands sep and "," as decimal.
# ============================================================================
_EUR_RE = re.compile(r"€?\s*([\d]{1,3}(?:[\.\s][\d]{3})*(?:,\d+)?)\s*€?", re.UNICODE)
_RANGE_RE = re.compile(
    r"([\d]{1,3}(?:[\.\s][\d]{3})*(?:,\d+)?)\s*[-–]\s*([\d]{1,3}(?:[\.\s][\d]{3})*(?:,\d+)?)"
)
_SAMPLES_RE = re.compile(r"(\d+)\s*(?:Gehälter|Geh\.|Datenpunkte|Samples|Bewertungen)", re.IGNORECASE)


def _to_eur(raw: str) -> int | None:
    """Parse a German-formatted euro amount string → integer EUR/yr."""
    if not raw:
        return None
    s = raw.strip().replace(" ", " ").replace(" ", "")
    s = s.replace("€", "").strip()
    if not s:
        return None
    # German format: 65.000,50 → 65000.50
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(".", "")
    try:
        v = float(s)
    except ValueError:
        return None
    # If suspiciously small (< 1000), kununu sometimes shows monthly figures.
    # Convention here: keep raw — leave LLM to interpret. But cap obvious noise.
    if v <= 0 or v > 5_000_000:
        return None
    return int(v)


def _parse_salary_range(text: str) -> tuple[int | None, int | None, int | None]:
    """Try to extract (min, mid, max) EUR/yr from a salary cell text."""
    if not text:
        return None, None, None
    rm = _RANGE_RE.search(text)
    if rm:
        lo = _to_eur(rm.group(1))
        hi = _to_eur(rm.group(2))
        mid = (lo + hi) // 2 if (lo and hi) else None
        return lo, mid, hi
    # Fallback: single number, treat as median.
    em = _EUR_RE.search(text)
    if em:
        v = _to_eur(em.group(1))
        return None, v, None
    return None, None, None


def _parse_samples(text: str) -> int:
    if not text:
        return 0
    m = _SAMPLES_RE.search(text)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return 0
    return 0


# ============================================================================
# JSON / NEXT_DATA extraction — kununu (Next.js) embeds props in __NEXT_DATA__.
# Parsing this is more reliable than DOM scraping; fall back to DOM.
# ============================================================================
def _next_data(html: str) -> dict | None:
    if not html:
        return None
    m = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def _walk_for_salary_nodes(obj, out: list[dict]):
    """Walk Next.js JSON for salary-shaped nodes.

    Heuristic: a dict that has a job-title-ish key plus a numeric salary key.
    """
    if isinstance(obj, dict):
        # Common shapes: {jobTitle/profession/title, salary{min,max,median}, count}
        title = (
            obj.get("jobTitle") or obj.get("profession") or obj.get("title")
            or obj.get("name") or obj.get("position")
        )
        sal = obj.get("salary") or obj.get("salaryRange") or obj.get("estimatedSalary")
        if title and isinstance(sal, dict):
            lo = sal.get("min") or sal.get("minValue") or sal.get("low")
            hi = sal.get("max") or sal.get("maxValue") or sal.get("high")
            mid = sal.get("median") or sal.get("mid") or sal.get("value") or sal.get("avg")
            n = obj.get("count") or obj.get("samples") or obj.get("sampleSize") or 0
            try:
                lo = int(lo) if isinstance(lo, (int, float)) else None
                hi = int(hi) if isinstance(hi, (int, float)) else None
                mid = int(mid) if isinstance(mid, (int, float)) else None
                n = int(n) if isinstance(n, (int, float)) else 0
            except Exception:
                lo = hi = mid = None
                n = 0
            if (lo or hi or mid) and isinstance(title, str):
                out.append({
                    "role": title.strip()[:160],
                    "min_eur_yr": lo,
                    "mid_eur_yr": mid,
                    "max_eur_yr": hi,
                    "samples": n,
                })
        for v in obj.values():
            _walk_for_salary_nodes(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_for_salary_nodes(v, out)


def _walk_for_review_nodes(obj, out: list[dict]):
    """Walk Next.js JSON for review-shaped nodes.

    Heuristic: dict with a long text body + numeric rating + maybe helpfulCount.
    """
    if isinstance(obj, dict):
        text = (
            obj.get("text") or obj.get("body") or obj.get("comment")
            or obj.get("commentText") or obj.get("review")
        )
        title_t = obj.get("title") or obj.get("headline") or ""
        rating = obj.get("rating") or obj.get("score") or obj.get("overall")
        helpful = obj.get("helpfulCount") or obj.get("helpful") or obj.get("likeCount") or 0
        if isinstance(text, str) and len(text) >= 80 and len(text) <= 8000:
            try:
                helpful = int(helpful) if isinstance(helpful, (int, float)) else 0
            except Exception:
                helpful = 0
            try:
                rating_v = float(rating) if isinstance(rating, (int, float)) else None
            except Exception:
                rating_v = None
            out.append({
                "title": str(title_t)[:200] if title_t else "",
                "body": text.strip()[:5000],
                "rating": rating_v,
                "helpful": helpful,
            })
        for v in obj.values():
            _walk_for_review_nodes(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_for_review_nodes(v, out)


# ============================================================================
# DOM scraping fallbacks
# ============================================================================
def _dom_salaries(html: str) -> list[dict]:
    """Pull role × salary tuples from a /gehalt page DOM as best-effort fallback."""
    if BeautifulSoup is None or not html:
        return []
    out: list[dict] = []
    soup = BeautifulSoup(html, "html.parser")
    # Look for blocks containing both a € and a German-format number.
    for blk in soup.find_all(["div", "li", "tr", "article"]):
        txt = (blk.get_text(" ", strip=True) or "")[:500]
        if "€" not in txt:
            continue
        # Heuristic: must contain a 4-6 digit number or a thousands-separator pattern.
        if not re.search(r"\d[\d\.\s]{2,}", txt):
            continue
        lo, mid, hi = _parse_salary_range(txt)
        if not (lo or mid or hi):
            continue
        # Role: text segment before the first € or digit-block.
        head = re.split(r"€|\d{2,}", txt, maxsplit=1)[0]
        role = head.strip().rstrip(":–-").strip()[:160]
        if not role or len(role) < 3:
            continue
        n = _parse_samples(txt)
        out.append({
            "role": role,
            "min_eur_yr": lo,
            "mid_eur_yr": mid,
            "max_eur_yr": hi,
            "samples": n,
        })
        if len(out) >= 80:
            break
    return out


def _dom_reviews(html: str) -> list[dict]:
    """Pull employee review bodies from a /kommentare page DOM."""
    if BeautifulSoup is None or not html:
        return []
    out: list[dict] = []
    soup = BeautifulSoup(html, "html.parser")
    candidates = soup.find_all(
        ["article", "div", "section"],
        class_=re.compile(r"(?i)review|kommentar|card|comment"),
    )
    for blk in candidates:
        txt = blk.get_text(" ", strip=True) or ""
        if len(txt) < 80 or len(txt) > 6000:
            continue
        # Title: first heading
        h = blk.find(["h1", "h2", "h3", "h4", "h5"])
        title_t = h.get_text(" ", strip=True)[:200] if h else ""
        # Helpful counter: hat/found helpful patterns
        helpful = 0
        m = re.search(r"(?:hilfreich|helpful)[^\d]*([\d,]+)", txt, re.I)
        if m:
            try:
                helpful = int(m.group(1).replace(",", ""))
            except ValueError:
                helpful = 0
        out.append({
            "title": title_t,
            "body": txt[:5000],
            "rating": None,
            "helpful": helpful,
        })
        if len(out) >= 30:
            break
    return out


# ============================================================================
# Emitters
# ============================================================================
def _emit_salaries(company: str, country: str, sals: list[dict],
                   sal_url: str, state: State) -> int:
    added = 0
    for s in sals:
        role = (s.get("role") or "").strip()
        if not role:
            continue
        lo = s.get("min_eur_yr")
        mid = s.get("mid_eur_yr")
        hi = s.get("max_eur_yr")
        if not (lo or mid or hi):
            continue
        salary_range = {
            "min": int(lo) if lo else None,
            "mid": int(mid) if mid else None,
            "max": int(hi) if hi else None,
            "samples": int(s.get("samples", 0) or 0),
        }
        rid = make_id("kununu", "salary", company, role, lo, mid, hi)
        if state.is_seen(rid):
            continue
        # Compose a body string suitable for downstream LLM extraction.
        amt_disp = mid or hi or lo
        rng_disp = ""
        if lo and hi:
            rng_disp = f"€{lo:,}–€{hi:,}/yr"
        elif amt_disp:
            rng_disp = f"€{amt_disp:,}/yr"
        body = f"{role} bei {company}: {rng_disp}"
        if salary_range["samples"]:
            body += f" (Stichprobe: {salary_range['samples']})"
        item = {
            "id": rid,
            "raw_id": f"sal:{company}:{role}",
            "platform": "kununu",
            "kind": "salary",
            "lang": "de",
            "country_hint": country,
            "company": company,
            "role": role,
            "salary_range_eur_yr": salary_range,
            "location": "",
            "title": f"{role} Gehalt bei {company}",
            "body": body,
            "url": sal_url,
            "engagement": {"score": 0, "comments": 0},
        }
        append_jsonl(item, "kununu", RAW_DIR)
        state.mark_seen(rid)
        added += 1
    return added


def _emit_reviews(company: str, country: str, revs: list[dict],
                  rev_url: str, state: State, max_n: int = 10) -> int:
    added = 0
    for r in revs[:max_n]:
        body = (r.get("body") or "").strip()
        if len(body) < 80:
            continue
        title_t = (r.get("title") or "").strip()
        helpful = int(r.get("helpful", 0) or 0)
        rid = make_id("kununu", "review", company, body[:200])
        if state.is_seen(rid):
            continue
        item = {
            "id": rid,
            "raw_id": f"rev:{company}:{rid}",
            "platform": "kununu",
            "kind": "review",
            "lang": "de",
            "country_hint": country,
            "company": company,
            "role": "",
            "salary_range_eur_yr": None,
            "location": "",
            "title": title_t or f"Review: {company}",
            "body": body[:5000],
            "url": rev_url,
            "engagement": {"score": helpful, "comments": 0},
        }
        append_jsonl(item, "kununu", RAW_DIR)
        state.mark_seen(rid)
        added += 1
    return added


# ============================================================================
# Per-company orchestration
# ============================================================================
def crawl_company(slug: str, country_path: str, state: State) -> int:
    added = 0
    country = _country_for(country_path)

    # 1) Salary tab
    sal_url = _build_url(slug, country_path, "gehalt")
    try:
        html = fetch_html(sal_url)
    except KununuError as e:
        print(f"  [kununu] {slug} gehalt err: {e}")
        html = ""

    sals: list[dict] = []
    if html:
        nd = _next_data(html)
        if nd:
            _walk_for_salary_nodes(nd, sals)
        if not sals:
            sals = _dom_salaries(html)
        if sals:
            added += _emit_salaries(slug, country, sals, sal_url, state)
    polite_sleep()

    # 2) Reviews tab
    rev_url = _build_url(slug, country_path, "kommentare")
    try:
        rhtml = fetch_html(rev_url)
    except KununuError as e:
        print(f"  [kununu] {slug} kommentare err: {e}")
        return added

    revs: list[dict] = []
    if rhtml:
        nd = _next_data(rhtml)
        if nd:
            _walk_for_review_nodes(nd, revs)
        if not revs:
            revs = _dom_reviews(rhtml)
        if revs:
            added += _emit_reviews(slug, country, revs, rev_url, state, max_n=10)
    polite_sleep()

    return added


def run():
    state = State("kununu")
    preload_seen(state, "kununu", key_field="id")
    items_added = 0
    budget = TimeBudget(PLATFORM_TIME_BUDGET_SEC)

    smoke = bool(os.environ.get("SMOKE_TEST"))
    companies = COMPANIES[:15] if smoke else COMPANIES

    try:
        for slug, country_path in companies:
            if budget.expired():
                print("[kununu] time budget expired")
                break
            kw_key = f"{country_path}:{slug}" if country_path else slug
            if state.is_kw_done(kw_key):
                continue
            print(f"[kununu] company={slug!r} country={_country_for(country_path)}")
            try:
                got = crawl_company(slug, country_path, state)
            except Exception as e:
                print(f"  [kununu] {slug} fatal: {e}")
                state.save()
                time.sleep(3)
                continue
            items_added += got
            print(f"  [kununu] +{got} (total {items_added})")
            state.mark_kw_done(kw_key)
            state.save()
            polite_sleep()
            if items_added >= PER_PLATFORM_LIMIT:
                print(f"[kununu] hit PER_PLATFORM_LIMIT={PER_PLATFORM_LIMIT}")
                break
    finally:
        state.save(force=True)

    print(f"[kununu] done, +{items_added} items this run")


if __name__ == "__main__":
    run()
