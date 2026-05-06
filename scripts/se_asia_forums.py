"""SE Asia 本地论坛收入帖抓取：VN(voz, tinhte) / ID(kaskus) / TH(blognone, sanook) / MY(lowyat, cari)。

输出（每文件 schema 同 r_mexico_native）：
  data/raw/voz_native_<DAY>.jsonl          (VN, vi, platform=voz)
  data/raw/tinhte_native_<DAY>.jsonl       (VN, vi, platform=tinhte)
  data/raw/kaskus_native_<DAY>.jsonl       (ID, id, platform=kaskus)
  data/raw/blognone_native_<DAY>.jsonl     (TH, th, platform=blognone)
  data/raw/sanook_money_native_<DAY>.jsonl (TH, th, platform=sanook_money)
  data/raw/lowyat_native_<DAY>.jsonl       (MY, ms, platform=lowyat)
  data/raw/cari_native_<DAY>.jsonl         (MY, ms, platform=cari)
"""
import json, hashlib, re, time, random
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

def hdr(lang, referer=""):
    h = {
        "User-Agent": UA,
        "Accept-Language": lang,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if referer:
        h["Referer"] = referer
    return h

DAY = datetime.now().strftime("%Y%m%d")
OUT_VOZ = Path(f"data/raw/voz_native_{DAY}.jsonl")
OUT_TINHTE = Path(f"data/raw/tinhte_native_{DAY}.jsonl")
OUT_KASKUS = Path(f"data/raw/kaskus_native_{DAY}.jsonl")
OUT_BLOGNONE = Path(f"data/raw/blognone_native_{DAY}.jsonl")
OUT_SANOOK = Path(f"data/raw/sanook_money_native_{DAY}.jsonl")
OUT_LOWYAT = Path(f"data/raw/lowyat_native_{DAY}.jsonl")
OUT_CARI = Path(f"data/raw/cari_native_{DAY}.jsonl")

# 关键词（小写匹配；泰语不区分大小写无影响）
KW_VI = ["lương", "thu nhập", "kiếm tiền", "freelance", "kỹ sư", "lập trình",
         "thưởng", "thuế thu nhập", "lương net", "lương gross", "công ty",
         "tiền", "triệu/tháng", "triệu / tháng", "đồng/tháng"]
KW_ID = ["gaji", "pendapatan", "freelance", "kerja remote", "pensiun",
         "penghasilan", "upah", "thr", "tunjangan", "rupiah", "juta", "ribu",
         "umk", "umr", "honor", "freelancer", "wfh"]
KW_TH = ["เงินเดือน", "รายได้", "freelance", "อาชีพ", "ค่าจ้าง",
         "โบนัส", "ฟรีแลนซ์", "บาท/เดือน", "บาท / เดือน", "เงินได้",
         "ภาษี", "เก็บเงิน"]
KW_MS = ["gaji", "pendapatan", "freelance", "take home", "elaun",
         "bonus", "kerja", "pencen", "duit", "bayaran", "rm",
         "upah", "income", "salary", "epf", "kwsp"]


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
        "captcha", "cf-challenge", "are you human",
        "press &amp; hold", "press and hold", "verify you are human",
        "checking your browser before accessing",
    ]) and "<form" in low or "cf-mitigated" in low


def kw_match(text: str, kws) -> str:
    low = text.lower()
    for kw in kws:
        if kw.lower() in low:
            return kw
    return ""


def safe_get(url, headers, timeout=25, label=""):
    try:
        r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        return r
    except Exception as e:
        print(f"[{label}] GET {url} err: {e}")
        return None


# ---------------- VN: voz.vn (XenForo) ----------------

VOZ_BOARDS = [
    ("cong-so-noi-cong-so.50", 3, "office"),
    ("lam-an-kinh-doanh.27", 3, "business"),
]

def voz_listing_url(slug, page):
    if page <= 1:
        return f"https://voz.vn/f/{slug}/"
    return f"https://voz.vn/f/{slug}/page-{page}"


