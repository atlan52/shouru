"""Rich-list crawler — Forbes Billionaires, Hurun, Bloomberg Billionaires Index.

Why: rich-list entries explicitly include "source of wealth" — exactly the
data point the project needs for the top tier. This is the only realistic
way to gather 100+ samples of "people earning >$10M/yr" with both
profession and earning mechanism explicit.

Sources:
  (1) Forbes — public JSON API (billionaires/2024 list, ~2700 entries)
  (2) Hurun — China rich-list HTML page (zh-CN and en-US variants)
  (3) Bloomberg — Billionaires Index top 500 daily HTML page

Each yields one record per billionaire. LLM downstream populates:
  - earning_mechanisms (typically business_owner + equity_compensation)
  - profession (e.g. "tech_founder", "hedge_fund_manager")
  - income_amount_local = net_worth_usd_b * 1e9 (one-time net worth, not annual)
"""
import json
import re
import time
import requests
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from config import PER_PLATFORM_LIMIT, RAW_DIR
from crawlers.common import (
    append_jsonl, make_id, preload_seen, polite_sleep, default_headers,
)
from crawlers.state import State


PLATFORM = "richlists"

FORBES_LIST_URL = "https://www.forbes.com/forbesapi/person/billionaires/2024/position/true.json"
FORBES_RTB_URL = "https://www.forbes.com/forbesapi/person/rtb/0/-estWorthPrev/true.json"
HURUN_URL_EN = "https://www.hurun.net/en-US/Rank/HsRankDetails?pagetype=rich"
HURUN_URL_ZH = "https://www.hurun.net/zh-CN/Rank/HsRankDetails?pagetype=rich"
HURUN_API = "https://www.hurun.net/zh-CN/Rank/HsRankDetailsList"
BLOOMBERG_URL = "https://www.bloomberg.com/billionaires/"


# ============================================================================
# Country name → ISO-2 mapper
# Forbes/Bloomberg/Hurun use English country names; we normalize to ISO-2.
# ============================================================================
COUNTRY_NAME_TO_ISO2 = {
    "united states": "US", "usa": "US", "u.s.": "US", "u.s.a.": "US",
    "america": "US", "united states of america": "US",
    "china": "CN", "china (mainland)": "CN", "mainland china": "CN",
    "people's republic of china": "CN", "prc": "CN",
    "india": "IN",
    "russia": "RU", "russian federation": "RU",
    "hong kong": "HK", "hong kong sar": "HK",
    "taiwan": "TW", "taiwan, china": "TW", "republic of china": "TW",
    "macau": "MO", "macao": "MO",
    "saudi arabia": "SA", "kingdom of saudi arabia": "SA",
    "germany": "DE",
    "japan": "JP",
    "united kingdom": "GB", "uk": "GB", "u.k.": "GB", "britain": "GB",
    "england": "GB", "great britain": "GB",
    "mexico": "MX",
    "brazil": "BR",
    "italy": "IT",
    "france": "FR",
    "canada": "CA",
    "spain": "ES",
    "switzerland": "CH",
    "australia": "AU",
    "singapore": "SG",
    "israel": "IL",
    "south korea": "KR", "korea, south": "KR", "republic of korea": "KR",
    "korea": "KR",
    "north korea": "KP",
    "indonesia": "ID",
    "malaysia": "MY",
    "thailand": "TH",
    "philippines": "PH", "the philippines": "PH",
    "vietnam": "VN", "viet nam": "VN",
    "turkey": "TR", "türkiye": "TR", "turkiye": "TR",
    "uae": "AE", "united arab emirates": "AE",
    "egypt": "EG",
    "south africa": "ZA",
    "nigeria": "NG",
    "argentina": "AR",
    "colombia": "CO",
    "chile": "CL",
    "poland": "PL",
    "sweden": "SE",
    "norway": "NO",
    "morocco": "MA",
    "pakistan": "PK",
    "bangladesh": "BD",
    "ukraine": "UA",
    "netherlands": "NL", "the netherlands": "NL", "holland": "NL",
    "belgium": "BE",
    "austria": "AT",
    "ireland": "IE",
    "portugal": "PT",
    "greece": "GR",
    "denmark": "DK",
    "finland": "FI",
    "iceland": "IS",
    "czech republic": "CZ", "czechia": "CZ",
    "hungary": "HU",
    "romania": "RO",
    "bulgaria": "BG",
    "cyprus": "CY",
    "monaco": "MC",
    "liechtenstein": "LI",
    "luxembourg": "LU",
    "new zealand": "NZ",
    "kazakhstan": "KZ",
    "uzbekistan": "UZ",
    "georgia": "GE",
    "armenia": "AM",
    "azerbaijan": "AZ",
    "qatar": "QA",
    "kuwait": "KW",
    "bahrain": "BH",
    "oman": "OM",
    "jordan": "JO",
    "lebanon": "LB",
    "iran": "IR",
    "iraq": "IQ",
    "venezuela": "VE",
    "peru": "PE",
    "uruguay": "UY",
    "ecuador": "EC",
    "panama": "PA",
    "guatemala": "GT",
    "dominican republic": "DO",
    "cuba": "CU",
    "kenya": "KE",
    "ghana": "GH",
    "tanzania": "TZ",
    "ethiopia": "ET",
    "algeria": "DZ",
    "tunisia": "TN",
    "zimbabwe": "ZW",
    "angola": "AO",
    "cyprus (greek part)": "CY",
    "the bahamas": "BS", "bahamas": "BS",
    "barbados": "BB",
    "bermuda": "BM",
    "cayman islands": "KY",
}


