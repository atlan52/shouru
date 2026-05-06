"""非洲 + 中东本地母语收入帖 — Nairaland (NG) / MyBroadband (ZA) / 阿语 SA EG AE / 波斯语 IR / 希伯来语 IL。

每文件 / 国家或语种独立输出，schema 同 r_mexico_native。
"""
import json, hashlib, time, random, re, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urljoin
import requests
from bs4 import BeautifulSoup

DAY = datetime.now().strftime("%Y%m%d")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
TIMEOUT = 25
SLEEP = (1.3, 1.7)

# ===== 关键词正则 =====
KW_EN = re.compile(
    r"\b(salary|salaries|wage|wages|earn|earning|earnings|income|paid|"
    r"naira|shilling|rand|FIRE|pension|retire|retirement|payslip|"
    r"freelance|side hustle|bonus)\b",
    re.IGNORECASE,
)
KW_AR = re.compile(
    r"راتب|دخل|أجر|مكافأة|تقاعد|معاش|عمل حر|مستقل|"
    r"ريال|جنيه|درهم|FIRE|أعمال|كسب|دخول|رواتب"
)
KW_FA = re.compile(
    r"حقوق|درآمد|تومان|ریال|بازنشست|FIRE|کار آزاد|"
    r"فریلنس|دستمزد|پاداش|سرمایه‌گذاری|پس‌انداز"
)
KW_HE = re.compile(
    r"משכורת|הכנסה|שכר|פנסיה|FIRE|פרילנס|"
    r"בונוס|פרישה|שקל|חיסכון|השקעה"
)

# ===== Feed 配置：(name, url, [body_selectors], country_hint) =====
RSS_NG = [  # punch + thisday
    ("rss_punchng_business", "https://punchng.com/business/feed/",
     ["article", ".post-content", ".entry-content", ".td-post-content"], "NG"),
    ("rss_thisday_business", "https://www.thisdaylive.com/index.php/category/business/feed/",
     ["article", ".td-post-content", ".entry-content"], "NG"),
]
RSS_KE = [
    ("rss_businessdailyafrica", "https://www.businessdailyafrica.com/feed/",
     ["article", ".article-body", ".story-content"], "KE"),
    ("rss_tuko_ke", "https://www.tuko.co.ke/feed/",
     ["article", ".post-content", ".entry-content"], "KE"),
    ("rss_nation_africa_ke_biz", "https://nation.africa/kenya/business?service=rss",
     ["article", ".article-body", ".story-content"], "KE"),
]
RSS_ZA = [
    ("rss_mybroadband", "https://mybroadband.co.za/news/feed/",
     ["article", ".entry-content", ".post-content"], "ZA"),
    ("rss_dailymaverick_biz", "https://www.dailymaverick.co.za/section/business-maverick/feed/",
     ["article", ".article-body", ".article__body"], "ZA"),
]
RSS_AR_EXTRA = [  # SA / EG / AE
    ("rss_alyaum_eco", "https://www.alyaum.com/rss/economy.xml",
     ["article", ".article-body", ".entry-content"], "SA"),
    ("rss_skynewsarabia_eco", "https://www.skynewsarabia.com/rss/economy.xml",
     ["article", ".article-body", ".article-content"], "AE"),
    ("rss_akhbarak_eco", "https://akhbarak.net/rss/economy",
     ["article", ".article-body", ".content"], "EG"),
    ("rss_gulfnews_ae_biz", "https://www.gulfnews.ae/feeds/rss/business.xml",
     ["article", ".article-body", ".story-element"], "AE"),
]
RSS_FA = [
    ("rss_donya_e_eqtesad", "https://www.donya-e-eqtesad.com/fa/rss/category/iran",
     ["article", ".item-text", ".article-body"], "IR"),
    ("rss_ilna_eqtesadi", "https://www.ilna.ir/fa/rss/eqtesadi",
     ["article", ".body", ".item-text"], "IR"),
]
RSS_HE = [
    ("rss_themarker", "https://www.themarker.com/cmlink/1.144",
     ["article", ".article-body", ".articleBody"], "IL"),
    ("rss_calcalist_finance", "https://www.calcalist.co.il/RSS/articles_finance.xml",
     ["article", ".article-body", "#articleBody"], "IL"),
    ("rss_globes", "https://www.globes.co.il/rss/RSSfeed.aspx?iID=585",
     ["article", ".article-body", ".article_body"], "IL"),
]


def md5_16(*p): return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]
def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def polite(): time.sleep(random.uniform(*SLEEP))