def voz_parse_threads(soup):
    threads = []
    items = soup.select(".structItem--thread")
    if not items:
        items = soup.select("a[href*='/t/']")
    seen_ids = set()
    for it in items:
        a = it.select_one("a[href*='/t/']") if hasattr(it, "select_one") else None
        if a is None and getattr(it, "name", "") == "a":
            a = it
        if a is None:
            continue
        href = a.get("href", "") or ""
        if "/t/" not in href:
            continue
        if href.startswith("/"):
            href = "https://voz.vn" + href
        m = re.search(r"/t/([^/]+?)\.(\d+)/?", href)
        if not m:
            continue
        slug, tid = m.group(1), m.group(2)
        if tid in seen_ids:
            continue
        seen_ids.add(tid)
        title_el = it.select_one(".structItem-title a") if hasattr(it, "select_one") else None
        title = title_el.get_text(" ", strip=True) if title_el else a.get_text(" ", strip=True)
        threads.append({
            "raw_id": tid, "slug": slug, "title": title,
            "url": f"https://voz.vn/t/{slug}.{tid}/",
        })
    return threads


def voz_fetch_thread(url):
    r = safe_get(url, hdr("vi-VN,vi;q=0.9,en;q=0.5", "https://voz.vn/"), label="voz")
    if r is None: return None, "", -1
    if r.status_code != 200: return None, "", r.status_code
    if detect_captcha(r.text): return None, "", "captcha"
    soup = BeautifulSoup(r.text, "html.parser")
    title_el = soup.select_one("h1.p-title-value")
    title = title_el.get_text(" ", strip=True) if title_el else ""
    posts = soup.select(".message-body .bbWrapper") or soup.select(".bbWrapper")
    chunks = []
    for p in posts[:5]:
        t = p.get_text(" ", strip=True)
        if t: chunks.append(t)
    return title, "\n\n---\n\n".join(chunks), 200


def crawl_voz():
    seen = load_seen(OUT_VOZ)
    total = 0
    diag = False
    for slug, n_pages, label in VOZ_BOARDS:
        for page in range(1, n_pages + 1):
            url = voz_listing_url(slug, page)
            r = safe_get(url, hdr("vi-VN,vi;q=0.9,en;q=0.5", "https://voz.vn/"), label="voz")
            if r is None: polite(); continue
            if r.status_code != 200:
                print(f"[voz] list {label} p{page} status={r.status_code}")
                polite(); continue
            if detect_captcha(r.text):
                print(f"[voz] CAPTCHA on {label} p{page} — abort voz.")
                return total
            soup = BeautifulSoup(r.text, "html.parser")
            threads = voz_parse_threads(soup)
            if not threads and not diag and page == 1:
                print(f"[voz] {label} p1 0 threads. HTML 800-char dump:")
                print(r.text[:800])
                diag = True
            print(f"[voz] {label} p{page} threads={len(threads)}")
            polite(0.8, 1.3)
            picked = 0
            for th in threads:
                kw_t = kw_match(th["title"], KW_VI)
                if not kw_t and picked >= 6:
                    continue
                rid = md5_16("voz", th["raw_id"])
                if rid in seen: continue
                t2, body, st = voz_fetch_thread(th["url"])
                polite()
                if st == "captcha":
                    print(f"[voz] CAPTCHA on thread — abort.")
                    return total
                if st != 200: continue
                full = (t2 or th["title"]) + "\n" + body
                kw = kw_t or kw_match(full, KW_VI)
                if not kw: continue
                obj = {
                    "id": rid, "raw_id": th["raw_id"], "platform": "voz", "lang": "vi",
                    "title": t2 or th["title"], "body": body[:5000], "author": "",
                    "url": th["url"], "country_hint": "VN", "matched_keyword": kw,
                    "engagement": {"score": 0, "comments": 0},
                    "section": label, "crawled_at": now_iso(),
                }
                append(OUT_VOZ, obj); seen.add(rid); total += 1; picked += 1
            print(f"[voz] {label} p{page} picked={picked} total={total}")
            polite()
    print(f"[voz] DONE +{total}")
    return total


# ---------------- VN: tinhte.vn (XenForo style) ----------------

TINHTE_BOARDS = [
    ("cong-so-cong-viec.124", 3, "office"),
    ("kinh-doanh.50", 2, "business"),
]

def tinhte_listing_url(slug, page):
    if page <= 1:
        return f"https://tinhte.vn/forums/{slug}/"
    return f"https://tinhte.vn/forums/{slug}/page-{page}"


