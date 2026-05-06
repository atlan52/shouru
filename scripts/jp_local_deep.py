"""日本本地母语收入帖深挖：moneyforward / note / opensalary / 5ch career / anond / toyokeizai / diamond。

7 站平行抓，输出独立 JSONL，schema 同 r_mexico_native。
"""
import json, hashlib, re, time, random
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, quote
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HDR = {
    "User-Agent": UA,
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.4",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
HDR_RSS = {
    "User-Agent": UA,
    "Accept-Language": "ja-JP,ja;q=0.9",
    "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
}

DAY = datetime.now().strftime("%Y%m%d")
RAW = Path("data/raw")

OUT = {
    "moneyforward": RAW / f"moneyforward_native_{DAY}.jsonl",
    "note":         RAW / f"note_jp_deep_native_{DAY}.jsonl",
    "opensalary":   RAW / f"opensalary_deep_native_{DAY}.jsonl",
    "5ch_career":   RAW / f"5ch_career_native_{DAY}.jsonl",
    "anond":        RAW / f"anond_deep_native_{DAY}.jsonl",
    "toyokeizai":   RAW / f"toyokeizai_deep_native_{DAY}.jsonl",
    "diamond":      RAW / f"diamond_deep_native_{DAY}.jsonl",
}

KEYWORDS_JP = [
    "年収", "月収", "時給", "手取り", "給料", "ボーナス", "賞与",
    "副業", "フリーランス", "FIRE", "早期退職", "老後資金",
    "投資", "配当", "不労所得", "起業", "個人事業主", "会社員",
]


def md5_16(*p): return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]
def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def polite(a=1.2, b=1.8): time.sleep(random.uniform(a, b))


def load_seen(path):
    seen = set()
    if path.exists():
        for line in path.open():
            try: seen.add(json.loads(line)["id"])
            except Exception: pass
    return seen


def has_kw(text):
    if not text: return False, ""
    for kw in KEYWORDS_JP:
        if kw in text:
            return True, kw
    return False, ""


def safe_get(url, headers=None, timeout=25, **kw):
    try:
        r = requests.get(url, headers=headers or HDR, timeout=timeout, **kw)
        return r
    except Exception as e:
        print(f"  req err {url}: {e}")
        return None


# ----------------------------------------------------------------------
# 1. マネー・フォワード ME blog (RSS)
# ----------------------------------------------------------------------
def crawl_moneyforward():
    cats = [
        "household-account",  # 家計簿
        "saving",             # 節約
        "investment",         # 投資
        "salary",             # 給与
        "side-job",           # 副業
        "retirement",         # 老後
        "tax",                # 税金
        "career",             # キャリア
    ]
    out = OUT["moneyforward"]
    seen = load_seen(out)
    total = 0
    for cat in cats:
        url = f"https://moneyforward.com/media/category/{cat}/feed/"
        r = safe_get(url, headers=HDR_RSS)
        if not r or r.status_code != 200:
            print(f"[mf] cat={cat} status={getattr(r,'status_code','-')}")
            polite(); continue
        soup = BeautifulSoup(r.text, "xml") if "xml" in (r.headers.get("Content-Type") or "") else BeautifulSoup(r.text, "html.parser")
        items = soup.find_all("item") or soup.find_all("entry")
        added = 0
        for it in items:
            link_el = it.find("link")
            link = ""
            if link_el:
                link = link_el.get_text(strip=True) if link_el.get_text(strip=True) else (link_el.get("href", "") or "")
            title_el = it.find("title")
            title = title_el.get_text(strip=True) if title_el else ""
            desc_el = it.find("description") or it.find("content:encoded") or it.find("summary") or it.find("content")
            desc = desc_el.get_text(" ", strip=True) if desc_el else ""
            if not link: continue
            rid = md5_16("moneyforward", link)
            if rid in seen: continue
            # fetch detail
            polite(0.8, 1.4)
            dr = safe_get(link)
            body = desc
            if dr and dr.status_code == 200:
                ds = BeautifulSoup(dr.text, "html.parser")
                main = ds.select_one("article") or ds.select_one("main") or ds.select_one(".article-body") or ds.select_one(".entry-content")
                if main: body = main.get_text(" ", strip=True)
            ok, kw = has_kw(title + " " + body)
            if not ok: continue
            obj = {
                "id": rid,
                "raw_id": link,
                "platform": "moneyforward",
                "lang": "ja",
                "title": title,
                "body": body[:5000],
                "author": "",
                "url": link,
                "country_hint": "JP",
                "matched_keyword": kw,
                "engagement": {"score": 0, "comments": 0, "views": None},
                "category": cat,
                "crawled_at": now_iso(),
            }
            append(out, obj); seen.add(rid); total += 1; added += 1
        print(f"[mf] cat={cat} items={len(items)} new={added} total={total}")
        polite()
    print(f"[moneyforward] DONE +{total}")
    return total


