"""South Asia 多国本地求职 / 财经站抓取 — 非 Reddit。

覆盖国家与站点：
  IN: Naukri, JobBuzz (TimesJobs), Quikr Jobs, Shine, MoneyControl Personal Finance
  PK: Rozee.pk, Pakwheels Forum
  BD: BDJobs, Prothomalo Business
  LK: TopJobs.lk, DailyMirror.lk Business
  NP: MeroJob

每站逻辑：列表 → 详情；详情优先 JSON-LD JobPosting (baseSalary, hiringOrganization)。
关键词过滤偏向收入数额讨论（lakh / crore / lpa / ctc / package / take home / gross / net pay 等）。
输出按站独立 JSONL，schema 与 r_mexico_native 一致。
"""
import json, hashlib, re, time, random, sys, traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, quote_plus
import requests
from bs4 import BeautifulSoup

# -------------------- shared infra --------------------
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

def hdr(lang_country):
    """lang_country e.g. 'en-IN' / 'en-PK' / 'en-BD' / 'en-LK' / 'en-NP'."""
    return {
        "User-Agent": UA,
        "Accept-Language": f"{lang_country},en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Cache-Control": "no-cache",
    }

DAY = datetime.now().strftime("%Y%m%d")
RAW = Path("data/raw")
RAW.mkdir(parents=True, exist_ok=True)


def out_path(name):
    return RAW / f"{name}_native_{DAY}.jsonl"


def md5_16(*p):
    return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def polite():
    time.sleep(random.uniform(1.3, 1.8))


def load_seen(path):
    seen = set()
    if path.exists():
        for line in path.open():
            try:
                seen.add(json.loads(line)["id"])
            except Exception:
                pass
    return seen


# Income / pay-related keywords (English variants common across South Asia).
# These are used to *filter* discussion-style content (forums, finance) — for raw
# job postings (Naukri/Rozee/etc.) we keep the post regardless because salary may
# be in a structured baseSalary field even if the description doesn't mention it.
PAY_KW = [
    "salary", "salaries", "lakh", "lakhs", "crore", "crores", "lpa", "package",
    "ctc", "take home", "take-home", "gross", "net pay", "pay scale",
    "freelance", "remote", "USD", "INR", "PKR", "BDT", "LKR", "NPR",
    "rs.", "rs ", "₹", "Rs.", "Rs ", "income", "earn", "earning", "monthly pay",
    "annual package", "in hand", "in-hand", "stipend", "compensation",
]
PAY_RE = re.compile("|".join(re.escape(k) for k in PAY_KW), re.I)


def has_pay_signal(text):
    if not text:
        return False
    return bool(PAY_RE.search(text))


def fetch(url, headers, timeout=25, allow_4xx=True):
    """GET with cloudflare / 4xx / 5xx tolerance. Returns (status, text) or (status, '')."""
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        if r.status_code >= 400:
            # Cloudflare challenge often returns 403 + 'cf-' html
            if r.status_code in (403, 503) and ("cloudflare" in r.text.lower() or "cf-chl" in r.text.lower()):
                return ("cloudflare", "")
            if not allow_4xx:
                return (r.status_code, "")
            return (r.status_code, r.text)
        return (200, r.text)
    except Exception as e:
        return ("err:" + str(e)[:60], "")


