"""越南语 + 泰语：通过 RSS / 替代渠道抓本地母语收入披露原文。

vnexpress.net (VN) 和 pantip.com (TH) detail page 被反爬挡，但 RSS endpoint
通常不挡。即使 detail 403，RSS 自带的 description 字段也能作为 body fallback。

输出：
  data/raw/rss_alt_vn_native_<DAY>.jsonl  (lang=vi, country_hint=VN)
  data/raw/rss_alt_th_native_<DAY>.jsonl  (lang=th, country_hint=TH)
"""
import json, hashlib, re, time, random, ssl
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from lxml import etree

UA_BROWSER = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

DAY = datetime.now().strftime("%Y%m%d")
OUT_VN = Path(f"data/raw/rss_alt_vn_native_{DAY}.jsonl")
OUT_TH = Path(f"data/raw/rss_alt_th_native_{DAY}.jsonl")

# ------------------------------------------------------------------
# Feeds — 选了判断最有内容 + 最稳的（kinh-doanh / business / money 板块）
# ------------------------------------------------------------------
VN_FEEDS = [
    # name, url, accept-language, lang
    ("rss_vnexpress_kinhdoanh", "https://vnexpress.net/rss/kinh-doanh.rss"),
    ("rss_vnexpress_congnghe",  "https://vnexpress.net/rss/cong-nghe.rss"),
    ("rss_dantri_kinhdoanh",    "https://dantri.com.vn/rss/kinh-doanh.rss"),
    ("rss_thanhnien_kinhdoanh", "https://thanhnien.vn/rss/kinh-doanh.rss"),
    ("rss_tuoitre_kinhte",      "https://tuoitre.vn/rss/kinh-te.rss"),
    ("rss_vietnamnet_kinhdoanh","https://vietnamnet.vn/rss/kinh-doanh.rss"),
]

TH_FEEDS = [
    ("rss_thairath_business",      "https://www.thairath.co.th/rss/news/business"),
    ("rss_bangkokbiznews_business","https://www.bangkokbiznews.com/rss/news/business.xml"),
    ("rss_kapook_business",        "https://www.kapook.com/rss/business.xml"),
    ("rss_sanook_money",           "https://www.sanook.com/money/rss.xml"),
    ("rss_workpointtoday",         "https://workpointtoday.com/feed/"),
    ("rss_thaipbs_economy",        "https://www.thaipbs.or.th/rss/news/economy.xml"),
    # pantip 板块 .rss — 不一定有，能拿就拿不到就跳
    ("rss_pantip_sinthorn",        "https://pantip.com/forum/sinthorn.rss"),
    ("rss_pantip_klaibaan",        "https://pantip.com/forum/klaibaan.rss"),
]

# ------------------------------------------------------------------
# Keywords (本地母语，未做 normalization)
# ------------------------------------------------------------------
VN_KEYWORDS = [
    "lương", "thu nhập", "kiếm tiền", "freelance", "nghỉ hưu", "FIRE",
    "lương kỹ sư", "lương lập trình", "đầu tư", "tiết kiệm",
    "triệu/tháng", "triệu đồng", "thu nhập thụ động", "khởi nghiệp",
    "làm thêm", "nghề tay trái", "lương tháng",
]
TH_KEYWORDS = [
    "เงินเดือน", "รายได้", "freelance", "อาชีพ", "ลาออก", "เกษียณ",
    "FIRE", "เก็บเงิน", "ออมเงิน", "ทำเงิน", "ลงทุน", "พนักงาน",
    "บาท/เดือน", "หาเงิน", "ค่าจ้าง", "อาชีพเสริม",
]


# ------------------------------------------------------------------
# Utils
# ------------------------------------------------------------------
def md5_16(*p): return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]
def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")