# ----------------------------------------------------------------------
# 2. Note.com search SSR
# ----------------------------------------------------------------------
def crawl_note():
    queries = [
        "年収公開", "月収", "副業収入", "フリーランス収入",
        "月100万", "月50万", "手取り", "FIRE達成",
    ]
    out = OUT["note"]
    seen = load_seen(out)
    total = 0
    href_re = re.compile(r"^/[A-Za-z0-9_\-]+/n/[A-Za-z0-9]+")
    for q in queries:
        for page in range(1, 4):  # 3 pages each
            url = f"https://note.com/search?context=note&q={quote(q)}&page={page}"
            r = safe_get(url)
            if not r or r.status_code != 200:
                print(f"[note] q={q} page={page} status={getattr(r,'status_code','-')}")
                polite(); continue
            soup = BeautifulSoup(r.text, "html.parser")
            # Pull from links
            links = set()
            for a in soup.find_all("a", href=True):
                h = a.get("href", "")
                if href_re.match(h):
                    links.add(h.split("?")[0])
            # Also try JSON-ish from __NEXT_DATA__
            for s in soup.find_all("script"):
                t = s.string or ""
                for m in re.finditer(r'"/[A-Za-z0-9_\-]+/n/[A-Za-z0-9]+"', t):
                    raw = m.group(0).strip('"')
                    if href_re.match(raw):
                        links.add(raw)
            if not links:
                print(f"[note] q={q!r} p{page} no links. head: {r.text[:200]}")
                polite(); continue
            added = 0
            picked = 0
            for path in list(links)[:12]:
                if picked >= 8: break
                full = "https://note.com" + path
                rid = md5_16("note_jp", path)
                if rid in seen: continue
                polite(0.9, 1.5)
                dr = safe_get(full)
                if not dr or dr.status_code != 200:
                    continue
                ds = BeautifulSoup(dr.text, "html.parser")
                t_el = ds.select_one("h1") or ds.select_one("title")
                title = t_el.get_text(" ", strip=True) if t_el else ""
                body_el = ds.select_one("div.note-common-styles__textnote-body") \
                    or ds.select_one("div[class*=textnote-body]") \
                    or ds.select_one("article") \
                    or ds.select_one("main")
                body = body_el.get_text(" ", strip=True) if body_el else ds.get_text(" ", strip=True)[:3000]
                author_el = ds.select_one("a[href^='/'][class*=user]") or ds.select_one("a[class*=Author]")
                author = author_el.get_text(" ", strip=True) if author_el else path.split("/")[1]
                ok, kw = has_kw(title + " " + body)
                if not ok:
                    continue
                obj = {
                    "id": rid,
                    "raw_id": path,
                    "platform": "note_jp",
                    "lang": "ja",
                    "title": title,
                    "body": body[:5000],
                    "author": author,
                    "url": full,
                    "country_hint": "JP",
                    "matched_keyword": kw or q,
                    "engagement": {"score": 0, "comments": 0, "views": None},
                    "search_query": q,
                    "crawled_at": now_iso(),
                }
                append(out, obj); seen.add(rid); total += 1; added += 1; picked += 1
            print(f"[note] q={q!r} p{page} links={len(links)} added={added} total={total}")
            polite()
    print(f"[note_jp] DONE +{total}")
    return total