def country_to_iso2(name: str) -> str:
    """Convert country name to ISO-2 code. Returns '??' if unknown."""
    if not name:
        return "??"
    key = str(name).strip().lower()
    if key in COUNTRY_NAME_TO_ISO2:
        return COUNTRY_NAME_TO_ISO2[key]
    # If already ISO-2-like (2 chars, alpha), accept it
    if len(key) == 2 and key.isalpha():
        return key.upper()
    # Try first segment if comma-separated ("Israel, USA")
    if "," in key:
        first = key.split(",")[0].strip()
        if first in COUNTRY_NAME_TO_ISO2:
            return COUNTRY_NAME_TO_ISO2[first]
    return "??"


# ============================================================================
# HTTP helper
# ============================================================================
class RichlistError(Exception):
    pass


def fetch_json(url: str, params=None, timeout: int = 30):
    try:
        r = requests.get(url, headers=default_headers(), params=params, timeout=timeout)
    except Exception as e:
        raise RichlistError(f"network err on {url}: {e}")
    if r.status_code in (403, 429):
        raise RichlistError(f"{r.status_code} on {url}")
    if r.status_code != 200:
        raise RichlistError(f"status {r.status_code} on {url}")
    try:
        return r.json()
    except Exception:
        # Some Forbes responses have JSONP-like wrappers; try to strip
        text = r.text or ""
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        raise RichlistError(f"non-JSON response on {url}")


def fetch_html(url: str, timeout: int = 30, headers: dict | None = None):
    try:
        h = headers or default_headers()
        r = requests.get(url, headers=h, timeout=timeout)
    except Exception as e:
        raise RichlistError(f"network err on {url}: {e}")
    if r.status_code in (403, 429):
        raise RichlistError(f"{r.status_code} on {url}")
    if r.status_code != 200:
        raise RichlistError(f"status {r.status_code} on {url}")
    return r.text or ""


