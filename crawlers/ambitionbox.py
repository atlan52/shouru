"""AmbitionBox crawler — Indian Glassdoor with detailed salary breakdowns.

Strategy:
  - Public, no auth. Pure requests + BeautifulSoup.
  - URL pattern: https://www.ambitionbox.com/salaries/{slug}-salaries
  - For each company, try to parse the JSON-LD <script type="application/ld+json">
    blocks first (cheaper, more reliable than DOM scraping). Fall back to DOM.
  - Collect both salary tuples (per role) and employee reviews from
    /reviews/{slug}-reviews.
  - Country: IN, lang: en. Honors SMOKE_TEST + polite_sleep + time budget.
"""
import json
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

BASE = "https://www.ambitionbox.com"
SAL_URL = BASE + "/salaries/{slug}-salaries"
REV_URL = BASE + "/reviews/{slug}-reviews"

# Top IN companies — tech, IT services, consulting, finance, conglomerates.
COMPANIES = [
    "infosys", "tcs", "accenture", "wipro", "hcl-technologies",
    "capgemini", "cognizant", "ibm", "microsoft-corporation", "google",
    "amazon", "flipkart", "paytm", "swiggy", "zomato",
    "ola-cabs", "byjus", "oyo-rooms", "freshworks", "zoho",
    "mu-sigma", "deloitte", "ey", "kpmg", "jp-morgan-services-india",
    "goldman-sachs", "morgan-stanley", "hdfc-bank", "icici-bank", "axis-bank",
    "sbi", "reliance-industries", "tata-motors", "mahindra-mahindra",
    "asian-paints", "hindustan-unilever", "itc", "larsen-toubro",
    "hero-motocorp", "bajaj-finserv", "paytm-payments-bank",
]

BOT_MARKERS = ("captcha", "are you a human", "access denied", "unusual traffic")


class AmbitionBoxError(Exception):
    pass


def _ab_headers() -> dict:
    h = default_headers(accept_lang="en-IN,en;q=0.9")
    h["Referer"] = BASE + "/"
    return h


def fetch_html(url: str, timeout: int = 25) -> str:
    try:
        r = requests.get(url, headers=_ab_headers(), timeout=timeout)
        if r.status_code in (403, 429):
            raise AmbitionBoxError(f"{r.status_code} on {url}")
        if r.status_code == 404:
            raise AmbitionBoxError(f"404 on {url}")
        if r.status_code != 200:
            raise AmbitionBoxError(f"status {r.status_code} on {url}")
        body = r.text or ""
        low = body.lower()
        if any(m in low for m in BOT_MARKERS):
            raise AmbitionBoxError("bot-block / captcha on page")
        return body
    except AmbitionBoxError:
        raise
    except Exception as e:
        raise AmbitionBoxError(str(e))


# ============================================================================
# Number parsing — INR amounts come in formats like:
#   "₹3.5 Lakhs", "3,50,000 / yr", "₹5 LPA", "5L - 8L", "12 LPA"
# ============================================================================
_NUM_RE = re.compile(r"([\d]+(?:[\.,][\d]+)*)")


def _to_inr_yr(raw_amount: str) -> int | None:
    """Best-effort parse '₹3.5 Lakhs / yr' style strings → integer INR / yr."""
    if not raw_amount:
        return None
    s = raw_amount.strip()
    s_low = s.lower().replace(",", "")
    m = _NUM_RE.search(s_low.replace(",", ""))
    if not m:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    # Multiplier hints
    if "crore" in s_low or re.search(r"\bcr\b", s_low):
        v *= 10_000_000
    elif "lakh" in s_low or "lpa" in s_low or re.search(r"\bl\b", s_low):
        v *= 100_000
    elif "k" in s_low and v < 1000:
        v *= 1_000
    # If raw value is small (<10000) and no multiplier matched, assume LPA
    elif v < 10_000:
        v *= 100_000
    return int(v)


def _exp_range(raw: str) -> str:
    """Normalize experience strings like '0 - 2 yrs' or '3 to 5 years'."""
    if not raw:
        return ""
    nums = re.findall(r"\d+", raw)
    if len(nums) >= 2:
        return f"{nums[0]}-{nums[1]} yrs"
    if len(nums) == 1:
        return f"{nums[0]} yrs"
    return raw.strip()[:40]


# ============================================================================
# JSON-LD extraction — AmbitionBox embeds Occupation / JobPosting schemas.
# ============================================================================
def _iter_jsonld(html: str):
    """Yield parsed JSON objects from <script type="application/ld+json"> blocks."""
    if not html:
        return
    # Tolerant regex parse first; bs4 parsing for fallback.
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE,
    ):
        raw = m.group(1).strip()
        if not raw:
            continue
        try:
            yield json.loads(raw)
        except Exception:
            # Try to peel a single object out of an array-like blob.
            try:
                yield json.loads(raw.strip().rstrip(","))
            except Exception:
                continue