def parse_jsonld_jobposting(soup):
    """Return dict {title, salary, currency, company, location, description, employment_type}
    based on the first JobPosting JSON-LD found, or {} if none."""
    out = {}
    for s in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            j = json.loads(s.string or "{}")
        except Exception:
            try:
                j = json.loads((s.string or "").strip().rstrip(";"))
            except Exception:
                continue
        items = j if isinstance(j, list) else [j]
        for it in items:
            if not isinstance(it, dict):
                continue
            t = it.get("@type")
            if isinstance(t, list):
                t = t[0] if t else ""
            if t != "JobPosting":
                continue
            out["title"] = it.get("title", "") or ""
            out["description"] = re.sub(r"<[^>]+>", " ", it.get("description", "") or "")[:5000]
            out["employment_type"] = it.get("employmentType", "") or ""
            org = it.get("hiringOrganization") or {}
            if isinstance(org, dict):
                out["company"] = org.get("name", "") or ""
            bs = it.get("baseSalary") or {}
            if isinstance(bs, dict):
                cu = bs.get("currency", "") or ""
                v = bs.get("value") or {}
                if isinstance(v, dict):
                    mn = v.get("minValue")
                    mx = v.get("maxValue")
                    val = v.get("value")
                    unit = v.get("unitText", "") or ""
                    if mn or mx:
                        out["salary"] = f"{mn or ''}-{mx or ''} {cu} {unit}".strip()
                    elif val:
                        out["salary"] = f"{val} {cu} {unit}".strip()
                    out["currency"] = cu
            loc = it.get("jobLocation") or {}
            if isinstance(loc, list) and loc:
                loc = loc[0]
            if isinstance(loc, dict):
                addr = loc.get("address") or {}
                if isinstance(addr, dict):
                    out["location"] = ", ".join(
                        v for v in [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")] if v
                    )
            return out  # first match wins
    return out


def text_clean(s, lim=5000):
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()[:lim]


# ===================================================================
# IN: Naukri.com
# ===================================================================
def crawl_naukri():
    """SSR pages: https://www.naukri.com/<role>-jobs."""
    out = out_path("naukri")
    seen = load_seen(out)
    n = 0
    roles = [
        "software-developer", "data-scientist", "accountant", "marketing-manager",
        "civil-engineer", "doctor", "teacher", "sales-executive", "chartered-accountant",
        "product-manager", "graphic-designer", "nurse",
    ]
    H = hdr("en-IN")
    for role in roles:
        listing_url = f"https://www.naukri.com/{role}-jobs"
        st, html = fetch(listing_url, H)
        if st != 200:
            print(f"[naukri] role={role} listing status={st}")
            polite()
            continue
        soup = BeautifulSoup(html, "html.parser")
        # Listing JobPosting items often appear as anchor tiles. Naukri SPA-ish:
        # try multiple selectors + extract links.
        links = set()
        for a in soup.select("a[href*='/job-listings-']"):
            href = a.get("href", "")
            if href:
                links.add(urljoin("https://www.naukri.com", href))
        # JSON-LD ItemList sometimes embeds the urls
        for s in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                j = json.loads(s.string or "{}")
            except Exception:
                continue
            items = j if isinstance(j, list) else [j]
            for it in items:
                if isinstance(it, dict) and it.get("@type") == "ItemList":
                    for el in (it.get("itemListElement") or []):
                        u = (el.get("url") if isinstance(el, dict) else "") or ""
                        if u and "naukri.com" in u:
                            links.add(u)
        if not links:
            print(f"[naukri] role={role} no detail links. head={html[:160]!r}")
            polite()
            continue
        picked = 0
        for href in list(links)[:14]:
            m = re.search(r"/job-listings-([^?#/]+)", href)
            raw_id = m.group(1) if m else href
            rid = md5_16("naukri", raw_id)
            if rid in seen:
                continue
            st2, html2 = fetch(href, H)
            polite()
            if st2 != 200:
                continue
            soup2 = BeautifulSoup(html2, "html.parser")
            jl = parse_jsonld_jobposting(soup2)
            title = jl.get("title") or text_clean(soup2.title.string if soup2.title else "", 200)
            desc_el = soup2.select_one("section.job-desc") or soup2.select_one("[class*=job-desc]") or soup2.select_one("main")
            desc = jl.get("description") or text_clean(desc_el.get_text(" ", strip=True) if desc_el else soup2.get_text(" ", strip=True))
            obj = {
                "id": rid,
                "raw_id": raw_id,
                "platform": "naukri",
                "lang": "en",
                "title": title,
                "body": desc[:5000],
                "author": jl.get("company", ""),
                "url": href,
                "country_hint": "IN",
                "matched_keyword": role,
                "engagement": {"score": 0, "comments": 0, "views": None},
                "company": jl.get("company", ""),
                "location": jl.get("location", ""),
                "salary": jl.get("salary", ""),
                "currency": jl.get("currency", ""),
                "employment_type": jl.get("employment_type", ""),
                "crawled_at": now_iso(),
            }
            append(out, obj)
            seen.add(rid)
            n += 1
            picked += 1
        print(f"[naukri] role={role} links={len(links)} picked={picked} total={n}")
        polite()
    print(f"[naukri] DONE +{n}")
    return n


# ===================================================================
# IN: JobBuzz (TimesJobs reviews)
# ===================================================================
def crawl_jobbuzz():
    out = out_path("jobbuzz")
    seen = load_seen(out)
    n = 0
    companies = [
        "TCS", "Infosys", "Wipro", "HCL-Technologies", "Tech-Mahindra", "Cognizant",
        "Accenture", "Capgemini", "IBM", "Oracle", "SAP", "Deloitte", "EY",
        "ICICI-Bank", "HDFC-Bank", "Axis-Bank", "Reliance-Industries", "Flipkart",
        "Amazon", "Google", "Microsoft", "Paytm", "Zomato", "Swiggy",
    ]
    H = hdr("en-IN")
    for c in companies:
        url = f"https://jobbuzz.timesjobs.com/Reviews/{c}"
        st, html = fetch(url, H)
        if st != 200:
            print(f"[jobbuzz] {c} status={st}")
            polite()
            continue
        soup = BeautifulSoup(html, "html.parser")
        # JobBuzz reviews often live in .review-card / .salary-card / .pros-cons.
        cards = soup.select("[class*=review], [class*=salary], [class*=Reviews], article")
        added = 0
        for card in cards:
            txt = text_clean(card.get_text(" ", strip=True))
            if len(txt) < 80:
                continue
            if not has_pay_signal(txt):
                continue
            raw_id = md5_16(c, txt[:200])
            rid = md5_16("jobbuzz", raw_id)
            if rid in seen:
                continue
            obj = {
                "id": rid,
                "raw_id": raw_id,
                "platform": "jobbuzz",
                "lang": "en",
                "title": f"Review on {c}",
                "body": txt[:5000],
                "author": "",
                "url": url,
                "country_hint": "IN",
                "matched_keyword": c,
                "engagement": {"score": 0, "comments": 0, "views": None},
                "company": c.replace("-", " "),
                "location": "",
                "salary": "",
                "crawled_at": now_iso(),
            }
            append(out, obj)
            seen.add(rid)
            n += 1
            added += 1
            if added >= 10:
                break
        print(f"[jobbuzz] company={c} cards={len(cards)} new={added} total={n}")
        polite()
    print(f"[jobbuzz] DONE +{n}")
    return n


# ===================================================================
# IN: Quikr Jobs
# ===================================================================
def crawl_quikr():
    out = out_path("quikr")
    seen = load_seen(out)
    n = 0
    cats = ["sales", "bpo", "telecaller", "data-entry", "delivery", "driver", "accountant", "receptionist"]
    H = hdr("en-IN")
    base = "https://www.quikr.com/jobs/"
    st, html = fetch(base, H)
    polite()
    seed_urls = {base}
    if st == 200:
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href*='/jobs/']"):
            href = a.get("href", "")
            if href and "/jobs/" in href:
                seed_urls.add(urljoin(base, href))
    for cat in cats:
        seed_urls.add(f"https://www.quikr.com/jobs/{cat}+zfilter")
    for url in list(seed_urls)[:20]:
        st, html = fetch(url, hdr("en-IN"))
        if st != 200:
            print(f"[quikr] {url} status={st}")
            polite()
            continue
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("[class*=AdItem], [class*=adsnippet], a[href*='/jobs/']")
        added = 0
        for card in cards[:30]:
            text = text_clean(card.get_text(" ", strip=True))
            if len(text) < 30:
                continue
            href = ""
            if card.name == "a":
                href = card.get("href", "")
            else:
                a = card.select_one("a[href]")
                if a:
                    href = a.get("href", "")
            if href and not href.startswith("http"):
                href = urljoin(url, href)
            if not href:
                continue
            raw_id = md5_16(href)
            rid = md5_16("quikr", raw_id)
            if rid in seen:
                continue
            # title heuristic
            title_el = card.select_one("h2, h3, [class*=title], [class*=Title]")
            title = text_clean(title_el.get_text(" ", strip=True) if title_el else text[:120], 200)
            if len(title) < 4:
                continue
            obj = {
                "id": rid,
                "raw_id": raw_id,
                "platform": "quikr",
                "lang": "en",
                "title": title,
                "body": text[:3000],
                "author": "",
                "url": href,
                "country_hint": "IN",
                "matched_keyword": "jobs",
                "engagement": {"score": 0, "comments": 0, "views": None},
                "company": "",
                "location": "",
                "salary": "",
                "crawled_at": now_iso(),
            }
            append(out, obj)
            seen.add(rid)
            n += 1
            added += 1
            if added >= 12:
                break
        print(f"[quikr] {url} cards={len(cards)} new={added} total={n}")
        polite()
    print(f"[quikr] DONE +{n}")
    return n