# ============================================================================
# Forbes — public JSON API
# ============================================================================
def normalize_forbes(p: dict) -> dict | None:
    """Turn one Forbes person dict into our schema. Returns None if invalid."""
    name = p.get("personName") or p.get("name") or ""
    if not name:
        return None
    rank = p.get("rank") or p.get("position")
    final_worth = p.get("finalWorth") or p.get("estWorthPrev") or p.get("netWorth")
    # finalWorth is in millions USD per Forbes API convention
    try:
        net_worth_usd_b = round(float(final_worth) / 1000.0, 3) if final_worth else None
    except (TypeError, ValueError):
        net_worth_usd_b = None

    source_of_wealth = p.get("source") or ""
    industries = p.get("industries") or []
    if isinstance(industries, str):
        industries = [s.strip() for s in industries.split(",") if s.strip()]
    industries_csv = ", ".join(industries) if industries else ""

    country_name = (
        p.get("countryOfCitizenship")
        or p.get("country")
        or p.get("citizenship")
        or ""
    )
    country_iso2 = country_to_iso2(country_name)

    city = p.get("city") or ""
    state_residence = p.get("state") or ""
    residence_msa = p.get("residenceMsa") or p.get("residence") or ""
    residence = ", ".join(x for x in (city, state_residence, residence_msa) if x)

    age = p.get("age")
    gender = p.get("gender") or ""
    bio = p.get("bio") or ""
    if isinstance(bio, list):
        bio = " ".join(str(b) for b in bio if b)
    bio_snippet = (bio or "")[:1500]

    uri = p.get("uri") or ""
    url = f"https://www.forbes.com/profile/{uri}/" if uri else "https://www.forbes.com/billionaires/"

    company = ""
    fin_assets = p.get("financialAssets") or []
    if isinstance(fin_assets, list) and fin_assets:
        first = fin_assets[0] or {}
        if isinstance(first, dict):
            company = first.get("companyName") or first.get("ticker") or ""

    title = (
        f"{name}: ${net_worth_usd_b}B from {source_of_wealth}"
        if net_worth_usd_b is not None
        else f"{name}: {source_of_wealth}"
    )
    body = (
        f"Rank #{rank}. {name}, {age}, citizen of {country_name}, lives in {residence}. "
        f"Net worth ${net_worth_usd_b}B (Forbes 2024). Source of wealth: {source_of_wealth}. "
        f"Industries: {industries_csv}. Company: {company}. {bio_snippet}"
    )

    return {
        "id": make_id(PLATFORM, "forbes", name, str(rank or "")),
        "platform": PLATFORM,
        "source": "forbes",
        "lang": "en",
        "title": title,
        "body": body,
        "author": name,
        "url": url,
        "country_hint": country_iso2,
        "country_iso": country_iso2,
        "rank": rank,
        "net_worth_usd_billion": net_worth_usd_b,
        "industries": industries,
        "company": company,
        "age": age,
        "gender": gender,
        "source_of_wealth": source_of_wealth,
        "residence": residence,
        "engagement": {"score": 0, "comments": 0, "views": None},
    }


def crawl_forbes(state: State, max_items: int):
    """Yield normalized Forbes billionaire records."""
    print(f"[{PLATFORM}] forbes: fetching list...")
    persons = []
    for url in (FORBES_LIST_URL, FORBES_RTB_URL):
        try:
            data = fetch_json(url)
        except RichlistError as e:
            print(f"  [{PLATFORM}] forbes {url}: {e}")
            continue
        # Forbes wraps under personList.personsLists or just personsLists
        if isinstance(data, dict):
            pl = data.get("personList") or {}
            persons = pl.get("personsLists") or data.get("personsLists") or []
            if not persons and isinstance(data.get("data"), list):
                persons = data["data"]
        elif isinstance(data, list):
            persons = data
        if persons:
            print(f"  [{PLATFORM}] forbes: got {len(persons)} entries from {url}")
            break

    if not persons:
        print(f"  [{PLATFORM}] forbes: no data, skipping")
        return

    yielded = 0
    for p in persons:
        if not isinstance(p, dict):
            continue
        if yielded >= max_items:
            break
        try:
            item = normalize_forbes(p)
        except Exception as e:
            print(f"  [{PLATFORM}] forbes normalize err: {e}")
            continue
        if not item:
            continue
        if state.is_seen(item["id"]):
            continue
        yield item
        yielded += 1
    print(f"  [{PLATFORM}] forbes: yielded {yielded}")


