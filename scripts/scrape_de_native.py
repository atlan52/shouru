"""Scrape gehalt.de + kununu.com — German salary data + employee reviews.

Outputs:
  data/raw/gehalt_native_<YYYYMMDD>.jsonl
  data/raw/kununu_native_<YYYYMMDD>.jsonl
"""
import datetime as _dt
import hashlib
import json
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

OUT_DIR = "/Users/jan/sen/code/spider/shouru/data/raw"
TODAY = _dt.datetime.now().strftime("%Y%m%d")
GEHALT_OUT = os.path.join(OUT_DIR, f"gehalt_native_{TODAY}.jsonl")
KUNUNU_OUT = os.path.join(OUT_DIR, f"kununu_native_{TODAY}.jsonl")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

POLITE_SEC = 1.5

GEHALT_ROLES = [
    "softwareentwickler", "datenwissenschaftler", "ingenieur",
    "krankenschwester", "lehrer",
    "arzt", "anwalt", "marketingmanager", "vertriebsleiter",
    "projektmanager",
    "buchhalter", "steuerberater", "architekt", "mechaniker",
    "elektriker",
    "pflegefachkraft", "finanzberater", "controller", "designer",
    "redakteur",
    "frisor", "koch", "kellner", "busfahrer", "lkw-fahrer",
    "bankkaufmann", "versicherungskaufmann", "immobilienmakler",
    "einzelhandelskaufmann", "polizist",
]

KUNUNU_COMPANIES = [
    "siemens", "sap", "allianz", "bmw", "mercedes-benz-group",
    "volkswagen", "audi", "deutsche-bank", "commerzbank",
    "deutsche-telekom",
    "vodafone-deutschland", "microsoft-deutschland", "lufthansa",
    "ikea-deutschland", "edeka",
    "rewe", "aldi-sued", "lidl", "dm-drogerie-markt", "otto",
    "henkel", "bayer", "basf", "eon", "deutsche-bahn",
]


def md5_id(*parts) -> str:
    h = hashlib.md5()
    for p in parts:
        h.update(("|" + str(p)).encode("utf-8", errors="replace"))
    return h.hexdigest()


def fetch(url: str, retries: int = 2, timeout: int = 25):
    last = None
    for i in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout,
                             allow_redirects=True)
            if r.status_code == 200 and r.text:
                low = r.text.lower()
                if any(m in low for m in ("captcha", "are you a human",
                                          "access denied",
                                          "unusual traffic")):
                    last = "bot-block"
                    return None
                return r.text
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(2 + i * 2)
    print(f"  [fetch fail] {url}: {last}", file=sys.stderr)
    return None


def to_eur(raw):
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        v = float(raw)
        if v <= 0 or v > 5_000_000:
            return None
        return int(v)
    s = str(raw).strip().replace("\xa0", "").replace(" ", "")
    s = s.replace("€", "").replace("EUR", "").strip()
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


# ---------- gehalt.de ----------
GEHALT_BASE = "https://www.gehalt.de/einkommen/suche/{slug}"


def _iter_jsonld(html):
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html or "", re.DOTALL | re.IGNORECASE,
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


def _next_data(html):
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


