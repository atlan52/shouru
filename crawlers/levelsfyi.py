"""Levels.fyi crawler — comprehensive tech compensation by company × level × location.

Strategy:
  - Levels.fyi exposes a public REST-ish JSON API. No auth required.
      * https://www.levels.fyi/api/companies?search={slug}
      * https://www.levels.fyi/api/comps?company={slug}&track={track}
    `comps` returns individual self-reported comp records: { level, total_comp,
    base, stock, bonus, location, years_experience, focus_tag, ... }
  - We iterate (company × track) over a curated seed list of top tech /
    finance / consumer / hardware companies. Each comp record becomes a
    single jsonl item.
  - Country detection: the `location` field is a city string ("Mountain View,
    CA, US", "London, UK", "Bangalore, KA, IN"). We map common cities to
    ISO-2 country codes; default "US".
  - Honors SMOKE_TEST + polite_sleep + PLATFORM_TIME_BUDGET_SEC.
"""
import re
import time

import requests

from config import (
    PER_PLATFORM_LIMIT, RAW_DIR, PLATFORM_TIME_BUDGET_SEC,
)
from crawlers.common import (
    append_jsonl, make_id, polite_sleep, preload_seen,
    default_headers, TimeBudget,
)
from crawlers.state import State


PLATFORM = "levelsfyi"
BASE = "https://www.levels.fyi"
COMPS_API = BASE + "/api/comps"
COMPANIES_API = BASE + "/api/companies"

# Job tracks supported by the comps endpoint (URL-encoded `track` param).
TRACKS = [
    "Software Engineer",
    "Product Manager",
    "Data Scientist",
    "Hardware Engineer",
    "Designer",
    "Mechanical Engineer",
    "Sales",
    "Recruiter",
    "Consultant",
    "Marketing",
    "Solution Architect",
    "Customer Service",
    "Information Technologist",
    "Technical Program Manager",
]

# URL slug used in the Software Engineer comp landing page (for record url).
TRACK_URL_SLUG = {
    "Software Engineer": "software-engineer",
    "Product Manager": "product-manager",
    "Data Scientist": "data-scientist",
    "Hardware Engineer": "hardware-engineer",
    "Designer": "designer",
    "Mechanical Engineer": "mechanical-engineer",
    "Sales": "sales",
    "Recruiter": "recruiter",
    "Consultant": "management-consultant",
    "Marketing": "marketing",
    "Solution Architect": "solution-architect",
    "Customer Service": "customer-service",
    "Information Technologist": "information-technologist",
    "Technical Program Manager": "technical-program-manager",
}

# Top company slugs — tech, finance, hardware, consumer, retail.
COMPANIES = [
    # FAANG+ / cloud / chips
    "google", "meta", "apple", "microsoft", "amazon", "netflix",
    "openai", "anthropic", "nvidia", "tesla", "linkedin",
    "salesforce", "oracle", "ibm", "intel", "amd", "qualcomm",
    "adobe", "paypal", "square", "stripe", "robinhood", "palantir",
    "snowflake", "databricks", "twilio", "atlassian", "gitlab",
    "github", "cloudflare", "fastly", "mongodb", "datadog", "splunk",
    "servicenow", "intuit", "autodesk", "vmware", "redhat",
    "hashicorp", "confluent", "anaconda", "scale-ai", "cohere",
    "mistral", "hugging-face", "perplexity", "character-ai",
    # Asia-Pacific tech
    "bytedance", "tencent", "alibaba", "baidu", "jd", "didi",
    "kuaishou", "miHoYo", "samsung", "toyota", "sony", "nintendo",
    "panasonic", "honda",
    # Industrial / consumer
    "ge",
    # Finance / quant / HFT
    "jpmorgan-chase", "goldman-sachs", "morgan-stanley", "blackrock",
    "citadel", "jane-street", "two-sigma", "deshaw",
    "hudson-river-trading",
    # Consumer internet
    "tiktok", "pinterest", "uber", "lyft", "doordash", "instacart",
    "shopify", "snap", "reddit", "discord", "slack", "dropbox",
    "box", "zoom", "spotify",
    # Retail / commerce
    "mcdonalds", "walmart", "costco", "target", "wayfair", "bestbuy",
    "etsy", "ebay",
    # Hardware / aerospace / defense
    "hp", "dell", "lockheed", "boeing", "raytheon", "anduril",
    "spacex",
]


