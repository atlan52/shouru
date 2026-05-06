"""台湾本地三大论坛繁体中文收入帖抓取：PTT + Dcard + Mobile01。
不用 Reddit。country_hint=TW, lang=zh。"""
import json, hashlib, re, time, random, sys, traceback
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HDR_HTML = {
    "User-Agent": UA,
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
HDR_JSON = {
    "User-Agent": UA,
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.dcard.tw/",
}
HDR_PTT = dict(HDR_HTML)  # PTT also needs over18 cookie
COOKIES_PTT = {"over18": "1"}

DAY = datetime.now().strftime("%Y%m%d")
OUT_PTT = Path(f"data/raw/ptt_native_{DAY}.jsonl")
OUT_DCARD = Path(f"data/raw/dcard_native_{DAY}.jsonl")
OUT_M01 = Path(f"data/raw/mobile01_native_{DAY}.jsonl")

# 繁中关键词（用户给的列表）
KEYWORDS = [
    "薪水", "月薪", "年薪", "工資", "收入", "賺錢", "副業", "自由業",
    "退休", "FIRE", "月入", "年入", "加薪", "獎金", "分紅", "派息",
    "房租", "股息", "免稅",
]


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


def match_keyword(text):
    """返回第一个命中的关键词或 None。"""
    if not text: return None
    for kw in KEYWORDS:
        if kw in text:
            return kw
    return None


def is_cloudflare(resp):
    if resp is None: return False
    if resp.status_code in (403, 503):
        body_low = (resp.text or "")[:1500].lower()
        if "cloudflare" in body_low or "cf-ray" in body_low or "cf-chl" in body_low:
            return True
    return False


# ---------------- PTT ----------------

def ptt_list_page(board, index_url):
    """抓 PTT 一个 index 页，返回 (threads, prev_url)。
    threads = list of (raw_id, abs_url, title)."""
    r = requests.get(index_url, headers=HDR_PTT, cookies=COOKIES_PTT, timeout=25)
    if is_cloudflare(r):
        print(f"[ptt] {board} cloudflare on {index_url}, abort board")
        return None, None
    if r.status_code != 200:
        print(f"[ptt] {board} {index_url} status={r.status_code}")
        return [], None
    soup = BeautifulSoup(r.text, "html.parser")
    threads = []
    # PTT 的列表项: div.r-ent > div.title > a href="/bbs/<board>/<MID>.html"
    for div in soup.select("div.r-ent"):
        a = div.select_one("div.title a")
        if not a: continue  # 已删文章
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if not href: continue
        m = re.search(r"/bbs/[^/]+/([^/]+)\.html", href)
        raw_id = m.group(1) if m else href
        abs_url = "https://www.ptt.cc" + href if href.startswith("/") else href
        threads.append((raw_id, abs_url, title))
    if not threads:
        dump = (r.text or "")[:800]
        print(f"[ptt] {board} 0 threads on {index_url}; HTML head: {dump}")
    # prev page link: <a class="btn wide">‹ 上頁</a>
    prev_url = None
    for a in soup.select("a.btn.wide"):
        if "上頁" in a.get_text():
            href = a.get("href", "")
            if href:
                prev_url = "https://www.ptt.cc" + href if href.startswith("/") else href
            break
    return threads, prev_url


def ptt_fetch_post(url):
    try:
        r = requests.get(url, headers=HDR_PTT, cookies=COOKIES_PTT, timeout=25)
    except Exception as e:
        return None, f"req-err {e}"
    if is_cloudflare(r):
        return None, "cloudflare"
    if r.status_code != 200:
        return None, f"status={r.status_code}"
    soup = BeautifulSoup(r.text, "html.parser")
    title = ""
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"): title = og["content"].strip()
    author = ""
    am = soup.find("meta", attrs={"name": "author"})
    if am and am.get("content"): author = am["content"].strip()
    body_el = soup.select_one("#main-content")
    body = ""
    if body_el:
        # 去掉 metaline / push 留主文
        for sub in body_el.select(".article-metaline, .article-metaline-right, .push"):
            sub.decompose()
        body = body_el.get_text("\n", strip=True)
    if not title:
        h_el = soup.select_one("title")
        if h_el: title = h_el.get_text(strip=True)
    return {"title": title, "author": author, "body": body, "url": url}, None


def crawl_ptt():
    boards = ["Salary", "Tech_Job", "job", "Foreign_Inv"]
    pages_per_board = 5
    seen = load_seen(OUT_PTT)
    n = 0
    for board in boards:
        url = f"https://www.ptt.cc/bbs/{board}/index.html"
        page_count = 0
        b_added = 0
        while url and page_count < pages_per_board:
            threads, prev_url = ptt_list_page(board, url)
            if threads is None:  # cloudflare
                break
            print(f"[ptt] {board} page#{page_count+1} {url} threads={len(threads)}")
            for raw_id, abs_url, list_title in threads:
                rid = md5_16("ptt", board, raw_id)
                if rid in seen: continue
                # 标题级筛一遍以减少详情请求
                kw_t = match_keyword(list_title)
                # 即使标题没命中也可能正文命中；给 Salary/Tech_Job 板块全抓，其他板做标题筛
                if board not in ("Salary", "Tech_Job") and not kw_t:
                    continue
                post, err = ptt_fetch_post(abs_url)
                polite()
                if err == "cloudflare":
                    print(f"[ptt] {board} cloudflare on detail, abort board")
                    url = None  # break out
                    break
                if err or not post:
                    continue
                full_text = (post.get("title") or "") + "\n" + (post.get("body") or "")
                kw = match_keyword(full_text)
                if not kw:
                    continue
                obj = {
                    "id": rid,
                    "raw_id": raw_id,
                    "platform": "ptt",
                    "lang": "zh",
                    "title": post.get("title", "") or list_title,
                    "body": (post.get("body") or "")[:5000],
                    "author": post.get("author", ""),
                    "url": abs_url,
                    "country_hint": "TW",
                    "matched_keyword": kw,
                    "engagement": {"score": 0, "comments": 0, "board": board},
                    "board": board,
                    "crawled_at": now_iso(),
                }
                append(OUT_PTT, obj); seen.add(rid); n += 1; b_added += 1
            page_count += 1
            url = prev_url
            polite()
        print(f"[ptt] board={board} +{b_added} total={n}")
    print(f"[ptt] DONE +{n}")
    return n


# ---------------- Dcard ----------------

DCARD_BOARDS = [
    ("job", "工作"),
    ("money", "理財"),
]


def dcard_list(board, limit=100):
    """走公开 forum posts API。"""
    url = f"https://www.dcard.tw/_api/forums/{board}/posts"
    params = {"popular": "true", "limit": str(min(limit, 30))}
    out = []
    before = None
    fetched = 0
    while fetched < limit:
        if before: params["before"] = str(before)
        try:
            r = requests.get(url, params=params, headers=HDR_JSON, timeout=25)
        except Exception as e:
            print(f"[dcard] {board} list req-err {e}"); break
        if is_cloudflare(r):
            print(f"[dcard] {board} cloudflare list, abort"); break
        if r.status_code != 200:
            print(f"[dcard] {board} list status={r.status_code}; head: {(r.text or '')[:400]}")
            break
        try:
            data = r.json()
        except Exception:
            print(f"[dcard] {board} list non-json head: {(r.text or '')[:400]}"); break
        if not isinstance(data, list) or not data:
            if fetched == 0:
                print(f"[dcard] {board} 0 posts; resp head: {str(data)[:400]}")
            break
        out.extend(data)
        fetched += len(data)
        before = data[-1].get("id")
        polite()
        if not before: break
    return out


def dcard_fetch_post(post_id):
    """取详情正文以便 body 完整。也能直接用列表数据。"""
    url = f"https://www.dcard.tw/_api/posts/{post_id}"
    try:
        r = requests.get(url, headers=HDR_JSON, timeout=25)
    except Exception:
        return None
    if r.status_code != 200: return None
    try:
        return r.json()
    except Exception:
        return None


def crawl_dcard():
    seen = load_seen(OUT_DCARD)
    n = 0
    for board, _ in DCARD_BOARDS:
        posts = dcard_list(board, limit=100)
        print(f"[dcard] board={board} fetched {len(posts)} posts from API")
        b_added = 0
        for p in posts:
            pid = p.get("id")
            if pid is None: continue
            rid = md5_16("dcard", board, pid)
            if rid in seen: continue
            title = p.get("title", "") or ""
            excerpt = p.get("excerpt", "") or ""
            content = p.get("content", "") or ""
            # 列表 API 有时返回 excerpt 而非 content；正文短则补取详情
            if not content or len(content) < 200:
                detail = dcard_fetch_post(pid)
                polite()
                if isinstance(detail, dict):
                    content = detail.get("content", "") or content
                    if not title: title = detail.get("title", "") or ""
            full_text = title + "\n" + (content or excerpt)
            kw = match_keyword(full_text)
            if not kw:
                continue
            forum_alias = p.get("forumAlias", board)
            url = f"https://www.dcard.tw/f/{forum_alias}/p/{pid}"
            author = ""
            sa = p.get("school") or p.get("department") or p.get("gender") or ""
            if isinstance(sa, str): author = sa
            obj = {
                "id": rid,
                "raw_id": str(pid),
                "platform": "dcard",
                "lang": "zh",
                "title": title,
                "body": (content or excerpt)[:5000],
                "author": author,
                "url": url,
                "country_hint": "TW",
                "matched_keyword": kw,
                "engagement": {
                    "score": int(p.get("likeCount", 0) or 0),
                    "comments": int(p.get("commentCount", 0) or 0),
                    "board": board,
                },
                "board": board,
                "created_at": p.get("createdAt"),
                "crawled_at": now_iso(),
            }
            append(OUT_DCARD, obj); seen.add(rid); n += 1; b_added += 1
        print(f"[dcard] board={board} +{b_added} total={n}")
    print(f"[dcard] DONE +{n}")
    return n


# ---------------- Mobile01 ----------------

M01_BOARDS = [
    ("37", "理財"),
    ("291", "工作"),
]


def m01_list_page(f_id, page):
    url = f"https://www.mobile01.com/topiclist.php?f={f_id}&p={page}"
    try:
        r = requests.get(url, headers=HDR_HTML, timeout=25)
    except Exception as e:
        print(f"[m01] f={f_id} p={page} req-err {e}")
        return None
    if is_cloudflare(r):
        print(f"[m01] f={f_id} p={page} cloudflare")
        return None
    if r.status_code != 200:
        print(f"[m01] f={f_id} p={page} status={r.status_code}")
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    threads = []
    # Mobile01 主题列表行常见为 .topic_gen_box / .l-listTable__tr / a[href*="topicdetail.php"]
    for a in soup.select('a[href*="topicdetail.php"]'):
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if not title or len(title) < 4: continue
        if "topicdetail.php" not in href: continue
        m = re.search(r"f=(\d+).*?t=(\d+)", href)
        if not m: continue
        f_, t_ = m.group(1), m.group(2)
        abs_url = href if href.startswith("http") else ("https://www.mobile01.com/" + href.lstrip("/"))
        # 去掉锚点 / 分页参数
        abs_url = re.sub(r"&p=\d+", "", abs_url).split("#")[0]
        raw_id = f"{f_}_{t_}"
        threads.append((raw_id, abs_url, title))
    # de-dup
    seen_id = set(); uniq = []
    for tup in threads:
        if tup[0] in seen_id: continue
        seen_id.add(tup[0]); uniq.append(tup)
    if not uniq:
        dump = (r.text or "")[:800]
        print(f"[m01] f={f_id} p={page} 0 threads; HTML head: {dump}")
    return uniq


def m01_fetch_post(url):
    try:
        r = requests.get(url, headers=HDR_HTML, timeout=25)
    except Exception as e:
        return None, f"req-err {e}"
    if is_cloudflare(r): return None, "cloudflare"
    if r.status_code != 200: return None, f"status={r.status_code}"
    soup = BeautifulSoup(r.text, "html.parser")
    # title
    title = ""
    h = soup.select_one("h1.topic-title, h1.l-articleTitle, h1")
    if h: title = h.get_text(strip=True)
    if not title:
        og = soup.find("meta", attrs={"property": "og:title"})
        if og and og.get("content"): title = og["content"].strip()
    # body — 取首楼
    body_el = (
        soup.select_one(".single-post-body")
        or soup.select_one(".l-articleBody")
        or soup.select_one("article")
        or soup.select_one(".topic_content")
    )
    body = body_el.get_text("\n", strip=True) if body_el else ""
    if not body:
        # fallback: 第一个 .post 区域
        first = soup.select_one(".l-post, .topic_gen_main")
        if first: body = first.get_text("\n", strip=True)
    # author
    author = ""
    a_el = soup.select_one(".l-post__meta a, .topic_author a, [class*=author] a")
    if a_el: author = a_el.get_text(strip=True)
    return {"title": title, "body": body, "author": author, "url": url}, None


def crawl_mobile01():
    pages = 3
    seen = load_seen(OUT_M01)
    n = 0
    for f_id, _ in M01_BOARDS:
        b_added = 0
        for p in range(1, pages + 1):
            threads = m01_list_page(f_id, p)
            if threads is None: break
            print(f"[m01] f={f_id} p={p} threads={len(threads)}")
            for raw_id, abs_url, list_title in threads:
                rid = md5_16("mobile01", raw_id)
                if rid in seen: continue
                # 标题预筛节约请求；但理财板可放宽
                kw_t = match_keyword(list_title)
                if not kw_t and f_id != "37":
                    continue
                post, err = m01_fetch_post(abs_url)
                polite()
                if err == "cloudflare":
                    print(f"[m01] f={f_id} cloudflare detail, abort board")
                    p = pages + 1
                    break
                if err or not post: continue
                full_text = (post.get("title") or "") + "\n" + (post.get("body") or "")
                kw = match_keyword(full_text)
                if not kw: continue
                obj = {
                    "id": rid,
                    "raw_id": raw_id,
                    "platform": "mobile01",
                    "lang": "zh",
                    "title": post.get("title", "") or list_title,
                    "body": (post.get("body") or "")[:5000],
                    "author": post.get("author", ""),
                    "url": abs_url,
                    "country_hint": "TW",
                    "matched_keyword": kw,
                    "engagement": {"score": 0, "comments": 0, "f": f_id},
                    "board": f_id,
                    "crawled_at": now_iso(),
                }
                append(OUT_M01, obj); seen.add(rid); n += 1; b_added += 1
            polite()
        print(f"[m01] f={f_id} +{b_added} total={n}")
    print(f"[m01] DONE +{n}")
    return n


# ---------------- 收尾 ----------------

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
            print(f"  - kw={o.get('matched_keyword')!r} | board={o.get('board')} | {t}")
            print(f"    body: {b}...")
        except Exception as e:
            print(f"  parse err: {e}")
    return len(lines)


if __name__ == "__main__":
    results = {}
    for name, fn in [("ptt", crawl_ptt), ("dcard", crawl_dcard), ("mobile01", crawl_mobile01)]:
        try:
            results[name] = fn()
        except Exception as e:
            traceback.print_exc()
            print(f"[{name}] crashed: {e}")
            results[name] = 0
    lp = print_samples(OUT_PTT, "ptt")
    ld = print_samples(OUT_DCARD, "dcard")
    lm = print_samples(OUT_M01, "mobile01")
    print(f"\n=== TOTAL: ptt +{results.get('ptt',0)} (file {lp}), "
          f"dcard +{results.get('dcard',0)} (file {ld}), "
          f"mobile01 +{results.get('mobile01',0)} (file {lm}) ===")