def tinhte_parse_threads(soup):
    threads = []
    items = soup.select(".structItem--thread") or soup.select("a[href*='/thread/']")
    seen_ids = set()
    for it in items:
        a = it.select_one("a[href*='/thread/']") if hasattr(it, "select_one") else None
        if a is None and getattr(it, "name", "") == "a":
            a = it
        if a is None:
            continue
        href = a.get("href", "") or ""
        if "/thread/" not in href:
            continue
        if href.startswith("/"):
            href = "https://tinhte.vn" + href
        m = re.search(r"/thread/([^/]*?\.)(\d+)/?", href) or re.search(r"/thread/(\d+)/?", href)
        if not m:
            continue
        if m.lastindex and m.lastindex >= 2:
            slug, tid = m.group(1).rstrip("."), m.group(2)
        else:
            slug, tid = "", m.group(1)
        if tid in seen_ids: continue
        seen_ids.add(tid)
        title_el = it.select_one(".structItem-title a, h3 a") if hasattr(it, "select_one") else None
        title = title_el.get_text(" ", strip=True) if title_el else a.get_text(" ", strip=True)
        threads.append({"raw_id": tid, "slug": slug, "title": title, "url": href})
    return threads


def tinhte_fetch_thread(url):
    r = safe_get(url, hdr("vi-VN,vi;q=0.9,en;q=0.5", "https://tinhte.vn/"), label="tinhte")
    if r is None: return None, "", -1
    if r.status_code != 200: return None, "", r.status_code
    if detect_captcha(r.text): return None, "", "captcha"
    soup = BeautifulSoup(r.text, "html.parser")
    title_el = soup.select_one("h1.p-title-value, h1.thread-title, h1")
    title = title_el.get_text(" ", strip=True) if title_el else ""
    posts = soup.select(".message-body .bbWrapper") or soup.select(".bbWrapper") or soup.select(".message-body")
    chunks = []
    for p in posts[:5]:
        t = p.get_text(" ", strip=True)
        if t: chunks.append(t)
    return title, "\n\n---\n\n".join(chunks), 200


def crawl_tinhte():
    seen = load_seen(OUT_TINHTE)
    total = 0
    diag = False
    for slug, n_pages, label in TINHTE_BOARDS:
        for page in range(1, n_pages + 1):
            url = tinhte_listing_url(slug, page)
            r = safe_get(url, hdr("vi-VN,vi;q=0.9,en;q=0.5", "https://tinhte.vn/"), label="tinhte")
            if r is None: polite(); continue
            if r.status_code == 404:
                print(f"[tinhte] {label} p{page} 404 — board likely missing, skip.")
                break
            if r.status_code != 200:
                print(f"[tinhte] list {label} p{page} status={r.status_code}")
                polite(); continue
            if detect_captcha(r.text):
                print(f"[tinhte] CAPTCHA — abort.")
                return total
            soup = BeautifulSoup(r.text, "html.parser")
            threads = tinhte_parse_threads(soup)
            if not threads and not diag and page == 1:
                print(f"[tinhte] {label} p1 0 threads. HTML 800-char dump:")
                print(r.text[:800])
                diag = True
            print(f"[tinhte] {label} p{page} threads={len(threads)}")
            polite(0.8, 1.3)
            picked = 0
            for th in threads:
                kw_t = kw_match(th["title"], KW_VI)
                if not kw_t and picked >= 6:
                    continue
                rid = md5_16("tinhte", th["raw_id"])
                if rid in seen: continue
                t2, body, st = tinhte_fetch_thread(th["url"])
                polite()
                if st == "captcha":
                    print("[tinhte] CAPTCHA on thread — abort."); return total
                if st != 200: continue
                full = (t2 or th["title"]) + "\n" + body
                kw = kw_t or kw_match(full, KW_VI)
                if not kw: continue
                obj = {
                    "id": rid, "raw_id": th["raw_id"], "platform": "tinhte", "lang": "vi",
                    "title": t2 or th["title"], "body": body[:5000], "author": "",
                    "url": th["url"], "country_hint": "VN", "matched_keyword": kw,
                    "engagement": {"score": 0, "comments": 0},
                    "section": label, "crawled_at": now_iso(),
                }
                append(OUT_TINHTE, obj); seen.add(rid); total += 1; picked += 1
            print(f"[tinhte] {label} p{page} picked={picked} total={total}")
            polite()
    print(f"[tinhte] DONE +{total}")
    return total


# ---------------- ID: kaskus.co.id ----------------

KASKUS_FORUMS = [
    ("13", "the-lounge", 3),
    ("15", "finance", 3),
]

def kaskus_listing_url(fid, slug, page):
    base = f"https://www.kaskus.co.id/forum/{fid}/{slug}"
    if page <= 1: return base
    return f"{base}/{page}"