# ----------------------------------------------------------------------
# 3. OpenSALARY.jp
# ----------------------------------------------------------------------
def crawl_opensalary():
    out = OUT["opensalary"]
    seen = load_seen(out)
    total = 0
    # try popular companies + roles. Slug guesses.
    companies = [
        "google-japan", "amazon-japan", "rakuten", "mercari", "cyberagent",
        "recruit", "softbank", "nintendo", "toyota", "sony",
        "hitachi", "nec", "ntt", "ntt-data", "dena",
        "line", "yahoo-japan", "salesforce-japan", "microsoft-japan", "apple-japan",
    ]
    roles = [
        "software-engineer", "data-scientist", "product-manager",
        "engineer", "designer", "sales", "marketing",
        "consultant", "researcher", "manager",
    ]
    # 1) try /companies/<slug>
    for c in companies:
        url = f"https://opensalary.jp/companies/{c}"
        r = safe_get(url)
        if not r or r.status_code != 200:
            print(f"[opensalary] company={c} status={getattr(r,'status_code','-')}")
            polite(); continue
        soup = BeautifulSoup(r.text, "html.parser")
        title_el = soup.select_one("h1") or soup.select_one("title")
        title = title_el.get_text(" ", strip=True) if title_el else c
        body_el = soup.select_one("main") or soup.select_one("body")
        body = body_el.get_text(" ", strip=True) if body_el else r.text
        ok, kw = has_kw(title + " " + body)
        if not ok and not re.search(r"年収|給与|salary|万円", body):
            polite(); continue
        rid = md5_16("opensalary", "c", c)
        if rid in seen:
            polite(); continue
        obj = {
            "id": rid,
            "raw_id": f"company:{c}",
            "platform": "opensalary",
            "lang": "ja",
            "title": title,
            "body": body[:5000],
            "author": c,
            "url": url,
            "country_hint": "JP",
            "matched_keyword": kw or "年収",
            "engagement": {"score": 0, "comments": 0, "views": None},
            "kind": "company",
            "crawled_at": now_iso(),
        }
        append(out, obj); seen.add(rid); total += 1
        print(f"[opensalary] company={c} added (total={total})")
        polite()
    # 2) try /jobs/<role>
    for ro in roles:
        url = f"https://opensalary.jp/jobs/{ro}"
        r = safe_get(url)
        if not r or r.status_code != 200:
            print(f"[opensalary] job={ro} status={getattr(r,'status_code','-')}")
            polite(); continue
        soup = BeautifulSoup(r.text, "html.parser")
        title_el = soup.select_one("h1") or soup.select_one("title")
        title = title_el.get_text(" ", strip=True) if title_el else ro
        body_el = soup.select_one("main") or soup.select_one("body")
        body = body_el.get_text(" ", strip=True) if body_el else r.text
        ok, kw = has_kw(title + " " + body)
        if not ok and not re.search(r"年収|給与|万円", body):
            polite(); continue
        rid = md5_16("opensalary", "j", ro)
        if rid in seen:
            polite(); continue
        obj = {
            "id": rid,
            "raw_id": f"job:{ro}",
            "platform": "opensalary",
            "lang": "ja",
            "title": title,
            "body": body[:5000],
            "author": "",
            "url": url,
            "country_hint": "JP",
            "matched_keyword": kw or "年収",
            "engagement": {"score": 0, "comments": 0, "views": None},
            "kind": "job",
            "crawled_at": now_iso(),
        }
        append(out, obj); seen.add(rid); total += 1
        print(f"[opensalary] job={ro} added (total={total})")
        polite()
    print(f"[opensalary] DONE +{total}")
    return total


