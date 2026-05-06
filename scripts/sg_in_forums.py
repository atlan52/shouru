"""HardwareZone EDMW (SG) + AmbitionBox (IN) — 新加坡英语/Singlish + 印度英语收入数据抓取。

输出：
  data/raw/hwz_edmw_native_<DAY>.jsonl     (country_hint=SG, platform=hwz_edmw)
  data/raw/ambitionbox_native_<DAY>.jsonl  (country_hint=IN, platform=ambitionbox)
"""
import json, hashlib, re, time, random
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HDR_SG = {
    "User-Agent": UA,
    "Accept-Language": "en-SG,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://forums.hardwarezone.com.sg/",
}
HDR_IN = {
    "User-Agent": UA,
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.ambitionbox.com/",
}
DAY = datetime.now().strftime("%Y%m%d")
OUT_HWZ = Path(f"data/raw/hwz_edmw_native_{DAY}.jsonl")
OUT_AB = Path(f"data/raw/ambitionbox_native_{DAY}.jsonl")

# HWZ keyword filter (English + Singlish)
HWZ_KEYWORDS = [
    "salary", "pay ", "earn", "income", "cpf", "take home", "takehome",
    "nsf allowance", "bonus", "aws", "package", "faang", "rich uncle",
    "$", "k/year", "k/month", "k/mth", "monthly pay", "annual",
    "pay rise", "increment", "starting pay", "sgd", "rich", "poor",
    "rich friend", "atas", "tcc", "associate", "manager pay",
]