def kaskus_parse_threads(soup):
    threads = []
    # Kaskus thread links pattern: /thread/<hex_id>/<slug>
    anchors = soup.select("a[href*='/thread/']")
    seen_ids = set()
    for a in anchors:
        href = a.get("href", "") or ""
        if "/thread/" not in href: continue
        if href.startswith("/"):
            href = "https://www.kaskus.co.id" + href
        m = re.search(r"/thread/([0-9a-fA-F]+)(?:/([^/?#]+))?", href)
        if not m: continue
        tid = m.group(1)
        slug = m.group(2) or ""
        if tid in seen_ids: continue
        seen_ids.add(tid)
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 5: continue
        threads.append({"raw_id": tid, "slug": slug, "title": title, "url": href})
    return threads


def kaskus_fetch_thread(url):
    r = safe_get(url, hdr("id-ID,id;q=0.9,en;q=0.5", "https://www.kaskus.co.id/"), label="kaskus")
    if r is None: return None, "", -1
    if r.status_code != 200: return None, "", r.status_code
    if detect_captcha(r.text): return None, "", "captcha"
    soup = BeautifulSoup(r.text, "html.parser")
    title_el = soup.select_one("h1.thread-title, h1[class*=title], h1")
    title = title_el.get_text(" ", strip=True) if title_el else ""
    posts = (soup.select(".post-content") or soup.select("[class*=post-content]")
             or soup.select("[class*=PostContent]") or soup.select("article"))
    chunks = []
    for p in posts[:5]:
        t = p.get_text(" ", strip=True)
        if t: chunks.append(t)
    return title, "\n\n---\n\n".join(chunks), 200


def crawl_kaskus():
    seen = load_seen(OUT_KASKUS)
    total = 0
    diag = False
    for fid, slug, n_pages in KASKUS_FORUMS:
        for page in range(1, n_pages + 1):
            url = kaskus_listing_url(fid, slug, page)
            r = safe_get(url, hdr("id-ID,id;q=0.9,en;q=0.5", "https://www.kaskus.co.id/"), label="kaskus")
            if r is None: polite(); continue
            if r.status_code != 200:
                print(f"[kaskus] list {slug} p{page} status={r.status_code}")
                polite(); continue
            if detect_captcha(r.text):
                print("[kaskus] CAPTCHA — abort."); return total
            soup = BeautifulSoup(r.text, "html.parser")
            threads = kaskus_parse_threads(soup)
            if not threads and not diag and page == 1:
                print(f"[kaskus] {slug} p1 0 threads. HTML 800-char dump:")
                print(r.text[:800])
                diag = True
            print(f"[kaskus] {slug} p{page} threads={len(threads)}")
            polite(0.8, 1.3)
            picked = 0
            for th in threads:
                kw_t = kw_match(th["title"], KW_ID)
                if not kw_t and picked >= 6:
                    continue
                rid = md5_16("kaskus", th["raw_id"])
                if rid in seen: continue
                t2, body, st = kaskus_fetch_thread(th["url"])
                polite()
                if st == "captcha":
                    print("[kaskus] CAPTCHA on thread — abort."); return total
                if st != 200: continue
                full = (t2 or th["title"]) + "\n" + body
                kw = kw_t or kw_match(full, KW_ID)
                if not kw: continue
                obj = {
                    "id": rid, "raw_id": th["raw_id"], "platform": "kaskus", "lang": "id",
                    "title": t2 or th["title"], "body": body[:5000], "author": "",
                    "url": th["url"], "country_hint": "ID", "matched_keyword": kw,
                    "engagement": {"score": 0, "comments": 0},
                    "section": slug, "crawled_at": now_iso(),
                }
                append(OUT_KASKUS, obj); seen.add(rid); total += 1; picked += 1
            print(f"[kaskus] {slug} p{page} picked={picked} total={total}")
            polite()
    print(f"[kaskus] DONE +{total}")
    return total


# ---------------- TH: blognone.com ----------------

BLOGNONE_LISTS = [
    ("https://www.blognone.com/topics/jobs", 3, "jobs"),
    ("https://www.blognone.com/news", 3, "news"),
]

def blognone_listing_url(base, page):
    if page <= 1: return base
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}page={page-1}"  # Drupal uses 0-indexed page param often


def blognone_parse_threads(soup):
    threads = []
    anchors = soup.select("a[href*='/node/']")
    seen_ids = set()
    for a in anchors:
        href = a.get("href", "") or ""
        m = re.search(r"/node/(\d+)", href)
        if not m: continue
        nid = m.group(1)
        if nid in seen_ids: continue
        seen_ids.add(nid)
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 5: continue
        if href.startswith("/"):
            href = "https://www.blognone.com" + href
        # restrict to canonical /node/ID URLs
        threads.append({"raw_id": nid, "title": title, "url": f"https://www.blognone.com/node/{nid}"})
    return threads


