"""LIHKG.com + Discuss.com.hk — 香港繁体粤语收入帖直接抓取。

不用 Reddit。两站都有公开端点：
- LIHKG: api_v2/thread/category JSON, api_v2/thread/<tid>/page/1 JSON
- Discuss.com.hk: forumdisplay.php / viewthread.php SSR HTML

输出：
  data/raw/lihkg_native_<DAY>.jsonl
  data/raw/discuss_hk_native_<DAY>.jsonl
"""
import json, hashlib, re, time, random
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

UA_BROWSER = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HDR_JSON = {
    "User-Agent": UA_BROWSER,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.5",
    "Referer": "https://lihkg.com/",
    "X-Requested-With": "XMLHttpRequest",
}
HDR_HTML = {
    "User-Agent": UA_BROWSER,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.5",
}

DAY = datetime.now().strftime("%Y%m%d")
OUT_LIHKG = Path(f"data/raw/lihkg_native_{DAY}.jsonl")
OUT_DISCUSS = Path(f"data/raw/discuss_hk_native_{DAY}.jsonl")

# 繁体 + 粤语收入相关关键词 — 放宽
KEYWORDS = [
    "人工", "月薪", "年薪", "工資", "搵錢", "賺錢", "副業", "兼職",
    "自僱", "退休", "FIRE", "月入", "年入", "凍薪", "加人工", "獎金",
    "花紅", "分紅", "收租", "股息", "免稅", "MPF", "強積金",
    "$", "萬", "蚊", "薪水", "薪金", "薪酬", "出糧", "雙糧", "Bonus",
    "返工", "炒車", "失業", "搵工", "Offer", "Banker", "工程師",
    "醫生", "律師", "老師", "公務員", "freelance", "斜槓",
]

# LIHKG 分类: 1=吹水, 5=財經, 14=創意, 15=時事(舊), 20=工作, 24=創意(新)
# 大幅扩展板块 + 翻更多页
LIHKG_CATS = [
    (1, 8, "吹水"),     # 最大板，大量自述
    (5, 8, "財經"),
    (20, 8, "工作"),
    (15, 5, "時事"),
    (24, 5, "創意"),
    (29, 5, "時事(舊)"),
]

# Discuss.com.hk forum id
DISCUSS_FIDS = [
    (22, 3, "投資理財"),
    (74, 3, "工作"),
]