def md5_16(*p): return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]
def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def append(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
def polite(a=1.3, b=1.8): time.sleep(random.uniform(a, b))


def load_seen(path):
    seen = set()
    if path.exists():
        for line in path.open():
            try: seen.add(json.loads(line)["id"])
            except: pass
    return seen


def detect_captcha(html: str) -> bool:
    low = html.lower()
    return any(k in low for k in [
        "captcha", "cf-challenge", "cloudflare", "are you human",
        "press &amp; hold", "press and hold", "verify you are human",
    ]) and "<form" in low


# ---------- HardwareZone EDMW + Financial Talk ----------

HWZ_SECTIONS = [
    # (board_slug, n_pages, label)
    ("eat-drink-man-woman.13", 3, "edmw"),
    ("financial-talk-money.117", 2, "ft"),
]

def hwz_listing_url(slug, page):
    if page <= 1:
        return f"https://forums.hardwarezone.com.sg/forums/{slug}/"
    return f"https://forums.hardwarezone.com.sg/forums/{slug}/page-{page}"


def hwz_parse_thread_links(soup, base_label):
    """Return list of dicts: {raw_id, slug, title, url, replies}."""
    threads = []
    items = soup.select(".structItem--thread")
    if not items:
        # fallback: any link to /threads/
        items = soup.select("a[href*='/threads/']")
    seen_ids = set()
    for it in items:
        a = it.select_one("a[href*='/threads/']") if hasattr(it, "select_one") else None
        if a is None and getattr(it, "name", "") == "a":
            a = it
        if a is None:
            continue
        href = a.get("href", "") or ""
        if "/threads/" not in href:
            continue
        if href.startswith("/"):
            href = "https://forums.hardwarezone.com.sg" + href
        m = re.search(r"/threads/([^/]+?)\.(\d+)/?", href)
        if not m:
            continue
        slug, tid = m.group(1), m.group(2)
        if tid in seen_ids:
            continue
        seen_ids.add(tid)
        title = a.get_text(" ", strip=True)
        # try richer title
        title_el = it.select_one(".structItem-title a") if hasattr(it, "select_one") else None
        if title_el:
            title = title_el.get_text(" ", strip=True) or title
        # replies
        replies = ""
        rep_el = it.select_one("dl.structItem-minor dd, .structItem-cell--meta dd") if hasattr(it, "select_one") else None
        if rep_el:
            replies = rep_el.get_text(" ", strip=True)
        threads.append({
            "raw_id": tid,
            "slug": slug,
            "title": title,
            "url": f"https://forums.hardwarezone.com.sg/threads/{slug}.{tid}/",
            "replies": replies,
            "section": base_label,
        })
    return threads


def hwz_fetch_thread_body(url):
    """Fetch first page of a thread, return (title, body_concat, n_posts)."""
    try:
        r = requests.get(url, headers=HDR_SG, timeout=25)
        if r.status_code != 200:
            return None, "", 0, r.status_code
        if detect_captcha(r.text):
            return None, "", 0, "captcha"
        soup = BeautifulSoup(r.text, "html.parser")
        title_el = soup.select_one("h1.p-title-value")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        # collect first ~5 posts
        posts = soup.select(".message-body .bbWrapper") or soup.select(".bbWrapper") or soup.select(".message-body")
        chunks = []
        for p in posts[:5]:
            t = p.get_text(" ", strip=True)
            if t:
                chunks.append(t)
        body = "\n\n---\n\n".join(chunks)
        return title, body, len(posts), 200
    except Exception as e:
        return None, "", 0, f"err:{e}"


def hwz_keyword_match(text: str) -> str:
    low = text.lower()
    for kw in HWZ_KEYWORDS:
        if kw in low:
            return kw
    return ""


def crawl_hwz():
    seen = load_seen(OUT_HWZ)
    total = 0
    diag_dumped = False
    for slug, n_pages, label in HWZ_SECTIONS:
        for page in range(1, n_pages + 1):
            list_url = hwz_listing_url(slug, page)
            try:
                r = requests.get(list_url, headers=HDR_SG, timeout=25)
            except Exception as e:
                print(f"[hwz] list {label} p{page} err: {e}")
                polite(); continue
            if r.status_code != 200:
                print(f"[hwz] list {label} p{page} status={r.status_code}")
                polite(); continue
            if detect_captcha(r.text):
                print(f"[hwz] CAPTCHA detected on {label} p{page} — abort HWZ.")
                return total
            soup = BeautifulSoup(r.text, "html.parser")
            threads = hwz_parse_thread_links(soup, label)
            if not threads and not diag_dumped and page == 1:
                print(f"[hwz] {label} p1 returned 0 threads. HTML 800-char dump:")
                print(r.text[:800])
                diag_dumped = True
            print(f"[hwz] list {label} p{page} threads={len(threads)}")
            polite(0.8, 1.3)
            picked = 0
            for th in threads:
                # quick keyword pre-filter on title
                kw_title = hwz_keyword_match(th["title"])
                # if no title hit, fetch anyway sometimes for EDMW because money posts buried
                # but limit fetches per page to keep polite
                if not kw_title and picked >= 8:
                    continue
                rid = md5_16("hwz", th["raw_id"])
                if rid in seen:
                    continue
                title2, body, n_posts, status = hwz_fetch_thread_body(th["url"])
                polite()
                if status == "captcha":
                    print(f"[hwz] CAPTCHA at thread {th['url']} — abort HWZ.")
                    return total
                if status != 200:
                    continue
                full_text = (title2 or th["title"]) + "\n" + body
                kw = kw_title or hwz_keyword_match(full_text)
                if not kw:
                    continue
                obj = {
                    "id": rid,
                    "raw_id": th["raw_id"],
                    "platform": "hwz_edmw",
                    "lang": "en",
                    "title": title2 or th["title"],
                    "body": body[:5000],
                    "author": "",
                    "url": th["url"],
                    "country_hint": "SG",
                    "matched_keyword": kw,
                    "engagement": {"score": 0, "comments": 0, "replies_meta": th.get("replies", "")},
                    "section": th["section"],
                    "n_posts_first_page": n_posts,
                    "crawled_at": now_iso(),
                }
                append(OUT_HWZ, obj); seen.add(rid); total += 1; picked += 1
            print(f"[hwz] {label} p{page} picked={picked} total={total}")
            polite()
    print(f"[hwz] DONE +{total}")
    return total


# ---------- AmbitionBox (India) ----------

AB_COMPANIES = [
    "infosys", "tcs", "accenture", "wipro", "cognizant", "hcl-technologies",
    "tech-mahindra", "capgemini", "ibm", "deloitte", "ey", "kpmg",
    "amazon", "microsoft", "google", "flipkart", "swiggy", "zomato",
    "paytm", "ola", "uber", "byjus", "razorpay", "freshworks",
    "reliance-industries", "tata-motors", "mahindra-and-mahindra", "icici-bank",
    "hdfc-bank", "sbi", "axis-bank", "kotak-mahindra-bank",
]
AB_ROLES = [
    "software-engineer", "data-scientist", "data-analyst", "product-manager",
    "doctor", "teacher", "nurse", "accountant", "civil-engineer",
    "mechanical-engineer", "sales-executive", "marketing-manager",
    "consultant", "business-analyst", "devops-engineer", "qa-engineer",
    "chartered-accountant", "lawyer",
]


def ab_company_url(slug):
    return f"https://www.ambitionbox.com/salaries/{slug}-salaries"

def ab_role_url(slug):
    return f"https://www.ambitionbox.com/profile/{slug}-salary"

def ab_role_url_alt(slug):
    return f"https://www.ambitionbox.com/salaries/{slug}-salaries"


def ab_extract_listing(soup, page_url, kind, slug):
    """Extract salary cards / list items from a salary page."""
    rows = []
    # try multiple containers
    selectors = [
        ".salary-list li",
        ".salary-card",
        ".job-card",
        "[class*=SalaryRow]",
        "[class*=salary-row]",
        "[class*=salaryItem]",
        "li[class*=jobs]",
        "div[class*=salary-list-row]",
    ]
    items = []
    for sel in selectors:
        items = soup.select(sel)
        if items:
            break
    # JSON-LD fallback
    jsonld_items = []
    for s in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            j = json.loads(s.string or "{}")
            if isinstance(j, list):
                for it in j:
                    if isinstance(it, dict) and it.get("@type") in ("Occupation", "JobPosting", "Article"):
                        jsonld_items.append(it)
            elif isinstance(j, dict):
                if j.get("@type") in ("Occupation", "JobPosting", "Article"):
                    jsonld_items.append(j)
        except Exception:
            pass

    for it in items:
        text = it.get_text(" ", strip=True)
        if not text or len(text) < 10:
            continue
        title_el = it.select_one("h2, h3, h4, a[class*=title], [class*=designation], [class*=role]")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        sal_el = it.select_one(".salary-amount, [class*=salary-amount], [class*=salary], [class*=Salary]")
        sal = sal_el.get_text(" ", strip=True) if sal_el else ""
        if not sal:
            m = re.search(r"₹\s?[\d\.,]+(?:\s?(?:L|LPA|lakh|Cr|K|/yr|/year|per\s+annum|per\s+month))?", text, re.I)
            if m:
                sal = m.group(0)
        a = it.select_one("a[href]")
        href = a.get("href", "") if a else ""
        if href and not href.startswith("http"):
            href = "https://www.ambitionbox.com" + href
        rows.append({
            "title": title or text[:120],
            "salary_text": sal,
            "url": href or page_url,
            "raw_text": text[:1500],
        })

    # if listing is empty but page itself has salary info (header / summary)
    if not rows:
        # try header-level salary summary
        h1 = soup.select_one("h1")
        title = h1.get_text(" ", strip=True) if h1 else ""
        # whole page text looking for ₹ amounts
        page_text = soup.get_text(" ", strip=True)
        amounts = re.findall(r"₹\s?[\d\.,]+\s?(?:L|LPA|lakh|Cr|K|/yr|/year|per\s+annum|per\s+month)?", page_text, re.I)
        if title and amounts:
            rows.append({
                "title": title,
                "salary_text": " | ".join(amounts[:6]),
                "url": page_url,
                "raw_text": page_text[:2000],
            })
    return rows


def crawl_ambitionbox():
    seen = load_seen(OUT_AB)
    total = 0
    diag_dumped = False

    targets = []
    for c in AB_COMPANIES:
        targets.append(("company", c, ab_company_url(c)))
    for r in AB_ROLES:
        # try role URL pattern, fallback handled inside
        targets.append(("role", r, ab_role_url_alt(r)))

    for kind, slug, url in targets:
        try:
            resp = requests.get(url, headers=HDR_IN, timeout=25)
        except Exception as e:
            print(f"[ab] {kind}/{slug} err: {e}")
            polite(); continue
        if resp.status_code == 404 and kind == "role":
            # try alternate URL
            url2 = ab_role_url(slug)
            try:
                resp = requests.get(url2, headers=HDR_IN, timeout=25)
                url = url2
            except Exception as e:
                print(f"[ab] {kind}/{slug} alt err: {e}")
                polite(); continue
        if resp.status_code != 200:
            print(f"[ab] {kind}/{slug} status={resp.status_code}")
            polite(); continue
        if detect_captcha(resp.text):
            print(f"[ab] CAPTCHA on {kind}/{slug} — abort AmbitionBox.")
            return total
        soup = BeautifulSoup(resp.text, "html.parser")
        rows = ab_extract_listing(soup, url, kind, slug)
        if not rows and not diag_dumped:
            print(f"[ab] {kind}/{slug} returned 0 rows. HTML 800-char dump:")
            print(resp.text[:800])
            diag_dumped = True
        added = 0
        for row in rows:
            raw_id = f"{kind}:{slug}:" + (row.get("url") or row.get("title", ""))[:200]
            rid = md5_16("ambitionbox", raw_id)
            if rid in seen:
                continue
            obj = {
                "id": rid,
                "raw_id": raw_id,
                "platform": "ambitionbox",
                "lang": "en",
                "title": row.get("title", ""),
                "body": row.get("raw_text", "")[:5000],
                "author": slug if kind == "company" else "",
                "url": row.get("url", url),
                "country_hint": "IN",
                "matched_keyword": kind + ":" + slug,
                "engagement": {"score": 0, "comments": 0},
                "kind": kind,
                "company_or_role_slug": slug,
                "salary_text": row.get("salary_text", ""),
                "crawled_at": now_iso(),
            }
            append(OUT_AB, obj); seen.add(rid); total += 1; added += 1
        print(f"[ab] {kind}/{slug} rows={len(rows)} new={added} total={total}")
        polite()
    print(f"[ab] DONE +{total}")
    return total


# ---------- samples ----------

def print_samples(path, label, k=3):
    if not path.exists():
        print(f"[{label}] file missing: {path}")
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    print(f"\n=== {label}: {path} | {len(lines)} lines ===")
    for ln in lines[:k]:
        try:
            o = json.loads(ln)
            t = (o.get("title") or "").replace("\n", " ")[:120]
            b = (o.get("body") or "").replace("\n", " ")[:240]
            extra = ""
            if o.get("salary_text"):
                extra = f" | sal={o['salary_text'][:80]}"
            print(f"  - kw={o.get('matched_keyword')!r} | {t}{extra}")
            print(f"    body: {b}...")
        except Exception as e:
            print(f"  parse err: {e}")
    return len(lines)


if __name__ == "__main__":
    n_h = crawl_hwz()
    n_a = crawl_ambitionbox()
    lh = print_samples(OUT_HWZ, "hwz_edmw")
    la = print_samples(OUT_AB, "ambitionbox")
    print(f"\n=== TOTAL: hwz +{n_h} (file {lh}), ambitionbox +{n_a} (file {la}) ===")