def blognone_fetch_thread(url):
    r = safe_get(url, hdr("th-TH,th;q=0.9,en;q=0.5", "https://www.blognone.com/"), label="blognone")
    if r is None: return None, "", -1
    if r.status_code != 200: return None, "", r.status_code
    if detect_captcha(r.text): return None, "", "captcha"
    soup = BeautifulSoup(r.text, "html.parser")
    title_el = soup.select_one("h1, h1.node-title, h1.title")
    title = title_el.get_text(" ", strip=True) if title_el else ""
    body_el = (soup.select_one(".node-content") or soup.select_one(".field-body")
               or soup.select_one("article .content") or soup.select_one("article")
               or soup.select_one("main"))
    body = body_el.get_text(" ", strip=True) if body_el else ""
    return title, body[:5000], 200


def crawl_blognone():
    seen = load_seen(OUT_BLOGNONE)
    total = 0
    diag = False
    for base, n_pages, label in BLOGNONE_LISTS:
        for page in range(1, n_pages + 1):
            url = blognone_listing_url(base, page)
            r = safe_get(url, hdr("th-TH,th;q=0.9,en;q=0.5", "https://www.blognone.com/"), label="blognone")
            if r is None: polite(); continue
            if r.status_code != 200:
                print(f"[blognone] list {label} p{page} status={r.status_code}")
                polite(); continue
            if detect_captcha(r.text):
                print("[blognone] CAPTCHA — abort."); return total
            soup = BeautifulSoup(r.text, "html.parser")
            threads = blognone_parse_threads(soup)
            if not threads and not diag and page == 1:
                print(f"[blognone] {label} p1 0 threads. HTML 800-char dump:")
                print(r.text[:800])
                diag = True
            print(f"[blognone] {label} p{page} threads={len(threads)}")
            polite(0.8, 1.3)
            picked = 0
            for th in threads:
                kw_t = kw_match(th["title"], KW_TH)
                # blognone is more news-y; for jobs-section accept w/o keyword too
                if not kw_t and label != "jobs" and picked >= 6:
                    continue
                rid = md5_16("blognone", th["raw_id"])
                if rid in seen: continue
                t2, body, st = blognone_fetch_thread(th["url"])
                polite()
                if st == "captcha":
                    print("[blognone] CAPTCHA on detail — abort."); return total
                if st != 200: continue
                full = (t2 or th["title"]) + "\n" + body
                kw = kw_t or kw_match(full, KW_TH)
                if not kw and label != "jobs":
                    continue
                if not kw: kw = "jobs"
                obj = {
                    "id": rid, "raw_id": th["raw_id"], "platform": "blognone", "lang": "th",
                    "title": t2 or th["title"], "body": body[:5000], "author": "",
                    "url": th["url"], "country_hint": "TH", "matched_keyword": kw,
                    "engagement": {"score": 0, "comments": 0},
                    "section": label, "crawled_at": now_iso(),
                }
                append(OUT_BLOGNONE, obj); seen.add(rid); total += 1; picked += 1
            print(f"[blognone] {label} p{page} picked={picked} total={total}")
            polite()
    print(f"[blognone] DONE +{total}")
    return total


# ---------------- TH: sanook.com/money ----------------

SANOOK_LISTS = [
    ("https://www.sanook.com/money/", 1, "home"),
    ("https://www.sanook.com/money/category/career/", 2, "career"),
    ("https://www.sanook.com/money/category/finance/", 2, "finance"),
]

def sanook_listing_url(base, page):
    if page <= 1: return base
    return f"{base}page/{page}/"


def sanook_parse_threads(soup):
    threads = []
    anchors = soup.select("a[href*='sanook.com/money/']")
    seen_ids = set()
    for a in anchors:
        href = a.get("href", "") or ""
        m = re.search(r"sanook\.com/money/(\d+)/?", href)
        if not m: continue
        nid = m.group(1)
        if nid in seen_ids: continue
        seen_ids.add(nid)
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 6: continue
        if href.startswith("/"):
            href = "https://www.sanook.com" + href
        threads.append({"raw_id": nid, "title": title, "url": href})
    return threads