# ----------------------------------------------------------------------
# 4. 5ch career (shift_jis)
# ----------------------------------------------------------------------
def crawl_5ch_career():
    out = OUT["5ch_career"]
    seen = load_seen(out)
    total = 0
    base = "https://lavender.5ch.net/career/"
    sub = base + "subback.html"
    r = safe_get(sub, headers={**HDR, "Accept-Charset": "Shift_JIS"})
    if not r or r.status_code != 200:
        print(f"[5ch] subback status={getattr(r,'status_code','-')}")
        return 0
    # 5ch is shift_jis
    try:
        text = r.content.decode("shift_jis", errors="replace")
    except Exception:
        text = r.text
    soup = BeautifulSoup(text, "html.parser")
    # threads listed as <a href="NNNN/l50">title</a>
    threads = []
    for a in soup.find_all("a", href=True):
        h = a.get("href", "")
        # forms: "1234567890/l50" or "../test/read.cgi/career/1234567890/l50"
        m = re.match(r"^(\d{8,})/l50$", h)
        if m:
            tid = m.group(1)
            t = a.get_text(" ", strip=True)
            threads.append((tid, t, base + h))
    print(f"[5ch] threads_found={len(threads)}")
    if not threads:
        print(f"[5ch] head: {text[:300]}")
        return 0
    # filter by kw in thread title
    kw_threads = [(tid, t, u) for (tid, t, u) in threads if has_kw(t)[0]]
    if not kw_threads:
        # fall back to first 30 threads
        kw_threads = threads[:30]
    for tid, ttitle, turl in kw_threads[:50]:
        rid = md5_16("5ch_career", tid)
        if rid in seen: continue
        # build read.cgi URL
        read_url = f"https://lavender.5ch.net/test/read.cgi/career/{tid}/"
        polite()
        rr = safe_get(read_url, headers={**HDR, "Accept-Charset": "Shift_JIS"})
        if not rr or rr.status_code != 200:
            print(f"[5ch] thread={tid} status={getattr(rr,'status_code','-')}")
            continue
        try:
            t2 = rr.content.decode("shift_jis", errors="replace")
        except Exception:
            t2 = rr.text
        s2 = BeautifulSoup(t2, "html.parser")
        # posts: <div class="post"> or <dl class="thread">
        posts = s2.select("div.post") or s2.select("dl.thread dd") or s2.select("dd")
        body_chunks = []
        for p in posts[:50]:
            tx = p.get_text(" ", strip=True)
            if tx and len(tx) > 20:
                body_chunks.append(tx)
        body = "\n".join(body_chunks)[:5000]
        if not body:
            body = s2.get_text(" ", strip=True)[:3000]
        ok, kw = has_kw(ttitle + " " + body)
        if not ok: continue
        obj = {
            "id": rid,
            "raw_id": tid,
            "platform": "5ch_career",
            "lang": "ja",
            "title": ttitle,
            "body": body,
            "author": "",
            "url": read_url,
            "country_hint": "JP",
            "matched_keyword": kw,
            "engagement": {"score": 0, "comments": len(posts), "views": None},
            "crawled_at": now_iso(),
        }
        append(out, obj); seen.add(rid); total += 1
        if total % 10 == 0:
            print(f"[5ch] progress total={total}")
    print(f"[5ch_career] DONE +{total}")
    return total