# ============================================================================
# City → ISO-2 country mapping for `location` field (extend as needed).
# ============================================================================
CITY_TO_COUNTRY = {
    # GB
    "london": "GB", "manchester": "GB", "edinburgh": "GB", "cambridge": "GB",
    "oxford": "GB", "bristol": "GB", "dublin": "IE",
    # IN
    "bangalore": "IN", "bengaluru": "IN", "hyderabad": "IN", "mumbai": "IN",
    "delhi": "IN", "gurgaon": "IN", "gurugram": "IN", "noida": "IN",
    "pune": "IN", "chennai": "IN", "kolkata": "IN",
    # SG / HK / TW / MY / PH / TH / VN / ID
    "singapore": "SG", "hong kong": "HK", "taipei": "TW", "kuala lumpur": "MY",
    "manila": "PH", "bangkok": "TH", "ho chi minh": "VN", "hanoi": "VN",
    "jakarta": "ID",
    # CN
    "beijing": "CN", "shanghai": "CN", "shenzhen": "CN", "guangzhou": "CN",
    "hangzhou": "CN", "chengdu": "CN", "xiamen": "CN", "nanjing": "CN",
    # JP
    "tokyo": "JP", "osaka": "JP", "kyoto": "JP", "yokohama": "JP",
    "fukuoka": "JP",
    # KR
    "seoul": "KR", "busan": "KR",
    # CA
    "toronto": "CA", "vancouver": "CA", "montreal": "CA", "ottawa": "CA",
    "calgary": "CA", "waterloo": "CA",
    # AU / NZ
    "sydney": "AU", "melbourne": "AU", "brisbane": "AU", "perth": "AU",
    "auckland": "NZ", "wellington": "NZ",
    # DE / AT / CH
    "berlin": "DE", "munich": "DE", "münchen": "DE", "hamburg": "DE",
    "frankfurt": "DE", "cologne": "DE", "stuttgart": "DE",
    "vienna": "AT", "wien": "AT",
    "zurich": "CH", "zürich": "CH", "geneva": "CH", "basel": "CH",
    "lausanne": "CH", "bern": "CH",
    # NL / BE / LU
    "amsterdam": "NL", "rotterdam": "NL", "utrecht": "NL", "the hague": "NL",
    "eindhoven": "NL",
    "brussels": "BE", "antwerp": "BE",
    "luxembourg": "LU",
    # FR
    "paris": "FR", "lyon": "FR", "marseille": "FR", "toulouse": "FR",
    "lille": "FR", "bordeaux": "FR",
    # IT / ES / PT
    "milan": "IT", "rome": "IT", "turin": "IT",
    "madrid": "ES", "barcelona": "ES", "valencia": "ES",
    "lisbon": "PT", "porto": "PT",
    # Nordics
    "stockholm": "SE", "gothenburg": "SE",
    "copenhagen": "DK",
    "oslo": "NO",
    "helsinki": "FI",
    "reykjavik": "IS",
    # Israel / MENA
    "tel aviv": "IL", "jerusalem": "IL", "haifa": "IL",
    "dubai": "AE", "abu dhabi": "AE", "riyadh": "SA",
    # Latin America
    "são paulo": "BR", "sao paulo": "BR", "rio de janeiro": "BR",
    "buenos aires": "AR", "santiago": "CL", "bogotá": "CO", "bogota": "CO",
    "mexico city": "MX", "ciudad de méxico": "MX", "guadalajara": "MX",
    "monterrey": "MX", "lima": "PE",
    # Eastern Europe
    "warsaw": "PL", "kraków": "PL", "krakow": "PL", "wrocław": "PL",
    "wroclaw": "PL", "prague": "CZ", "budapest": "HU",
    "moscow": "RU", "saint petersburg": "RU", "st. petersburg": "RU",
    "kyiv": "UA", "kiev": "UA",
    "istanbul": "TR", "ankara": "TR",
    # Africa
    "cairo": "EG", "lagos": "NG", "johannesburg": "ZA", "cape town": "ZA",
    "nairobi": "KE",
}

# Two-letter "country part" suffixes already in ISO-2 form (US, UK, GB, ...).
ISO2_TAIL_RE = re.compile(r",\s*([A-Z]{2})\s*$")