def hdr(lang_region: str):
    """lang_region: en-NG / en-KE / en-ZA / ar / fa-IR / he-IL"""
    accept_map = {
        "en-NG": "en-NG,en;q=0.9",
        "en-KE": "en-KE,en;q=0.9",
        "en-ZA": "en-ZA,en;q=0.9",
        "ar":    "ar,en;q=0.5",
        "fa-IR": "fa-IR,fa;q=0.9,en;q=0.5",
        "he-IL": "he-IL,he;q=0.9,en;q=0.5",
    }
    return {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": accept_map.get(lang_region, "en;q=0.9"),
    }


def fetch(url: str, lang_region: str, label: str = "") -> str | None:
    try:
        r = requests.get(url, headers=hdr(lang_region), timeout=TIMEOUT, verify=True)
    except requests.exceptions.SSLError as e:
        print(f"  [{label}] SSL err: {e}", file=sys.stderr); return None
    except Exception as e:
        print(f"  [{label}] err: {e}", file=sys.stderr); return None
    if r.status_code >= 400:
        print(f"  [{label}] status={r.status_code}", file=sys.stderr); return None
    return r.text


def parse_rss(xml: str):
    soup = BeautifulSoup(xml, "xml")
    items = soup.find_all("item") or soup.find_all("entry")
    out = []
    for it in items:
        t = it.find("title"); l = it.find("link"); g = it.find("guid") or it.find("id")
        d = it.find("description") or it.find("summary") or it.find("content")
        a = it.find("author") or it.find("dc:creator")
        p = it.find("pubDate") or it.find("published") or it.find("updated")
        title = t.get_text(strip=True) if t else ""
        link = ""
        if l:
            link = l.get("href") or l.get_text(strip=True) or ""
        guid = (g.get_text(strip=True) if g else "") or link
        desc_html = d.get_text(" ", strip=True) if d else ""
        # description 可能含 HTML entity / 标签，再过一层去标签
        desc = BeautifulSoup(desc_html, "html.parser").get_text(" ", strip=True) if desc_html else ""
        author = a.get_text(strip=True) if a else ""
        pub = p.get_text(strip=True) if p else ""
        if title and link:
            out.append({
                "raw_id": guid, "title": title, "summary": desc,
                "link": link, "author": author, "pub_date": pub,
            })
    return out