def append(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def polite(): time.sleep(random.uniform(1.3, 1.8))

def load_seen(path):
    seen = set()
    if path.exists():
        for line in path.open():
            try: seen.add(json.loads(line)["id"])
            except: pass
    return seen


def headers_for(lang):
    if lang == "vi":
        al = "vi-VN,vi;q=0.9,en;q=0.5"
    elif lang == "th":
        al = "th-TH,th;q=0.9,en;q=0.5"
    else:
        al = "en-US,en;q=0.9"
    return {
        "User-Agent": UA_BROWSER,
        "Accept-Language": al,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


# ------------------------------------------------------------------
# RSS parsing
# ------------------------------------------------------------------
def fetch_rss_items(url, lang, timeout=20):
    """Return list of dict {title, link, description, guid, pubDate} or []."""
    try:
        r = requests.get(url, headers=headers_for(lang), timeout=timeout, verify=True)
    except (requests.exceptions.SSLError, ssl.SSLError) as e:
        # 某些泰国站 SSL 链不全，降级一次
        try:
            r = requests.get(url, headers=headers_for(lang), timeout=timeout, verify=False)
        except Exception as e2:
            print(f"[rss] {url} SSL+fallback err: {e2}")
            return [], -1
    except Exception as e:
        print(f"[rss] {url} err: {e}")
        return [], -1
    if r.status_code != 200:
        return [], r.status_code
    raw = r.content
    try:
        # lxml-xml 解析；recover=True 容忍小毛病
        parser = etree.XMLParser(recover=True, encoding="utf-8")
        root = etree.fromstring(raw, parser=parser)
    except Exception as e:
        print(f"[rss] {url} parse err: {e}")
        return [], r.status_code
    if root is None:
        return [], r.status_code

    items = []
    # RSS 2.0
    for it in root.findall(".//item"):
        items.append(_extract_item(it, ns=False))
    # Atom
    if not items:
        atom_ns = {"a": "http://www.w3.org/2005/Atom"}
        for it in root.findall(".//a:entry", atom_ns):
            items.append(_extract_atom_entry(it, atom_ns))
    return items, r.status_code


def _xtxt(el, tag):
    t = el.find(tag)
    return (t.text or "").strip() if t is not None and t.text else ""


def _extract_item(it, ns=False):
    title = _xtxt(it, "title")
    link = _xtxt(it, "link")
    desc = _xtxt(it, "description")
    guid = _xtxt(it, "guid") or link
    pub = _xtxt(it, "pubDate")
    # 有的 feed 里 description 是 CDATA 嵌 HTML
    if desc and ("<" in desc and ">" in desc):
        try:
            desc = BeautifulSoup(desc, "html.parser").get_text(" ", strip=True)
        except Exception:
            pass
    # content:encoded (常见于 wordpress feed)
    enc = it.find("{http://purl.org/rss/1.0/modules/content/}encoded")
    if enc is not None and enc.text:
        try:
            extra = BeautifulSoup(enc.text, "html.parser").get_text(" ", strip=True)
            if len(extra) > len(desc):
                desc = extra
        except Exception:
            pass
    return {"title": title, "link": link, "description": desc, "guid": guid, "pubDate": pub}


def _extract_atom_entry(it, ns):
    def t(tag):
        e = it.find("a:" + tag, ns)
        return (e.text or "").strip() if e is not None and e.text else ""
    title = t("title")
    link = ""
    le = it.find("a:link", ns)
    if le is not None:
        link = le.get("href", "") or (le.text or "").strip()
    summary = t("summary") or t("content")
    if summary and "<" in summary:
        try: summary = BeautifulSoup(summary, "html.parser").get_text(" ", strip=True)
        except: pass
    guid = t("id") or link
    pub = t("published") or t("updated")
    return {"title": title, "link": link, "description": summary, "guid": guid, "pubDate": pub}


# ------------------------------------------------------------------
# Article detail fetch (best-effort; 403 is OK, fallback to RSS desc)
# ------------------------------------------------------------------
DETAIL_SELECTORS = [
    "article.fck_detail",   # vnexpress
    ".fck_detail",
    "div.detail-content",   # dantri / thairath variants
    ".detail-content",
    "article.entry-content",
    ".entry-content",
    ".post-content",
    "article",
    "main",
]


def fetch_article_body(url, lang, timeout=15):
    if not url: return ""
    try:
        r = requests.get(url, headers=headers_for(lang), timeout=timeout)
    except Exception:
        return ""
    if r.status_code != 200:
        return ""
    try:
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception:
        return ""
    body = ""
    for sel in DETAIL_SELECTORS:
        el = soup.select_one(sel)
        if el:
            txt = el.get_text(" ", strip=True)
            if len(txt) > len(body):
                body = txt
            if len(body) > 800:
                break
    if not body:
        # fallback: 拼所有 <p>
        ps = soup.find_all("p")
        body = " ".join(p.get_text(" ", strip=True) for p in ps if p.get_text(strip=True))
    return body


# ------------------------------------------------------------------
# Crawl loop
# ------------------------------------------------------------------
def matches_keywords(text, keywords):
    """Return matched keyword (lowered match) or empty string."""
    if not text: return ""
    low = text.lower()
    for kw in keywords:
        if kw.lower() in low:
            return kw
    return ""


def crawl_feeds(feeds, lang, country, keywords, out_path):
    seen = load_seen(out_path)
    total = 0
    feed_stats = []
    for feed_name, url in feeds:
        items, status = fetch_rss_items(url, lang)
        polite()
        if status != 200:
            print(f"[{feed_name}] FAIL status={status} url={url}")
            feed_stats.append((feed_name, status, 0, 0, 0))
            continue
        if not items:
            print(f"[{feed_name}] empty (status=200 but no items) url={url}")
            feed_stats.append((feed_name, status, 0, 0, 0))
            continue
        added_for_feed = 0
        matched_for_feed = 0
        for it in items:
            title = it.get("title", "")
            desc = it.get("description", "")
            link = it.get("link", "")
            guid = it.get("guid", "") or link
            haystack = (title + " \n " + desc)
            kw = matches_keywords(haystack, keywords)
            if not kw:
                continue
            matched_for_feed += 1
            rid_raw = guid or link
            if not rid_raw:
                continue
            rid = md5_16(feed_name, rid_raw)
            if rid in seen:
                continue
            # 拿正文（best-effort），若失败就用 description
            body = fetch_article_body(link, lang)
            polite()
            if not body or len(body) < 80:
                body = desc
            if not body:
                # 完全没拿到任何内容就跳
                continue
            obj = {
                "id": rid,
                "raw_id": rid_raw,
                "platform": feed_name,
                "lang": lang,
                "title": title,
                "body": body[:5000],
                "author": "",
                "url": link,
                "country_hint": country,
                "matched_keyword": kw,
                "engagement": {"score": 0, "comments": 0, "views": None},
                "pubDate": it.get("pubDate", ""),
                "feed_url": url,
                "crawled_at": now_iso(),
            }
            append(out_path, obj)
            seen.add(rid)
            total += 1
            added_for_feed += 1
        print(f"[{feed_name}] items={len(items)} matched={matched_for_feed} new={added_for_feed} (running total={total})")
        feed_stats.append((feed_name, status, len(items), matched_for_feed, added_for_feed))
    return total, feed_stats


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
            b = (o.get("body") or "").replace("\n", " ")[:200]
            print(f"  - [{o.get('platform')}] kw={o.get('matched_keyword')!r} | {t}")
            print(f"    body: {b}...")
        except Exception as e:
            print(f"  parse err: {e}")
    return len(lines)


if __name__ == "__main__":
    print(f"=== RSS-alt VN/TH crawler — DAY={DAY} ===\n")

    print(">>> VN feeds")
    n_vn, stats_vn = crawl_feeds(VN_FEEDS, "vi", "VN", VN_KEYWORDS, OUT_VN)

    print("\n>>> TH feeds")
    n_th, stats_th = crawl_feeds(TH_FEEDS, "th", "TH", TH_KEYWORDS, OUT_TH)

    lr_vn = print_samples(OUT_VN, "VN")
    lr_th = print_samples(OUT_TH, "TH")

    print("\n=== FEED STATUS SUMMARY ===")
    print(f"{'feed':40s} {'status':>6s} {'items':>6s} {'match':>6s} {'new':>5s}")
    for s in stats_vn + stats_th:
        name, status, n_items, n_match, n_added = s
        print(f"{name:40s} {str(status):>6s} {n_items:>6d} {n_match:>6d} {n_added:>5d}")

    print(f"\n=== TOTAL: VN +{n_vn} (file {lr_vn}), TH +{n_th} (file {lr_th}) ===")
