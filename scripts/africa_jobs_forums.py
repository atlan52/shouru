"""非洲非 Reddit 本地求职 + 财经论坛抓取 (NG / KE / ZA / GH / EG / ET).

覆盖站点（每个独立输出 jsonl，schema 同 r_mexico_native）：
  NG 尼日利亚
    - nairaland_business : Nairaland /business + /jobs-vacancies + /career
    - jobberman          : jobberman.com /jobs?q=
    - myjobmag_ng        : myjobmag.com /jobs?q=
    - hotnigerianjobs    : hotnigerianjobs.com 首页 + /tag/job/
  KE 肯尼亚
    - myjobmag_ke        : myjobmag.co.ke /jobs
    - brightermonday     : brightermonday.co.ke /jobs?q=
    - careerpoint_ke     : careerpointkenya.co.ke
  ZA 南非
    - careers24          : careers24.com /jobs/k-<role>/
    - careerjunction     : careerjunction.co.za /jobs/
    - mybroadband_forum  : mybroadband.co.za/forum/forums/
  GH 加纳
    - jobsinghana        : jobsinghana.com
    - jobhouse_gh        : jobhouse.com.gh
  EG 埃及（英语 +阿语界面，用英语关键词）
    - gulftalent_eg      : gulftalent.com/egypt-jobs/
    - forsa_eg           : forsa.com.eg
  ET 埃塞俄比亚
    - ethiojobs          : ethiojobs.net

抓取策略：
  1. 列表页 2-3 页 → 收集详情链接（job listing thread）
  2. 详情页：JSON-LD JobPosting 优先，否则 h1 + main 文本
  3. 关键词过滤（含数字 / 货币）：salary, naira, shilling, rand, cedi,
     birr, USD, package, ctc, freelance, remote, EGP, GHS, KES, NGN, ZAR
  4. UA Chrome/124, Accept-Language en-NG/KE/ZA/GH/EG/ET
  5. polite 1.5s; 4xx/5xx 跳过；Cloudflare 退站
  6. 输出 data/raw/<site>_native_<DAY>.jsonl

CLI: python scripts/africa_jobs_forums.py [site_id ...]
"""
import json, hashlib, re, time, random, sys, traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, quote
import requests
from bs4 import BeautifulSoup

# ---- common --------------------------------------------------------------

UA_BROWSER = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DAY = datetime.now().strftime("%Y%m%d")
OUT_DIR = Path("data/raw")

ACCEPT_LANG = {
    "NG": "en-NG,en;q=0.9",
    "KE": "en-KE,en-GB;q=0.9,en;q=0.8",
    "ZA": "en-ZA,en-GB;q=0.9,en;q=0.8",
    "GH": "en-GH,en-GB;q=0.9,en;q=0.8",
    "EG": "en-EG,en;q=0.9,ar;q=0.6",
    "ET": "en-ET,en;q=0.9,am;q=0.5",
}

CURRENCY_HINT = {
    "NG": "NGN",
    "KE": "KES",
    "ZA": "ZAR",
    "GH": "GHS",
    "EG": "EGP",
    "ET": "ETB",
}

# 各国/求职常见角色关键词（搜索词）。英语为主。
ROLES = [
    "engineer", "developer", "accountant", "manager", "sales", "teacher",
    "nurse", "designer",
]

# 工资 / 收入信号：货币符号 + 关键词
SALARY_RE = re.compile(
    r"(?:N|₦|NGN|KSh|Ksh|KES|R\s?\d|ZAR|GH|GHS|GH₵|EGP|LE|ETB|USD|US\$|\$)\s?[\d\.,]+|"
    r"\b\d{2,3}[,\.]\d{3}\b|"  # 50,000 / 50.000
    r"\b\d{4,}\b\s?(?:per\s?month|monthly|p\.?m\.?|per\s?year|annum|p\.?a\.?|"
    r"naira|shilling|rand|cedi|birr|pound|dollar)",
    re.I,
)
NUM_RE = re.compile(r"\d{3,}")

KEYWORDS = [
    "salary", "naira", "shilling", "rand", "cedi", "birr", "usd",
    "package", "ctc", "freelance", "remote", "wage", "earn", "income",
    "monthly", "annual", "per month", "per annum", "compensation",
]


