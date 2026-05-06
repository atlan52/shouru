"""Gehalt.de crawler — German salary database (role × industry × region).

Strategy:
  - Public, no auth. Pure requests + BeautifulSoup.
  - URL pattern: https://www.gehalt.de/einkommen/suche/{role-slug}
                 https://www.gehalt.de/einkommen/suche/{role-slug}/{region-slug}
                 (region-specific page, when available)
  - Per role page: extract role label, mean €/yr, percentiles (25/50/75),
    sample count, region (Bundesland), narrative commentary.
  - Country: "DE", lang: "de".

Honors SMOKE_TEST (limit to ~10 roles when smoke).
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

BASE = "https://www.gehalt.de"
SEARCH_URL = BASE + "/einkommen/suche/{slug}"
REGION_URL = BASE + "/einkommen/suche/{slug}/{region}"

# 16 German Bundesländer (region slugs as gehalt.de uses them).
REGIONS = [
    "baden-wuerttemberg", "bayern", "berlin", "brandenburg",
    "bremen", "hamburg", "hessen", "mecklenburg-vorpommern",
    "niedersachsen", "nordrhein-westfalen", "rheinland-pfalz",
    "saarland", "sachsen", "sachsen-anhalt", "schleswig-holstein",
    "thueringen",
]

# ~50 role slugs spanning industries: software, finance, healthcare,
# education, blue-collar, sales, government, science, trades, retail.
ROLES: list[str] = [
    # Tech / engineering
    "softwareentwickler", "data-scientist", "datenwissenschaftler",
    "it-consultant", "systemadministrator", "wirtschaftsinformatiker",
    "elektroingenieur", "maschinenbauingenieur", "ingenieur",
    "bauingenieur", "chemieingenieur",
    # Finance / business
    "controller", "buchhalter", "steuerberater", "finanzberater",
    "bankkaufmann", "wirtschaftspruefer", "versicherungskaufmann",
    "investment-banker",
    # Healthcare
    "arzt", "facharzt", "krankenschwester", "pflegefachkraft",
    "altenpfleger", "apotheker", "physiotherapeut", "zahnarzt",
    # Education / academia
    "lehrer", "grundschullehrer", "hochschullehrer", "erzieher",
    # Sales / marketing
    "vertriebsmitarbeiter", "key-account-manager", "marketing-manager",
    "produktmanager",
    # Blue-collar / trades
    "elektriker", "schreiner", "kfz-mechatroniker", "maurer",
    "lkw-fahrer", "industriemechaniker", "anlagenmechaniker",
    # Government / public
    "polizist", "verwaltungsangestellter", "beamter",
    # Service / retail / logistics
    "einzelhandelskaufmann", "logistik-mitarbeiter", "koch",
    "hotelfachmann",
    # Science / research / law
    "rechtsanwalt", "biologe", "chemiker", "psychologe",
]

BOT_MARKERS = ("captcha", "are you a human", "access denied", "unusual traffic", "bot detection")


class GehaltDeError(Exception):
    pass


def _gd_headers() -> dict:
    h = default_headers(accept_lang="de-DE,de;q=0.9,en;q=0.5")
    h["Referer"] = BASE + "/"
    return h


def fetch_html(url: str, timeout: int = 25) -> str:
    try:
        r = requests.get(url, headers=_gd_headers(), timeout=timeout, allow_redirects=True)
        if r.status_code in (403, 429):
            raise GehaltDeError(f"{r.status_code} on {url}")
        if r.status_code == 404:
            raise GehaltDeError(f"404 on {url}")
        if r.status_code != 200:
            raise GehaltDeError(f"status {r.status_code} on {url}")
        body = r.text or ""
        low = body.lower()
        if any(m in low for m in BOT_MARKERS):
            raise GehaltDeError("bot-block / captcha on page")
        return body
    except GehaltDeError:
        raise
    except Exception as e:
        raise GehaltDeError(str(e))


# ============================================================================
# German euro number parsing — "65.000 €", "55.345,67 €", "Ø 60.000".
# ============================================================================
_EUR_RE = re.compile(r"([\d]{1,3}(?:[\.\s][\d]{3})+(?:,\d+)?|[\d]{4,6}(?:,\d+)?)")


def _to_eur(raw: str) -> int | None:
    if not raw:
        return None
    s = raw.strip()
    s = s.replace("€", "").replace("EUR", "").replace(" ", " ").replace(" ", "").strip()
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(".", "")
    try:
        v = float(s)
    except ValueError:
        return None
    if v <= 0 or v > 5_000_000:
        return None
    return int(v)


def _first_eur(text: str) -> int | None:
    if not text:
        return None
    m = _EUR_RE.search(text)
    if not m:
        return None
    return _to_eur(m.group(1))


# ============================================================================
# JSON-LD / NEXT_DATA extraction — gehalt.de exposes structured Occupation /
# AggregateOffer data in JSON-LD on most role pages. Try this first.
# ============================================================================
def _iter_jsonld(html: str):
    if not html:
        return
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
            try:
                yield json.loads(raw.rstrip(","))
            except Exception:
                continue


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


def _walk_jsonld_for_salary(obj, found: dict):
    """Walk JSON-LD looking for Occupation / MonetaryAmountDistribution.

    Mutates `found` with keys: role, mean, p25, p50, p75, samples.
    """
    if isinstance(obj, dict):
        t = obj.get("@type") or obj.get("type") or ""
        if t in ("Occupation", "JobPosting", "WorkRole"):
            name = obj.get("name") or obj.get("title")
            if name and not found.get("role"):
                found["role"] = str(name)[:160]
            sal = obj.get("estimatedSalary") or obj.get("baseSalary") or obj.get("salary")
            if isinstance(sal, list):
                # Sometimes a list of MonetaryAmount entries
                for s in sal:
                    _walk_jsonld_for_salary(s, found)
            elif isinstance(sal, dict):
                _walk_jsonld_for_salary(sal, found)
        if t == "MonetaryAmountDistribution":
            med = obj.get("median")
            p25 = obj.get("percentile25")
            p75 = obj.get("percentile75")
            if isinstance(med, (int, float)) and not found.get("p50"):
                found["p50"] = int(med)
                found.setdefault("mean", int(med))
            if isinstance(p25, (int, float)):
                found["p25"] = int(p25)
            if isinstance(p75, (int, float)):
                found["p75"] = int(p75)
        if t == "MonetaryAmount":
            v = obj.get("value")
            if isinstance(v, (int, float)) and not found.get("mean"):
                found["mean"] = int(v)
        for v in obj.values():
            _walk_jsonld_for_salary(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _walk_jsonld_for_salary(v, found)


def _walk_next_for_salary(obj, found: dict):
    """Walk Next.js __NEXT_DATA__ for known shapes used by gehalt.de.

    Looks for keys like avg/median/p25/p75/sampleSize/n/count.
    """
    if isinstance(obj, dict):
        # Try direct hits first.
        for k_avg in ("mean", "average", "avg", "averageSalary", "durchschnitt"):
            v = obj.get(k_avg)
            if isinstance(v, (int, float)) and not found.get("mean"):
                found["mean"] = int(v)
        for k_med in ("median", "p50", "medianSalary"):
            v = obj.get(k_med)
            if isinstance(v, (int, float)) and not found.get("p50"):
                found["p50"] = int(v)
        for k_p25 in ("p25", "percentile25", "lowerQuartile"):
            v = obj.get(k_p25)
            if isinstance(v, (int, float)) and not found.get("p25"):
                found["p25"] = int(v)
        for k_p75 in ("p75", "percentile75", "upperQuartile"):
            v = obj.get(k_p75)
            if isinstance(v, (int, float)) and not found.get("p75"):
                found["p75"] = int(v)
        for k_n in ("sampleSize", "samples", "count", "n", "datapoints"):
            v = obj.get(k_n)
            if isinstance(v, (int, float)) and not found.get("samples"):
                found["samples"] = int(v)
        for v in obj.values():
            _walk_next_for_salary(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _walk_next_for_salary(v, found)


# ============================================================================
# DOM scraping fallback
# ============================================================================
def _dom_salary(html: str) -> dict:
    """Best-effort DOM scrape for mean/percentiles/sample count + commentary."""
    found: dict = {}
    if BeautifulSoup is None or not html:
        return found
    soup = BeautifulSoup(html, "html.parser")

    # Page title / role h1
    h1 = soup.find("h1")
    if h1:
        found["role_h1"] = h1.get_text(" ", strip=True)[:200]

    # Find euro figures appearing near labels like "Median", "Durchschnitt",
    # "25 %", "75 %", "Mittelwert".
    txt = soup.get_text(" ", strip=True)
    if not txt:
        return found

    def _find_near(label_pattern: str) -> int | None:
        m = re.search(label_pattern + r"[^\d€]{0,40}([\d\.\s]{4,}(?:,\d+)?)\s*€?", txt, re.I)
        if not m:
            return None
        return _to_eur(m.group(1))

    for lab, key in [
        (r"Mittelwert|Durchschnitt|durchschnittliches?", "mean"),
        (r"Median", "p50"),
        (r"unteres Quartil|25\s*%|25\.\s*Perzentil", "p25"),
        (r"oberes Quartil|75\s*%|75\.\s*Perzentil", "p75"),
    ]:
        v = _find_near(lab)
        if v and not found.get(key):
            found[key] = v

    # Sample count: "basierend auf 1.234 Datensätzen" / "1.234 Gehaltsangaben"
    m = re.search(
        r"(?:basierend auf|aus|mit)?\s*([\d\.\s]+)\s*(?:Datens[äa]tzen?|Gehaltsangaben?|Datenpunkten?|Stichproben?)",
        txt, re.I,
    )
    if m:
        try:
            n_raw = m.group(1).replace(".", "").replace(" ", "").strip()
            found["samples"] = int(n_raw)
        except ValueError:
            pass

    # Commentary block — first sizable <p> on the page about the role.
    paras = []
    for p in soup.find_all("p"):
        t = p.get_text(" ", strip=True)
        if 60 <= len(t) <= 1200:
            paras.append(t)
        if len(paras) >= 3:
            break
    if paras:
        found["commentary"] = " ".join(paras)[:3000]

    return found


# ============================================================================
# Per-role / per-region orchestration
# ============================================================================
def _slug_to_label(slug: str) -> str:
    return slug.replace("-", " ").title()


def _region_to_label(slug: str) -> str:
    if not slug:
        return ""
    return slug.replace("-", " ").replace("ue", "ü").title()


def _emit(role_slug: str, region_slug: str, url: str, data: dict,
          state: State) -> int:
    role_label = data.get("role") or data.get("role_h1") or _slug_to_label(role_slug)
    region_label = _region_to_label(region_slug) if region_slug else "Deutschland"
    mean = data.get("mean") or data.get("p50")
    p25 = data.get("p25")
    p50 = data.get("p50")
    p75 = data.get("p75")
    samples = int(data.get("samples", 0) or 0)
    commentary = (data.get("commentary") or "").strip()

    if not mean and not (p25 or p50 or p75):
        return 0

    rid = make_id("gehalt_de", role_slug, region_slug or "DE", mean or p50)
    if state.is_seen(rid):
        return 0

    n_disp = f", samples={samples}" if samples else ""
    body = f"{role_label} {region_label} mean €{mean:,}/yr{n_disp}" if mean else \
           f"{role_label} {region_label} median €{p50 or 0:,}/yr{n_disp}"

    item = {
        "id": rid,
        "raw_id": f"{role_slug}:{region_slug or 'DE'}",
        "platform": "gehalt_de",
        "kind": "salary",
        "lang": "de",
        "country_hint": "DE",
        "role": role_label,
        "role_slug": role_slug,
        "region": region_label,
        "region_slug": region_slug,
        "title": f"{role_label} Gehalt — {region_label}",
        "body": body,
        "body_full": commentary or body,
        "mean_eur_yr": int(mean) if mean else None,
        "median_eur_yr": int(p50) if p50 else None,
        "percentiles": {
            "p25": int(p25) if p25 else None,
            "p50": int(p50) if p50 else None,
            "p75": int(p75) if p75 else None,
        },
        "samples": samples,
        "url": url,
        "engagement": {"score": 0, "comments": 0},
    }
    append_jsonl(item, "gehalt_de", RAW_DIR)
    state.mark_seen(rid)
    return 1


def crawl_role(role_slug: str, state: State, *, do_regions: bool = True,
               max_regions: int = 4) -> int:
    added = 0

    # 1) Nationwide page
    url = SEARCH_URL.format(slug=role_slug)
    try:
        html = fetch_html(url)
    except GehaltDeError as e:
        print(f"  [gehalt_de] {role_slug} err: {e}")
        return 0

    found: dict = {}
    for blob in _iter_jsonld(html):
        _walk_jsonld_for_salary(blob, found)
    if not found.get("mean") and not found.get("p50"):
        nd = _next_data(html)
        if nd:
            _walk_next_for_salary(nd, found)
    # DOM scrape always supplements (commentary + missing percentiles)
    dom = _dom_salary(html)
    for k, v in dom.items():
        found.setdefault(k, v)

    added += _emit(role_slug, "", url, found, state)
    polite_sleep()

    # 2) Per-region pages — sample first N (smoke trims further)
    if not do_regions:
        return added
    for region in REGIONS[:max_regions]:
        if state.is_kw_done(f"{role_slug}:{region}"):
            continue
        url_r = REGION_URL.format(slug=role_slug, region=region)
        try:
            html_r = fetch_html(url_r)
        except GehaltDeError as e:
            print(f"  [gehalt_de] {role_slug}/{region} err: {e}")
            state.mark_kw_done(f"{role_slug}:{region}")
            continue
        f_r: dict = {}
        for blob in _iter_jsonld(html_r):
            _walk_jsonld_for_salary(blob, f_r)
        if not f_r.get("mean") and not f_r.get("p50"):
            nd = _next_data(html_r)
            if nd:
                _walk_next_for_salary(nd, f_r)
        dom_r = _dom_salary(html_r)
        for k, v in dom_r.items():
            f_r.setdefault(k, v)
        added += _emit(role_slug, region, url_r, f_r, state)
        state.mark_kw_done(f"{role_slug}:{region}")
        state.maybe_save(every=5)
        polite_sleep()

    return added


def run():
    state = State("gehalt_de")
    preload_seen(state, "gehalt_de", key_field="id")
    items_added = 0
    budget = TimeBudget(PLATFORM_TIME_BUDGET_SEC)

    smoke = bool(os.environ.get("SMOKE_TEST"))
    roles = ROLES[:10] if smoke else ROLES
    max_regions = 1 if smoke else 6

    try:
        for role_slug in roles:
            if budget.expired():
                print("[gehalt_de] time budget expired")
                break
            if state.is_kw_done(role_slug):
                continue
            print(f"[gehalt_de] role={role_slug!r}")
            try:
                got = crawl_role(role_slug, state, do_regions=True,
                                 max_regions=max_regions)
            except Exception as e:
                print(f"  [gehalt_de] {role_slug} fatal: {e}")
                state.save()
                time.sleep(3)
                continue
            items_added += got
            print(f"  [gehalt_de] +{got} (total {items_added})")
            state.mark_kw_done(role_slug)
            state.save()
            polite_sleep()
            if items_added >= PER_PLATFORM_LIMIT:
                print(f"[gehalt_de] hit PER_PLATFORM_LIMIT={PER_PLATFORM_LIMIT}")
                break
    finally:
        state.save(force=True)

    print(f"[gehalt_de] done, +{items_added} items this run")


if __name__ == "__main__":
    run()
