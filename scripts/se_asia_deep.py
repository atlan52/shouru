"""SE Asia 深挖：VN/TH/ID/MY 非 Reddit 本地求职站 + 财经 RSS。

目标站点（每国都拿求职 listing+详情 + 财经 RSS 关键词过滤）：

VN: VietnamWorks, TopCV, CareerBuilder VN, ITviec, ZingNews kinh-doanh RSS,
    Soha kinh-doanh RSS, CafeF tai-chinh-quoc-te + thi-truong-chung-khoan RSS
TH: JobsDB Thailand, JobThai, JobBKK, Pantip mobile, Prachachat RSS
ID: JobStreet ID, Karier.com, GajiMu, Bisnis.com RSS, CNBC Indonesia RSS
MY: JobStreet MY, MalaysianPaySlip, TheStar Business RSS, TheEdge.my

逻辑：
- 求职站翻 2-3 页 → 详情。详情提 title + 描述 + 工资。优先 JSON-LD JobPosting。
- RSS 拉 → 关键词过滤。
- UA Chrome/124, Accept-Language 按国。polite 1.5s。
- 4xx/5xx 跳过；cloudflare(403/503/cf-ray header)退站。
- 输出 schema 同 r_mexico_native。每站一文件。country_hint 按域名。
"""
import json, hashlib, re, time, random, html
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, quote
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
DAY = datetime.now().strftime("%Y%m%d")
RAW = Path("data/raw")