def location_to_country(location: str) -> str:
    """Best-effort: parse a Levels.fyi location string → ISO-2 country code."""
    if not location:
        return "US"
    s = location.strip()
    # 1) Trailing ISO-2 (e.g. "Mountain View, CA, US")
    m = ISO2_TAIL_RE.search(s)
    if m:
        tail = m.group(1).upper()
        if tail == "UK":
            return "GB"
        # Skip US-state two-letter abbreviations: those are second-from-last;
        # Levels typically appends the actual country code at the very end,
        # but if the only tail is "CA" it could be either Canada or California.
        # If location has 3 parts, first tail is usually state, second is country.
        parts = [p.strip() for p in s.split(",")]
        if len(parts) >= 3:
            country = parts[-1].upper()
            if country == "UK":
                return "GB"
            if len(country) == 2:
                return country
        # 2-part location with tail "US"/"CA" — assume country if not a known US state
        US_STATES = {
            "AL", "AK", "AZ", "AR", "CO", "CT", "DE", "FL", "GA",
            "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
            "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV",
            "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR",
            "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA",
            "WA", "WV", "WI", "WY", "DC",
            # Note: CA omitted intentionally — too ambiguous.
        }
        if tail in US_STATES:
            return "US"
        if tail == "CA":
            # Bare "City, CA" — treat as US California.
            return "US"
        if len(tail) == 2:
            return tail
    # 2) City lookup
    s_low = s.lower()
    for city, country in CITY_TO_COUNTRY.items():
        if city in s_low:
            return country
    return "US"


# ============================================================================
# HTTP
# ============================================================================
class LevelsError(Exception):
    pass


def _hdrs() -> dict:
    h = default_headers("en-US,en;q=0.9")
    h["Accept"] = "application/json, text/plain, */*"
    h["Referer"] = BASE + "/"
    return h


def fetch_json(url: str, params=None, timeout: int = 25):
    try:
        r = requests.get(url, headers=_hdrs(), params=params, timeout=timeout)
    except Exception as e:
        raise LevelsError(f"net err {url}: {e}")
    if r.status_code in (403, 429):
        raise LevelsError(f"{r.status_code} on {url}")
    if r.status_code == 404:
        raise LevelsError(f"404 on {url}")
    if r.status_code != 200:
        raise LevelsError(f"status {r.status_code} on {url}")
    try:
        return r.json()
    except Exception:
        raise LevelsError(f"non-JSON response on {url}")


# ============================================================================
# Comp record normalization
# ============================================================================
def _to_int(x) -> int:
    if x is None:
        return 0
    if isinstance(x, bool):
        return 0
    if isinstance(x, (int, float)):
        return int(x)
    if isinstance(x, str):
        s = x.replace(",", "").replace("$", "").strip().lower()
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
    return 0


def _yoe(rec: dict) -> str:
    """Pull a years-experience string out of various possible keys."""
    for k in ("years_experience", "yearsOfExperience", "yoe", "years_of_experience"):
        v = rec.get(k)
        if isinstance(v, (int, float)):
            return str(int(v))
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _location(rec: dict) -> str:
    for k in ("location", "city", "locationName"):
        v = rec.get(k)
        if isinstance(v, dict):
            # Sometimes nested {"name": ..., "country": ...}
            name = v.get("name") or v.get("city") or ""
            ctry = v.get("country") or ""
            return f"{name}, {ctry}".strip(", ").strip()
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _level(rec: dict) -> str:
    for k in ("level", "levelName", "title", "jobLevel"):
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):
            n = v.get("name") or v.get("title") or ""
            if n:
                return str(n).strip()
    return ""


def _focus(rec: dict) -> str:
    for k in ("focus_tag", "focusTag", "specialization", "tag"):
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _track_url(company: str, track: str) -> str:
    slug = TRACK_URL_SLUG.get(track, "software-engineer")
    return f"{BASE}/companies/{company}/salaries/{slug}"