# ----------------------------------------------------------------------
# 5. anond.hatelabo.jp (はてな匿名)
# ----------------------------------------------------------------------
def crawl_anond():
    out = OUT["anond"]
    seen = load_seen(out)
    total = 0
    base = "https://anond.hatelabo.jp/"
    # top page paginates with ?page=N
    for page in range(1, 12):  # 10+ pages
        url = base if page == 1 else f"{base}?page={page}"
        r = safe_get(url)
        if not r or r.status_code != 200:
            print(f"[anond] p{page} status={getattr(r,'status_code','-')}")
            polite(); continue
        soup = BeautifulSoup(r.text, "html.parser")
        sections = soup.select("div.section")
        added = 0
        for sec in sections:
            # title link
            h_el = sec.select_one("h3") or sec.select_one("h2")
            title = h_el.get_text(" ", strip=True) if h_el else ""
            a = h_el.select_one("a") if h_el else None
            href = a.get("href", "") if a else ""
            if href and not href.startswith("http"):
                href = urljoin(base, href)
            # body
            body_el = sec
            body = body_el.get_text(" ", strip=True) if body_el else ""
            # raw_id: try to extract /YYYYMMDDHHMMSS
            m = re.search(r"/(\d{14})", href or "")
            raw_id = m.group(1) if m else (href or md5_16("anond_anon", body[:120]))
            rid = md5_16("anond", raw_id)
            if rid in seen: continue
            ok, kw = has_kw(title + " " + body)
            if not ok: continue
            obj = {
                "id": rid,
                "raw_id": raw_id,
                "platform": "anond",
                "lang": "ja",
                "title": title or body[:60],
                "body": body[:5000],
                "author": "anonymous",
                "url": href or url,
                "country_hint": "JP",
                "matched_keyword": kw,
                "engagement": {"score": 0, "comments": 0, "views": None},
                "page": page,
                "crawled_at": now_iso(),
            }
            append(out, obj); seen.add(rid); total += 1; added += 1
        print(f"[anond] p{page} sections={len(sections)} added={added} total={total}")
        polite()
    print(f"[anond] DONE +{total}")
    return total


# ----------------------------------------------------------------------
# 6. 東洋経済 (toyokeizai.net)
# ----------------------------------------------------------------------
def crawl_toyokeizai():
    out = OUT["toyokeizai"]
    seen = load_seen(out)
    total = 0
    cats = [
        "category/income",
        "category/money",
        "category/career",
        "category/job",
        "category/working-style",
    ]
    for cat in cats:
        for page in range(1, 5):
            url = f"https://toyokeizai.net/{cat}?page={page}"
            r = safe_get(url)
            if not r or r.status_code != 200:
                print(f"[toyo] cat={cat} p{page} status={getattr(r,'status_code','-')}")
                polite(); continue
            soup = BeautifulSoup(r.text, "html.parser")
            # article links: /articles/-/12345
            links = set()
            for a in soup.find_all("a", href=True):
                h = a.get("href", "")
                if "/articles/-/" in h:
                    if h.startswith("/"): h = "https://toyokeizai.net" + h
                    links.add(h.split("?")[0])
            if not links:
                print(f"[toyo] cat={cat} p{page} no links")
                polite(); continue
            added = 0
            for full in list(links)[:15]:
                m = re.search(r"/articles/-/(\d+)", full)
                aid = m.group(1) if m else full
                rid = md5_16("toyokeizai", aid)
                if rid in seen: continue
                polite(0.9, 1.5)
                dr = safe_get(full)
                if not dr or dr.status_code != 200: continue
                ds = BeautifulSoup(dr.text, "html.parser")
                t_el = ds.select_one("h1") or ds.select_one("title")
                title = t_el.get_text(" ", strip=True) if t_el else ""
                body_el = ds.select_one("div.article-body") \
                    or ds.select_one("article") \
                    or ds.select_one("main")
                body = body_el.get_text(" ", strip=True) if body_el else ds.get_text(" ", strip=True)[:3000]
                ok, kw = has_kw(title + " " + body)
                if not ok: continue
                obj = {
                    "id": rid,
                    "raw_id": aid,
                    "platform": "toyokeizai",
                    "lang": "ja",
                    "title": title,
                    "body": body[:5000],
                    "author": "",
                    "url": full,
                    "country_hint": "JP",
                    "matched_keyword": kw,
                    "engagement": {"score": 0, "comments": 0, "views": None},
                    "category": cat,
                    "crawled_at": now_iso(),
                }
                append(out, obj); seen.add(rid); total += 1; added += 1
            print(f"[toyo] cat={cat} p{page} links={len(links)} added={added} total={total}")
            polite()
    print(f"[toyokeizai] DONE +{total}")
    return total