def hdr(country):
    return {
        "User-Agent": UA_BROWSER,
        "Accept-Language": ACCEPT_LANG.get(country, "en;q=0.9"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


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


def is_cloudflare(text):
    head = text[:3000].lower()
    if "just a moment" in head or "cf-chl" in head or "checking your browser" in head:
        return True
    if "attention required" in head and "cloudflare" in head:
        return True
    return False


def fetch(url, country, params=None, timeout=25, max_retry=2):
    for i in range(max_retry):
        try:
            r = requests.get(url, params=params, headers=hdr(country), timeout=timeout)
            if r.status_code == 200:
                if is_cloudflare(r.text):
                    return None, "cloudflare"
                return r, "ok"
            if r.status_code in (403, 429, 503):
                if r.status_code == 403 and is_cloudflare(r.text):
                    return None, "cloudflare"
                if i + 1 < max_retry:
                    time.sleep(2 + i * 2)
                    continue
                return None, f"status_{r.status_code}"
            return None, f"status_{r.status_code}"
        except requests.RequestException as e:
            if i + 1 < max_retry:
                time.sleep(2)
                continue
            return None, f"err:{type(e).__name__}"
    return None, "exhausted"


def parse_jsonld_jobposting(soup):
    """First JobPosting on page → title/desc/salary/empresa/loc."""
    out = {"salario": "", "empresa": "", "ubicacion": "", "title": "", "description": ""}
    for s in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            txt = (s.string or s.get_text() or "").strip()
            if not txt:
                continue
            j = json.loads(txt)
        except Exception:
            continue
        candidates = j if isinstance(j, list) else [j]
        # also handle @graph wrapper
        flat = []
        for c in candidates:
            if isinstance(c, dict) and isinstance(c.get("@graph"), list):
                flat.extend(c["@graph"])
            else:
                flat.append(c)
        for c in flat:
            if not isinstance(c, dict):
                continue
            t = c.get("@type")
            if isinstance(t, list):
                if "JobPosting" not in t:
                    continue
            elif t != "JobPosting":
                continue
            if c.get("title") and not out["title"]:
                out["title"] = str(c.get("title"))[:200]
            if c.get("description") and not out["description"]:
                desc = re.sub(r"<[^>]+>", " ", str(c.get("description")))
                out["description"] = re.sub(r"\s+", " ", desc).strip()[:5000]
            bs = c.get("baseSalary") or {}
            if isinstance(bs, dict) and not out["salario"]:
                cu = bs.get("currency", "")
                v = bs.get("value", {})
                if isinstance(v, dict):
                    mn = v.get("minValue")
                    mx = v.get("maxValue")
                    unit = v.get("unitText", "")
                    if mn or mx:
                        out["salario"] = f"{mn or ''}-{mx or ''} {cu} {unit}".strip(" -")
                elif isinstance(v, (int, float, str)) and v:
                    out["salario"] = f"{v} {cu}".strip()
            org = c.get("hiringOrganization") or {}
            if isinstance(org, dict) and not out["empresa"]:
                out["empresa"] = str(org.get("name") or "")[:200]
            loc = c.get("jobLocation")
            if isinstance(loc, list) and loc:
                loc = loc[0]
            if isinstance(loc, dict) and not out["ubicacion"]:
                addr = loc.get("address") or {}
                if isinstance(addr, dict):
                    out["ubicacion"] = ", ".join(
                        x for x in [addr.get("addressLocality"),
                                    addr.get("addressRegion"),
                                    addr.get("addressCountry")] if x
                    )[:200]
            return out
    return out


def has_money_signal(*texts):
    blob = " ".join(t or "" for t in texts)
    if SALARY_RE.search(blob):
        return True
    low = blob.lower()
    if any(k in low for k in KEYWORDS) and NUM_RE.search(blob):
        return True
    return False


def matched_keyword(*texts):
    low = " ".join(t or "" for t in texts).lower()
    for k in KEYWORDS:
        if k in low:
            return k
    return ""


def harvest_links(soup, base_url, link_filter):
    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        full = urljoin(base_url, href).split("#")[0]
        if not link_filter(full):
            continue
        if full in seen:
            continue
        seen.add(full)
        out.append(full)
    return out


def fetch_detail(url, country):
    r, status = fetch(url, country)
    if r is None:
        return None, status
    soup = BeautifulSoup(r.text, "html.parser")
    jl = parse_jsonld_jobposting(soup)
    desc = jl.get("description") or ""
    if not desc:
        cand = (
            soup.select_one("[class*=job-description]")
            or soup.select_one("[class*=jobdescription]")
            or soup.select_one("[class*=description]")
            or soup.select_one("[class*=detail]")
            or soup.select_one("article")
            or soup.select_one("main")
            or soup.select_one(".narrow")  # nairaland
            or soup.select_one(".bbWrapper")  # xenforo (mybroadband)
            or soup.select_one(".messageContent")
        )
        if cand:
            desc = re.sub(r"\s+", " ", cand.get_text(" ", strip=True))[:5000]
        else:
            desc = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:5000]
    title = jl.get("title")
    if not title:
        h = soup.find(["h1", "h2"])
        if h:
            title = h.get_text(" ", strip=True)[:200]
    if not title:
        # <title> tag
        tt = soup.find("title")
        if tt:
            title = tt.get_text(" ", strip=True)[:200]
    return {
        "title": title or "",
        "description": desc,
        "salario": jl.get("salario", ""),
        "empresa": jl.get("empresa", ""),
        "ubicacion": jl.get("ubicacion", ""),
    }, "ok"


# ---- listing strategies --------------------------------------------------

def crawl_search_role(site_id, country, list_url_tpl, link_filter, out_path,
                      max_per_role=10, max_total=120, lang="en"):
    """通用 search ?q=<role> 翻一页详情。"""
    seen = load_seen(out_path)
    n = 0
    for role in ROLES:
        if n >= max_total:
            break
        url = list_url_tpl.format(role=quote(role))
        r, status = fetch(url, country)
        if r is None:
            print(f"[{site_id}] role={role!r} list status={status}")
            polite()
            if status == "cloudflare":
                print(f"[{site_id}] cloudflare — abort site")
                return n
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        links = harvest_links(soup, url, link_filter)
        if not links:
            head = re.sub(r"\s+", " ", r.text[:240])
            print(f"[{site_id}] role={role!r} 0 links. head={head}")
            polite()
            continue
        picked = 0
        for href in links:
            if picked >= max_per_role or n >= max_total:
                break
            raw_id = re.sub(r"^https?://[^/]+/", "", href).split("?")[0]
            rid = md5_16(site_id, raw_id)
            if rid in seen:
                continue
            d, dstatus = fetch_detail(href, country)
            polite()
            if d is None:
                continue
            title = d["title"]
            if not title or len(title) < 4:
                continue
            body = d["description"]
            if not has_money_signal(body, d["salario"], title):
                continue
            kw = matched_keyword(body, title) or role
            obj = {
                "id": rid,
                "raw_id": raw_id,
                "platform": site_id,
                "lang": lang,
                "title": title[:200],
                "body": body[:5000],
                "author": d["empresa"][:200] if d["empresa"] else "",
                "url": href,
                "country_hint": country,
                "matched_keyword": kw,
                "engagement": {"score": 0, "comments": 0},
                "empresa": d["empresa"][:200] if d["empresa"] else "",
                "ubicacion": d["ubicacion"][:200] if d["ubicacion"] else "",
                "salario": d["salario"][:300] if d["salario"] else "",
                "currency_hint": CURRENCY_HINT.get(country, ""),
                "crawled_at": now_iso(),
            }
            append(out_path, obj)
            seen.add(rid)
            n += 1
            picked += 1
        print(f"[{site_id}] role={role!r} links={len(links)} picked={picked} total={n}")
        polite()
    return n


def crawl_paginated_lists(site_id, country, list_urls, link_filter, out_path,
                          page_count=3, page_param=None, max_total=200, lang="en"):
    """单/多个 list URL 翻 N 页（page_param 决定 ?page= 或 ?p= 或 None=URL 末尾追加）。

    list_urls: [(label, base_url, page_url_fn or None)]
        page_url_fn(base_url, page_int) -> str
    若 page_url_fn 为 None：page=1 用 base_url；page>=2 加 ?page={N}
    """
    seen = load_seen(out_path)
    n = 0
    for label, base_url, page_fn in list_urls:
        if n >= max_total:
            break
        for p in range(1, page_count + 1):
            if n >= max_total:
                break
            url = base_url if p == 1 and page_fn is None else (
                page_fn(base_url, p) if page_fn else f"{base_url}{'&' if '?' in base_url else '?'}page={p}"
            )
            r, status = fetch(url, country)
            if r is None:
                print(f"[{site_id}] {label} p={p} status={status}")
                polite()
                if status == "cloudflare":
                    return n
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            links = harvest_links(soup, url, link_filter)
            if not links:
                head = re.sub(r"\s+", " ", r.text[:240])
                print(f"[{site_id}] {label} p={p} 0 links. head={head}")
                polite()
                continue
            picked = 0
            for href in links:
                if n >= max_total:
                    break
                raw_id = re.sub(r"^https?://[^/]+/", "", href).split("?")[0]
                rid = md5_16(site_id, raw_id)
                if rid in seen:
                    continue
                d, dstatus = fetch_detail(href, country)
                polite()
                if d is None:
                    continue
                title = d["title"]
                if not title or len(title) < 4:
                    continue
                body = d["description"]
                if not has_money_signal(body, d["salario"], title):
                    continue
                kw = matched_keyword(body, title) or label
                obj = {
                    "id": rid,
                    "raw_id": raw_id,
                    "platform": site_id,
                    "lang": lang,
                    "title": title[:200],
                    "body": body[:5000],
                    "author": d["empresa"][:200] if d["empresa"] else "",
                    "url": href,
                    "country_hint": country,
                    "matched_keyword": kw,
                    "engagement": {"score": 0, "comments": 0},
                    "empresa": d["empresa"][:200] if d["empresa"] else "",
                    "ubicacion": d["ubicacion"][:200] if d["ubicacion"] else "",
                    "salario": d["salario"][:300] if d["salario"] else "",
                    "currency_hint": CURRENCY_HINT.get(country, ""),
                    "section": label,
                    "crawled_at": now_iso(),
                }
                append(out_path, obj)
                seen.add(rid)
                n += 1
                picked += 1
            print(f"[{site_id}] {label} p={p} links={len(links)} picked={picked} total={n}")
            polite()
    return n


# ---- per-site link filters ----------------------------------------------

# Nairaland: /<numeric_id>/<slug>  (also /<slug> for boards). Detail = numeric leading.
def lf_nairaland(u):
    if "nairaland.com" not in u:
        return False
    p = urlparse(u).path
    # e.g. /6987654/why-i-quit-my-job  → numeric first segment
    m = re.match(r"^/(\d{4,})/[A-Za-z0-9\-_]+", p)
    return bool(m)


def lf_jobberman(u):
    return "jobberman.com" in u and "/listings/" in u


def lf_myjobmag_ng(u):
    return "myjobmag.com" in u and (
        "/job/" in u or "/job-vacancy/" in u or "/job-vacancies-" in u
    )


def lf_myjobmag_ke(u):
    return "myjobmag.co.ke" in u and (
        "/job/" in u or "/job-vacancy/" in u or "/job-vacancies-" in u
    )


def lf_hotnigerianjobs(u):
    if "hotnigerianjobs.com" not in u:
        return False
    p = urlparse(u).path
    # detail pages: /hot-jobs/<n>/<slug>.html or /hotjobs/<n>/<slug>.html
    return bool(re.search(r"/hot[\-_]?jobs?/\d+/.+?\.html", p, re.I))


def lf_brightermonday(u):
    return "brightermonday.co.ke" in u and "/listings/" in u


def lf_careerpoint_ke(u):
    if "careerpointkenya.co.ke" not in u:
        return False
    p = urlparse(u).path
    # post-style permalink ending with /
    return bool(re.search(r"/[a-z0-9\-]{20,}/?$", p, re.I))


def lf_careers24(u):
    return "careers24.com" in u and ("/jobs/ads/" in u or "/jobs/job-" in u)


def lf_careerjunction(u):
    return "careerjunction.co.za" in u and ("/jobs/job-detail/" in u or "/jobs/" in u and re.search(r"/\d{6,}", u))


def lf_mybroadband_forum(u):
    if "mybroadband.co.za" not in u:
        return False
    p = urlparse(u).path
    # XenForo thread URLs: /forum/threads/<slug>.<id>/
    return bool(re.search(r"/forum/threads/[^/]+\.\d+", p))


def lf_jobsinghana(u):
    if "jobsinghana.com" not in u:
        return False
    p = urlparse(u).path
    return ("/jobs/" in p and re.search(r"/\d{4,}", p)) or "/job/" in p


def lf_jobhouse_gh(u):
    return "jobhouse.com.gh" in u and ("/job/" in u or "/jobs/" in u and re.search(r"/\d{4,}", u))


def lf_gulftalent_eg(u):
    return "gulftalent.com" in u and "/job/" in u


def lf_forsa_eg(u):
    return "forsa.com.eg" in u and ("/job/" in u or "/jobs/" in u and re.search(r"/\d{3,}", u))


def lf_ethiojobs(u):
    return "ethiojobs.net" in u and (
        "/job/" in u or "/jobs/" in u and re.search(r"/\d{4,}", u)
    )


# ---- Nairaland board-page handling --------------------------------------

def crawl_nairaland(site_id, country, out_path, max_total=180):
    """Nairaland 三个 board，每个翻 5 页。Board URL 模式：
       /business, /business/0, /business/1, /business/2 ... /business/4
    详情页：/<id>/<slug>。
    """
    boards = [
        ("business", "https://www.nairaland.com/business"),
        ("jobs-vacancies", "https://www.nairaland.com/jobs-vacancies"),
        ("career", "https://www.nairaland.com/career"),
    ]
    list_urls = []
    for label, base in boards:
        # nairaland board pagination is /<board>/<pageIndex 0-based>
        def make_page(b):
            def fn(_url, p):
                return b if p == 1 else f"{b}/{p-1}"
            return fn
        list_urls.append((label, base, make_page(base)))
    return crawl_paginated_lists(
        site_id, country, list_urls, lf_nairaland, out_path,
        page_count=5, max_total=max_total, lang="en",
    )


# ---- MyBroadband XenForo forum ------------------------------------------

def crawl_mybroadband(site_id, country, out_path, max_total=120):
    """XenForo 子论坛 — 抓 finance/employment 两个 forum 列表的前 3 页。"""
    forums = [
        # Forum slugs based on mybroadband.co.za/forum structure
        ("the-money-and-business-forum",
         "https://mybroadband.co.za/forum/forums/the-money-and-business-forum.16/"),
        ("careers-and-employment",
         "https://mybroadband.co.za/forum/forums/careers-and-employment.18/"),
        ("personal-finance",
         "https://mybroadband.co.za/forum/forums/personal-finance.111/"),
    ]
    list_urls = []
    for label, base in forums:
        def make_fn(b):
            def fn(_url, p):
                return b if p == 1 else f"{b}page-{p}"
            return fn
        list_urls.append((label, base, make_fn(base)))
    return crawl_paginated_lists(
        site_id, country, list_urls, lf_mybroadband_forum, out_path,
        page_count=3, max_total=max_total, lang="en",
    )


# ---- HotNigerianJobs special (paginated index)  ----------------------------

def crawl_hotnigerianjobs(site_id, country, out_path, max_total=100):
    """homepage + /hot-jobs/page/<n> 翻几页。"""
    list_urls = [
        ("home", "https://hotnigerianjobs.com/", lambda u, p: u if p == 1 else f"{u}page/{p}/"),
        ("hot-jobs", "https://hotnigerianjobs.com/hot-jobs/",
         lambda u, p: u if p == 1 else f"{u}page/{p}/"),
    ]
    return crawl_paginated_lists(
        site_id, country, list_urls, lf_hotnigerianjobs, out_path,
        page_count=3, max_total=max_total, lang="en",
    )


# ---- CareerPoint Kenya (WP-style index) ---------------------------------

def crawl_careerpoint_ke(site_id, country, out_path, max_total=80):
    list_urls = [
        ("jobs", "https://www.careerpointkenya.co.ke/category/jobs-in-kenya/",
         lambda u, p: u if p == 1 else f"{u}page/{p}/"),
        ("home", "https://www.careerpointkenya.co.ke/",
         lambda u, p: u if p == 1 else f"{u}page/{p}/"),
    ]
    return crawl_paginated_lists(
        site_id, country, list_urls, lf_careerpoint_ke, out_path,
        page_count=3, max_total=max_total, lang="en",
    )


# ---- site definitions ----------------------------------------------------

# search-style sites (?q=role / k-role/ ...)
SEARCH_SITES = [
    # (site_id, country, tpl, link_filter, fname)
    ("jobberman", "NG",
     "https://www.jobberman.com/jobs?q={role}",
     lf_jobberman, "jobberman_native"),
    ("myjobmag_ng", "NG",
     "https://www.myjobmag.com/jobs?q={role}",
     lf_myjobmag_ng, "myjobmag_ng_native"),
    ("myjobmag_ke", "KE",
     "https://www.myjobmag.co.ke/jobs?q={role}",
     lf_myjobmag_ke, "myjobmag_ke_native"),
    ("brightermonday", "KE",
     "https://www.brightermonday.co.ke/jobs?q={role}",
     lf_brightermonday, "brightermonday_native"),
    ("careers24", "ZA",
     "https://www.careers24.com/jobs/k-{role}/",
     lf_careers24, "careers24_native"),
    ("careerjunction", "ZA",
     "https://www.careerjunction.co.za/jobs/?q={role}",
     lf_careerjunction, "careerjunction_native"),
    ("jobsinghana", "GH",
     "https://www.jobsinghana.com/jobs?keyword={role}",
     lf_jobsinghana, "jobsinghana_native"),
    ("jobhouse_gh", "GH",
     "https://www.jobhouse.com.gh/jobs?q={role}",
     lf_jobhouse_gh, "jobhouse_gh_native"),
    ("gulftalent_eg", "EG",
     "https://www.gulftalent.com/egypt-jobs?keyword={role}",
     lf_gulftalent_eg, "gulftalent_eg_native"),
    ("forsa_eg", "EG",
     "https://forsa.com.eg/jobs?q={role}",
     lf_forsa_eg, "forsa_eg_native"),
    ("ethiojobs", "ET",
     "https://www.ethiojobs.net/?q={role}",
     lf_ethiojobs, "ethiojobs_native"),
]

# special crawlers (boards / paginated indexes)
SPECIAL_SITES = [
    # site_id, country, fname, fn(site_id, country, out_path)
    ("nairaland_business", "NG", "nairaland_business_native", crawl_nairaland),
    ("hotnigerianjobs", "NG", "hotnigerianjobs_native", crawl_hotnigerianjobs),
    ("careerpoint_ke", "KE", "careerpoint_ke_native", crawl_careerpoint_ke),
    ("mybroadband_forum", "ZA", "mybroadband_forum_native", crawl_mybroadband),
]


def print_samples(path, label, k=2):
    if not path.exists():
        print(f"[{label}] file missing")
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    print(f"=== {label}: {path.name} | {len(lines)} lines ===")
    for ln in lines[:k]:
        try:
            o = json.loads(ln)
            t = (o.get("title") or "")[:90]
            sal = o.get("salario", "")
            emp = o.get("empresa", "")
            print(f"  - {t} | salario={sal!r} | empresa={emp!r}")
        except Exception as e:
            print(f"  parse err: {e}")
    return len(lines)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    results = {}

    for site_id, country, tpl, lf, fname in SEARCH_SITES:
        if only and site_id not in only:
            continue
        out_path = OUT_DIR / f"{fname}_{DAY}.jsonl"
        print(f"\n###### {site_id} ({country}) -> {out_path}")
        try:
            n = crawl_search_role(site_id, country, tpl, lf, out_path)
        except Exception as e:
            print(f"[{site_id}] FATAL {e}")
            traceback.print_exc()
            n = 0
        results[site_id] = (out_path, n)

    for site_id, country, fname, fn in SPECIAL_SITES:
        if only and site_id not in only:
            continue
        out_path = OUT_DIR / f"{fname}_{DAY}.jsonl"
        print(f"\n###### {site_id} ({country}) -> {out_path}")
        try:
            n = fn(site_id, country, out_path)
        except Exception as e:
            print(f"[{site_id}] FATAL {e}")
            traceback.print_exc()
            n = 0
        results[site_id] = (out_path, n)

    print("\n\n========= SUMMARY =========")
    grand = 0
    for site_id, (path, n) in results.items():
        ln = print_samples(path, site_id)
        grand += ln
    print(f"\nTOTAL across {len(results)} sites: {grand} lines")


if __name__ == "__main__":
    main()