# Per-country headers
HDR_VN = {"User-Agent": UA, "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.5",
          "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
HDR_TH = {"User-Agent": UA, "Accept-Language": "th-TH,th;q=0.9,en;q=0.5",
          "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
HDR_ID = {"User-Agent": UA, "Accept-Language": "id-ID,id;q=0.9,en;q=0.5",
          "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
HDR_MY = {"User-Agent": UA, "Accept-Language": "ms-MY,ms;q=0.9,en;q=0.7",
          "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

KEYWORDS = {
    "VN": ["lương", "thu nhập", "kiếm tiền", "freelance", "lương kỹ sư",
           "lương lập trình", "triệu/tháng", "triệu một tháng", "lương tháng"],
    "TH": ["เงินเดือน", "รายได้", "freelance", "อาชีพ", "บาท",
           "บาทต่อเดือน", "ฟรีแลนซ์", "เงินได้"],
    "ID": ["gaji", "pendapatan", "freelance", "kerja remote", "IDR",
           "juta/bulan", "juta per bulan", "rupiah", "penghasilan"],
    "MY": ["gaji", "pendapatan", "EPF", "KWSP", "freelance", "RM", "MYR",
           "ringgit", "pendapatan bulanan"],
}


def md5_16(*p): return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]
def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def polite(): time.sleep(random.uniform(1.2, 1.9))


def append(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def load_seen(path):
    seen = set()
    if path.exists():
        for line in path.open(encoding="utf-8"):
            try: seen.add(json.loads(line)["id"])
            except Exception: pass
    return seen


def is_cf_block(r):
    if r.status_code in (403, 503):
        return True
    if r.headers.get("cf-ray") and r.status_code != 200:
        return True
    if "Just a moment" in r.text[:2000] or "challenge-platform" in r.text[:2000]:
        return True
    return False


def safe_get(url, headers, params=None, timeout=22):
    try:
        r = requests.get(url, headers=headers, params=params, timeout=timeout)
        return r
    except Exception as e:
        print(f"  [GET err] {url[:80]}: {e}")
        return None


def parse_jsonld_jobposting(soup):
    """Extract JobPosting JSON-LD: returns dict with title/desc/salary/employer/loc."""
    out = {}
    for s in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            txt = s.string or s.get_text() or ""
            txt = txt.strip()
            if not txt: continue
            j = json.loads(txt)
            cand = []
            if isinstance(j, list): cand.extend(j)
            elif isinstance(j, dict):
                if "@graph" in j and isinstance(j["@graph"], list):
                    cand.extend(j["@graph"])
                else:
                    cand.append(j)
            for it in cand:
                if not isinstance(it, dict): continue
                if it.get("@type") != "JobPosting": continue
                out["title"] = it.get("title", "") or out.get("title", "")
                desc = it.get("description", "") or ""
                if desc:
                    desc = re.sub(r"<[^>]+>", " ", desc)
                    desc = html.unescape(desc)
                    desc = re.sub(r"\s+", " ", desc).strip()
                    out["description"] = desc
                bs = it.get("baseSalary") or {}
                if isinstance(bs, dict):
                    v = bs.get("value") or {}
                    cu = bs.get("currency", "") or ""
                    if isinstance(v, dict):
                        mn = v.get("minValue"); mx = v.get("maxValue"); val = v.get("value")
                        unit = v.get("unitText", "")
                        bits = [str(mn) if mn else "", str(mx) if mx else "", str(val) if val else "", cu, unit]
                        out["salary"] = " ".join(b for b in bits if b).strip()
                org = it.get("hiringOrganization") or {}
                if isinstance(org, dict):
                    out["employer"] = org.get("name", "") or ""
                loc = it.get("jobLocation")
                if isinstance(loc, list) and loc: loc = loc[0]
                if isinstance(loc, dict):
                    addr = loc.get("address") or {}
                    if isinstance(addr, dict):
                        out["location"] = ", ".join(
                            v for v in [addr.get("addressLocality"),
                                        addr.get("addressRegion"),
                                        addr.get("addressCountry")] if v
                        )
                if out.get("description"): return out
        except Exception:
            continue
    return out


def parse_rss(xml_text):
    """Tiny RSS/Atom parser → list of {title, link, desc}."""
    items = []
    soup = BeautifulSoup(xml_text, "xml")
    for it in soup.find_all(["item", "entry"]):
        title_el = it.find("title")
        link_el = it.find("link")
        desc_el = it.find("description") or it.find("summary") or it.find("content")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        if link_el:
            link = link_el.get("href") or link_el.get_text(strip=True)
        else:
            link = ""
        desc = desc_el.get_text(" ", strip=True) if desc_el else ""
        # strip leftover html
        desc = re.sub(r"<[^>]+>", " ", desc)
        desc = re.sub(r"\s+", " ", desc).strip()
        items.append({"title": title, "link": link, "desc": desc})
    return items


def kw_match(text, kws):
    low = text.lower()
    for k in kws:
        if k.lower() in low:
            return k
    return ""


# ============================================================
# 通用：求职站 listing+详情抓取器
# ============================================================
def crawl_jobsite(*, platform, country, lang, headers, list_url_fn,
                  roles, pages=2, card_selectors, link_filter,
                  base_url, max_per_role=8):
    """
    list_url_fn(role, page) -> URL string
    card_selectors: list of CSS selectors to find job cards
    link_filter: lambda href -> bool (keep only real job detail links)
    """
    out_path = RAW / f"{platform}_native_{DAY}.jsonl"
    seen = load_seen(out_path)
    n = 0
    for role in roles:
        for page in range(1, pages + 1):
            url = list_url_fn(role, page)
            r = safe_get(url, headers)
            if r is None: polite(); continue
            if is_cf_block(r):
                print(f"[{platform}] CF block role={role} p={page} → skip site")
                return n
            if r.status_code != 200:
                print(f"[{platform}] role={role} p={page} status={r.status_code}")
                polite(); continue
            soup = BeautifulSoup(r.text, "html.parser")
            cards = []
            for sel in card_selectors:
                cards.extend(soup.select(sel))
            # Dedup by element id
            uniq = []
            seen_eid = set()
            for c in cards:
                if id(c) in seen_eid: continue
                seen_eid.add(id(c)); uniq.append(c)
            picked = 0
            for c in uniq:
                if picked >= max_per_role: break
                a = c if (c.name == "a" and c.get("href")) else (c.select_one("a[href]"))
                if not a: continue
                href = a.get("href", "")
                if not href: continue
                if not href.startswith("http"):
                    href = urljoin(base_url, href)
                if not link_filter(href): continue
                rid_raw = re.sub(r"[#?].*$", "", href)
                rid = md5_16(platform, rid_raw)
                if rid in seen: continue
                title = (a.select_one("h1,h2,h3,[class*=title],[class*=Title]") or a).get_text(" ", strip=True)
                if not title or len(title) < 4: continue
                # detail
                dr = safe_get(href, headers)
                polite()
                description = ""; salary = ""; employer = ""; location = ""
                if dr is not None and dr.status_code == 200 and not is_cf_block(dr):
                    dsoup = BeautifulSoup(dr.text, "html.parser")
                    jl = parse_jsonld_jobposting(dsoup)
                    if jl.get("description"): description = jl["description"]
                    if jl.get("salary"): salary = jl["salary"]
                    if jl.get("employer"): employer = jl["employer"]
                    if jl.get("location"): location = jl["location"]
                    if not description:
                        # heuristic main content
                        main = (dsoup.select_one("article")
                                or dsoup.select_one("[class*=description]")
                                or dsoup.select_one("[class*=Description]")
                                or dsoup.select_one("[class*=detail]")
                                or dsoup.select_one("[class*=content]")
                                or dsoup.select_one("main"))
                        if main:
                            description = re.sub(r"\s+", " ", main.get_text(" ", strip=True))[:5000]
                # try to extract salary digits from description / card text if absent
                card_text = c.get_text(" ", strip=True)
                if not salary:
                    m = re.search(
                        r"(\d{1,3}(?:[.,]\d{3})*(?:\s?-\s?\d{1,3}(?:[.,]\d{3})*)?\s?"
                        r"(?:VND|đ|triệu|million|THB|บาท|baht|IDR|Rp|juta|MYR|RM|ringgit|USD|\$))",
                        (description + " " + card_text), re.I)
                    if m: salary = m.group(0).strip()
                obj = {
                    "id": rid,
                    "raw_id": rid_raw,
                    "platform": platform,
                    "lang": lang,
                    "title": title,
                    "body": (description or card_text)[:5000],
                    "author": employer,
                    "url": href,
                    "country_hint": country,
                    "matched_keyword": role,
                    "engagement": {"score": 0, "comments": 0, "views": None},
                    "employer": employer,
                    "location": location,
                    "salary": salary,
                    "crawled_at": now_iso(),
                }
                append(out_path, obj); seen.add(rid); n += 1; picked += 1
            print(f"[{platform}] role={role!r} p={page} cards={len(uniq)} picked={picked} total={n}")
            polite()
    print(f"[{platform}] DONE +{n}")
    return n


# ============================================================
# 通用：RSS 抓 + 关键词过滤
# ============================================================
def crawl_rss(*, platform, country, lang, headers, feeds, kws, fetch_body=True):
    out_path = RAW / f"{platform}_native_{DAY}.jsonl"
    seen = load_seen(out_path)
    n = 0
    for feed_url in feeds:
        r = safe_get(feed_url, headers)
        if r is None: polite(); continue
        if r.status_code != 200:
            print(f"[{platform}] RSS {feed_url} status={r.status_code}")
            polite(); continue
        items = parse_rss(r.text)
        print(f"[{platform}] RSS {feed_url} items={len(items)}")
        for it in items:
            link = it.get("link") or ""
            if not link: continue
            rid_raw = re.sub(r"[#?].*$", "", link)
            rid = md5_16(platform, rid_raw)
            if rid in seen: continue
            title = it.get("title", "")
            desc = it.get("desc", "")
            text_for_kw = title + " " + desc
            kw = kw_match(text_for_kw, kws)
            body = desc
            # Optional: fetch full body for context if kw matched, then re-check?
            if not kw and fetch_body:
                # also fetch body — many RSS only have summary
                fr = safe_get(link, headers)
                polite()
                if fr is not None and fr.status_code == 200 and not is_cf_block(fr):
                    fsoup = BeautifulSoup(fr.text, "html.parser")
                    main = (fsoup.select_one("article")
                            or fsoup.select_one("[class*=content]")
                            or fsoup.select_one("[class*=detail]")
                            or fsoup.select_one("main"))
                    if main:
                        body = re.sub(r"\s+", " ", main.get_text(" ", strip=True))[:5000]
                        kw = kw_match(title + " " + body, kws)
            if not kw: continue
            obj = {
                "id": rid,
                "raw_id": rid_raw,
                "platform": platform,
                "lang": lang,
                "title": title,
                "body": body[:5000],
                "author": "",
                "url": link,
                "country_hint": country,
                "matched_keyword": kw,
                "engagement": {"score": 0, "comments": 0, "views": None},
                "feed": feed_url,
                "crawled_at": now_iso(),
            }
            append(out_path, obj); seen.add(rid); n += 1
        polite()
    print(f"[{platform}] DONE +{n}")
    return n


# ============================================================
# VN
# ============================================================
def crawl_vietnamworks():
    roles = ["ky-su", "lap-trinh-vien", "ke-toan", "marketing", "ban-hang", "y-ta"]
    return crawl_jobsite(
        platform="vietnamworks", country="VN", lang="vi", headers=HDR_VN,
        list_url_fn=lambda role, p: f"https://www.vietnamworks.com/{role}-kv?page={p}",
        roles=roles, pages=2,
        card_selectors=["a[href*='-jv']", "a[href*='/viec-lam/']",
                         "[class*=job-item]", "[class*=JobCard]", "article"],
        link_filter=lambda h: ("vietnamworks.com" in h) and ("-jv" in h or "/viec-lam/" in h),
        base_url="https://www.vietnamworks.com",
    )


def crawl_topcv():
    roles = ["lap-trinh-vien", "ky-su", "ke-toan", "marketing", "ban-hang"]
    return crawl_jobsite(
        platform="topcv", country="VN", lang="vi", headers=HDR_VN,
        list_url_fn=lambda role, p: f"https://www.topcv.vn/tim-viec-lam-{role}?page={p}",
        roles=roles, pages=2,
        card_selectors=["a[href*='/viec-lam/']", "a[href*='/brand/']",
                         "[class*=job-item]", "[class*=JobItem]"],
        link_filter=lambda h: "topcv.vn" in h and "/viec-lam/" in h,
        base_url="https://www.topcv.vn",
    )


def crawl_careerbuilder_vn():
    roles = ["lap-trinh-vien", "ky-su", "ke-toan", "marketing"]
    return crawl_jobsite(
        platform="careerbuilder_vn", country="VN", lang="vi", headers=HDR_VN,
        list_url_fn=lambda role, p: f"https://careerbuilder.vn/viec-lam/{role}-c0-pcb{p}-vi.html",
        roles=roles, pages=2,
        card_selectors=["a[href*='/viec-lam/']", "[class*=job], article"],
        link_filter=lambda h: "careerbuilder.vn" in h and ".html" in h and "/viec-lam/" in h,
        base_url="https://careerbuilder.vn",
    )


def crawl_itviec():
    roles = ["python", "java", "javascript", "devops", "data-engineer"]
    return crawl_jobsite(
        platform="itviec", country="VN", lang="vi", headers=HDR_VN,
        list_url_fn=lambda role, p: f"https://itviec.com/it-jobs/{role}?page={p}",
        roles=roles, pages=2,
        card_selectors=["a[href*='/it-jobs/']", "[class*=job], article"],
        link_filter=lambda h: "itviec.com" in h and "/it-jobs/" in h,
        base_url="https://itviec.com",
    )


def crawl_vn_finance_rss():
    feeds = [
        "https://zingnews.vn/kinh-doanh.rss",
        "https://soha.vn/kinh-doanh.rss",
        "https://cafef.vn/tai-chinh-quoc-te.rss",
        "https://cafef.vn/thi-truong-chung-khoan.rss",
    ]
    return crawl_rss(platform="vn_finance_rss", country="VN", lang="vi",
                     headers=HDR_VN, feeds=feeds, kws=KEYWORDS["VN"])


# ============================================================
# TH
# ============================================================
def crawl_jobsdb_th():
    roles = ["software-engineer", "accountant", "marketing", "sales", "nurse"]
    return crawl_jobsite(
        platform="jobsdb_th", country="TH", lang="th", headers=HDR_TH,
        list_url_fn=lambda role, p: f"https://th.jobsdb.com/{role}-jobs?page={p}",
        roles=roles, pages=2,
        card_selectors=["a[href*='/job/']", "article"],
        link_filter=lambda h: "jobsdb.com" in h and "/job/" in h,
        base_url="https://th.jobsdb.com",
    )


def crawl_jobthai():
    # jobthai uses search
    roles = ["programmer", "engineer", "accountant", "sales", "marketing"]
    return crawl_jobsite(
        platform="jobthai", country="TH", lang="th", headers=HDR_TH,
        list_url_fn=lambda role, p: f"https://www.jobthai.com/th/find-job?keyword={quote(role)}&page={p}",
        roles=roles, pages=2,
        card_selectors=["a[href*='/jobs/']", "a[href*='/job/']", "article"],
        link_filter=lambda h: "jobthai.com" in h and ("/job/" in h or "/jobs/" in h),
        base_url="https://www.jobthai.com",
    )


def crawl_jobbkk():
    roles = ["programmer", "engineer", "accountant", "marketing"]
    return crawl_jobsite(
        platform="jobbkk", country="TH", lang="th", headers=HDR_TH,
        list_url_fn=lambda role, p: f"https://www.jobbkk.com/en/jobs/search?key={quote(role)}&pg={p}",
        roles=roles, pages=2,
        card_selectors=["a[href*='/jobs/']", "a[href*='/job']", "article"],
        link_filter=lambda h: "jobbkk.com" in h and "/job" in h,
        base_url="https://www.jobbkk.com",
    )


def crawl_pantip_mobile():
    """Try Pantip mobile/api endpoints across boards. Best-effort."""
    out_path = RAW / f"pantip_mobile_native_{DAY}.jsonl"
    seen = load_seen(out_path)
    n = 0
    boards = ["sinthorn", "klaibaan", "silom"]  # finance, work, business
    for board in boards:
        # mobile listing
        for url in [
            f"https://m.pantip.com/forum/{board}",
            f"https://api.pantip.com/forum/topic/list/{board}",
        ]:
            r = safe_get(url, HDR_TH)
            if r is None: polite(); continue
            if is_cf_block(r):
                print(f"[pantip_mobile] CF block board={board} url={url}")
                continue
            if r.status_code != 200:
                print(f"[pantip_mobile] board={board} url={url} status={r.status_code}")
                polite(); continue
            ct = r.headers.get("content-type", "")
            topics = []
            if "json" in ct:
                try:
                    j = r.json()
                    if isinstance(j, dict) and "topics" in j:
                        topics = j["topics"]
                    elif isinstance(j, list):
                        topics = j
                except Exception:
                    pass
            else:
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.select("a[href*='/topic/']"):
                    href = a.get("href", "")
                    if not href: continue
                    if not href.startswith("http"):
                        href = urljoin("https://m.pantip.com", href)
                    title = a.get_text(" ", strip=True)
                    if not title: continue
                    topics.append({"title": title, "url": href})
            print(f"[pantip_mobile] board={board} url={url[:60]} topics={len(topics)}")
            for t in topics[:30]:
                if isinstance(t, dict):
                    title = t.get("title") or t.get("topic_title") or ""
                    href = t.get("url") or ""
                    if not href:
                        tid = t.get("topic_id") or t.get("id") or ""
                        if tid: href = f"https://m.pantip.com/topic/{tid}"
                    if not title or not href: continue
                    rid_raw = href
                    rid = md5_16("pantip_mobile", rid_raw)
                    if rid in seen: continue
                    body = ""
                    dr = safe_get(href, HDR_TH); polite()
                    if dr is not None and dr.status_code == 200 and not is_cf_block(dr):
                        dsoup = BeautifulSoup(dr.text, "html.parser")
                        main = (dsoup.select_one("[class*=topic]")
                                or dsoup.select_one("article")
                                or dsoup.select_one("main"))
                        if main:
                            body = re.sub(r"\s+", " ", main.get_text(" ", strip=True))[:5000]
                    text_kw = title + " " + body
                    kw = kw_match(text_kw, KEYWORDS["TH"])
                    if not kw: continue
                    obj = {
                        "id": rid, "raw_id": rid_raw,
                        "platform": "pantip_mobile", "lang": "th",
                        "title": title, "body": body[:5000], "author": "",
                        "url": href, "country_hint": "TH",
                        "matched_keyword": kw,
                        "engagement": {"score": 0, "comments": 0, "views": None},
                        "board": board, "crawled_at": now_iso(),
                    }
                    append(out_path, obj); seen.add(rid); n += 1
            polite()
    print(f"[pantip_mobile] DONE +{n}")
    return n


def crawl_th_finance_rss():
    feeds = ["https://www.prachachat.net/feed"]
    return crawl_rss(platform="th_finance_rss", country="TH", lang="th",
                     headers=HDR_TH, feeds=feeds, kws=KEYWORDS["TH"])


# ============================================================
# ID
# ============================================================
def crawl_jobstreet_id():
    roles = ["software-engineer", "accountant", "marketing", "sales", "nurse"]
    return crawl_jobsite(
        platform="jobstreet_id", country="ID", lang="id", headers=HDR_ID,
        list_url_fn=lambda role, p: f"https://id.jobstreet.com/id/{role}-jobs?page={p}",
        roles=roles, pages=2,
        card_selectors=["a[href*='/job/']", "article"],
        link_filter=lambda h: "jobstreet.co" in h and "/job/" in h,
        base_url="https://id.jobstreet.com",
    )


def crawl_karier():
    roles = ["software-engineer", "accountant", "marketing", "sales"]
    return crawl_jobsite(
        platform="karier_id", country="ID", lang="id", headers=HDR_ID,
        list_url_fn=lambda role, p: f"https://www.karier.com/search-lowongan?keyword={quote(role)}&page={p}",
        roles=roles, pages=2,
        card_selectors=["a[href*='/lowongan']", "a[href*='/job/']", "article"],
        link_filter=lambda h: "karier.com" in h and ("/lowongan" in h or "/job" in h),
        base_url="https://www.karier.com",
    )


def crawl_gajimu():
    """GajiMu salary check pages (not job listings — direct salary pages)."""
    out_path = RAW / f"gajimu_native_{DAY}.jsonl"
    seen = load_seen(out_path)
    n = 0
    # Try sitemap or known section URLs
    section_urls = [
        "https://gajimu.com/main/gaji-pekerjaan",
        "https://gajimu.com/main/gajimu/",
        "https://gajimu.com/main/cek-gaji",
    ]
    discovered = set()
    for s in section_urls:
        r = safe_get(s, HDR_ID)
        if r is None: polite(); continue
        if r.status_code != 200 or is_cf_block(r):
            print(f"[gajimu] section {s} status={r.status_code}")
            polite(); continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if not href: continue
            if not href.startswith("http"): href = urljoin(s, href)
            if "gajimu.com" not in href: continue
            if any(k in href for k in ["/gaji-", "/profesi", "/cek-gaji", "/main/gaji"]):
                discovered.add(href)
        polite()
    print(f"[gajimu] discovered={len(discovered)} pages")
    for href in list(discovered)[:60]:
        rid_raw = re.sub(r"[#?].*$", "", href)
        rid = md5_16("gajimu", rid_raw)
        if rid in seen: continue
        dr = safe_get(href, HDR_ID); polite()
        if dr is None or dr.status_code != 200 or is_cf_block(dr): continue
        dsoup = BeautifulSoup(dr.text, "html.parser")
        title_el = dsoup.select_one("h1") or dsoup.select_one("title")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        main = (dsoup.select_one("article") or dsoup.select_one("main")
                or dsoup.select_one("[class*=content]") or dsoup.body)
        body = re.sub(r"\s+", " ", main.get_text(" ", strip=True))[:5000] if main else ""
        kw = kw_match(title + " " + body, KEYWORDS["ID"])
        if not kw and not re.search(r"(Rp|IDR|juta|gaji)", title + body, re.I): continue
        obj = {
            "id": rid, "raw_id": rid_raw,
            "platform": "gajimu", "lang": "id",
            "title": title, "body": body[:5000], "author": "",
            "url": href, "country_hint": "ID",
            "matched_keyword": kw or "gaji",
            "engagement": {"score": 0, "comments": 0, "views": None},
            "crawled_at": now_iso(),
        }
        append(out_path, obj); seen.add(rid); n += 1
    print(f"[gajimu] DONE +{n}")
    return n


def crawl_id_finance_rss():
    feeds = [
        "https://www.bisnis.com/index.rss",
        "https://www.bisnis.com/rss",
        "https://www.cnbcindonesia.com/rss",
    ]
    return crawl_rss(platform="id_finance_rss", country="ID", lang="id",
                     headers=HDR_ID, feeds=feeds, kws=KEYWORDS["ID"])


# ============================================================
# MY
# ============================================================
def crawl_jobstreet_my():
    roles = ["software-engineer", "accountant", "marketing", "sales", "nurse"]
    return crawl_jobsite(
        platform="jobstreet_my", country="MY", lang="ms", headers=HDR_MY,
        list_url_fn=lambda role, p: f"https://www.jobstreet.com.my/en/{role}-jobs?page={p}",
        roles=roles, pages=2,
        card_selectors=["a[href*='/job/']", "article"],
        link_filter=lambda h: "jobstreet.com" in h and "/job/" in h,
        base_url="https://www.jobstreet.com.my",
    )


def crawl_malaysianpayslip():
    """MalaysianPaySlip — salary database. Try sitemap / category pages."""
    out_path = RAW / f"malaysianpayslip_native_{DAY}.jsonl"
    seen = load_seen(out_path)
    n = 0
    seeds = [
        "https://www.malaysianpayslip.com/",
        "https://www.malaysianpayslip.com/category/salary/",
        "https://www.malaysianpayslip.com/jobs/",
    ]
    discovered = set()
    for s in seeds:
        r = safe_get(s, HDR_MY)
        if r is None: polite(); continue
        if is_cf_block(r):
            print(f"[malaysianpayslip] CF block on {s}")
            return n
        if r.status_code != 200:
            print(f"[malaysianpayslip] {s} status={r.status_code}")
            polite(); continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if not href: continue
            if not href.startswith("http"): href = urljoin(s, href)
            if "malaysianpayslip.com" not in href: continue
            if href in seeds: continue
            if any(seg in href for seg in ["/2024/", "/2025/", "/2026/", "/salary", "/gaji", "/jobs"]):
                discovered.add(href)
        polite()
    print(f"[malaysianpayslip] discovered={len(discovered)} pages")
    for href in list(discovered)[:60]:
        rid_raw = re.sub(r"[#?].*$", "", href)
        rid = md5_16("malaysianpayslip", rid_raw)
        if rid in seen: continue
        dr = safe_get(href, HDR_MY); polite()
        if dr is None or dr.status_code != 200 or is_cf_block(dr): continue
        dsoup = BeautifulSoup(dr.text, "html.parser")
        title_el = dsoup.select_one("h1") or dsoup.select_one("title")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        main = (dsoup.select_one("article") or dsoup.select_one("main")
                or dsoup.select_one("[class*=content]") or dsoup.body)
        body = re.sub(r"\s+", " ", main.get_text(" ", strip=True))[:5000] if main else ""
        kw = kw_match(title + " " + body, KEYWORDS["MY"])
        if not kw and not re.search(r"(RM\s?\d|MYR|EPF|KWSP)", title + body, re.I): continue
        obj = {
            "id": rid, "raw_id": rid_raw,
            "platform": "malaysianpayslip", "lang": "ms",
            "title": title, "body": body[:5000], "author": "",
            "url": href, "country_hint": "MY",
            "matched_keyword": kw or "RM",
            "engagement": {"score": 0, "comments": 0, "views": None},
            "crawled_at": now_iso(),
        }
        append(out_path, obj); seen.add(rid); n += 1
    print(f"[malaysianpayslip] DONE +{n}")
    return n


def crawl_my_finance_rss():
    feeds = [
        "https://www.thestar.com.my/rss/business",
        "https://www.theedgemalaysia.com/rss.xml",
        "https://www.theedgemarkets.com/rss.xml",
    ]
    return crawl_rss(platform="my_finance_rss", country="MY", lang="en",
                     headers=HDR_MY, feeds=feeds, kws=KEYWORDS["MY"])


# ============================================================
# 主入口
# ============================================================
TASKS = [
    # VN
    ("vietnamworks", crawl_vietnamworks),
    ("topcv", crawl_topcv),
    ("careerbuilder_vn", crawl_careerbuilder_vn),
    ("itviec", crawl_itviec),
    ("vn_finance_rss", crawl_vn_finance_rss),
    # TH
    ("jobsdb_th", crawl_jobsdb_th),
    ("jobthai", crawl_jobthai),
    ("jobbkk", crawl_jobbkk),
    ("pantip_mobile", crawl_pantip_mobile),
    ("th_finance_rss", crawl_th_finance_rss),
    # ID
    ("jobstreet_id", crawl_jobstreet_id),
    ("karier_id", crawl_karier),
    ("gajimu", crawl_gajimu),
    ("id_finance_rss", crawl_id_finance_rss),
    # MY
    ("jobstreet_my", crawl_jobstreet_my),
    ("malaysianpayslip", crawl_malaysianpayslip),
    ("my_finance_rss", crawl_my_finance_rss),
]


def count_lines(p):
    if not p.exists(): return 0
    return sum(1 for _ in p.open(encoding="utf-8"))


if __name__ == "__main__":
    summary = []
    for name, fn in TASKS:
        print(f"\n========== {name} ==========")
        try:
            added = fn()
        except Exception as e:
            print(f"[{name}] FATAL: {e}")
            added = 0
        f = RAW / f"{name}_native_{DAY}.jsonl"
        # pantip_mobile uses different filename
        if name == "pantip_mobile":
            f = RAW / f"pantip_mobile_native_{DAY}.jsonl"
        summary.append((name, added, count_lines(f)))
    print("\n=========== SE ASIA DEEP SUMMARY ===========")
    total_added = 0; total_file = 0
    for name, added, lines in summary:
        print(f"  {name:24s} +{added:4d}  file_lines={lines}")
        total_added += added; total_file += lines
    print(f"  {'TOTAL':24s} +{total_added:4d}  file_lines={total_file}")