# ----------------------------------------------------------------------
# 7. Diamond Online
# ----------------------------------------------------------------------
def crawl_diamond():
    out = OUT["diamond"]
    seen = load_seen(out)
    total = 0
    cats = [
        "category/s-money",
        "category/s-career",
        "category/s-investment",
        "category/s-zaiteku",
        "category/s-fire",
    ]
    for cat in cats:
        for page in range(1, 5):
            url = f"https://diamond.jp/{cat}?page={page}" if page > 1 else f"https://diamond.jp/{cat}"
            r = safe_get(url)
            if not r or r.status_code != 200:
                print(f"[diamond] cat={cat} p{page} status={getattr(r,'status_code','-')}")
                polite(); continue
            soup = BeautifulSoup(r.text, "html.parser")
            # diamond article URLs: /articles/-/12345
            links = set()
            for a in soup.find_all("a", href=True):
                h = a.get("href", "")
                if "/articles/-/" in h:
                    if h.startswith("/"): h = "https://diamond.jp" + h
                    links.add(h.split("?")[0].split("#")[0])
            if not links:
                print(f"[diamond] cat={cat} p{page} no links")
                polite(); continue
            added = 0
            for full in list(links)[:15]:
                m = re.search(r"/articles/-/(\d+)", full)
                aid = m.group(1) if m else full
                rid = md5_16("diamond", aid)
                if rid in seen: continue
                polite(0.9, 1.5)
                dr = safe_get(full)
                if not dr or dr.status_code != 200: continue
                ds = BeautifulSoup(dr.text, "html.parser")
                t_el = ds.select_one("h1") or ds.select_one("title")
                title = t_el.get_text(" ", strip=True) if t_el else ""
                body_el = ds.select_one("div.article-body") \
                    or ds.select_one("div#article-body") \
                    or ds.select_one("article") \
                    or ds.select_one("main")
                body = body_el.get_text(" ", strip=True) if body_el else ds.get_text(" ", strip=True)[:3000]
                ok, kw = has_kw(title + " " + body)
                if not ok: continue
                obj = {
                    "id": rid,
                    "raw_id": aid,
                    "platform": "diamond",
                    "lang": "ja",
                    "title": title,
                    "body": body[:5000],
                    "author": "",
                    "url": full,
                    "country_hint": "JP",
                    "matched_keyword": kw,
                    "engagement": {"score": 0, "comments": 0, "views": None},
                    "category": cat,
                    "crawled_at": now_iso(),
                }
                append(out, obj); seen.add(rid); total += 1; added += 1
            print(f"[diamond] cat={cat} p{page} links={len(links)} added={added} total={total}")
            polite()
    print(f"[diamond] DONE +{total}")
    return total


# ----------------------------------------------------------------------
# samples
# ----------------------------------------------------------------------
def print_samples(path, label, k=3):
    if not path.exists():
        print(f"[{label}] missing: {path}")
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    print(f"\n=== {label}: {path} | {len(lines)} lines ===")
    for ln in lines[:k]:
        try:
            o = json.loads(ln)
            t = (o.get("title") or "").replace("\n", " ")[:120]
            b = (o.get("body") or "").replace("\n", " ")[:200]
            print(f"  - kw={o.get('matched_keyword')!r} | {t}")
            print(f"    body: {b}...")
        except Exception as e:
            print(f"  parse err: {e}")
    return len(lines)


if __name__ == "__main__":
    counts = {}
    for name, fn in [
        ("moneyforward", crawl_moneyforward),
        ("note",         crawl_note),
        ("opensalary",   crawl_opensalary),
        ("5ch_career",   crawl_5ch_career),
        ("anond",        crawl_anond),
        ("toyokeizai",   crawl_toyokeizai),
        ("diamond",      crawl_diamond),
    ]:
        try:
            counts[name] = fn()
        except Exception as e:
            print(f"[{name}] FATAL {e}")
            counts[name] = 0
    print("\n========== SAMPLES ==========")
    file_lines = {}
    for name, path in OUT.items():
        file_lines[name] = print_samples(path, name)
    print("\n========== TOTAL ==========")
    for name in OUT:
        print(f"  {name:15s} added={counts.get(name,0):4d}  file={file_lines.get(name,0):4d}")