# ===================================================================
# IN: Shine.com
# ===================================================================
def crawl_shine():
    out = out_path("shine")
    seen = load_seen(out)
    n = 0
    roles = [
        "software-developer", "data-analyst", "accountant", "civil-engineer",
        "marketing", "sales-executive", "doctor", "nurse", "teacher",
        "graphic-designer", "hr-executive", "chartered-accountant",
    ]
    H = hdr("en-IN")
    for role in roles:
        url = f"https://www.shine.com/job-search/{role}-jobs"
        st, html = fetch(url, H)
        if st != 200:
            print(f"[shine] role={role} status={st}")
            polite()
            continue
        soup = BeautifulSoup(html, "html.parser")
        links = set()
        for a in soup.select("a[href*='/jobs/']"):
            href = a.get("href", "")
            if href and "/jobs/" in href:
                links.add(urljoin("https://www.shine.com", href))
        if not links:
            print(f"[shine] role={role} no links. head={html[:160]!r}")
            polite()
            continue
        picked = 0
        for href in list(links)[:12]:
            m = re.search(r"/jobs/([^?#/]+)", href)
            raw_id = m.group(1) if m else href
            rid = md5_16("shine", raw_id)
            if rid in seen:
                continue
            st2, html2 = fetch(href, H)
            polite()
            if st2 != 200:
                continue
            soup2 = BeautifulSoup(html2, "html.parser")
            jl = parse_jsonld_jobposting(soup2)
            title = jl.get("title") or text_clean(soup2.title.string if soup2.title else "", 200)
            desc_el = soup2.select_one("[class*=jobDesc], [class*=job-desc], [class*=description], main")
            desc = jl.get("description") or text_clean(desc_el.get_text(" ", strip=True) if desc_el else soup2.get_text(" ", strip=True))
            obj = {
                "id": rid,
                "raw_id": raw_id,
                "platform": "shine",
                "lang": "en",
                "title": title,
                "body": desc[:5000],
                "author": jl.get("company", ""),
                "url": href,
                "country_hint": "IN",
                "matched_keyword": role,
                "engagement": {"score": 0, "comments": 0, "views": None},
                "company": jl.get("company", ""),
                "location": jl.get("location", ""),
                "salary": jl.get("salary", ""),
                "currency": jl.get("currency", ""),
                "crawled_at": now_iso(),
            }
            append(out, obj)
            seen.add(rid)
            n += 1
            picked += 1
        print(f"[shine] role={role} links={len(links)} picked={picked} total={n}")
        polite()
    print(f"[shine] DONE +{n}")
    return n