def _walk_jsonld_for_salaries(obj, out: list[dict]):
    """Recursively walk a JSON-LD object collecting salary-like nodes."""
    if isinstance(obj, dict):
        t = obj.get("@type") or obj.get("type") or ""
        # Common shapes: Occupation, JobPosting, MonetaryAmount, AggregateRating
        if t in ("Occupation", "JobPosting", "WorkRole"):
            role = obj.get("name") or obj.get("title") or ""
            sal = obj.get("estimatedSalary") or obj.get("baseSalary") or obj.get("salary")
            exp = obj.get("experienceRequirements") or obj.get("yearsOfExperience") or ""
            if isinstance(exp, dict):
                exp = exp.get("monthsOfExperience") or exp.get("description") or ""
            amt = None
            if isinstance(sal, dict):
                v = sal.get("value") or sal.get("median") or sal.get("minValue")
                if isinstance(v, (int, float)):
                    amt = int(v)
                elif isinstance(v, dict):
                    inner = v.get("value") or v.get("median")
                    if isinstance(inner, (int, float)):
                        amt = int(inner)
                if amt is None:
                    raw = sal.get("name") or ""
                    amt = _to_inr_yr(str(raw))
            elif isinstance(sal, (int, float)):
                amt = int(sal)
            elif isinstance(sal, str):
                amt = _to_inr_yr(sal)
            if role and amt:
                out.append({
                    "role": str(role)[:120],
                    "experience_years_range": _exp_range(str(exp)),
                    "amount_inr_yr": int(amt),
                })
        for v in obj.values():
            _walk_jsonld_for_salaries(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_jsonld_for_salaries(v, out)


# ============================================================================
# DOM scraping fallback for salary tables.
# ============================================================================
def _dom_salaries(html: str) -> list[dict]:
    """Extract role/experience/amount tuples from common salary table rows."""
    if BeautifulSoup is None or not html:
        return []
    out = []
    soup = BeautifulSoup(html, "html.parser")
    # Try a few patterns. AmbitionBox renders rows with role text + exp + ₹ amt.
    # Be permissive: look for any block containing both ₹ and a "yrs" hint.
    for blk in soup.find_all(["div", "li", "tr"]):
        txt = (blk.get_text(" ", strip=True) or "")[:400]
        if "₹" not in txt:
            continue
        if not re.search(r"\b\d+\s*(?:-|to)\s*\d+\s*(?:yr|year)", txt, re.I):
            continue
        # Pull the first ₹ amount.
        amt_m = re.search(r"₹[\s ]*([\d\.,]+)\s*(L|Lakh[s]?|Cr|Crore|LPA|K|k)?", txt)
        if not amt_m:
            continue
        unit = (amt_m.group(2) or "").lower()
        try:
            v = float(amt_m.group(1).replace(",", ""))
        except ValueError:
            continue
        if "cr" in unit:
            v *= 10_000_000
        elif "l" in unit or unit == "lpa":
            v *= 100_000
        elif "k" in unit:
            v *= 1_000
        elif v < 10_000:
            v *= 100_000
        # Pull the experience range and a candidate role.
        exp_m = re.search(r"(\d+)\s*(?:-|to)\s*(\d+)\s*(?:yr|year)", txt, re.I)
        exp = f"{exp_m.group(1)}-{exp_m.group(2)} yrs" if exp_m else ""
        # Role: first chunk before "₹" or "yrs"
        head = re.split(r"₹|\d+\s*(?:-|to)\s*\d+\s*(?:yr|year)", txt, maxsplit=1, flags=re.I)[0]
        role = head.strip()[:120]
        if not role:
            continue
        out.append({
            "role": role,
            "experience_years_range": exp,
            "amount_inr_yr": int(v),
        })
        if len(out) > 60:
            break
    return out


# ============================================================================
# Reviews
# ============================================================================
def _dom_reviews(html: str) -> list[dict]:
    """Pull employee review bodies + helpful counts."""
    if BeautifulSoup is None or not html:
        return []
    out = []
    soup = BeautifulSoup(html, "html.parser")
    # Reviews live in cards — look for blocks with substantial text and a "helpful" hint.
    candidates = soup.find_all(
        ["div", "article", "section"],
        class_=re.compile(r"(?i)review|card|feedback"),
    )
    for blk in candidates:
        txt = blk.get_text(" ", strip=True) or ""
        if len(txt) < 80 or len(txt) > 6000:
            continue
        # Helpful / likes count
        helpful = 0
        m = re.search(r"helpful[^\d]*([\d,]+)", txt, re.I)
        if m:
            try:
                helpful = int(m.group(1).replace(",", ""))
            except ValueError:
                helpful = 0
        # Heuristic role/title — first <a> or <h*> child
        role_el = blk.find(["h1", "h2", "h3", "h4", "h5"])
        role = role_el.get_text(" ", strip=True)[:120] if role_el else ""
        out.append({
            "role": role,
            "body": txt[:5000],
            "helpful": helpful,
        })
        if len(out) > 30:
            break
    return out


# ============================================================================
# Per-company processing
# ============================================================================
def _emit_salaries(company: str, sals: list[dict], state: State) -> int:
    added = 0
    sal_url = SAL_URL.format(slug=company)
    for s in sals:
        role = s.get("role", "").strip()
        amt = s.get("amount_inr_yr")
        if not role or not amt:
            continue
        exp = s.get("experience_years_range", "")
        rid = make_id("ambitionbox", "salary", company, role, exp, amt)
        if state.is_seen(rid):
            continue
        item = {
            "id": rid,
            "raw_id": f"sal:{company}:{role}:{exp}",
            "platform": "ambitionbox",
            "kind": "salary",
            "lang": "en",
            "country_hint": "IN",
            "company": company,
            "role": role,
            "experience_years_range": exp,
            "amount_inr_yr": int(amt),
            "title": f"{role} salary at {company}",
            "body": f"{role} at {company}, {exp}: ₹{amt:,}/yr",
            "url": sal_url,
            "engagement": {"score": 0, "comments": 0, "views": None},
        }
        append_jsonl(item, "ambitionbox", RAW_DIR)
        state.mark_seen(rid)
        added += 1
    return added


def _emit_reviews(company: str, revs: list[dict], state: State) -> int:
    added = 0
    rev_url = REV_URL.format(slug=company)
    for r in revs:
        body = r.get("body", "").strip()
        if len(body) < 80:
            continue
        role = r.get("role", "").strip()
        helpful = int(r.get("helpful", 0) or 0)
        rid = make_id("ambitionbox", "review", company, body[:200])
        if state.is_seen(rid):
            continue
        item = {
            "id": rid,
            "raw_id": f"rev:{company}:{rid}",
            "platform": "ambitionbox",
            "kind": "review",
            "lang": "en",
            "country_hint": "IN",
            "company": company,
            "role": role,
            "title": f"Review: {company}" + (f" — {role}" if role else ""),
            "body": body[:5000],
            "url": rev_url,
            "engagement": {"score": helpful, "comments": 0, "views": None},
        }
        append_jsonl(item, "ambitionbox", RAW_DIR)
        state.mark_seen(rid)
        added += 1
    return added


def crawl_company(company: str, state: State) -> int:
    added = 0

    # 1) Salaries page
    sal_url = SAL_URL.format(slug=company)
    try:
        html = fetch_html(sal_url)
    except AmbitionBoxError as e:
        print(f"  [ambitionbox] {company} salaries err: {e}")
        return 0

    salaries: list[dict] = []
    for blob in _iter_jsonld(html):
        _walk_jsonld_for_salaries(blob, salaries)
    if not salaries:
        salaries = _dom_salaries(html)
    if salaries:
        added += _emit_salaries(company, salaries, state)
    polite_sleep()

    # 2) Reviews page
    rev_url = REV_URL.format(slug=company)
    try:
        rhtml = fetch_html(rev_url)
    except AmbitionBoxError as e:
        print(f"  [ambitionbox] {company} reviews err: {e}")
        return added
    revs = _dom_reviews(rhtml)
    if revs:
        added += _emit_reviews(company, revs, state)
    polite_sleep()

    return added


def run():
    state = State("ambitionbox")
    preload_seen(state, "ambitionbox", key_field="id")
    items_added = 0
    budget = TimeBudget(PLATFORM_TIME_BUDGET_SEC)

    try:
        for company in COMPANIES:
            if budget.expired():
                print("[ambitionbox] time budget expired")
                break
            if state.is_kw_done(company):
                continue
            print(f"[ambitionbox] company={company!r}")
            try:
                got = crawl_company(company, state)
            except Exception as e:
                print(f"  [ambitionbox] {company} fatal: {e}")
                state.save()
                time.sleep(3)
                continue
            items_added += got
            print(f"  [ambitionbox] +{got} (total {items_added})")
            state.mark_kw_done(company)
            state.save()
            polite_sleep()
            if items_added >= PER_PLATFORM_LIMIT:
                print(f"[ambitionbox] hit PER_PLATFORM_LIMIT={PER_PLATFORM_LIMIT}")
                break
    finally:
        state.save(force=True)

    print(f"[ambitionbox] done, +{items_added} items this run")


if __name__ == "__main__":
    run()