def sanook_fetch_thread(url):
    r = safe_get(url, hdr("th-TH,th;q=0.9,en;q=0.5", "https://www.sanook.com/"), label="sanook")
    if r is None: return None, "", -1
    if r.status_code != 200: return None, "", r.status_code
    if detect_captcha(r.text): return None, "", "captcha"
    soup = BeautifulSoup(r.text, "html.parser")
    title_el = soup.select_one("h1, h1.entry-title, h1.title, h1.article-title")
    title = title_el.get_text(" ", strip=True) if title_el else ""
    body_el = (soup.select_one("article .content") or soup.select_one(".article-content")
               or soup.select_one(".entry-content") or soup.select_one("article")
               or soup.select_one("main"))
    body = body_el.get_text(" ", strip=True) if body_el else ""
    return title, body[:5000], 200


def crawl_sanook():
    seen = load_seen(OUT_SANOOK)
    total = 0
    diag = False
    for base, n_pages, label in SANOOK_LISTS:
        for page in range(1, n_pages + 1):
            url = sanook_listing_url(base, page)
            r = safe_get(url, hdr("th-TH,th;q=0.9,en;q=0.5", "https://www.sanook.com/"), label="sanook")
            if r is None: polite(); continue
            if r.status_code != 200:
                print(f"[sanook] list {label} p{page} status={r.status_code}")
                polite(); continue
            if detect_captcha(r.text):
                print("[sanook] CAPTCHA — abort."); return total
            soup = BeautifulSoup(r.text, "html.parser")
            threads = sanook_parse_threads(soup)
            if not threads and not diag and page == 1:
                print(f"[sanook] {label} p1 0 threads. HTML 800-char dump:")
                print(r.text[:800])
                diag = True
            print(f"[sanook] {label} p{page} threads={len(threads)}")
            polite(0.8, 1.3)
            picked = 0
            for th in threads:
                kw_t = kw_match(th["title"], KW_TH)
                if not kw_t and picked >= 6:
                    continue
                rid = md5_16("sanook", th["raw_id"])
                if rid in seen: continue
                t2, body, st = sanook_fetch_thread(th["url"])
                polite()
                if st == "captcha":
                    print("[sanook] CAPTCHA on detail — abort."); return total
                if st != 200: continue
                full = (t2 or th["title"]) + "\n" + body
                kw = kw_t or kw_match(full, KW_TH)
                if not kw: continue
                obj = {
                    "id": rid, "raw_id": th["raw_id"], "platform": "sanook_money", "lang": "th",
                    "title": t2 or th["title"], "body": body[:5000], "author": "",
                    "url": th["url"], "country_hint": "TH", "matched_keyword": kw,
                    "engagement": {"score": 0, "comments": 0},
                    "section": label, "crawled_at": now_iso(),
                }
                append(OUT_SANOOK, obj); seen.add(rid); total += 1; picked += 1
            print(f"[sanook] {label} p{page} picked={picked} total={total}")
            polite()
    print(f"[sanook] DONE +{total}")
    return total


# ---------------- MY: forum.lowyat.net (IPB) ----------------

LOWYAT_FORUMS = [
    # Lowyat IPB-style: /index.php?showforum=<id>
    ("Serserabad",  "https://forum.lowyat.net/SerseraNet", 3),
    ("Kerjaya",     "https://forum.lowyat.net/topic/jobs", 2),
    ("Bursa",       "https://forum.lowyat.net/Bursa", 2),
]

def lowyat_listing_url(base, page):
    if page <= 1: return base
    # IPB forum index pagination
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}prune_day=100&sort_by=Z-A&sort_key=last_post&topicfilter=all&st={(page-1)*30}"


def lowyat_parse_threads(soup):
    threads = []
    anchors = soup.select("a[href*='/topic/']")
    seen_ids = set()
    for a in anchors:
        href = a.get("href", "") or ""
        m = re.search(r"/topic/(\d+)", href)
        if not m: continue
        tid = m.group(1)
        if tid in seen_ids: continue
        seen_ids.add(tid)
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 5: continue
        if href.startswith("/"):
            href = "https://forum.lowyat.net" + href
        threads.append({"raw_id": tid, "title": title, "url": f"https://forum.lowyat.net/topic/{tid}"})
    return threads


def lowyat_fetch_thread(url):
    r = safe_get(url, hdr("ms-MY,ms;q=0.9,en;q=0.7", "https://forum.lowyat.net/"), label="lowyat")
    if r is None: return None, "", -1
    if r.status_code != 200: return None, "", r.status_code
    if detect_captcha(r.text): return None, "", "captcha"
    soup = BeautifulSoup(r.text, "html.parser")
    title_el = (soup.select_one(".maintitle") or soup.select_one("h1.ipsType_pagetitle")
                or soup.select_one("h1") or soup.select_one("title"))
    title = title_el.get_text(" ", strip=True) if title_el else ""
    posts = (soup.select(".postcolor") or soup.select(".post_body") or soup.select("[class*=post-content]")
             or soup.select(".content") or soup.select("article"))
    chunks = []
    for p in posts[:5]:
        t = p.get_text(" ", strip=True)
        if t: chunks.append(t)
    return title, "\n\n---\n\n".join(chunks), 200