# ===================================================================
# IN: MoneyControl Personal Finance
# ===================================================================
def crawl_moneycontrol():
    out = out_path("moneycontrol")
    seen = load_seen(out)
    n = 0
    H = hdr("en-IN")
    sections = [
        "https://www.moneycontrol.com/personal-finance/",
        "https://www.moneycontrol.com/personal-finance/news/",
        "https://www.moneycontrol.com/personal-finance/tax/",
        "https://www.moneycontrol.com/personal-finance/investing/",
        "https://www.moneycontrol.com/personal-finance/insurance/",
    ]
    article_urls = set()
    for sec in sections:
        st, html = fetch(sec, H)
        polite()
        if st != 200:
            print(f"[moneycontrol] section {sec} status={st}")
            continue
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href*='/personal-finance/']"):
            href = a.get("href", "")
            if href and re.search(r"/personal-finance/.+_\d+\.html", href):
                article_urls.add(href if href.startswith("http") else urljoin(sec, href))
    print(f"[moneycontrol] discovered {len(article_urls)} articles")
    for url in list(article_urls)[:60]:
        raw_id = md5_16(url)
        rid = md5_16("moneycontrol", raw_id)
        if rid in seen:
            continue
        st, html = fetch(url, H)
        polite()
        if st != 200:
            continue
        soup = BeautifulSoup(html, "html.parser")
        title_el = soup.select_one("h1") or soup.title
        title = text_clean(title_el.get_text(" ", strip=True) if title_el else "", 200)
        body_el = soup.select_one("[class*=content_wrapper], [class*=article_content], [class*=arti-flow], article")
        body = text_clean(body_el.get_text(" ", strip=True) if body_el else soup.get_text(" ", strip=True))
        if not has_pay_signal(title + " " + body[:1500]):
            continue
        obj = {
            "id": rid,
            "raw_id": raw_id,
            "platform": "moneycontrol",
            "lang": "en",
            "title": title,
            "body": body[:5000],
            "author": "",
            "url": url,
            "country_hint": "IN",
            "matched_keyword": "personal-finance",
            "engagement": {"score": 0, "comments": 0, "views": None},
            "crawled_at": now_iso(),
        }
        append(out, obj)
        seen.add(rid)
        n += 1
    print(f"[moneycontrol] DONE +{n}")
    return n


# ===================================================================
# PK: Rozee.pk
# ===================================================================
def crawl_rozee():
    out = out_path("rozee")
    seen = load_seen(out)
    n = 0
    H = hdr("en-PK")
    roles = [
        "software engineer", "developer", "accountant", "marketing", "sales",
        "doctor", "teacher", "data analyst", "hr", "civil engineer",
        "graphic designer", "nurse",
    ]
    for role in roles:
        url = f"https://www.rozee.pk/job-search?q={quote_plus(role)}"
        st, html = fetch(url, H)
        if st != 200:
            print(f"[rozee] role={role!r} status={st}")
            polite()
            continue
        soup = BeautifulSoup(html, "html.parser")
        # Rozee SSR job tiles use <div class='job'> typically
        cards = soup.select("div.job, [class*=job-listing], [class*=jobitem], [class*=jobs__list-item]")
        # fallback: anchor scan
        links = set()
        for a in soup.select("a[href*='/jobs/'], a[href*='/job/']"):
            href = a.get("href", "")
            if href and re.search(r"/jobs?/", href) and "search" not in href:
                links.add(urljoin("https://www.rozee.pk", href))
        # Pull a salary line at card level if present
        added = 0
        for href in list(links)[:14]:
            raw_id = md5_16(href)
            rid = md5_16("rozee", raw_id)
            if rid in seen:
                continue
            st2, html2 = fetch(href, H)
            polite()
            if st2 != 200:
                continue
            soup2 = BeautifulSoup(html2, "html.parser")
            jl = parse_jsonld_jobposting(soup2)
            title = jl.get("title")
            if not title:
                t_el = soup2.select_one("h1") or soup2.title
                title = text_clean(t_el.get_text(" ", strip=True) if t_el else "", 200)
            desc_el = soup2.select_one("[class*=jdesc], [class*=description], [class*=job-detail], main")
            desc = jl.get("description") or text_clean(desc_el.get_text(" ", strip=True) if desc_el else soup2.get_text(" ", strip=True))
            # try to find salary text manually if missing
            sal = jl.get("salary") or ""
            if not sal:
                m = re.search(r"PKR[\s\d,.\-/kK]+|Rs\.?\s?[\d,]+(?:\s?-\s?[\d,]+)?", desc)
                if m:
                    sal = m.group(0)
            obj = {
                "id": rid,
                "raw_id": raw_id,
                "platform": "rozee",
                "lang": "en",
                "title": title,
                "body": desc[:5000],
                "author": jl.get("company", ""),
                "url": href,
                "country_hint": "PK",
                "matched_keyword": role,
                "engagement": {"score": 0, "comments": 0, "views": None},
                "company": jl.get("company", ""),
                "location": jl.get("location", ""),
                "salary": sal,
                "currency": jl.get("currency", "PKR"),
                "crawled_at": now_iso(),
            }
            append(out, obj)
            seen.add(rid)
            n += 1
            added += 1
            if added >= 10:
                break
        print(f"[rozee] role={role!r} links={len(links)} cards={len(cards)} new={added} total={n}")
        polite()
    print(f"[rozee] DONE +{n}")
    return n