# ============================================================================
# Hurun — china rich list HTML / API
# ============================================================================
def crawl_hurun(state: State, max_items: int):
    """Yield normalized Hurun rich-list records.

    Hurun exposes a JSON-ish backend at /Rank/HsRankDetailsList that returns
    paginated entries. We try that first, then fall back to scraping the HTML
    page if the API misbehaves.
    """
    print(f"[{PLATFORM}] hurun: fetching list...")
    entries = []

    # Try the JSON-ish backend first. Recent Hurun lists are addressed by num.
    # Without knowing the exact list-num, we scan a small set of recent ones.
    candidate_nums = ["ODBYW2024", "ODBYW2023", "ODBYW2022", "LJZ2024", "LJZ2023"]
    for num in candidate_nums:
        if entries:
            break
        for offset in (0, 200, 400):
            try:
                params = {"num": num, "search": "", "offset": offset, "limit": 200}
                data = fetch_json(HURUN_API, params=params)
            except RichlistError as e:
                print(f"  [{PLATFORM}] hurun api {num} off={offset}: {e}")
                break
            if isinstance(data, dict):
                rows = (
                    data.get("rows")
                    or data.get("data")
                    or data.get("list")
                    or []
                )
            elif isinstance(data, list):
                rows = data
            else:
                rows = []
            if not rows:
                break
            entries.extend(rows)
            polite_sleep()
            if len(rows) < 200:
                break

    # Fallback: scrape the HTML rich-list page (parse embedded JSON or table rows)
    if not entries and BeautifulSoup is not None:
        for url, lang in ((HURUN_URL_EN, "en"), (HURUN_URL_ZH, "zh")):
            try:
                html = fetch_html(url)
            except RichlistError as e:
                print(f"  [{PLATFORM}] hurun html {url}: {e}")
                continue
            # Try to find an embedded JSON blob
            m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", html, re.DOTALL)
            if m:
                try:
                    blob = json.loads(m.group(1))
                    rows = []
                    # Walk the blob for any list-of-dicts with 'hs_Rank_Rich_NetWorth' etc.
                    def walk(obj):
                        if isinstance(obj, dict):
                            if any(k.startswith("hs_Rank") for k in obj.keys()):
                                rows.append(obj)
                            for v in obj.values():
                                walk(v)
                        elif isinstance(obj, list):
                            for v in obj:
                                walk(v)
                    walk(blob)
                    if rows:
                        entries.extend(rows)
                        break
                except Exception:
                    pass
            polite_sleep()

    if not entries:
        print(f"  [{PLATFORM}] hurun: no data, skipping")
        return

    print(f"  [{PLATFORM}] hurun: got {len(entries)} entries")
    yielded = 0
    seen_names = set()
    for e in entries:
        if not isinstance(e, dict):
            continue
        if yielded >= max_items:
            break
        # Hurun fields use hs_Rank_Rich_<X> prefix in API responses
        char = e.get("hs_Character") or {}
        if isinstance(char, list) and char:
            char = char[0]
        elif not isinstance(char, dict):
            char = {}

        name_zh = (
            e.get("hs_Rank_Rich_ChaName_Cn")
            or char.get("hs_Character_ChaName_Cn")
            or e.get("name_zh")
            or e.get("name")
            or ""
        )
        name_en = (
            e.get("hs_Rank_Rich_ChaName_En")
            or char.get("hs_Character_ChaName_En")
            or e.get("name_en")
            or ""
        )
        name = name_en or name_zh
        if not name:
            continue
        if name in seen_names:
            continue
        seen_names.add(name)

        rank = e.get("hs_Rank_Rich_Ranking") or e.get("rank")
        wealth_rmb = (
            e.get("hs_Rank_Rich_Wealth")
            or e.get("hs_Rank_Rich_Wealth_Rmb")
            or e.get("wealth_rmb")
        )
        wealth_usd = (
            e.get("hs_Rank_Rich_Wealth_USD")
            or e.get("wealth_usd")
        )
        # Hurun wealth values are in 亿 (100M RMB)
        try:
            wealth_rmb_v = float(wealth_rmb) if wealth_rmb is not None else None
        except (TypeError, ValueError):
            wealth_rmb_v = None
        try:
            wealth_usd_v = float(wealth_usd) if wealth_usd is not None else None
        except (TypeError, ValueError):
            wealth_usd_v = None
        # Convert: prefer USD if given (already in USD billion typically),
        # otherwise approx convert RMB亿 -> USD billion via 7.2 fx and /10
        if wealth_usd_v is not None:
            net_worth_usd_b = round(wealth_usd_v / 10.0, 3) if wealth_usd_v > 100 else round(wealth_usd_v, 3)
        elif wealth_rmb_v is not None:
            # wealth_rmb_v is in 亿 (1e8 RMB) -> USD billion = (v * 1e8) / 7.2 / 1e9
            net_worth_usd_b = round((wealth_rmb_v * 1e8) / 7.2 / 1e9, 3)
        else:
            net_worth_usd_b = None

        age = e.get("hs_Rank_Rich_Age") or char.get("hs_Character_Age") or e.get("age")
        try:
            age = int(age) if age else None
        except (TypeError, ValueError):
            age = None

        company = (
            e.get("hs_Rank_Rich_ComName_Cn")
            or e.get("hs_Rank_Rich_ComName_En")
            or e.get("company")
            or ""
        )
        industry = (
            e.get("hs_Rank_Rich_Industry_Cn")
            or e.get("hs_Rank_Rich_Industry_En")
            or e.get("industry")
            or ""
        )
        headquarters = (
            e.get("hs_Rank_Rich_ComHeadquarters_Cn")
            or e.get("hs_Rank_Rich_ComHeadquarters_En")
            or e.get("headquarters")
            or ""
        )
        nation = (
            e.get("hs_Rank_Rich_Nation_Cn")
            or e.get("hs_Rank_Rich_Nation_En")
            or char.get("hs_Character_NationOfCitizenship_Cn")
            or char.get("hs_Character_NationOfCitizenship_En")
            or "China"
        )
        country_iso2 = country_to_iso2(nation) if nation else "CN"
        if country_iso2 == "??":
            country_iso2 = "CN"

        # Determine lang based on which name we're using
        lang = "zh" if not name_en else "en"

        title = (
            f"{name}: ${net_worth_usd_b}B from {industry}"
            if net_worth_usd_b is not None
            else f"{name}: {industry}"
        )
        industries_list = [s.strip() for s in str(industry).split(",") if s.strip()]
        industries_csv = ", ".join(industries_list)
        body = (
            f"Rank #{rank}. {name}, {age}, citizen of {nation}, lives in {headquarters}. "
            f"Net worth ${net_worth_usd_b}B (Hurun). Source of wealth: {industry}. "
            f"Industries: {industries_csv}. Company: {company}."
        )

        item = {
            "id": make_id(PLATFORM, "hurun", name, str(rank or "")),
            "platform": PLATFORM,
            "source": "hurun",
            "lang": lang,
            "title": title,
            "body": body,
            "author": name,
            "url": HURUN_URL_EN if lang == "en" else HURUN_URL_ZH,
            "country_hint": country_iso2,
            "country_iso": country_iso2,
            "rank": rank,
            "net_worth_usd_billion": net_worth_usd_b,
            "industries": industries_list,
            "company": company,
            "age": age,
            "source_of_wealth": industry,
            "residence": headquarters,
            "engagement": {"score": 0, "comments": 0, "views": None},
        }
        if state.is_seen(item["id"]):
            continue
        yield item
        yielded += 1
    print(f"  [{PLATFORM}] hurun: yielded {yielded}")