def normalize_comp(rec: dict, company: str, track: str) -> dict | None:
    """Convert one comp record from the API into our jsonl schema."""
    if not isinstance(rec, dict):
        return None
    total = _to_int(rec.get("total_comp_usd_yr") or rec.get("totalCompensation")
                    or rec.get("total") or rec.get("totalComp"))
    base = _to_int(rec.get("base") or rec.get("baseSalary") or rec.get("base_salary"))
    stock = _to_int(rec.get("stock") or rec.get("stockGrantValue") or rec.get("equity"))
    bonus = _to_int(rec.get("bonus") or rec.get("bonusAmount") or rec.get("annualBonus"))

    if total <= 0 and (base + stock + bonus) > 0:
        total = base + stock + bonus
    if total <= 0:
        return None

    level = _level(rec)
    location = _location(rec)
    yoe = _yoe(rec)
    focus = _focus(rec)
    country_hint = location_to_country(location)

    body = (
        f"{track} {('L' + level) if level and level[0].isdigit() else level} "
        f"at {company}: TC ${total:,}/yr "
        f"(base ${base:,}, stock ${stock:,}, bonus ${bonus:,})"
    )
    if yoe:
        body += f" — {yoe} YOE"
    if location:
        body += f" in {location}"
    if focus:
        body += f" [{focus}]"

    rid_seed = (
        rec.get("id") or rec.get("submissionId")
        or f"{company}|{track}|{level}|{total}|{base}|{stock}|{bonus}|{location}|{yoe}"
    )
    our_id = make_id(PLATFORM, str(rid_seed))

    return {
        "id": our_id,
        "raw_id": str(rid_seed),
        "platform": PLATFORM,
        "lang": "en",
        "company": company,
        "role": track,
        "level": level,
        "title": f"{track} {level} at {company}".strip(),
        "body": body,
        "total_comp_usd_yr": total,
        "base_usd_yr": base,
        "stock_usd_yr": stock,
        "bonus_usd_yr": bonus,
        "location": location,
        "years_exp": yoe,
        "focus_tag": focus,
        "country_hint": country_hint,
        "url": _track_url(company, track),
        "engagement": {"score": 0, "comments": 0},
    }


# ============================================================================
# Per-(company, track) extraction
# ============================================================================
def _iter_records(payload) -> list[dict]:
    """The comps endpoint returns either a list, or a dict containing the list
    under one of several keys. Walk it tolerantly."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if not isinstance(payload, dict):
        return []
    for k in ("comps", "data", "results", "rows", "items", "salaries"):
        v = payload.get(k)
        if isinstance(v, list):
            return [r for r in v if isinstance(r, dict)]
        if isinstance(v, dict):
            for kk in ("comps", "data", "results", "rows", "items"):
                vv = v.get(kk)
                if isinstance(vv, list):
                    return [r for r in vv if isinstance(r, dict)]
    return []


def crawl_company_track(company: str, track: str, state: State) -> int:
    """Fetch comps for (company, track); emit jsonl rows. Returns # added."""
    try:
        payload = fetch_json(COMPS_API, params={"company": company, "track": track})
    except LevelsError as e:
        msg = str(e)
        print(f"  [{PLATFORM}] {company}/{track} err: {e}")
        if "403" in msg or "429" in msg:
            time.sleep(20)
        return 0
    records = _iter_records(payload)
    if not records:
        return 0
    added = 0
    for rec in records:
        try:
            item = normalize_comp(rec, company, track)
        except Exception as e:
            print(f"    [{PLATFORM}] normalize err: {e}")
            continue
        if not item:
            continue
        if state.is_seen(item["id"]):
            continue
        append_jsonl(item, PLATFORM, RAW_DIR)
        state.mark_seen(item["id"])
        added += 1
        state.maybe_save(every=15)
    return added


# ============================================================================
# Run loop
# ============================================================================
def run():
    state = State(PLATFORM)
    preload_seen(state, PLATFORM, key_field="id")
    budget = TimeBudget(PLATFORM_TIME_BUDGET_SEC)
    items_added = 0

    try:
        for company in COMPANIES:
            if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                break
            for track in TRACKS:
                if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                    break
                kw_label = f"{company}|{track}"
                if state.is_kw_done(kw_label):
                    continue
                print(f"[{PLATFORM}] {company} / {track}")
                try:
                    got = crawl_company_track(company, track, state)
                except Exception as e:
                    print(f"  [{PLATFORM}] {company}/{track} fatal: {e}")
                    state.save()
                    polite_sleep()
                    continue
                items_added += got
                if got:
                    print(f"  [{PLATFORM}] +{got} (total {items_added})")
                state.mark_kw_done(kw_label)
                state.save()
                polite_sleep()
            polite_sleep()
            if items_added >= PER_PLATFORM_LIMIT:
                print(f"[{PLATFORM}] hit PER_PLATFORM_LIMIT={PER_PLATFORM_LIMIT}")
                break
    finally:
        state.save(force=True)

    print(f"[{PLATFORM}] done, +{items_added} items this run")


if __name__ == "__main__":
    run()