# ===================================================================
# PK: Pakwheels Forum
# ===================================================================
def crawl_pakwheels_forum():
    out = out_path("pakwheels")
    seen = load_seen(out)
    n = 0
    H = hdr("en-PK")
    # Discourse forum: https://forum.pakwheels.com  topics in /latest.json
    base = "https://forum.pakwheels.com"
    # Fetch latest topics across multiple pages
    for page in range(0, 5):
        url = f"{base}/latest.json?page={page}"
        st, txt = fetch(url, {**H, "Accept": "application/json"})
        polite()
        if st != 200:
            print(f"[pakwheels] page={page} status={st}")
            continue
        try:
            data = json.loads(txt)
        except Exception:
            print(f"[pakwheels] page={page} bad json")
            continue
        topics = (data.get("topic_list") or {}).get("topics") or []
        added = 0
        for t in topics:
            slug = t.get("slug", "")
            tid = t.get("id")
            title = t.get("title", "") or ""
            if not tid:
                continue
            # filter: include if title mentions pay-ish OR fetch a few generic
            if not has_pay_signal(title) and added > 6:
                continue
            url_topic = f"{base}/t/{slug}/{tid}.json"
            st2, txt2 = fetch(url_topic, {**H, "Accept": "application/json"})
            polite()
            if st2 != 200:
                continue
            try:
                d2 = json.loads(txt2)
            except Exception:
                continue
            posts = (d2.get("post_stream") or {}).get("posts") or []
            body_all = " ".join(text_clean(re.sub(r"<[^>]+>", " ", p.get("cooked", "") or ""), 1500) for p in posts[:5])
            if not has_pay_signal(body_all):
                continue
            raw_id = str(tid)
            rid = md5_16("pakwheels", raw_id)
            if rid in seen:
                continue
            obj = {
                "id": rid,
                "raw_id": raw_id,
                "platform": "pakwheels",
                "lang": "en",
                "title": title,
                "body": body_all[:5000],
                "author": (posts[0].get("username") if posts else "") or "",
                "url": f"{base}/t/{slug}/{tid}",
                "country_hint": "PK",
                "matched_keyword": "forum",
                "engagement": {
                    "score": int(t.get("like_count", 0) or 0),
                    "comments": int(t.get("posts_count", 0) or 0),
                    "views": int(t.get("views", 0) or 0),
                },
                "crawled_at": now_iso(),
            }
            append(out, obj)
            seen.add(rid)
            n += 1
            added += 1
        print(f"[pakwheels] page={page} topics={len(topics)} new={added} total={n}")
    print(f"[pakwheels] DONE +{n}")
    return n