# ============================================================================
# Bloomberg — Billionaires Index HTML page
# ============================================================================
def crawl_bloomberg(state: State, max_items: int):
    """Yield normalized Bloomberg Billionaires Index records."""
    print(f"[{PLATFORM}] bloomberg: fetching list...")
    if BeautifulSoup is None:
        print(f"  [{PLATFORM}] bloomberg: bs4 not installed, skipping")
        return
    try:
        html = fetch_html(BLOOMBERG_URL)
    except RichlistError as e:
        print(f"  [{PLATFORM}] bloomberg: {e}")
        return

    soup = BeautifulSoup(html, "html.parser")
    rows = []

    # Bloomberg renders the ranking table with <tr> rows under a tbody, with
    # columns: rank, name, total_net_worth, last_change, ytd_change, country, industry
    table = soup.find("table")
    if table:
        body = table.find("tbody") or table
        for tr in body.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if not cells or len(cells) < 5:
                continue
            rows.append(cells)

    # Fallback: search divs styled as a rank list (Bloomberg sometimes uses
    # custom <div class="table__row">). We accept either shape.
    if not rows:
        for div in soup.select("[class*=table__row], [class*=row__cell]"):
            txt = div.get_text(" | ", strip=True)
            parts = [p.strip() for p in txt.split("|") if p.strip()]
            if len(parts) >= 5:
                rows.append(parts)

    if not rows:
        print(f"  [{PLATFORM}] bloomberg: parser found 0 rows")
        return
    print(f"  [{PLATFORM}] bloomberg: got {len(rows)} rows")

    yielded = 0
    for cells in rows:
        if yielded >= max_items:
            break
        # Defensive: pull fields by position
        rank_raw = cells[0] if len(cells) > 0 else ""
        name = cells[1] if len(cells) > 1 else ""
        net_worth_raw = cells[2] if len(cells) > 2 else ""
        last_change = cells[3] if len(cells) > 3 else ""
        ytd_change = cells[4] if len(cells) > 4 else ""
        country_name = cells[5] if len(cells) > 5 else ""
        industry = cells[6] if len(cells) > 6 else ""

        if not name or not re.search(r"[A-Za-z]", name):
            continue

        # Parse rank
        rank = None
        m = re.search(r"\d+", rank_raw)
        if m:
            try:
                rank = int(m.group(0))
            except ValueError:
                rank = None

        # Parse net worth — formatted as "$211B" or "$211.0B" or similar
        net_worth_usd_b = None
        m = re.search(r"\$?\s*([\d,]+(?:\.\d+)?)\s*([BMT]?)", net_worth_raw)
        if m:
            try:
                v = float(m.group(1).replace(",", ""))
                suf = (m.group(2) or "B").upper()
                if suf == "T":
                    v *= 1000.0
                elif suf == "M":
                    v /= 1000.0
                net_worth_usd_b = round(v, 3)
            except ValueError:
                pass

        country_iso2 = country_to_iso2(country_name)
        industries_list = [s.strip() for s in industry.split("&") if s.strip()] or (
            [industry] if industry else []
        )
        industries_csv = ", ".join(industries_list)

        title = (
            f"{name}: ${net_worth_usd_b}B from {industry}"
            if net_worth_usd_b is not None
            else f"{name}: {industry}"
        )
        body_text = (
            f"Rank #{rank}. {name}, citizen of {country_name}. "
            f"Net worth ${net_worth_usd_b}B (Bloomberg Billionaires Index). "
            f"Source of wealth: {industry}. Industries: {industries_csv}. "
            f"Last change: {last_change}. YTD change: {ytd_change}."
        )

        item = {
            "id": make_id(PLATFORM, "bloomberg", name, str(rank or "")),
            "platform": PLATFORM,
            "source": "bloomberg",
            "lang": "en",
            "title": title,
            "body": body_text,
            "author": name,
            "url": BLOOMBERG_URL,
            "country_hint": country_iso2,
            "country_iso": country_iso2,
            "rank": rank,
            "net_worth_usd_billion": net_worth_usd_b,
            "industries": industries_list,
            "company": "",
            "age": None,
            "source_of_wealth": industry,
            "residence": country_name,
            "last_change": last_change,
            "ytd_change": ytd_change,
            "engagement": {"score": 0, "comments": 0, "views": None},
        }
        if state.is_seen(item["id"]):
            continue
        yield item
        yielded += 1
    print(f"  [{PLATFORM}] bloomberg: yielded {yielded}")


# ============================================================================
# run() — fail-soft per source
# ============================================================================
def run():
    state = State(PLATFORM)
    preload_seen(state, PLATFORM, key_field="id")
    items_added = 0

    sources = [
        ("forbes", crawl_forbes),
        ("hurun", crawl_hurun),
        ("bloomberg", crawl_bloomberg),
    ]

    try:
        for label, fn in sources:
            if items_added >= PER_PLATFORM_LIMIT:
                break
            remaining = PER_PLATFORM_LIMIT - items_added
            try:
                for item in fn(state, remaining):
                    if items_added >= PER_PLATFORM_LIMIT:
                        break
                    append_jsonl(item, PLATFORM, RAW_DIR)
                    state.mark_seen(item["id"])
                    items_added += 1
                    if items_added % 50 == 0:
                        print(f"  [{PLATFORM}] +{items_added} so far")
                    state.maybe_save(every=10)
            except Exception as e:
                print(f"[{PLATFORM}] {label} fail-soft: {type(e).__name__}: {e}")
            state.save()
            polite_sleep()
    finally:
        state.save(force=True)

    print(f"[{PLATFORM}] done, +{items_added} items this run")


if __name__ == "__main__":
    run()