def fetch_body(url: str, sel: list[str], lang_region: str) -> str:
    html = fetch(url, lang_region, label=f"body {urlparse(url).netloc}")
    if not html: return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "aside", "header", "footer", "form"]):
        tag.decompose()
    for s in sel:
        el = soup.select_one(s)
        if el:
            txt = el.get_text(" ", strip=True)
            if len(txt) > 100:
                return txt[:5000]
    ps = [p.get_text(" ", strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 20]
    return " ".join(ps)[:5000]


def append(out_path: Path, obj: dict):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def load_seen(out_path: Path) -> set:
    seen = set()
    if out_path.exists():
        for line in out_path.open(encoding="utf-8"):
            try: seen.add(json.loads(line)["id"])
            except Exception: pass
    return seen


def country_from_domain(url: str, default_country: str) -> str:
    """根据 feed 域名做 country_hint 兜底判断。"""
    host = urlparse(url).netloc.lower()
    if host.endswith(".ng") or "punchng" in host or "thisdaylive" in host or "nairaland" in host: return "NG"
    if host.endswith(".co.ke") or "tuko.co.ke" in host or "businessdailyafrica" in host: return "KE"
    if host.endswith("nation.africa"): return "KE"
    if host.endswith(".co.za") or "mybroadband" in host or "dailymaverick" in host: return "ZA"
    if host.endswith(".sa") or "alyaum" in host: return "SA"
    if host.endswith(".ae") or "gulfnews.ae" in host: return "AE"
    if "akhbarak" in host or host.endswith(".eg"): return "EG"
    if host.endswith(".ir") or "donya-e-eqtesad" in host or "ilna.ir" in host: return "IR"
    if host.endswith(".co.il") or "themarker" in host or "calcalist" in host or "globes" in host: return "IL"
    if "skynewsarabia" in host: return "AE"  # 总部
    return default_country


# =================== RSS 通用爬取 ===================
def crawl_rss_group(group_name: str, feeds: list, kw_re, lang: str, lang_region: str, out_path: Path):
    seen = load_seen(out_path)
    print(f"\n========== GROUP={group_name} lang={lang} ==========")
    summary = []
    for name, url, sel, default_country in feeds:
        print(f"\n  --- {name} ({url}) ---")
        xml = fetch(url, lang_region, label=name)
        if not xml:
            summary.append((name, 0, 0, 0)); continue
        items = parse_rss(xml)
        print(f"    items={len(items)}")
        matched = 0; written = 0
        for it in items:
            text = it["title"] + " " + it["summary"]
            m = kw_re.search(text)
            if not m: continue
            matched += 1
            rid = md5_16(name, it["raw_id"])
            if rid in seen: continue
            body = fetch_body(it["link"], sel, lang_region) or it["summary"]
            if not body or len(body) < 50:
                polite(); continue
            ch = country_from_domain(it["link"], default_country)
            obj = {
                "id": rid,
                "raw_id": it["raw_id"],
                "platform": name,
                "lang": lang,
                "title": it["title"][:300],
                "body": body[:5000],
                "author": it["author"],
                "url": it["link"],
                "country_hint": ch,
                "matched_keyword": m.group(0),
                "engagement": {"score": 0, "comments": 0, "views": None},
                "pub_date": it.get("pub_date", ""),
                "crawled_at": now_iso(),
            }
            append(out_path, obj); seen.add(rid); written += 1
            polite()
        print(f"    matched={matched} written={written}")
        summary.append((name, len(items), matched, written))
        polite()
    final = sum(1 for _ in out_path.open()) if out_path.exists() else 0
    print(f"\n  SUMMARY {group_name}:")
    for name, i, mm, w in summary:
        print(f"    {name:<32} items={i:>4} matched={mm:>4} written={w:>4}")
    print(f"  FILE TOTAL: {final}  -> {out_path}")
    return final


# =================== Nairaland HTML 抓取 ===================
NAIRALAND_BASE = "https://www.nairaland.com"
NAIRALAND_OUT = Path(f"data/raw/nairaland_native_{DAY}.jsonl")


def parse_nairaland_listing(html: str) -> list[dict]:
    """从 /business 列表页提取帖子链接 + 标题。

    Nairaland 列表里每个主题是 `td.bold` 下的 `<a href="/<id>/<slug>">`，
    旁边是发帖人、跟随的 stats。
    """
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen_href = set()
    # 主选择：td.bold a
    for td in soup.select("td.bold"):
        a = td.find("a", href=True)
        if not a: continue
        href = a.get("href", "")
        # 帖子 URL 形如 /<numeric_id>/<slug>
        if not re.match(r"^/\d+/", href): continue
        if href in seen_href: continue
        seen_href.add(href)
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 4: continue
        # raw_id = 数字部分
        m = re.match(r"^/(\d+)/", href)
        raw_id = m.group(1) if m else href
        full = urljoin(NAIRALAND_BASE, href)
        out.append({"raw_id": raw_id, "title": title, "url": full})
    # fallback: 找所有 h2 a
    if not out:
        for h2 in soup.select("h2 a, .narrow a"):
            href = h2.get("href", "")
            if not re.match(r"^/\d+/", href): continue
            if href in seen_href: continue
            seen_href.add(href)
            title = h2.get_text(" ", strip=True)
            if not title: continue
            m = re.match(r"^/(\d+)/", href)
            raw_id = m.group(1) if m else href
            out.append({"raw_id": raw_id, "title": title, "url": urljoin(NAIRALAND_BASE, href)})
    return out


def fetch_nairaland_thread(url: str) -> tuple[str, str]:
    """返回 (body, author)。Nairaland 帖子正文在 .narrow td 里，作者在
    `.bold a[href^='/']` 之类。"""
    html = fetch(url, "en-NG", label=f"thread {urlparse(url).path}")
    if not html: return "", ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "aside", "header", "footer", "form"]):
        tag.decompose()
    # 帖子内容：td.l.pd 或 .narrow
    body = ""
    for sel in [".narrow", "td.l.pd", "td.l"]:
        el = soup.select_one(sel)
        if el:
            txt = el.get_text(" ", strip=True)
            if len(txt) > 100:
                body = txt[:5000]; break
    if not body:
        ps = [p.get_text(" ", strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 20]
        body = " ".join(ps)[:5000]
    # 作者：第一个 .bold > a 通常是发帖人
    author = ""
    a = soup.select_one("td.bold a[href^='/']")
    if a:
        author = a.get_text(" ", strip=True)
    return body, author


def crawl_nairaland():
    seen = load_seen(NAIRALAND_OUT)
    print(f"\n========== Nairaland HTML ==========")
    total_listed = 0; total_matched = 0; total_written = 0
    for page in range(0, 3):  # 前 3 页：/business/0  /business/1  /business/2
        list_url = f"{NAIRALAND_BASE}/business/{page}" if page > 0 else f"{NAIRALAND_BASE}/business"
        print(f"\n  --- list page {page} ({list_url}) ---")
        html = fetch(list_url, "en-NG", label=f"nairaland_list_{page}")
        if not html:
            continue
        threads = parse_nairaland_listing(html)
        print(f"    threads={len(threads)}")
        total_listed += len(threads)
        if not threads:
            # dump 前 200 字符 stderr 方便诊断
            print(f"    DEBUG html[:200]={html[:200]!r}", file=sys.stderr)
        for th in threads:
            text = th["title"]
            m = KW_EN.search(text)
            if not m: continue
            total_matched += 1
            rid = md5_16("nairaland", th["raw_id"])
            if rid in seen: continue
            body, author = fetch_nairaland_thread(th["url"])
            if not body or len(body) < 80:
                polite(); continue
            obj = {
                "id": rid,
                "raw_id": th["raw_id"],
                "platform": "nairaland",
                "lang": "en",
                "title": th["title"][:300],
                "body": body,
                "author": author,
                "url": th["url"],
                "country_hint": "NG",
                "matched_keyword": m.group(0),
                "engagement": {"score": 0, "comments": 0, "views": None},
                "crawled_at": now_iso(),
            }
            append(NAIRALAND_OUT, obj); seen.add(rid); total_written += 1
            polite()
        polite()
    final = sum(1 for _ in NAIRALAND_OUT.open()) if NAIRALAND_OUT.exists() else 0
    print(f"\n  Nairaland SUMMARY: listed={total_listed} matched={total_matched} written={total_written}")
    print(f"  FILE TOTAL: {final}  -> {NAIRALAND_OUT}")
    return final


# =================== samples ===================
def print_samples(path: Path, label: str, k: int = 3):
    if not path.exists():
        print(f"\n[{label}] file missing: {path}")
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    print(f"\n=== {label}: {path} | {len(lines)} lines ===")
    for ln in lines[:k]:
        try:
            o = json.loads(ln)
            t = (o.get("title") or "").replace("\n", " ")[:120]
            b = (o.get("body") or "").replace("\n", " ")[:180]
            print(f"  - [{o.get('country_hint')}] kw={o.get('matched_keyword')!r} | {t}")
            print(f"    body: {b}...")
        except Exception as e:
            print(f"  parse err: {e}")
    return len(lines)


def main():
    out_files = []

    # NG Nairaland
    try: crawl_nairaland()
    except Exception as e: print(f"[nairaland] fatal: {e}", file=sys.stderr)
    out_files.append((NAIRALAND_OUT, "nairaland (NG)"))

    # NG punch + thisday
    p = Path(f"data/raw/rss_alt_ng_native_{DAY}.jsonl")
    try: crawl_rss_group("NG_RSS", RSS_NG, KW_EN, "en", "en-NG", p)
    except Exception as e: print(f"[NG_RSS] fatal: {e}", file=sys.stderr)
    out_files.append((p, "rss_alt_ng (NG)"))

    # KE
    p = Path(f"data/raw/rss_alt_ke_native_{DAY}.jsonl")
    try: crawl_rss_group("KE_RSS", RSS_KE, KW_EN, "en", "en-KE", p)
    except Exception as e: print(f"[KE_RSS] fatal: {e}", file=sys.stderr)
    out_files.append((p, "rss_alt_ke (KE)"))

    # ZA
    p = Path(f"data/raw/rss_alt_za_native_{DAY}.jsonl")
    try: crawl_rss_group("ZA_RSS", RSS_ZA, KW_EN, "en", "en-ZA", p)
    except Exception as e: print(f"[ZA_RSS] fatal: {e}", file=sys.stderr)
    out_files.append((p, "rss_alt_za (ZA)"))

    # AR extra (SA / EG / AE)
    p = Path(f"data/raw/rss_alt_ar_extra_native_{DAY}.jsonl")
    try: crawl_rss_group("AR_EXTRA", RSS_AR_EXTRA, KW_AR, "ar", "ar", p)
    except Exception as e: print(f"[AR_EXTRA] fatal: {e}", file=sys.stderr)
    out_files.append((p, "rss_alt_ar_extra (SA/EG/AE)"))

    # FA
    p = Path(f"data/raw/rss_alt_fa_native_{DAY}.jsonl")
    try: crawl_rss_group("FA_RSS", RSS_FA, KW_FA, "fa", "fa-IR", p)
    except Exception as e: print(f"[FA_RSS] fatal: {e}", file=sys.stderr)
    out_files.append((p, "rss_alt_fa (IR)"))

    # HE
    p = Path(f"data/raw/rss_alt_he_native_{DAY}.jsonl")
    try: crawl_rss_group("HE_RSS", RSS_HE, KW_HE, "he", "he-IL", p)
    except Exception as e: print(f"[HE_RSS] fatal: {e}", file=sys.stderr)
    out_files.append((p, "rss_alt_he (IL)"))

    # 末尾汇总
    print("\n\n############ FINAL TOTALS ############")
    grand = 0
    for path, lab in out_files:
        n = print_samples(path, lab)
        grand += n
    print(f"\n=== GRAND TOTAL across all files: {grand} ===")


if __name__ == "__main__":
    main()