# ===================================================================
# BD: BDJobs.com
# ===================================================================
def crawl_bdjobs():
    out = out_path("bdjobs")
    seen = load_seen(out)
    n = 0
    H = hdr("en-BD")
    # The public listing: https://jobs.bdjobs.com/jobsearch.asp
    seed_urls = [
        "https://jobs.bdjobs.com/jobsearch.asp?fcatId=8",  # IT
        "https://jobs.bdjobs.com/jobsearch.asp?fcatId=21",  # Accounting
        "https://jobs.bdjobs.com/jobsearch.asp?fcatId=18",  # Engineering
        "https://jobs.bdjobs.com/jobsearch.asp?fcatId=11",  # Marketing
        "https://jobs.bdjobs.com/jobsearch.asp?fcatId=10",  # Medical
        "https://jobs.bdjobs.com/jobsearch.asp",
    ]
    for url in seed_urls:
        st, html = fetch(url, H)
        if st != 200:
            print(f"[bdjobs] {url} status={st}")
            polite()
            continue
        soup = BeautifulSoup(html, "html.parser")
        # detail links typically /jobdetails.asp?id=...
        links = set()
        for a in soup.select("a[href*='jobdetails']"):
            href = a.get("href", "")
            if href:
                links.add(urljoin(url, href))
        added = 0
        for href in list(links)[:15]:
            m = re.search(r"id=([^&]+)", href)
            raw_id = m.group(1) if m else href
            rid = md5_16("bdjobs", raw_id)
            if rid in seen:
                continue
            st2, html2 = fetch(href, H)
            polite()
            if st2 != 200:
                continue
            soup2 = BeautifulSoup(html2, "html.parser")
            jl = parse_jsonld_jobposting(soup2)
            title = jl.get("title") or text_clean((soup2.select_one("h1") or soup2.title).get_text(" ", strip=True) if (soup2.select_one("h1") or soup2.title) else "", 200)
            body_el = soup2.select_one("[class*=jdesc], #job_des, [class*=description], main, body")
            desc = jl.get("description") or text_clean(body_el.get_text(" ", strip=True) if body_el else soup2.get_text(" ", strip=True))
            sal = jl.get("salary") or ""
            if not sal:
                m = re.search(r"(BDT|Tk\.?)\s?[\d,]+(?:\s?-\s?[\d,]+)?", desc, re.I)
                if m:
                    sal = m.group(0)
            obj = {
                "id": rid,
                "raw_id": raw_id,
                "platform": "bdjobs",
                "lang": "en",
                "title": title,
                "body": desc[:5000],
                "author": jl.get("company", ""),
                "url": href,
                "country_hint": "BD",
                "matched_keyword": "bdjobs",
                "engagement": {"score": 0, "comments": 0, "views": None},
                "company": jl.get("company", ""),
                "location": jl.get("location", ""),
                "salary": sal,
                "currency": jl.get("currency", "BDT"),
                "crawled_at": now_iso(),
            }
            append(out, obj)
            seen.add(rid)
            n += 1
            added += 1
        print(f"[bdjobs] seed={url} links={len(links)} new={added} total={n}")
        polite()
    print(f"[bdjobs] DONE +{n}")
    return n