def md5_16(*p): return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]
def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def append(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
def polite(lo=1.3, hi=1.8): time.sleep(random.uniform(lo, hi))


def load_seen(path):
    seen = set()
    if path.exists():
        for line in path.open():
            try: seen.add(json.loads(line)["id"])
            except: pass
    return seen


def keyword_hit(*texts):
    """Return matched keyword or empty string."""
    blob = " ".join(t for t in texts if t)
    for kw in KEYWORDS:
        if kw in blob:
            return kw
    return ""


def looks_like_block(text):
    """Detect Cloudflare / captcha / 拒访问 page."""
    if not text: return False
    low = text.lower()
    bad = ["cloudflare", "cf-ray", "captcha", "attention required", "ddos protection",
           "checking your browser", "请完成", "請完成", "access denied", "forbidden"]
    return any(b in low for b in bad)


# ---------------------------------------------------------------- LIHKG ----

def lihkg_list_threads(cat_id, page):
    """Return list of thread dicts from category page."""
    url = f"https://lihkg.com/api_v2/thread/category"
    params = {"cat_id": str(cat_id), "page": str(page), "count": "60", "type": "now"}
    try:
        r = requests.get(url, params=params, headers=HDR_JSON, timeout=25)
        if r.status_code != 200:
            print(f"[lihkg] cat={cat_id} p={page} status={r.status_code}")
            return []
        if looks_like_block(r.text):
            print(f"[lihkg] cat={cat_id} p={page} blocked (cf/captcha) - aborting site")
            return None
        j = r.json()
        if not j.get("success"):
            print(f"[lihkg] cat={cat_id} p={page} success=false: {str(j)[:200]}")
            return []
        items = (j.get("response") or {}).get("items") or []
        return items
    except Exception as e:
        print(f"[lihkg] cat={cat_id} p={page} err: {e}")
        return []


def lihkg_fetch_thread(thread_id):
    """Fetch page 1 of a thread; return list of post dicts (主帖 + 高分回帖)."""
    url = f"https://lihkg.com/api_v2/thread/{thread_id}/page/1"
    params = {"order": "score"}
    try:
        r = requests.get(url, params=params, headers=HDR_JSON, timeout=25)
        if r.status_code != 200:
            return []
        if looks_like_block(r.text):
            return None
        j = r.json()
        if not j.get("success"):
            return []
        item_data = (j.get("response") or {}).get("item_data") or []
        return item_data
    except Exception as e:
        print(f"[lihkg] thread={thread_id} err: {e}")
        return []


def strip_html(s):
    if not s: return ""
    return BeautifulSoup(s, "html.parser").get_text(" ", strip=True)


def crawl_lihkg():
    seen = load_seen(OUT_LIHKG)
    total = 0
    aborted = False
    for cat_id, pages, label in LIHKG_CATS:
        if aborted: break
        for p in range(1, pages + 1):
            items = lihkg_list_threads(cat_id, p)
            if items is None:  # site block
                aborted = True
                break
            if not items:
                polite(); continue
            picked_in_page = 0
            for it in items:
                tid = str(it.get("thread_id") or it.get("thread_id_v2") or "")
                title = it.get("title") or ""
                if not tid: continue
                kw_title = keyword_hit(title)
                # If title doesn't hit but cat is 工作/財經, still allow with weaker filter:
                # only fetch thread body when title hits, to avoid wasted requests.
                if not kw_title:
                    continue
                posts = lihkg_fetch_thread(tid)
                polite()
                if posts is None:
                    aborted = True; break
                if not posts:
                    continue
                # main post: first one (msg_num == 1) usually
                op = None
                for ps in posts:
                    if str(ps.get("msg_num")) == "1":
                        op = ps; break
                if op is None and posts:
                    op = posts[0]
                op_body = strip_html(op.get("msg") or "") if op else ""
                op_author = ((op or {}).get("user") or {}).get("nickname") or ((op or {}).get("user_nickname")) or ""
                # high score replies (top 3 after OP)
                replies = []
                for ps in posts:
                    if str(ps.get("msg_num")) == "1": continue
                    body = strip_html(ps.get("msg") or "")
                    score = int(ps.get("like_count") or 0) - int(ps.get("dislike_count") or 0)
                    if score <= 0 and len(replies) >= 3: continue
                    replies.append((score, body))
                replies.sort(key=lambda x: -x[0])
                top_replies = [r[1] for r in replies[:5] if r[1]]
                full_body = op_body
                if top_replies:
                    full_body += "\n\n--- 高分回帖 ---\n" + "\n---\n".join(top_replies)
                kw_full = keyword_hit(title, full_body)
                if not kw_full:
                    continue
                rid = md5_16("lihkg", tid)
                if rid in seen: continue
                obj = {
                    "id": rid,
                    "raw_id": tid,
                    "platform": "lihkg",
                    "lang": "zh",
                    "title": title,
                    "body": full_body[:5000],
                    "author": op_author,
                    "url": f"https://lihkg.com/thread/{tid}",
                    "country_hint": "HK",
                    "matched_keyword": kw_full,
                    "engagement": {
                        "score": int(it.get("like_count") or 0) - int(it.get("dislike_count") or 0),
                        "comments": int(it.get("no_of_reply") or 0),
                        "views": None,
                    },
                    "category": label,
                    "category_id": cat_id,
                    "crawled_at": now_iso(),
                }
                append(OUT_LIHKG, obj); seen.add(rid); total += 1; picked_in_page += 1
            print(f"[lihkg] cat={cat_id}({label}) p={p} items={len(items)} picked={picked_in_page} total={total}")
            polite()
    print(f"[lihkg] DONE +{total} aborted={aborted}")
    return total


# ---------------------------------------------------------- Discuss.com.hk -

def discuss_list_threads(fid, page):
    """Return list of (tid, title) from forum display page."""
    url = "https://www.discuss.com.hk/forumdisplay.php"
    params = {"fid": str(fid), "page": str(page)}
    try:
        r = requests.get(url, params=params, headers=HDR_HTML, timeout=25)
        if r.status_code != 200:
            print(f"[discuss] fid={fid} p={page} status={r.status_code}")
            return []
        if looks_like_block(r.text):
            print(f"[discuss] fid={fid} p={page} blocked - aborting site")
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        out = []
        # Discuz! 标准: <th class="subject"> <a href="viewthread.php?tid=...">标题</a>
        for a in soup.select("a[href*='viewthread.php']"):
            href = a.get("href", "")
            m = re.search(r"tid=(\d+)", href)
            if not m: continue
            tid = m.group(1)
            title = a.get_text(" ", strip=True)
            if not title or len(title) < 4: continue
            out.append((tid, title))
        # de-dup
        seen_tid = set(); uniq = []
        for tid, title in out:
            if tid in seen_tid: continue
            seen_tid.add(tid); uniq.append((tid, title))
        return uniq
    except Exception as e:
        print(f"[discuss] fid={fid} p={page} err: {e}")
        return []


def discuss_fetch_thread(tid):
    """Return (title, op_body, op_author, url, status)."""
    url = f"https://www.discuss.com.hk/viewthread.php?tid={tid}&page=1"
    try:
        r = requests.get(url, headers=HDR_HTML, timeout=25)
        if r.status_code != 200:
            return None, None, None, url, r.status_code
        if looks_like_block(r.text):
            return None, None, None, url, -2
        soup = BeautifulSoup(r.text, "html.parser")
        title_el = soup.select_one("#thread_subject") or soup.select_one("title")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        # Discuz! post body usually .t_msgfont or .postmessage td.postcontent
        body_el = (
            soup.select_one(".t_msgfont")
            or soup.select_one(".postmessage")
            or soup.select_one("td.postcontent")
            or soup.select_one("[id^=postmessage_]")
        )
        op_body = body_el.get_text(" ", strip=True) if body_el else ""
        # author
        author_el = soup.select_one(".postauthor a") or soup.select_one("a.xi2") or soup.select_one(".postinfo a")
        author = author_el.get_text(" ", strip=True) if author_el else ""
        return title, op_body, author, url, 200
    except Exception as e:
        return None, None, None, url, -1


def crawl_discuss():
    seen = load_seen(OUT_DISCUSS)
    total = 0
    aborted = False
    for fid, pages, label in DISCUSS_FIDS:
        if aborted: break
        for p in range(1, pages + 1):
            threads = discuss_list_threads(fid, p)
            if threads is None:
                aborted = True; break
            if not threads:
                polite(); continue
            picked_in_page = 0
            for tid, title in threads:
                kw_title = keyword_hit(title)
                # Don't fetch every thread; only those with kw in title (saves 80% requests)
                if not kw_title: continue
                rid = md5_16("discuss_hk", tid)
                if rid in seen: continue
                t2, body, author, url, status = discuss_fetch_thread(tid)
                polite()
                if status == -2:
                    aborted = True; break
                if status != 200:
                    continue
                final_title = t2 or title
                kw_full = keyword_hit(final_title, body)
                if not kw_full: continue
                obj = {
                    "id": rid,
                    "raw_id": tid,
                    "platform": "discuss_hk",
                    "lang": "zh",
                    "title": final_title[:300],
                    "body": (body or "")[:5000],
                    "author": author,
                    "url": url,
                    "country_hint": "HK",
                    "matched_keyword": kw_full,
                    "engagement": {"score": 0, "comments": 0, "views": None},
                    "forum": label,
                    "forum_id": fid,
                    "crawled_at": now_iso(),
                }
                append(OUT_DISCUSS, obj); seen.add(rid); total += 1; picked_in_page += 1
            print(f"[discuss] fid={fid}({label}) p={p} threads={len(threads)} picked={picked_in_page} total={total}")
            polite()
    print(f"[discuss] DONE +{total} aborted={aborted}")
    return total


# ---------------------------------------------------------------- main ----

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
            print(f"  - kw={o.get('matched_keyword')!r} | {t}")
            print(f"    body: {b}...")
        except Exception as e:
            print(f"  parse err: {e}")
    return len(lines)


if __name__ == "__main__":
    n_l = crawl_lihkg()
    n_d = crawl_discuss()
    ll = print_samples(OUT_LIHKG, "lihkg")
    ld = print_samples(OUT_DISCUSS, "discuss_hk")
    print(f"\n=== TOTAL: lihkg +{n_l} (file {ll}), discuss_hk +{n_d} (file {ld}) ===")
