"""MENA / GCC / Turkey / Arabic-language native crawlers.

Targets:
  Job boards (GCC + ME + EG + TR):
    - Bayt.com (per-country)
    - GulfTalent
    - Naukrigulf
    - WUZZUF (Egypt)
    - Forsetak (Saudi)
    - Kariyer.net (Turkey)
  Arabic forums / Q&A:
    - Eqtsadi.com
    - Hawamer.com
    - Mawdoo3.com
    - SyrianForum.org
  Turkish forums:
    - Eksisozluk
    - DonanimHaber forum

Logic:
  - 1-3 list pages per site -> grab detail links -> fetch detail title + body + salary
  - Lang-keyword filter (ar / tr / en GCC expat)
  - Polite ~1.5s sleep
  - Skip 4xx/5xx; bail on Cloudflare challenge.
  - Multiple JSONL outputs under data/raw/<platform>_native_<DAY>.jsonl
  - Schema mirrors r_mexico_native.

Run from repo root:
  .venv/bin/python scripts/mena_jobs_forums.py
"""
import json
import hashlib
import re
import time
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, quote

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

UA_BROWSER = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

HDR_AR = {
    "User-Agent": UA_BROWSER,
    "Accept-Language": "ar,ar-SA;q=0.9,en;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
HDR_TR = {
    "User-Agent": UA_BROWSER,
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
HDR_GULF_EN = {
    "User-Agent": UA_BROWSER,
    "Accept-Language": "en-AE,en;q=0.9,ar;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

DAY = datetime.now().strftime("%Y%m%d")
RAW = Path("data/raw")
RAW.mkdir(parents=True, exist_ok=True)

# Keyword filters
KW_AR = ["راتب", "دخل", "أجر", "مكافأة", "تقاعد", "معاش", "عمل حر", "مرتب", "رواتب"]
KW_TR = [
    "maaş",
    "gelir",
    "kazan",
    "asgari ücret",
    "asgari",
    "prim",
    "freelance",
    "ücret",
]
KW_EN_GULF = [
    "salary",
    "package",
    "expat",
    "tax-free",
    "AED",
    "SAR",
    "KWD",
    "QAR",
    "OMR",
    "BHD",
]

# Currency-bearing regex for arabic / latin scripts
CUR_RE = re.compile(
    r"(?:ر\.س|ر\.\s?س|ج\.م|د\.إ|د\.\s?إ|د\.ك|ر\.ع|ر\.ق|د\.ب|"
    r"AED|SAR|KWD|QAR|OMR|BHD|EGP|EUR|USD|TRY|TL|₺)\s*[\d\.,]+"
    r"|[\d\.,]+\s*(?:ر\.س|ر\.\s?س|ج\.م|د\.إ|د\.\s?إ|د\.ك|ر\.ع|ر\.ق|د\.ب|"
    r"AED|SAR|KWD|QAR|OMR|BHD|EGP|EUR|USD|TRY|TL|₺)",
    re.I,
)

CLOUDFLARE_HINTS = (
    "Just a moment...",
    "Attention Required! | Cloudflare",
    "cf-browser-verification",
    "cf_chl_opt",
)


def md5_16(*parts):
    return hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()[:16]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append(path: Path, obj: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def polite(low=1.2, high=1.8):
    time.sleep(random.uniform(low, high))


def load_seen(path: Path):
    seen = set()
    if path.exists():
        for line in path.open():
            try:
                seen.add(json.loads(line)["id"])
            except Exception:
                pass
    return seen


def kw_match(text: str, kws):
    t = text.lower()
    return [k for k in kws if k.lower() in t]


def find_salary(text: str):
    m = CUR_RE.search(text or "")
    return m.group(0).strip() if m else ""


def is_cloudflare(html: str):
    return any(h in html for h in CLOUDFLARE_HINTS)


def safe_get(url, headers, timeout=25, label=""):
    """Return (status, text) or (None, '') on hard fail / cloudflare."""
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
    except Exception as e:
        print(f"[{label}] GET err {url}: {e}")
        return None, ""
    if r.status_code >= 400:
        print(f"[{label}] {r.status_code} {url}")
        return r.status_code, ""
    if is_cloudflare(r.text):
        print(f"[{label}] cloudflare challenge at {url} - aborting site")
        return "cf", ""
    return r.status_code, r.text


# ---------------------------------------------------------------------------
# 1. Bayt.com (UAE / KSA / Kuwait / Qatar / Bahrain / Oman)
# ---------------------------------------------------------------------------

OUT_BAYT = RAW / f"bayt_native_{DAY}.jsonl"

BAYT_COUNTRIES = [
    ("uae", "AE"),
    ("saudi-arabia", "SA"),
    ("kuwait", "KW"),
    ("qatar", "QA"),
    ("bahrain", "BH"),
    ("oman", "OM"),
]
BAYT_ROLES = [
    "software-engineer",
    "accountant",
    "nurse",
    "doctor",
    "sales",
    "marketing-manager",
    "civil-engineer",
]


def parse_bayt_list(html, base):
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("li[data-js-job], li.has-pointer-d, h2 a[href*='/jobs/']")
    out = []
    seen = set()
    for c in cards:
        a = c if c.name == "a" else c.select_one("a[href*='/jobs/']")
        if not a:
            continue
        href = a.get("href", "")
        if not href:
            continue
        full = urljoin(base, href)
        if full in seen:
            continue
        seen.add(full)
        title = a.get_text(" ", strip=True)
        out.append((title, full))
    return out


def fetch_bayt_detail(url):
    status, html = safe_get(url, HDR_GULF_EN, label="bayt-detail")
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    # Try JSON-LD JobPosting first
    title = ""
    desc = ""
    sal = ""
    company = ""
    location = ""
    for s in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            j = json.loads(s.string or "{}")
            if isinstance(j, list):
                for it in j:
                    if isinstance(it, dict) and it.get("@type") == "JobPosting":
                        j = it
                        break
            if isinstance(j, dict) and j.get("@type") == "JobPosting":
                title = j.get("title") or title
                desc = j.get("description") or desc
                bs = j.get("baseSalary") or {}
                if isinstance(bs, dict):
                    v = bs.get("value") or {}
                    if isinstance(v, dict):
                        mn = v.get("minValue")
                        mx = v.get("maxValue")
                        cu = bs.get("currency", "")
                        if mn or mx:
                            sal = f"{mn or ''}-{mx or ''} {cu}".strip(" -")
                org = j.get("hiringOrganization") or {}
                if isinstance(org, dict):
                    company = org.get("name", "") or ""
                loc = j.get("jobLocation") or {}
                if isinstance(loc, list) and loc:
                    loc = loc[0]
                if isinstance(loc, dict):
                    addr = loc.get("address") or {}
                    if isinstance(addr, dict):
                        location = ", ".join(
                            x
                            for x in [
                                addr.get("addressLocality"),
                                addr.get("addressRegion"),
                                addr.get("addressCountry"),
                            ]
                            if x
                        )
        except Exception:
            continue
    if not desc:
        d = (
            soup.select_one("[class*=job-description]")
            or soup.select_one("section.card")
            or soup.select_one("main")
        )
        if d:
            desc = d.get_text(" ", strip=True)
    if not title:
        h = soup.select_one("h1")
        if h:
            title = h.get_text(" ", strip=True)
    # description may be HTML in JSON-LD
    if "<" in desc and ">" in desc:
        desc = BeautifulSoup(desc, "html.parser").get_text(" ", strip=True)
    if not sal:
        sal = find_salary(desc) or find_salary(soup.get_text(" ", strip=True))
    return {
        "title": title,
        "description": desc[:5000],
        "salary": sal,
        "company": company,
        "location": location,
    }


def crawl_bayt():
    seen = load_seen(OUT_BAYT)
    n = 0
    for cslug, cc in BAYT_COUNTRIES:
        for role in BAYT_ROLES:
            url = f"https://www.bayt.com/en/{cslug}/jobs/{role}-jobs/"
            status, html = safe_get(url, HDR_GULF_EN, label=f"bayt-{cc}")
            if status == "cf":
                print("[bayt] cloudflare; abandoning bayt entirely")
                return n
            if not html:
                polite()
                continue
            cards = parse_bayt_list(html, url)
            picked = 0
            for title, link in cards[:6]:
                rid = md5_16("bayt", link)
                if rid in seen:
                    continue
                detail = fetch_bayt_detail(link)
                polite()
                if not detail:
                    continue
                full_title = detail["title"] or title
                body = detail["description"]
                blob = f"{full_title}\n{body}"
                hits = kw_match(blob, KW_EN_GULF + KW_AR)
                # If no kw and no salary, accept anyway (job listing implies income)
                obj = {
                    "id": rid,
                    "raw_id": link,
                    "platform": "bayt",
                    "lang": "ar" if any("؀" <= ch <= "ۿ" for ch in blob) else "en",
                    "title": full_title,
                    "body": body or "",
                    "author": detail["company"],
                    "url": link,
                    "country_hint": cc,
                    "matched_keyword": ",".join(hits),
                    "engagement": {"score": 0, "comments": 0, "views": None},
                    "empresa": detail["company"],
                    "ubicacion": detail["location"],
                    "salario": detail["salary"],
                    "crawled_at": now_iso(),
                }
                append(OUT_BAYT, obj)
                seen.add(rid)
                n += 1
                picked += 1
                if picked >= 5:
                    break
            print(f"[bayt] {cc}/{role} cards={len(cards)} picked={picked} total={n}")
            polite()
    print(f"[bayt] DONE +{n}")
    return n


# ---------------------------------------------------------------------------
# 2. GulfTalent
# ---------------------------------------------------------------------------

OUT_GULFTALENT = RAW / f"gulftalent_native_{DAY}.jsonl"


def crawl_gulftalent():
    seen = load_seen(OUT_GULFTALENT)
    n = 0
    roles = [
        "software-engineer",
        "accountant",
        "sales-manager",
        "nurse",
        "marketing",
        "finance",
        "civil-engineer",
        "hr",
    ]
    for role in roles:
        for page in range(1, 3):  # 2 pages
            url = f"https://www.gulftalent.com/jobs/job-search?keywords={quote(role)}&page={page}"
            status, html = safe_get(url, HDR_GULF_EN, label="gulftalent-list")
            if status == "cf":
                print("[gulftalent] cloudflare; abandon")
                return n
            if not html:
                polite()
                continue
            soup = BeautifulSoup(html, "html.parser")
            links = []
            for a in soup.select("a[href*='/jobs/']"):
                href = a.get("href", "")
                if "/jobs/" not in href or "job-search" in href:
                    continue
                full = urljoin(url, href)
                if full not in links:
                    links.append(full)
            picked = 0
            for link in links[:8]:
                rid = md5_16("gulftalent", link)
                if rid in seen:
                    continue
                s2, h2 = safe_get(link, HDR_GULF_EN, label="gulftalent-detail")
                polite()
                if not h2:
                    continue
                soup2 = BeautifulSoup(h2, "html.parser")
                h1 = soup2.select_one("h1")
                title = h1.get_text(" ", strip=True) if h1 else ""
                main = soup2.select_one("main") or soup2.select_one("article") or soup2
                desc = main.get_text(" ", strip=True)[:5000]
                # Try country from breadcrumb
                cc = ""
                bc = soup2.select_one("[class*=breadcrumb]")
                bc_text = bc.get_text(" ", strip=True).lower() if bc else ""
                for kw, code in [
                    ("uae", "AE"),
                    ("dubai", "AE"),
                    ("saudi", "SA"),
                    ("riyadh", "SA"),
                    ("kuwait", "KW"),
                    ("qatar", "QA"),
                    ("doha", "QA"),
                    ("bahrain", "BH"),
                    ("oman", "OM"),
                ]:
                    if kw in (bc_text + " " + desc[:300]).lower():
                        cc = code
                        break
                blob = f"{title}\n{desc}"
                hits = kw_match(blob, KW_EN_GULF + KW_AR)
                obj = {
                    "id": rid,
                    "raw_id": link,
                    "platform": "gulftalent",
                    "lang": "en",
                    "title": title,
                    "body": desc,
                    "author": "",
                    "url": link,
                    "country_hint": cc or "GCC",
                    "matched_keyword": ",".join(hits),
                    "engagement": {"score": 0, "comments": 0, "views": None},
                    "salario": find_salary(desc),
                    "crawled_at": now_iso(),
                }
                append(OUT_GULFTALENT, obj)
                seen.add(rid)
                n += 1
                picked += 1
            print(f"[gulftalent] role={role} page={page} links={len(links)} picked={picked} total={n}")
            polite()
    print(f"[gulftalent] DONE +{n}")
    return n


# ---------------------------------------------------------------------------
# 3. Naukrigulf
# ---------------------------------------------------------------------------

OUT_NAUKRIGULF = RAW / f"naukrigulf_native_{DAY}.jsonl"


def crawl_naukrigulf():
    seen = load_seen(OUT_NAUKRIGULF)
    n = 0
    roles = [
        "software-engineer",
        "accountant",
        "sales",
        "civil-engineer",
        "marketing",
        "nurse",
        "hr",
        "finance-manager",
    ]
    for role in roles:
        for page in (1, 2):
            url = f"https://www.naukrigulf.com/{role}-jobs"
            if page > 1:
                url = f"https://www.naukrigulf.com/{role}-jobs-{page}"
            status, html = safe_get(url, HDR_GULF_EN, label="naukrigulf-list")
            if status == "cf":
                print("[naukrigulf] cloudflare; abandon")
                return n
            if not html:
                polite()
                continue
            soup = BeautifulSoup(html, "html.parser")
            links = []
            for a in soup.select("a[href*='/job-listings-']"):
                href = a.get("href", "")
                full = urljoin(url, href)
                if full not in links:
                    links.append(full)
            picked = 0
            for link in links[:8]:
                rid = md5_16("naukrigulf", link)
                if rid in seen:
                    continue
                s2, h2 = safe_get(link, HDR_GULF_EN, label="naukrigulf-detail")
                polite()
                if not h2:
                    continue
                soup2 = BeautifulSoup(h2, "html.parser")
                h1 = soup2.select_one("h1")
                title = h1.get_text(" ", strip=True) if h1 else ""
                main = (
                    soup2.select_one(".jd-desc")
                    or soup2.select_one("[class*=description]")
                    or soup2.select_one("main")
                    or soup2
                )
                desc = main.get_text(" ", strip=True)[:5000]
                blob = f"{title}\n{desc}"
                # crude country detect
                cc = ""
                low = blob.lower()
                for kw, code in [
                    ("dubai", "AE"),
                    ("abu dhabi", "AE"),
                    ("uae", "AE"),
                    ("riyadh", "SA"),
                    ("saudi", "SA"),
                    ("doha", "QA"),
                    ("qatar", "QA"),
                    ("kuwait", "KW"),
                    ("bahrain", "BH"),
                    ("oman", "OM"),
                ]:
                    if kw in low:
                        cc = code
                        break
                hits = kw_match(blob, KW_EN_GULF + KW_AR)
                obj = {
                    "id": rid,
                    "raw_id": link,
                    "platform": "naukrigulf",
                    "lang": "en",
                    "title": title,
                    "body": desc,
                    "author": "",
                    "url": link,
                    "country_hint": cc or "GCC",
                    "matched_keyword": ",".join(hits),
                    "engagement": {"score": 0, "comments": 0, "views": None},
                    "salario": find_salary(desc),
                    "crawled_at": now_iso(),
                }
                append(OUT_NAUKRIGULF, obj)
                seen.add(rid)
                n += 1
                picked += 1
            print(f"[naukrigulf] role={role} p={page} links={len(links)} picked={picked} total={n}")
            polite()
    print(f"[naukrigulf] DONE +{n}")
    return n


# ---------------------------------------------------------------------------
# 4. WUZZUF (Egypt)
# ---------------------------------------------------------------------------

OUT_WUZZUF = RAW / f"wuzzuf_native_{DAY}.jsonl"


def crawl_wuzzuf():
    seen = load_seen(OUT_WUZZUF)
    n = 0
    roles = [
        "software engineer",
        "accountant",
        "sales",
        "civil engineer",
        "marketing",
        "doctor",
        "hr",
        "finance",
        "محاسب",
        "مهندس",
        "مبيعات",
        "تسويق",
    ]
    for role in roles:
        for page in (0, 1, 2):
            url = f"https://wuzzuf.net/search/jobs/?q={quote(role)}&start={page}"
            status, html = safe_get(url, HDR_AR, label="wuzzuf-list")
            if status == "cf":
                print("[wuzzuf] cloudflare; abandon")
                return n
            if not html:
                polite()
                continue
            soup = BeautifulSoup(html, "html.parser")
            links = []
            for a in soup.select("a[href*='/jobs/p/']"):
                href = a.get("href", "")
                full = urljoin(url, href)
                if full not in links:
                    links.append(full)
            picked = 0
            for link in links[:6]:
                rid = md5_16("wuzzuf", link)
                if rid in seen:
                    continue
                s2, h2 = safe_get(link, HDR_AR, label="wuzzuf-detail")
                polite()
                if not h2:
                    continue
                soup2 = BeautifulSoup(h2, "html.parser")
                h1 = soup2.select_one("h1")
                title = h1.get_text(" ", strip=True) if h1 else ""
                main = (
                    soup2.select_one("[class*=job-description]")
                    or soup2.select_one("main")
                    or soup2
                )
                desc = main.get_text(" ", strip=True)[:5000]
                blob = f"{title}\n{desc}"
                hits = kw_match(blob, KW_AR + KW_EN_GULF)
                obj = {
                    "id": rid,
                    "raw_id": link,
                    "platform": "wuzzuf",
                    "lang": "ar" if any("؀" <= c <= "ۿ" for c in blob) else "en",
                    "title": title,
                    "body": desc,
                    "author": "",
                    "url": link,
                    "country_hint": "EG",
                    "matched_keyword": ",".join(hits) or role,
                    "engagement": {"score": 0, "comments": 0, "views": None},
                    "salario": find_salary(desc),
                    "crawled_at": now_iso(),
                }
                append(OUT_WUZZUF, obj)
                seen.add(rid)
                n += 1
                picked += 1
            print(f"[wuzzuf] role={role!r} p={page} links={len(links)} picked={picked} total={n}")
            polite()
    print(f"[wuzzuf] DONE +{n}")
    return n


# ---------------------------------------------------------------------------
# 5. Forsetak (Saudi)
# ---------------------------------------------------------------------------

OUT_FORSETAK = RAW / f"forsetak_native_{DAY}.jsonl"


def crawl_forsetak():
    seen = load_seen(OUT_FORSETAK)
    n = 0
    seeds = [
        "https://www.forsetak.com/",
        "https://www.forsetak.com/jobs",
        "https://www.forsetak.com/sa/jobs",
    ]
    detail_links = []
    for seed in seeds:
        status, html = safe_get(seed, HDR_AR, label="forsetak-seed")
        if status == "cf":
            print("[forsetak] cloudflare; abandon")
            return n
        if not html:
            polite()
            continue
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a"):
            href = a.get("href", "")
            if not href:
                continue
            if any(p in href for p in ["/job/", "/jobs/", "/vacancy/", "/wazifa", "/وظيفة"]):
                full = urljoin(seed, href)
                if full not in detail_links and "forsetak.com" in full:
                    detail_links.append(full)
        polite()
    for link in detail_links[:50]:
        rid = md5_16("forsetak", link)
        if rid in seen:
            continue
        s2, h2 = safe_get(link, HDR_AR, label="forsetak-detail")
        polite()
        if not h2:
            continue
        soup2 = BeautifulSoup(h2, "html.parser")
        h1 = soup2.select_one("h1")
        title = h1.get_text(" ", strip=True) if h1 else ""
        main = soup2.select_one("main") or soup2.select_one("article") or soup2
        desc = main.get_text(" ", strip=True)[:5000]
        blob = f"{title}\n{desc}"
        hits = kw_match(blob, KW_AR + KW_EN_GULF)
        obj = {
            "id": rid,
            "raw_id": link,
            "platform": "forsetak",
            "lang": "ar",
            "title": title,
            "body": desc,
            "author": "",
            "url": link,
            "country_hint": "SA",
            "matched_keyword": ",".join(hits),
            "engagement": {"score": 0, "comments": 0, "views": None},
            "salario": find_salary(desc),
            "crawled_at": now_iso(),
        }
        append(OUT_FORSETAK, obj)
        seen.add(rid)
        n += 1
    print(f"[forsetak] DONE links_found={len(detail_links)} +{n}")
    return n


# ---------------------------------------------------------------------------
# 6. Kariyer.net (Turkey)
# ---------------------------------------------------------------------------

OUT_KARIYER = RAW / f"kariyer_native_{DAY}.jsonl"


def crawl_kariyer():
    seen = load_seen(OUT_KARIYER)
    n = 0
    roles = [
        "yazilim-muhendisi",
        "muhasebeci",
        "satis",
        "pazarlama",
        "insaat-muhendisi",
        "doktor",
        "hemsire",
        "ik",
    ]
    for role in roles:
        for page in (1, 2):
            url = f"https://www.kariyer.net/is-ilanlari/{role}"
            if page > 1:
                url = f"https://www.kariyer.net/is-ilanlari/{role}?cp={page}"
            status, html = safe_get(url, HDR_TR, label="kariyer-list")
            if status == "cf":
                print("[kariyer] cloudflare; abandon")
                return n
            if not html:
                polite()
                continue
            soup = BeautifulSoup(html, "html.parser")
            links = []
            for a in soup.select("a[href*='/is-ilani/']"):
                href = a.get("href", "")
                full = urljoin(url, href)
                if full not in links:
                    links.append(full)
            picked = 0
            for link in links[:6]:
                rid = md5_16("kariyer", link)
                if rid in seen:
                    continue
                s2, h2 = safe_get(link, HDR_TR, label="kariyer-detail")
                polite()
                if not h2:
                    continue
                soup2 = BeautifulSoup(h2, "html.parser")
                h1 = soup2.select_one("h1")
                title = h1.get_text(" ", strip=True) if h1 else ""
                main = (
                    soup2.select_one("[class*=description]")
                    or soup2.select_one("main")
                    or soup2
                )
                desc = main.get_text(" ", strip=True)[:5000]
                blob = f"{title}\n{desc}"
                hits = kw_match(blob, KW_TR)
                obj = {
                    "id": rid,
                    "raw_id": link,
                    "platform": "kariyer",
                    "lang": "tr",
                    "title": title,
                    "body": desc,
                    "author": "",
                    "url": link,
                    "country_hint": "TR",
                    "matched_keyword": ",".join(hits) or role,
                    "engagement": {"score": 0, "comments": 0, "views": None},
                    "salario": find_salary(desc),
                    "crawled_at": now_iso(),
                }
                append(OUT_KARIYER, obj)
                seen.add(rid)
                n += 1
                picked += 1
            print(f"[kariyer] role={role} p={page} links={len(links)} picked={picked} total={n}")
            polite()
    print(f"[kariyer] DONE +{n}")
    return n


# ---------------------------------------------------------------------------
# 7. Eqtsadi.com forum (Arabic)  -- includes Hawamer + Mawdoo3 + SyrianForum
#    They share crawl_arabic_forum logic.
# ---------------------------------------------------------------------------

OUT_EQTSADI = RAW / f"eqtsadi_native_{DAY}.jsonl"


def crawl_arabic_forum(seeds, platform, country, out_path, link_patterns, kws=None):
    seen = load_seen(out_path)
    n = 0
    detail_links = []
    for seed in seeds:
        status, html = safe_get(seed, HDR_AR, label=f"{platform}-seed")
        if status == "cf":
            print(f"[{platform}] cloudflare; abandon")
            return n
        if not html:
            polite()
            continue
        soup = BeautifulSoup(html, "html.parser")
        host = urlparse(seed).netloc
        for a in soup.select("a"):
            href = a.get("href", "")
            if not href:
                continue
            full = urljoin(seed, href)
            if host not in urlparse(full).netloc:
                continue
            if any(p in full for p in link_patterns):
                if full not in detail_links:
                    detail_links.append(full)
        polite()
    use_kws = kws if kws is not None else (KW_AR + KW_EN_GULF)
    for link in detail_links[:60]:
        rid = md5_16(platform, link)
        if rid in seen:
            continue
        s2, h2 = safe_get(link, HDR_AR, label=f"{platform}-detail")
        polite()
        if not h2:
            continue
        soup2 = BeautifulSoup(h2, "html.parser")
        h1 = soup2.select_one("h1") or soup2.select_one("title")
        title = h1.get_text(" ", strip=True) if h1 else ""
        # Try forum post bodies (vBulletin / Discuz / phpBB common selectors)
        bodies = (
            soup2.select(".post_body, .post-content, [class*=post-body], "
                         "[class*=postcontent], [class*=message], article, main")
        )
        if bodies:
            desc = " ".join(b.get_text(" ", strip=True) for b in bodies)[:6000]
        else:
            desc = soup2.get_text(" ", strip=True)[:5000]
        blob = f"{title}\n{desc}"
        hits = kw_match(blob, use_kws)
        if not hits and not find_salary(blob):
            # skip irrelevant pages
            continue
        obj = {
            "id": rid,
            "raw_id": link,
            "platform": platform,
            "lang": "ar",
            "title": title,
            "body": desc[:5000],
            "author": "",
            "url": link,
            "country_hint": country,
            "matched_keyword": ",".join(hits),
            "engagement": {"score": 0, "comments": 0, "views": None},
            "salario": find_salary(desc),
            "crawled_at": now_iso(),
        }
        append(out_path, obj)
        seen.add(rid)
        n += 1
    print(f"[{platform}] DONE detail_links={len(detail_links)} +{n}")
    return n


def crawl_eqtsadi():
    seeds = [
        "https://www.eqtsadi.com/",
        "https://www.eqtsadi.com/forum.php",
        "https://www.eqtsadi.com/forumdisplay.php?f=2",
    ]
    return crawl_arabic_forum(
        seeds,
        "eqtsadi",
        "AR",
        OUT_EQTSADI,
        link_patterns=["showthread.php", "/thread-", "/topic/", "/t-"],
    )


# Hawamer
OUT_HAWAMER = RAW / f"hawamer_native_{DAY}.jsonl"


def crawl_hawamer():
    seeds = [
        "https://www.hawamer.com/vb/",
        "https://www.hawamer.com/",
        "https://www.hawamer.com/vb/forumdisplay.php?f=1",
    ]
    # platform name reused as filename; folded into one combined arabic file
    return crawl_arabic_forum(
        seeds,
        "hawamer",
        "SA",
        OUT_HAWAMER,
        link_patterns=["showthread.php", "/thread-", "/topic/"],
    )


# Mawdoo3
OUT_MAWDOO3 = RAW / f"mawdoo3_native_{DAY}.jsonl"


def crawl_mawdoo3():
    # Mawdoo3 articles, search-by-keyword pages
    seen = load_seen(OUT_MAWDOO3)
    n = 0
    detail_links = []
    queries = ["راتب", "دخل", "أجر", "تقاعد", "عمل حر", "مرتب", "رواتب"]
    for q in queries:
        url = f"https://mawdoo3.com/index.php?title=Special:Search&search={quote(q)}"
        status, html = safe_get(url, HDR_AR, label="mawdoo3-search")
        if status == "cf":
            print("[mawdoo3] cloudflare; abandon")
            return n
        if not html:
            polite()
            continue
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            full = urljoin(url, href)
            if "mawdoo3.com" not in urlparse(full).netloc:
                continue
            # article URLs are like https://mawdoo3.com/<title>
            path = urlparse(full).path
            if path.startswith("/index.php"):
                continue
            if path in ("/", ""):
                continue
            # Avoid login / category pages
            if any(skip in path for skip in [":", "Special:", "edit", "Category"]):
                continue
            if full not in detail_links:
                detail_links.append(full)
        polite()
    for link in detail_links[:80]:
        rid = md5_16("mawdoo3", link)
        if rid in seen:
            continue
        s2, h2 = safe_get(link, HDR_AR, label="mawdoo3-detail")
        polite()
        if not h2:
            continue
        soup2 = BeautifulSoup(h2, "html.parser")
        h1 = soup2.select_one("h1")
        title = h1.get_text(" ", strip=True) if h1 else ""
        main = soup2.select_one("#mw-content-text") or soup2.select_one("main") or soup2
        desc = main.get_text(" ", strip=True)[:6000]
        blob = f"{title}\n{desc}"
        hits = kw_match(blob, KW_AR)
        if not hits and not find_salary(blob):
            continue
        obj = {
            "id": rid,
            "raw_id": link,
            "platform": "mawdoo3",
            "lang": "ar",
            "title": title,
            "body": desc[:5000],
            "author": "",
            "url": link,
            "country_hint": "AR",
            "matched_keyword": ",".join(hits),
            "engagement": {"score": 0, "comments": 0, "views": None},
            "salario": find_salary(desc),
            "crawled_at": now_iso(),
        }
        append(OUT_MAWDOO3, obj)
        seen.add(rid)
        n += 1
    print(f"[mawdoo3] DONE links={len(detail_links)} +{n}")
    return n


# SyrianForum
OUT_SYRIAN = RAW / f"syrianforum_native_{DAY}.jsonl"


def crawl_syrianforum():
    seeds = [
        "https://www.syrianforum.org/",
        "https://www.syrianforum.org/forums/",
        "https://syrianforum.org/",
    ]
    return crawl_arabic_forum(
        seeds,
        "syrianforum",
        "SY",
        OUT_SYRIAN,
        link_patterns=["/topic/", "/threads/", "showthread", "/t-"],
    )


# ---------------------------------------------------------------------------
# 8. Eksisozluk (Turkey)
# ---------------------------------------------------------------------------

OUT_EKSI = RAW / f"eksisozluk_native_{DAY}.jsonl"


def crawl_eksi():
    seen = load_seen(OUT_EKSI)
    n = 0
    # known-ish topic pages (numbers may shift, but slug routing usually works)
    topics = [
        ("maas", "https://eksisozluk.com/maas--32093"),
        ("asgari-ucret", "https://eksisozluk.com/asgari-ucret--32094"),
        ("yazilimci-maaslari", "https://eksisozluk.com/yazilimci-maaslari--3593540"),
        ("muhendis-maaslari", "https://eksisozluk.com/muhendis-maaslari--1389234"),
        ("doktor-maaslari", "https://eksisozluk.com/doktor-maaslari--1213099"),
        ("freelance", "https://eksisozluk.com/freelance--237568"),
    ]
    # fallback: search if direct slug 404s
    for slug, url in topics:
        for page in (1, 2, 3):
            full = f"{url}?p={page}"
            status, html = safe_get(full, HDR_TR, label="eksi")
            if status == "cf":
                print("[eksi] cloudflare; abandon")
                return n
            if status == 404:
                # Try title-only URL (eksisozluk usually 302s on slug-only)
                fallback = f"https://eksisozluk.com/?q={quote(slug.replace('-', ' '))}"
                status, html = safe_get(fallback, HDR_TR, label="eksi-search")
                if not html:
                    break
            if not html:
                break
            soup = BeautifulSoup(html, "html.parser")
            entries = soup.select("li[data-id], #entry-item-list li, ul#entry-item-list > li, article")
            picked = 0
            for e in entries:
                eid = e.get("data-id") or md5_16("eksi", e.get_text(" ", strip=True)[:120])
                rid = md5_16("eksi", slug, str(eid))
                if rid in seen:
                    continue
                content_el = e.select_one(".content") or e
                body = content_el.get_text(" ", strip=True)
                if len(body) < 30:
                    continue
                hits = kw_match(body, KW_TR)
                if not hits and not find_salary(body):
                    continue
                author_el = e.select_one("a.entry-author") or e.select_one("[class*=author]")
                author = author_el.get_text(" ", strip=True) if author_el else ""
                obj = {
                    "id": rid,
                    "raw_id": str(eid),
                    "platform": "eksisozluk",
                    "lang": "tr",
                    "title": slug,
                    "body": body[:5000],
                    "author": author,
                    "url": full,
                    "country_hint": "TR",
                    "matched_keyword": ",".join(hits),
                    "engagement": {"score": 0, "comments": 0, "views": None},
                    "salario": find_salary(body),
                    "crawled_at": now_iso(),
                }
                append(OUT_EKSI, obj)
                seen.add(rid)
                n += 1
                picked += 1
            print(f"[eksi] {slug} p{page} entries={len(entries)} picked={picked} total={n}")
            polite()
            if not entries:
                break
    print(f"[eksi] DONE +{n}")
    return n


# ---------------------------------------------------------------------------
# 9. DonanimHaber forum (Turkey)
# ---------------------------------------------------------------------------

OUT_DONANIM = RAW / f"donanim_native_{DAY}.jsonl"


def crawl_donanim():
    seen = load_seen(OUT_DONANIM)
    n = 0
    # listing pages of the salaries / wages subforum
    list_urls = [
        "https://forum.donanimhaber.com/i-yasamim-ucretler-prim-bonus--113",
        "https://forum.donanimhaber.com/i-yasamim-ucretler-prim-bonus--113?p=2",
        "https://forum.donanimhaber.com/i-yasamim-ucretler-prim-bonus--113?p=3",
        "https://forum.donanimhaber.com/i-yasamim--104",
        "https://forum.donanimhaber.com/serbest-meslek--140",
    ]
    detail_links = []
    for url in list_urls:
        status, html = safe_get(url, HDR_TR, label="donanim-list")
        if status == "cf":
            print("[donanim] cloudflare; abandon")
            return n
        if not html:
            polite()
            continue
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            full = urljoin(url, href)
            if "forum.donanimhaber.com" not in urlparse(full).netloc:
                continue
            # Topic URL pattern: /<slug>--<id>
            path = urlparse(full).path
            if "--" in path and not path.startswith("/i-yasamim") and not path.startswith("/serbest"):
                if full not in detail_links:
                    detail_links.append(full)
        polite()
    for link in detail_links[:60]:
        rid = md5_16("donanim", link)
        if rid in seen:
            continue
        s2, h2 = safe_get(link, HDR_TR, label="donanim-detail")
        polite()
        if not h2:
            continue
        soup2 = BeautifulSoup(h2, "html.parser")
        h1 = soup2.select_one("h1") or soup2.select_one("title")
        title = h1.get_text(" ", strip=True) if h1 else ""
        posts = soup2.select(".kygnmesaj, [class*=post-content], [class*=message], article")
        if posts:
            desc = " ".join(p.get_text(" ", strip=True) for p in posts[:5])[:6000]
        else:
            desc = soup2.get_text(" ", strip=True)[:5000]
        blob = f"{title}\n{desc}"
        hits = kw_match(blob, KW_TR)
        if not hits and not find_salary(blob):
            continue
        obj = {
            "id": rid,
            "raw_id": link,
            "platform": "donanim",
            "lang": "tr",
            "title": title,
            "body": desc[:5000],
            "author": "",
            "url": link,
            "country_hint": "TR",
            "matched_keyword": ",".join(hits),
            "engagement": {"score": 0, "comments": 0, "views": None},
            "salario": find_salary(desc),
            "crawled_at": now_iso(),
        }
        append(OUT_DONANIM, obj)
        seen.add(rid)
        n += 1
    print(f"[donanim] DONE links={len(detail_links)} +{n}")
    return n


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

OUTPUTS = [
    ("bayt", OUT_BAYT, crawl_bayt),
    ("gulftalent", OUT_GULFTALENT, crawl_gulftalent),
    ("naukrigulf", OUT_NAUKRIGULF, crawl_naukrigulf),
    ("wuzzuf", OUT_WUZZUF, crawl_wuzzuf),
    ("forsetak", OUT_FORSETAK, crawl_forsetak),
    ("kariyer", OUT_KARIYER, crawl_kariyer),
    ("eqtsadi", OUT_EQTSADI, crawl_eqtsadi),
    ("hawamer", OUT_HAWAMER, crawl_hawamer),
    ("mawdoo3", OUT_MAWDOO3, crawl_mawdoo3),
    ("syrianforum", OUT_SYRIAN, crawl_syrianforum),
    ("eksisozluk", OUT_EKSI, crawl_eksi),
    ("donanim", OUT_DONANIM, crawl_donanim),
]


def file_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for _ in path.open(encoding="utf-8"))


def main(argv):
    only = set(argv[1:]) if len(argv) > 1 else None
    totals = {}
    for label, path, fn in OUTPUTS:
        if only and label not in only:
            continue
        try:
            added = fn()
        except Exception as e:
            print(f"[{label}] CRASH: {e}")
            added = 0
        totals[label] = (added, file_lines(path), path)

    print("\n" + "=" * 60)
    print(f"SUMMARY (DAY={DAY})")
    print("=" * 60)
    grand_added = 0
    grand_lines = 0
    for label, (added, lines, path) in totals.items():
        print(f"  {label:14s}  added={added:5d}  total_in_file={lines:5d}  {path}")
        grand_added += added
        grand_lines += lines
    print("-" * 60)
    print(f"  GRAND TOTAL: added={grand_added}  file_lines_sum={grand_lines}")


if __name__ == "__main__":
    main(sys.argv)