# ===================================================================
# BD: Prothomalo Business RSS
# ===================================================================
def crawl_prothomalo():
    out = out_path("prothomalo")
    seen = load_seen(out)
    n = 0
    H = hdr("en-BD")
    feeds = [
        "https://en.prothomalo.com/business/feed",
        "https://en.prothomalo.com/business/local/feed",
        "https://en.prothomalo.com/business/economy/feed",
    ]
    for feed in feeds:
        st, xml = fetch(feed, H)
        polite()
        if st != 200:
            print(f"[prothomalo] feed {feed} status={st}")
            continue
        # Naive XML parse — the RSS is straightforward.
        items = re.findall(r"<item>(.*?)</item>", xml, re.S)
        added = 0
        for it in items:
            title_m = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", it, re.S)
            link_m = re.search(r"<link>(.*?)</link>", it, re.S)
            desc_m = re.search(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", it, re.S)
            if not link_m:
                continue
            url = (link_m.group(1) or "").strip()
            title = text_clean((title_m.group(1) if title_m else ""), 200)
            desc_html = desc_m.group(1) if desc_m else ""
            desc = text_clean(re.sub(r"<[^>]+>", " ", desc_html))
            raw_id = md5_16(url)
            rid = md5_16("prothomalo", raw_id)
            if rid in seen:
                continue
            # Fetch full article body
            st2, html2 = fetch(url, H)
            polite()
            full_body = desc
            if st2 == 200:
                soup2 = BeautifulSoup(html2, "html.parser")
                body_el = soup2.select_one("[class*=story-element], [class*=article-content], [itemprop=articleBody], main, article")
                if body_el:
                    full_body = text_clean(body_el.get_text(" ", strip=True))
            if not has_pay_signal(title + " " + full_body[:2000]):
                continue
            obj = {
                "id": rid,
                "raw_id": raw_id,
                "platform": "prothomalo",
                "lang": "en",
                "title": title,
                "body": full_body[:5000],
                "author": "",
                "url": url,
                "country_hint": "BD",
                "matched_keyword": "business-feed",
                "engagement": {"score": 0, "comments": 0, "views": None},
                "crawled_at": now_iso(),
            }
            append(out, obj)
            seen.add(rid)
            n += 1
            added += 1
        print(f"[prothomalo] feed={feed} items={len(items)} new={added} total={n}")
    print(f"[prothomalo] DONE +{n}")
    return n


# ===================================================================
# LK: TopJobs.lk
# ===================================================================
def crawl_topjobs_lk():
    out = out_path("topjobs_lk")
    seen = load_seen(out)
    n = 0
    H = hdr("en-LK")
    # TopJobs has /VAC.html SSR job vacancies; use search endpoint
    seed_urls = [
        "https://www.topjobs.lk/employer/JobAdvertismentServlet?ac=&Keyword=software",
        "https://www.topjobs.lk/employer/JobAdvertismentServlet?ac=&Keyword=accountant",
        "https://www.topjobs.lk/employer/JobAdvertismentServlet?ac=&Keyword=engineer",
        "https://www.topjobs.lk/employer/JobAdvertismentServlet?ac=&Keyword=marketing",
        "https://www.topjobs.lk/employer/JobAdvertismentServlet?ac=&Keyword=teacher",
        "https://www.topjobs.lk/employer/JobAdvertismentServlet?ac=&Keyword=manager",
        "https://www.topjobs.lk/",
    ]
    for url in seed_urls:
        st, html = fetch(url, H)
        if st != 200:
            print(f"[topjobs_lk] {url} status={st}")
            polite()
            continue
        soup = BeautifulSoup(html, "html.parser")
        links = set()
        for a in soup.select("a[href*='Advertisement'], a[href*='vacancy'], a[href*='/PVID']"):
            href = a.get("href", "")
            if href:
                links.add(urljoin(url, href))
        # also generic /<digits>.html
        for a in soup.select("a[href*='.html']"):
            href = a.get("href", "")
            if href and re.search(r"/\d{4,}", href):
                links.add(urljoin(url, href))
        added = 0
        for href in list(links)[:14]:
            raw_id = md5_16(href)
            rid = md5_16("topjobs_lk", raw_id)
            if rid in seen:
                continue
            st2, html2 = fetch(href, H)
            polite()
            if st2 != 200:
                continue
            soup2 = BeautifulSoup(html2, "html.parser")
            jl = parse_jsonld_jobposting(soup2)
            title_el = soup2.select_one("h1, h2, title")
            title = jl.get("title") or text_clean(title_el.get_text(" ", strip=True) if title_el else "", 200)
            body_el = soup2.select_one("body")
            desc = jl.get("description") or text_clean(body_el.get_text(" ", strip=True) if body_el else "", 5000)
            obj = {
                "id": rid,
                "raw_id": raw_id,
                "platform": "topjobs_lk",
                "lang": "en",
                "title": title,
                "body": desc[:5000],
                "author": jl.get("company", ""),
                "url": href,
                "country_hint": "LK",
                "matched_keyword": "topjobs",
                "engagement": {"score": 0, "comments": 0, "views": None},
                "company": jl.get("company", ""),
                "location": jl.get("location", ""),
                "salary": jl.get("salary", ""),
                "currency": jl.get("currency", "LKR"),
                "crawled_at": now_iso(),
            }
            append(out, obj)
            seen.add(rid)
            n += 1
            added += 1
        print(f"[topjobs_lk] seed={url[:80]} links={len(links)} new={added} total={n}")
        polite()
    print(f"[topjobs_lk] DONE +{n}")
    return n


# ===================================================================
# LK: DailyMirror.lk Business
# ===================================================================
def crawl_dailymirror_lk():
    out = out_path("dailymirror_lk")
    seen = load_seen(out)
    n = 0
    H = hdr("en-LK")
    feeds = [
        "https://www.dailymirror.lk/business-news/8/rss.xml",
        "https://www.dailymirror.lk/business/215/rss.xml",
        "https://www.dailymirror.lk/business__main/215/rss.xml",
        "https://www.dailymirror.lk/rss.xml",
    ]
    article_urls = set()
    for feed in feeds:
        st, xml = fetch(feed, H)
        polite()
        if st != 200:
            print(f"[dailymirror_lk] feed {feed} status={st}")
            continue
        items = re.findall(r"<item>(.*?)</item>", xml, re.S)
        for it in items:
            link_m = re.search(r"<link>(.*?)</link>", it, re.S)
            if link_m:
                article_urls.add((link_m.group(1) or "").strip())
        print(f"[dailymirror_lk] feed={feed} items={len(items)}")
    print(f"[dailymirror_lk] discovered {len(article_urls)} articles")
    for url in list(article_urls)[:80]:
        raw_id = md5_16(url)
        rid = md5_16("dailymirror_lk", raw_id)
        if rid in seen:
            continue
        st, html = fetch(url, H)
        polite()
        if st != 200:
            continue
        soup = BeautifulSoup(html, "html.parser")
        title_el = soup.select_one("h1") or soup.title
        title = text_clean(title_el.get_text(" ", strip=True) if title_el else "", 200)
        body_el = soup.select_one("[class*=article-content], [itemprop=articleBody], article, main")
        body = text_clean(body_el.get_text(" ", strip=True) if body_el else soup.get_text(" ", strip=True))
        if not has_pay_signal(title + " " + body[:2000]):
            continue
        obj = {
            "id": rid,
            "raw_id": raw_id,
            "platform": "dailymirror_lk",
            "lang": "en",
            "title": title,
            "body": body[:5000],
            "author": "",
            "url": url,
            "country_hint": "LK",
            "matched_keyword": "business",
            "engagement": {"score": 0, "comments": 0, "views": None},
            "crawled_at": now_iso(),
        }
        append(out, obj)
        seen.add(rid)
        n += 1
    print(f"[dailymirror_lk] DONE +{n}")
    return n


# ===================================================================
# NP: MeroJob.com
# ===================================================================
def crawl_merojob():
    out = out_path("merojob")
    seen = load_seen(out)
    n = 0
    H = hdr("en-NP")
    seed_urls = [
        "https://merojob.com/search/?q=software",
        "https://merojob.com/search/?q=accountant",
        "https://merojob.com/search/?q=engineer",
        "https://merojob.com/search/?q=manager",
        "https://merojob.com/search/?q=marketing",
        "https://merojob.com/search/?q=teacher",
        "https://merojob.com/",
    ]
    for url in seed_urls:
        st, html = fetch(url, H)
        if st != 200:
            print(f"[merojob] {url} status={st}")
            polite()
            continue
        soup = BeautifulSoup(html, "html.parser")
        links = set()
        for a in soup.select("a[href*='/job/']"):
            href = a.get("href", "")
            if href:
                links.add(urljoin("https://merojob.com", href))
        added = 0
        for href in list(links)[:14]:
            m = re.search(r"/job/([^?#/]+)", href)
            raw_id = m.group(1) if m else href
            rid = md5_16("merojob", raw_id)
            if rid in seen:
                continue
            st2, html2 = fetch(href, H)
            polite()
            if st2 != 200:
                continue
            soup2 = BeautifulSoup(html2, "html.parser")
            jl = parse_jsonld_jobposting(soup2)
            title = jl.get("title") or text_clean((soup2.select_one("h1") or soup2.title).get_text(" ", strip=True) if (soup2.select_one("h1") or soup2.title) else "", 200)
            body_el = soup2.select_one("[class*=job-detail], [class*=description], main, article")
            desc = jl.get("description") or text_clean(body_el.get_text(" ", strip=True) if body_el else soup2.get_text(" ", strip=True))
            sal = jl.get("salary") or ""
            if not sal:
                m = re.search(r"NPR\s?[\d,]+(?:\s?-\s?[\d,]+)?|Rs\.?\s?[\d,]+", desc, re.I)
                if m:
                    sal = m.group(0)
            obj = {
                "id": rid,
                "raw_id": raw_id,
                "platform": "merojob",
                "lang": "en",
                "title": title,
                "body": desc[:5000],
                "author": jl.get("company", ""),
                "url": href,
                "country_hint": "NP",
                "matched_keyword": "merojob",
                "engagement": {"score": 0, "comments": 0, "views": None},
                "company": jl.get("company", ""),
                "location": jl.get("location", ""),
                "salary": sal,
                "currency": jl.get("currency", "NPR"),
                "crawled_at": now_iso(),
            }
            append(out, obj)
            seen.add(rid)
            n += 1
            added += 1
        print(f"[merojob] seed={url} links={len(links)} new={added} total={n}")
        polite()
    print(f"[merojob] DONE +{n}")
    return n


# ===================================================================
# Sample printer
# ===================================================================
def print_samples(label, k=3):
    p = out_path(label)
    if not p.exists():
        print(f"[{label}] file missing: {p}")
        return 0
    lines = p.read_text(encoding="utf-8").splitlines()
    print(f"\n=== {label}: {p} | {len(lines)} lines ===")
    for ln in lines[:k]:
        try:
            o = json.loads(ln)
            t = (o.get("title") or "").replace("\n", " ")[:120]
            b = (o.get("body") or "").replace("\n", " ")[:200]
            extras = []
            for f in ("salary", "company", "location", "currency"):
                v = o.get(f)
                if v:
                    extras.append(f"{f}={v}")
            print(f"  - kw={o.get('matched_keyword')!r} | {t}")
            if extras:
                print(f"    " + " | ".join(extras))
            print(f"    body: {b}...")
        except Exception as e:
            print(f"  parse err: {e}")
    return len(lines)


# ===================================================================
# main
# ===================================================================
TASKS = [
    ("naukri",         crawl_naukri),
    ("jobbuzz",        crawl_jobbuzz),
    ("quikr",          crawl_quikr),
    ("shine",          crawl_shine),
    ("moneycontrol",   crawl_moneycontrol),
    ("rozee",          crawl_rozee),
    ("pakwheels",      crawl_pakwheels_forum),
    ("bdjobs",         crawl_bdjobs),
    ("prothomalo",     crawl_prothomalo),
    ("topjobs_lk",     crawl_topjobs_lk),
    ("dailymirror_lk", crawl_dailymirror_lk),
    ("merojob",        crawl_merojob),
]


if __name__ == "__main__":
    only = set(sys.argv[1:]) if len(sys.argv) > 1 else None
    summary = []
    for name, fn in TASKS:
        if only and name not in only:
            continue
        print(f"\n========== {name} ==========")
        try:
            added = fn()
        except Exception as e:
            print(f"[{name}] FATAL: {e}")
            traceback.print_exc()
            added = 0
        summary.append((name, added))
    print("\n========== SAMPLES ==========")
    file_lines = {}
    for name, _ in TASKS:
        if only and name not in only:
            continue
        file_lines[name] = print_samples(name)
    print("\n========== TOTAL ==========")
    grand = 0
    for name, added in summary:
        flines = file_lines.get(name, 0)
        print(f"  {name:18s} +{added:4d}   file_lines={flines}")
        grand += added
    print(f"  GRAND TOTAL: +{grand}")