def _walk_jsonld(obj, found):
    if isinstance(obj, dict):
        t = obj.get("@type") or obj.get("type") or ""
        if t in ("Occupation", "JobPosting", "WorkRole"):
            name = obj.get("name") or obj.get("title")
            if name and not found.get("role"):
                found["role"] = str(name)[:160]
            sal = (obj.get("estimatedSalary") or obj.get("baseSalary")
                   or obj.get("salary"))
            if isinstance(sal, list):
                for s in sal:
                    _walk_jsonld(s, found)
            elif isinstance(sal, dict):
                _walk_jsonld(sal, found)
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
            _walk_jsonld(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _walk_jsonld(v, found)


def _walk_next(obj, found):
    if isinstance(obj, dict):
        for k_avg in ("mean", "average", "avg", "averageSalary",
                      "durchschnitt"):
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
        for k_n in ("sampleSize", "samples", "count", "n", "datapoints",
                    "datasets"):
            v = obj.get(k_n)
            if isinstance(v, (int, float)) and not found.get("samples"):
                found["samples"] = int(v)
        for v in obj.values():
            _walk_next(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _walk_next(v, found)


def _dom_gehalt(html):
    found = {}
    if not html:
        return found
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if h1:
        found["role_h1"] = h1.get_text(" ", strip=True)[:200]
    txt = soup.get_text(" ", strip=True)
    if not txt:
        return found

    def _find_near(label_pattern):
        m = re.search(label_pattern + r"[^\d€]{0,40}([\d\.\s]{4,}(?:,\d+)?)\s*€?",
                      txt, re.I)
        if not m:
            return None
        return to_eur(m.group(1))

    for lab, key in [
        (r"Mittelwert|Durchschnitt|durchschnittliches?", "mean"),
        (r"Median", "p50"),
        (r"unteres Quartil|25\s*%|25\.\s*Perzentil", "p25"),
        (r"oberes Quartil|75\s*%|75\.\s*Perzentil", "p75"),
    ]:
        v = _find_near(lab)
        if v and not found.get(key):
            found[key] = v

    m = re.search(
        r"(?:basierend auf|aus|mit)?\s*([\d\.\s]+)\s*"
        r"(?:Datens[äa]tzen?|Gehaltsangaben?|Datenpunkten?|Stichproben?)",
        txt, re.I,
    )
    if m:
        try:
            n_raw = m.group(1).replace(".", "").replace(" ", "").strip()
            found["samples"] = int(n_raw)
        except ValueError:
            pass

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


def _slug_label(slug):
    return slug.replace("-", " ").title()


def scrape_gehalt():
    written = 0
    with open(GEHALT_OUT, "w", encoding="utf-8") as fh:
        for slug in GEHALT_ROLES:
            url = GEHALT_BASE.format(slug=slug)
            print(f"[gehalt] {slug}")
            html = fetch(url)
            if not html:
                time.sleep(POLITE_SEC)
                continue

            found = {}
            for blob in _iter_jsonld(html):
                _walk_jsonld(blob, found)
            if not found.get("mean") and not found.get("p50"):
                nd = _next_data(html)
                if nd:
                    _walk_next(nd, found)
            for k, v in _dom_gehalt(html).items():
                found.setdefault(k, v)

            mean = found.get("mean") or found.get("p50")
            p25 = found.get("p25")
            p50 = found.get("p50")
            p75 = found.get("p75")
            samples = int(found.get("samples", 0) or 0)
            commentary = (found.get("commentary") or "").strip()
            role_label = (found.get("role") or found.get("role_h1")
                          or _slug_label(slug))

            if not mean and not (p25 or p50 or p75) and not commentary:
                print(f"  [gehalt] {slug}: no data extracted")
                time.sleep(POLITE_SEC)
                continue

            mean_s = f"€{mean:,}/Jahr" if mean else "n/a"
            title = f"{role_label} in Deutschland: {mean_s}"

            body_lines = [
                f"Beruf: {role_label}",
                "Land: Deutschland",
            ]
            if mean:
                body_lines.append(
                    f"Durchschnittsgehalt (Mittelwert): "
                    f"{mean:,} EUR/Jahr".replace(",", "."))
            if p50:
                body_lines.append(
                    f"Median: {p50:,} EUR/Jahr".replace(",", "."))
            if p25:
                body_lines.append(
                    f"Unteres Quartil (25%): {p25:,} EUR/Jahr"
                    .replace(",", "."))
            if p75:
                body_lines.append(
                    f"Oberes Quartil (75%): {p75:,} EUR/Jahr"
                    .replace(",", "."))
            if samples:
                body_lines.append(f"Stichprobengröße: {samples} Datensätze")
            if commentary:
                body_lines.append("")
                body_lines.append("Originaltext (gehalt.de):")
                body_lines.append(commentary)

            body = "\n".join(body_lines)

            rid = md5_id("gehalt_de", slug, mean or p50 or 0)
            item = {
                "id": rid,
                "raw_id": slug,
                "platform": "gehalt_de",
                "lang": "de",
                "title": title,
                "body": body,
                "author": "gehalt.de",
                "url": url,
                "country_hint": "DE",
                "mean_eur_yr": int(mean) if mean else None,
                "median_eur_yr": int(p50) if p50 else None,
                "engagement": {"score": 0, "comments": 0},
            }
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
            fh.flush()
            written += 1
            print(f"  [gehalt] +1 mean={mean} p50={p50} samples={samples}")
            time.sleep(POLITE_SEC)
    return written


# ---------- kununu ----------
KUNUNU_BASE = "https://www.kununu.com"


def _walk_salary_nodes(obj, out):
    if isinstance(obj, dict):
        title = (obj.get("jobTitle") or obj.get("profession")
                 or obj.get("title") or obj.get("name") or obj.get("position"))
        sal = (obj.get("salary") or obj.get("salaryRange")
               or obj.get("estimatedSalary"))
        if title and isinstance(sal, dict):
            lo = sal.get("min") or sal.get("minValue") or sal.get("low")
            hi = sal.get("max") or sal.get("maxValue") or sal.get("high")
            mid = (sal.get("median") or sal.get("mid") or sal.get("value")
                   or sal.get("avg"))
            n = (obj.get("count") or obj.get("samples")
                 or obj.get("sampleSize") or 0)
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
                    "min": lo, "mid": mid, "max": hi, "samples": n,
                })
        for v in obj.values():
            _walk_salary_nodes(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_salary_nodes(v, out)


def _walk_review_nodes(obj, out):
    if isinstance(obj, dict):
        text = (obj.get("text") or obj.get("body") or obj.get("comment")
                or obj.get("commentText") or obj.get("review"))
        title_t = obj.get("title") or obj.get("headline") or ""
        rating = obj.get("rating") or obj.get("score") or obj.get("overall")
        helpful = (obj.get("helpfulCount") or obj.get("helpful")
                   or obj.get("likeCount") or 0)
        author = (obj.get("author") or obj.get("createdBy")
                  or obj.get("position") or "")
        if isinstance(text, str) and 80 <= len(text) <= 8000:
            try:
                helpful = (int(helpful)
                           if isinstance(helpful, (int, float)) else 0)
            except Exception:
                helpful = 0
            try:
                rating_v = (float(rating)
                            if isinstance(rating, (int, float)) else None)
            except Exception:
                rating_v = None
            out.append({
                "title": str(title_t)[:200] if title_t else "",
                "body": text.strip()[:5000],
                "rating": rating_v,
                "helpful": helpful,
                "author": str(author)[:120] if author else "",
            })
        for v in obj.values():
            _walk_review_nodes(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_review_nodes(v, out)


def _dom_salaries(html):
    out = []
    if not html:
        return out
    soup = BeautifulSoup(html, "html.parser")
    range_re = re.compile(
        r"([\d]{1,3}(?:[\.\s][\d]{3})*(?:,\d+)?)\s*[-–]\s*"
        r"([\d]{1,3}(?:[\.\s][\d]{3})*(?:,\d+)?)"
    )
    eur_re = re.compile(
        r"€?\s*([\d]{1,3}(?:[\.\s][\d]{3})*(?:,\d+)?)\s*€?"
    )
    samples_re = re.compile(
        r"(\d+)\s*(?:Geh[äa]lter|Geh\.|Datenpunkte|Samples|Bewertungen)",
        re.I,
    )
    for blk in soup.find_all(["div", "li", "tr", "article", "section"]):
        txt = (blk.get_text(" ", strip=True) or "")[:500]
        if "€" not in txt:
            continue
        if not re.search(r"\d[\d\.\s]{2,}", txt):
            continue
        rm = range_re.search(txt)
        lo = mid = hi = None
        if rm:
            lo = to_eur(rm.group(1))
            hi = to_eur(rm.group(2))
            mid = (lo + hi) // 2 if (lo and hi) else None
        else:
            em = eur_re.search(txt)
            if em:
                mid = to_eur(em.group(1))
        if not (lo or mid or hi):
            continue
        head = re.split(r"€|\d{2,}", txt, maxsplit=1)[0]
        role = head.strip().rstrip(":–-").strip()[:160]
        if not role or len(role) < 3:
            continue
        n = 0
        ms = samples_re.search(txt)
        if ms:
            try:
                n = int(ms.group(1))
            except ValueError:
                n = 0
        out.append({"role": role, "min": lo, "mid": mid, "max": hi,
                    "samples": n})
        if len(out) >= 60:
            break
    return out


def _dom_reviews(html):
    out = []
    if not html:
        return out
    soup = BeautifulSoup(html, "html.parser")
    candidates = soup.find_all(
        ["article", "div", "section"],
        class_=re.compile(r"(?i)review|kommentar|card|comment"),
    )
    for blk in candidates:
        txt = blk.get_text(" ", strip=True) or ""
        if len(txt) < 80 or len(txt) > 6000:
            continue
        h = blk.find(["h1", "h2", "h3", "h4", "h5"])
        title_t = h.get_text(" ", strip=True)[:200] if h else ""
        helpful = 0
        m = re.search(r"(?:hilfreich|helpful)[^\d]*([\d,]+)", txt, re.I)
        if m:
            try:
                helpful = int(m.group(1).replace(",", ""))
            except ValueError:
                helpful = 0
        out.append({
            "title": title_t, "body": txt[:5000], "rating": None,
            "helpful": helpful, "author": "",
        })
        if len(out) >= 20:
            break
    return out


def scrape_kununu():
    written = 0
    with open(KUNUNU_OUT, "w", encoding="utf-8") as fh:
        for slug in KUNUNU_COMPANIES:
            sal_url = f"{KUNUNU_BASE}/de/{slug}/gehalt"
            print(f"[kununu] {slug}")

            html = fetch(sal_url)
            sals = []
            company_summary_lines = []
            if html:
                nd = _next_data(html)
                if nd:
                    _walk_salary_nodes(nd, sals)
                if not sals:
                    sals = _dom_salaries(html)
                soup = BeautifulSoup(html, "html.parser")
                for p in soup.find_all(["p", "li"]):
                    t = p.get_text(" ", strip=True)
                    if 80 <= len(t) <= 800:
                        company_summary_lines.append(t)
                    if len(company_summary_lines) >= 4:
                        break
            time.sleep(POLITE_SEC)

            rev_url = f"{KUNUNU_BASE}/de/{slug}/kommentare"
            rhtml = fetch(rev_url)
            revs = []
            if rhtml:
                nd = _next_data(rhtml)
                if nd:
                    _walk_review_nodes(nd, revs)
                if not revs:
                    revs = _dom_reviews(rhtml)
            time.sleep(POLITE_SEC)

            company_label = slug.replace("-", " ").title()
            mid_estimates = [s.get("mid") or s.get("max") or s.get("min")
                             for s in sals]
            mid_estimates = [m for m in mid_estimates if m]
            avg = (sum(mid_estimates) // len(mid_estimates)
                   if mid_estimates else None)

            body_lines = [f"Unternehmen: {company_label}",
                          "Land: Deutschland", ""]
            body_lines.append("Gehälter (kununu.com):")
            if sals:
                for s in sals[:8]:
                    role = s.get("role", "").strip()
                    lo = s.get("min")
                    mid = s.get("mid")
                    hi = s.get("max")
                    n = s.get("samples", 0)
                    if lo and hi:
                        rng = f"{lo:,}–{hi:,} EUR/Jahr".replace(",", ".")
                    elif mid:
                        rng = f"{mid:,} EUR/Jahr".replace(",", ".")
                    elif hi:
                        rng = f"{hi:,} EUR/Jahr".replace(",", ".")
                    elif lo:
                        rng = f"{lo:,} EUR/Jahr".replace(",", ".")
                    else:
                        rng = "n/a"
                    n_disp = f" ({n} Gehälter)" if n else ""
                    body_lines.append(f"  - {role}: {rng}{n_disp}")
            else:
                body_lines.append("  (keine Gehaltsdaten extrahiert)")

            if company_summary_lines:
                body_lines.append("")
                body_lines.append("Beschreibung (kununu, Originaltext):")
                for cs in company_summary_lines[:2]:
                    body_lines.append(f"  {cs}")

            top_author = "kununu.com"
            top_helpful = 0
            if revs:
                body_lines.append("")
                body_lines.append("Mitarbeiterbewertungen (Originaltexte):")
                for rv in revs[:5]:
                    rb = rv.get("body", "").strip()
                    rt = rv.get("title", "").strip()
                    rh = rv.get("helpful", 0) or 0
                    ra = rv.get("author", "").strip() or "Mitarbeiter"
                    if rt:
                        body_lines.append(f"  • [{rt}] ({ra})")
                    else:
                        body_lines.append(f"  • ({ra})")
                    body_lines.append(f"    {rb[:1000]}")
                    if rh > top_helpful:
                        top_helpful = rh
                        top_author = ra or top_author

            body = "\n".join(body_lines)
            avg_disp = (f": Ø €{avg:,}/Jahr" if avg else "")
            title = f"Gehalt bei {company_label}{avg_disp}"

            rid = md5_id("kununu", slug, avg or 0,
                         len(sals), len(revs))
            item = {
                "id": rid,
                "raw_id": slug,
                "platform": "kununu",
                "lang": "de",
                "title": title,
                "body": body,
                "author": top_author,
                "url": sal_url,
                "country_hint": "DE",
                "engagement": {"score": int(top_helpful), "comments": 0},
            }
            if not (sals or revs or company_summary_lines):
                print(f"  [kununu] {slug}: no data extracted")
                continue
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
            fh.flush()
            written += 1
            print(f"  [kununu] +1 sals={len(sals)} revs={len(revs)} "
                  f"summary={len(company_summary_lines)} avg={avg}")
    return written


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"== gehalt.de -> {GEHALT_OUT}")
    n_g = scrape_gehalt()
    print(f"== kununu.com -> {KUNUNU_OUT}")
    n_k = scrape_kununu()
    print(f"\nDONE: gehalt={n_g} lines, kununu={n_k} lines")


if __name__ == "__main__":
    main()