def crawl_lowyat():
    seen = load_seen(OUT_LOWYAT)
    total = 0
    diag = False
    for label, base, n_pages in LOWYAT_FORUMS:
        for page in range(1, n_pages + 1):
            url = lowyat_listing_url(base, page)
            r = safe_get(url, hdr("ms-MY,ms;q=0.9,en;q=0.7", "https://forum.lowyat.net/"), label="lowyat")
            if r is None: polite(); continue
            if r.status_code != 200:
                print(f"[lowyat] list {label} p{page} status={r.status_code}")
                polite(); continue
            if detect_captcha(r.text):
                print("[lowyat] CAPTCHA — abort."); return total
            soup = BeautifulSoup(r.text, "html.parser")
            threads = lowyat_parse_threads(soup)
            if not threads and not diag and page == 1:
                print(f"[lowyat] {label} p1 0 threads. HTML 800-char dump:")
                print(r.text[:800])
                diag = True
            print(f"[lowyat] {label} p{page} threads={len(threads)}")
            polite(0.8, 1.3)
            picked = 0
            for th in threads:
                kw_t = kw_match(th["title"], KW_MS)
                if not kw_t and picked >= 6:
                    continue
                rid = md5_16("lowyat", th["raw_id"])
                if rid in seen: continue
                t2, body, st = lowyat_fetch_thread(th["url"])
                polite()
                if st == "captcha":
                    print("[lowyat] CAPTCHA on detail — abort."); return total
                if st != 200: continue
                full = (t2 or th["title"]) + "\n" + body
                kw = kw_t or kw_match(full, KW_MS)
                if not kw: continue
                obj = {
                    "id": rid, "raw_id": th["raw_id"], "platform": "lowyat", "lang": "ms",
                    "title": t2 or th["title"], "body": body[:5000], "author": "",
                    "url": th["url"], "country_hint": "MY", "matched_keyword": kw,
                    "engagement": {"score": 0, "comments": 0},
                    "section": label, "crawled_at": now_iso(),
                }
                append(OUT_LOWYAT, obj); seen.add(rid); total += 1; picked += 1
            print(f"[lowyat] {label} p{page} picked={picked} total={total}")
            polite()
    print(f"[lowyat] DONE +{total}")
    return total


# ---------------- MY: cari.com.my (Discuz!) ----------------

CARI_FORUMS = [
    # Discuz style portal list — finance, career
    ("https://b.cari.com.my/portal.php?mod=list&catid=2", 3, "finance"),
    ("https://b.cari.com.my/portal.php?mod=list&catid=4", 2, "career"),
    ("https://b.cari.com.my/forum.php?mod=forumdisplay&fid=63", 2, "kerjaya"),
]

def cari_listing_url(base, page):
    if page <= 1: return base
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}page={page}"


def cari_parse_threads(soup):
    threads = []
    # Discuz: thread links look like /forum.php?mod=viewthread&tid=<id>
    # Portal articles: /portal.php?mod=view&aid=<id> or /article-<id>-<page>-<rand>.html
    anchors = soup.select("a[href*='thread']") + soup.select("a[href*='aid=']") + soup.select("a[href*='article-']") + soup.select("a[href*='tid=']")
    seen_ids = set()
    for a in anchors:
        href = a.get("href", "") or ""
        # thread id
        m = re.search(r"tid=(\d+)", href) or re.search(r"thread-(\d+)-", href)
        kind = "thread"
        if not m:
            m = re.search(r"aid=(\d+)", href) or re.search(r"article-(\d+)-", href)
            kind = "article"
        if not m: continue
        nid = m.group(1)
        key = f"{kind}:{nid}"
        if key in seen_ids: continue
        seen_ids.add(key)
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 5: continue
        if href.startswith("/"):
            href = "https://b.cari.com.my" + href
        elif href.startswith("portal.php") or href.startswith("forum.php") or href.startswith("article-") or href.startswith("thread-"):
            href = "https://b.cari.com.my/" + href
        threads.append({"raw_id": f"{kind}_{nid}", "title": title, "url": href, "kind": kind})
    return threads


def cari_fetch_thread(url):
    r = safe_get(url, hdr("ms-MY,ms;q=0.9,zh-CN;q=0.7,en;q=0.5", "https://b.cari.com.my/"), label="cari")
    if r is None: return None, "", -1
    if r.status_code != 200: return None, "", r.status_code
    if detect_captcha(r.text): return None, "", "captcha"
    # cari may serve gbk; requests will guess. Force apparent encoding.
    if r.encoding and r.encoding.lower() in ("iso-8859-1", "ascii"):
        r.encoding = r.apparent_encoding or "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")
    title_el = soup.select_one("h1, .ph .ts, #thread_subject, span#thread_subject, .article_title")
    title = title_el.get_text(" ", strip=True) if title_el else ""
    posts = (soup.select(".t_f") or soup.select(".article_content")
             or soup.select("td.t_f") or soup.select(".pcb")
             or soup.select("article"))
    chunks = []
    for p in posts[:5]:
        t = p.get_text(" ", strip=True)
        if t: chunks.append(t)
    return title, "\n\n---\n\n".join(chunks), 200


def crawl_cari():
    seen = load_seen(OUT_CARI)
    total = 0
    diag = False
    for base, n_pages, label in CARI_FORUMS:
        for page in range(1, n_pages + 1):
            url = cari_listing_url(base, page)
            r = safe_get(url, hdr("ms-MY,ms;q=0.9,zh-CN;q=0.7,en;q=0.5", "https://b.cari.com.my/"), label="cari")
            if r is None: polite(); continue
            if r.status_code != 200:
                print(f"[cari] list {label} p{page} status={r.status_code}")
                polite(); continue
            if r.encoding and r.encoding.lower() in ("iso-8859-1", "ascii"):
                r.encoding = r.apparent_encoding or "utf-8"
            if detect_captcha(r.text):
                print("[cari] CAPTCHA — abort."); return total
            soup = BeautifulSoup(r.text, "html.parser")
            threads = cari_parse_threads(soup)
            if not threads and not diag and page == 1:
                print(f"[cari] {label} p1 0 threads. HTML 800-char dump:")
                print(r.text[:800])
                diag = True
            print(f"[cari] {label} p{page} threads={len(threads)}")
            polite(0.8, 1.3)
            picked = 0
            for th in threads:
                kw_t = kw_match(th["title"], KW_MS)
                if not kw_t and picked >= 6:
                    continue
                rid = md5_16("cari", th["raw_id"])
                if rid in seen: continue
                t2, body, st = cari_fetch_thread(th["url"])
                polite()
                if st == "captcha":
                    print("[cari] CAPTCHA on detail — abort."); return total
                if st != 200: continue
                full = (t2 or th["title"]) + "\n" + body
                kw = kw_t or kw_match(full, KW_MS)
                if not kw: continue
                obj = {
                    "id": rid, "raw_id": th["raw_id"], "platform": "cari", "lang": "ms",
                    "title": t2 or th["title"], "body": body[:5000], "author": "",
                    "url": th["url"], "country_hint": "MY", "matched_keyword": kw,
                    "engagement": {"score": 0, "comments": 0},
                    "section": label, "crawled_at": now_iso(),
                }
                append(OUT_CARI, obj); seen.add(rid); total += 1; picked += 1
            print(f"[cari] {label} p{page} picked={picked} total={total}")
            polite()
    print(f"[cari] DONE +{total}")
    return total


# ---------------- samples ----------------

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
            print(f"  - kw={o.get('matched_keyword')!r} | {t}")
            print(f"    body: {b}...")
        except Exception as e:
            print(f"  parse err: {e}")
    return len(lines)


if __name__ == "__main__":
    results = {}
    for name, fn, out in [
        ("voz", crawl_voz, OUT_VOZ),
        ("tinhte", crawl_tinhte, OUT_TINHTE),
        ("kaskus", crawl_kaskus, OUT_KASKUS),
        ("blognone", crawl_blognone, OUT_BLOGNONE),
        ("sanook_money", crawl_sanook, OUT_SANOOK),
        ("lowyat", crawl_lowyat, OUT_LOWYAT),
        ("cari", crawl_cari, OUT_CARI),
    ]:
        print(f"\n###### START {name} ######")
        try:
            n = fn()
        except Exception as e:
            print(f"[{name}] CRASH: {e}")
            n = 0
        results[name] = (n, out)

    print("\n\n========= SUMMARY =========")
    for name, (n, out) in results.items():
        ln = print_samples(out, name)
        print(f"[{name}] +{n} new | file lines={ln} | path={out}")
