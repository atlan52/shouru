"""日韩本地母语收入数据补充爬虫。

覆盖站点（任选 6-8 个，逐站独立 try/except，单站失败不影响其余）：

JP（lang=ja, country_hint=JP）：
  - opensalary    : https://opensalary.jp/                                公开工资数据库
  - anond         : https://anond.hatelabo.jp/?mode=top                   はてな匿名ダイアリー
  - note_jp       : https://note.com/search_v2?query=...                  note 搜索
  - 5ch           : https://lavender.5ch.net/career/subback.html          5ch career 板（shift_jis）
  - mynavi        : https://news.mynavi.jp/rss/career                     RSS

KR（lang=ko, country_hint=KR）：
  - clien         : https://www.clien.net/service/board/cm_money|cm_jirum
  - ppomppu       : https://www.ppomppu.co.kr/zboard/zboard.php?id=freeboard
  - saramin       : https://www.saramin.co.kr/zf_user/jobs/recruit/list.php
  - jobplanet     : https://www.jobplanet.co.kr/search?query=연봉

输出：每站独立 jsonl 到 data/raw/<platform>_native_<YYYYMMDD>.jsonl，
     schema 与 r_mexico_native 一致。

注意：subagent python 被 deny，只写脚本不跑；主 agent 用 .venv/bin/python 跑。
"""
import json
import re
import time
import random
import hashlib
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

# ---------- 通用 ----------

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HDR_JP = {
    "User-Agent": UA,
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
HDR_KR = {
    "User-Agent": UA,
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

DAY = datetime.now().strftime("%Y%m%d")
RAW_DIR = Path("data/raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)

KW_JP = ["年収", "月収", "時給", "手取り", "給料", "ボーナス", "副業", "フリーランス", "FIRE", "早期退職"]
KW_KR = ["연봉", "월급", "월소득", "시급", "보너스", "부업", "프리랜서", "FIRE", "은퇴"]

CF_MARKERS = ("just a moment", "checking your browser", "cf-chl-", "attention required! | cloudflare")


def md5_16(*p):
    return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def polite():
    time.sleep(random.uniform(1.3, 1.8))


def has_kw(text, kws):
    if not text:
        return False
    return any(k in text for k in kws)


def append(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def load_seen(path):
    seen = set()
    if path.exists():
        for line in path.open():
            try:
                seen.add(json.loads(line)["id"])
            except Exception:
                pass
    return seen


def get(url, headers, timeout=25, encoding=None):
    try:
        r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    except Exception as e:
        print(f"  [GET err] {url}: {e}", file=sys.stderr)
        return None
    if r.status_code in (403, 404, 429) or r.status_code >= 500:
        print(f"  [GET {r.status_code}] {url}", file=sys.stderr)
        return None
    if encoding:
        r.encoding = encoding
    elif not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding or "utf-8"
    text = r.text or ""
    low = text.lower()
    if any(m in low for m in CF_MARKERS):
        print(f"  [CF block] {url}", file=sys.stderr)
        return "__CF__"
    return text


def first_page_dump(label, url, html):
    """第一页 0 条时打印 800 字诊断 dump。"""
    if html in (None, "__CF__"):
        print(f"  [{label}] first-page failed ({html}); url={url}", file=sys.stderr)
        return
    snippet = re.sub(r"\s+", " ", html)[:800]
    print(f"  [{label}] first-page 0 thread; url={url}\n    HTML: {snippet}", file=sys.stderr)


# ============================================================
# JP - OpenSALARY
# ============================================================

def crawl_opensalary():
    label = "opensalary"
    out = RAW_DIR / f"opensalary_native_{DAY}.jsonl"
    seen = load_seen(out)
    base = "https://opensalary.jp"
    n = 0
    list_urls = [
        f"{base}/",
        f"{base}/companies",
        f"{base}/jobs",
        f"{base}/salaries",
    ]
    detail_urls = []
    for i, url in enumerate(list_urls):
        html = get(url, HDR_JP)
        polite()
        if html is None or html == "__CF__":
            if i == 0:
                first_page_dump(label, url, html)
            continue
        soup = BeautifulSoup(html, "html.parser")
        new_links = 0
        for a in soup.find_all("a", href=True):
            h = a["href"]
            if not h or h.startswith("#"):
                continue
            full = urljoin(base + "/", h)
            if not full.startswith(base):
                continue
            # SSR pages with salary detail
            if any(seg in full for seg in ("/companies/", "/jobs/", "/salaries/", "/positions/")):
                if full not in detail_urls:
                    detail_urls.append(full)
                    new_links += 1
        if i == 0 and new_links == 0:
            first_page_dump(label, url, html)
        print(f"  [{label}] list={url} +{new_links} candidates", file=sys.stderr)

    detail_urls = detail_urls[:120]
    for url in detail_urls:
        rid_raw = url
        rid = md5_16("opensalary", rid_raw)
        if rid in seen:
            continue
        html = get(url, HDR_JP)
        polite()
        if html is None or html == "__CF__":
            continue
        soup = BeautifulSoup(html, "html.parser")
        title_el = soup.select_one("h1") or soup.select_one("title")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        main_el = soup.select_one("main") or soup.select_one("article") or soup.body or soup
        body = main_el.get_text(" ", strip=True) if main_el else ""
        if not has_kw(title + " " + body, KW_JP + ["円", "万円"]):
            continue
        obj = {
            "id": rid, "raw_id": rid_raw, "platform": "opensalary", "lang": "ja",
            "title": title[:300], "body": body[:5000], "author": "",
            "url": url, "country_hint": "JP",
            "matched_keyword": next((k for k in KW_JP + ["円"] if k in (title + body)), ""),
            "engagement": {"score": 0, "comments": 0, "views": None},
            "crawled_at": now_iso(),
        }
        append(out, obj); seen.add(rid); n += 1
    print(f"[{label}] DONE +{n} -> {out}")
    return out, n


# ============================================================
# JP - anond.hatelabo.jp 翻 5 页
# ============================================================

def crawl_anond():
    label = "anond"
    out = RAW_DIR / f"anond_native_{DAY}.jsonl"
    seen = load_seen(out)
    base = "https://anond.hatelabo.jp"
    n = 0
    detail_urls = []
    page_url = f"{base}/?mode=top"
    for page in range(1, 6):
        url = page_url if page == 1 else f"{base}/?mode=top&page={page}"
        html = get(url, HDR_JP)
        polite()
        if html is None or html == "__CF__":
            if page == 1:
                first_page_dump(label, url, html)
            break
        soup = BeautifulSoup(html, "html.parser")
        # anond 文章详情页路径形如 /YYYYMMDDHHMMSS
        found = 0
        for a in soup.find_all("a", href=True):
            h = a["href"]
            m = re.match(r"^/(\d{14})$", h) or re.match(r"^/(\d{12})$", h)
            if m:
                full = base + h
                if full not in detail_urls:
                    detail_urls.append(full)
                    found += 1
        if page == 1 and found == 0:
            first_page_dump(label, url, html)
        print(f"  [{label}] p{page} +{found} entries", file=sys.stderr)
        if found == 0:
            break

    detail_urls = detail_urls[:200]
    for url in detail_urls:
        rid_raw = url.rsplit("/", 1)[-1]
        rid = md5_16("anond", rid_raw)
        if rid in seen:
            continue
        html = get(url, HDR_JP)
        polite()
        if html is None or html == "__CF__":
            continue
        soup = BeautifulSoup(html, "html.parser")
        article = soup.select_one(".section") or soup.select_one("article") or soup.select_one("#main") or soup
        title_el = article.select_one("h1, h3, .title")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        body = article.get_text(" ", strip=True)
        if not has_kw(title + " " + body, KW_JP):
            continue
        kw = next((k for k in KW_JP if k in (title + body)), "")
        obj = {
            "id": rid, "raw_id": rid_raw, "platform": "anond", "lang": "ja",
            "title": title[:300] or f"anond {rid_raw}",
            "body": body[:5000], "author": "",
            "url": url, "country_hint": "JP",
            "matched_keyword": kw,
            "engagement": {"score": 0, "comments": 0, "views": None},
            "crawled_at": now_iso(),
        }
        append(out, obj); seen.add(rid); n += 1
    print(f"[{label}] DONE +{n} -> {out}")
    return out, n


# ============================================================
# JP - note.com 搜索
# ============================================================

def crawl_note_jp():
    label = "note_jp"
    out = RAW_DIR / f"note_jp_native_{DAY}.jsonl"
    seen = load_seen(out)
    n = 0
    queries = ["年収", "月収", "フリーランス収入", "副業 収入", "手取り"]
    detail_urls = []
    for qi, q in enumerate(queries):
        url = f"https://note.com/search_v2?query={quote(q)}"
        html = get(url, HDR_JP)
        polite()
        if html is None or html == "__CF__":
            if qi == 0:
                first_page_dump(label, url, html)
            continue
        soup = BeautifulSoup(html, "html.parser")
        found = 0
        for a in soup.find_all("a", href=True):
            h = a["href"]
            full = urljoin("https://note.com/", h)
            # note 详情页：https://note.com/<user>/n/<id>
            if re.search(r"^https?://note\.com/[^/]+/n/[A-Za-z0-9_]+/?$", full):
                if full not in detail_urls:
                    detail_urls.append(full)
                    found += 1
        if qi == 0 and found == 0:
            first_page_dump(label, url, html)
        print(f"  [{label}] q={q!r} +{found} notes", file=sys.stderr)

    detail_urls = detail_urls[:80]
    for url in detail_urls:
        rid_raw = url.rstrip("/").split("/n/")[-1]
        rid = md5_16("note_jp", rid_raw)
        if rid in seen:
            continue
        html = get(url, HDR_JP)
        polite()
        if html is None or html == "__CF__":
            continue
        soup = BeautifulSoup(html, "html.parser")
        title_el = soup.select_one("h1") or soup.select_one("meta[property='og:title']")
        if title_el and title_el.name == "meta":
            title = title_el.get("content", "")
        else:
            title = title_el.get_text(" ", strip=True) if title_el else ""
        body_el = soup.select_one("article") or soup.select_one("main") or soup.body or soup
        body = body_el.get_text(" ", strip=True) if body_el else ""
        if not has_kw(title + " " + body, KW_JP):
            continue
        kw = next((k for k in KW_JP if k in (title + body)), "")
        author_el = soup.select_one("a[class*=user], [class*=author]")
        author = author_el.get_text(" ", strip=True) if author_el else ""
        obj = {
            "id": rid, "raw_id": rid_raw, "platform": "note_jp", "lang": "ja",
            "title": title[:300], "body": body[:5000], "author": author,
            "url": url, "country_hint": "JP",
            "matched_keyword": kw,
            "engagement": {"score": 0, "comments": 0, "views": None},
            "crawled_at": now_iso(),
        }
        append(out, obj); seen.add(rid); n += 1
    print(f"[{label}] DONE +{n} -> {out}")
    return out, n


# ============================================================
# JP - 5ch career 板（shift_jis）
# ============================================================

def crawl_5ch():
    label = "5ch"
    out = RAW_DIR / f"5ch_native_{DAY}.jsonl"
    seen = load_seen(out)
    n = 0
    base = "https://lavender.5ch.net"
    subback_url = f"{base}/career/subback.html"
    html = get(subback_url, HDR_JP, encoding="shift_jis")
    polite()
    threads = []
    if html is None or html == "__CF__":
        first_page_dump(label, subback_url, html)
    else:
        soup = BeautifulSoup(html, "html.parser")
        # subback.html 链接形如 /test/read.cgi/career/<id>/l50
        for a in soup.find_all("a", href=True):
            h = a["href"]
            m = re.search(r"/test/read\.cgi/career/(\d+)/?", h)
            if not m:
                continue
            tid = m.group(1)
            title = a.get_text(" ", strip=True)
            full = urljoin(base + "/", h)
            # 标准化到 read.cgi 主链接
            full = f"{base}/test/read.cgi/career/{tid}/"
            threads.append((tid, title, full))
        if not threads:
            first_page_dump(label, subback_url, html)
        print(f"  [{label}] subback: {len(threads)} threads total", file=sys.stderr)

    # 关键词预过滤
    cand = [(tid, title, url) for (tid, title, url) in threads if has_kw(title, KW_JP) or has_kw(title, ["年", "月", "給", "収"])]
    cand = cand[:80]
    print(f"  [{label}] kw-filtered: {len(cand)}", file=sys.stderr)

    for tid, title_hint, url in cand:
        rid_raw = f"career/{tid}"
        rid = md5_16("5ch", rid_raw)
        if rid in seen:
            continue
        html = get(url, HDR_JP, encoding="shift_jis")
        polite()
        if html is None or html == "__CF__":
            continue
        soup = BeautifulSoup(html, "html.parser")
        title_el = soup.select_one("h1") or soup.select_one("title")
        title = title_el.get_text(" ", strip=True) if title_el else title_hint
        # 5ch 帖子结构：div.post 或者 dl.thread
        posts = soup.select("div.post, .post-content, dd")
        body_parts = []
        for p in posts[:30]:
            t = p.get_text(" ", strip=True)
            if t:
                body_parts.append(t)
        body = "\n".join(body_parts)
        if not body:
            body = soup.get_text(" ", strip=True)
        if not has_kw(title + " " + body, KW_JP):
            continue
        kw = next((k for k in KW_JP if k in (title + body)), "")
        obj = {
            "id": rid, "raw_id": rid_raw, "platform": "5ch", "lang": "ja",
            "title": title[:300], "body": body[:5000], "author": "",
            "url": url, "country_hint": "JP",
            "matched_keyword": kw,
            "engagement": {"score": 0, "comments": len(posts), "views": None},
            "crawled_at": now_iso(),
        }
        append(out, obj); seen.add(rid); n += 1
    print(f"[{label}] DONE +{n} -> {out}")
    return out, n


# ============================================================
# JP - マイナビ転職 ニュース RSS
# ============================================================

def crawl_mynavi():
    label = "mynavi"
    out = RAW_DIR / f"mynavi_native_{DAY}.jsonl"
    seen = load_seen(out)
    n = 0
    feeds = [
        "https://news.mynavi.jp/rss/career",
        "https://news.mynavi.jp/rss/index",
    ]
    items = []
    for fi, feed_url in enumerate(feeds):
        html = get(feed_url, HDR_JP)
        polite()
        if html is None or html == "__CF__":
            if fi == 0:
                first_page_dump(label, feed_url, html)
            continue
        try:
            root = ET.fromstring(html.encode("utf-8") if isinstance(html, str) else html)
        except Exception as e:
            print(f"  [{label}] xml parse err {feed_url}: {e}", file=sys.stderr)
            if fi == 0:
                first_page_dump(label, feed_url, html)
            continue
        # RSS 2.0
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            desc = (it.findtext("description") or "").strip()
            pub = (it.findtext("pubDate") or "").strip()
            if link:
                items.append({"title": title, "link": link, "desc": desc, "pub": pub})
        # Atom fallback
        if not any(items):
            for it in root.iter("{http://www.w3.org/2005/Atom}entry"):
                title = (it.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
                link_el = it.find("{http://www.w3.org/2005/Atom}link")
                link = link_el.get("href") if link_el is not None else ""
                desc = (it.findtext("{http://www.w3.org/2005/Atom}summary") or "").strip()
                items.append({"title": title, "link": link, "desc": desc, "pub": ""})
        print(f"  [{label}] feed={feed_url} items={len(items)}", file=sys.stderr)

    # de-dup by link
    seen_link = set()
    uniq = []
    for it in items:
        if it["link"] in seen_link:
            continue
        seen_link.add(it["link"])
        uniq.append(it)

    for it in uniq[:120]:
        title, link, desc = it["title"], it["link"], it["desc"]
        # 关键词初筛（标题或摘要）
        if not has_kw(title + " " + desc, KW_JP):
            continue
        rid_raw = link
        rid = md5_16("mynavi", rid_raw)
        if rid in seen:
            continue
        # 抓正文
        html = get(link, HDR_JP)
        polite()
        body = desc
        if html and html != "__CF__":
            soup = BeautifulSoup(html, "html.parser")
            art = soup.select_one("article") or soup.select_one("main") or soup.select_one(".article-body") or soup.body or soup
            if art:
                body = art.get_text(" ", strip=True)
        if not has_kw(title + " " + body, KW_JP):
            continue
        kw = next((k for k in KW_JP if k in (title + body)), "")
        obj = {
            "id": rid, "raw_id": rid_raw, "platform": "mynavi", "lang": "ja",
            "title": title[:300], "body": body[:5000], "author": "",
            "url": link, "country_hint": "JP",
            "matched_keyword": kw,
            "engagement": {"score": 0, "comments": 0, "views": None},
            "pub_date": it.get("pub", ""),
            "crawled_at": now_iso(),
        }
        append(out, obj); seen.add(rid); n += 1
    print(f"[{label}] DONE +{n} -> {out}")
    return out, n


# ============================================================
# KR - Clien.net  cm_money / cm_jirum
# ============================================================

def crawl_clien():
    label = "clien"
    out = RAW_DIR / f"clien_native_{DAY}.jsonl"
    seen = load_seen(out)
    n = 0
    base = "https://www.clien.net"
    boards = ["cm_money", "cm_jirum"]
    detail_urls = []
    for bi, board in enumerate(boards):
        for page in range(0, 4):
            url = f"{base}/service/board/{board}" + (f"?&od=T31&po={page}" if page > 0 else "")
            html = get(url, HDR_KR)
            polite()
            if html is None or html == "__CF__":
                if bi == 0 and page == 0:
                    first_page_dump(label, url, html)
                break
            soup = BeautifulSoup(html, "html.parser")
            found = 0
            # Clien 列表项标题用 .subject_fixed，链接形如 /service/board/cm_money/<id>
            for a in soup.find_all("a", href=True):
                h = a["href"]
                m = re.search(rf"/service/board/{board}/(\d+)", h)
                if not m:
                    continue
                full = urljoin(base + "/", h.split("?")[0])
                if full not in detail_urls:
                    detail_urls.append(full)
                    found += 1
            if bi == 0 and page == 0 and found == 0:
                first_page_dump(label, url, html)
            print(f"  [{label}] board={board} p{page} +{found}", file=sys.stderr)
            if found == 0:
                break

    detail_urls = detail_urls[:200]
    for url in detail_urls:
        rid_raw = "/".join(url.rstrip("/").split("/")[-2:])
        rid = md5_16("clien", rid_raw)
        if rid in seen:
            continue
        html = get(url, HDR_KR)
        polite()
        if html is None or html == "__CF__":
            continue
        soup = BeautifulSoup(html, "html.parser")
        title_el = soup.select_one(".subject_fixed, .post_subject, h3.post_subject, h3")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        body_el = soup.select_one(".post_view, .post_content, article")
        body = body_el.get_text(" ", strip=True) if body_el else ""
        if not body:
            body = (soup.select_one("main") or soup).get_text(" ", strip=True)
        if not has_kw(title + " " + body, KW_KR):
            continue
        kw = next((k for k in KW_KR if k in (title + body)), "")
        author_el = soup.select_one(".nickname, .post_writer, .contact_name")
        author = author_el.get_text(" ", strip=True) if author_el else ""
        obj = {
            "id": rid, "raw_id": rid_raw, "platform": "clien", "lang": "ko",
            "title": title[:300], "body": body[:5000], "author": author,
            "url": url, "country_hint": "KR",
            "matched_keyword": kw,
            "engagement": {"score": 0, "comments": 0, "views": None},
            "crawled_at": now_iso(),
        }
        append(out, obj); seen.add(rid); n += 1
    print(f"[{label}] DONE +{n} -> {out}")
    return out, n


# ============================================================
# KR - Ppomppu freeboard 翻 3 页
# ============================================================

def crawl_ppomppu():
    label = "ppomppu"
    out = RAW_DIR / f"ppomppu_native_{DAY}.jsonl"
    seen = load_seen(out)
    n = 0
    base = "https://www.ppomppu.co.kr/zboard"
    detail_urls = []
    for page in range(1, 4):
        url = f"{base}/zboard.php?id=freeboard&page={page}"
        html = get(url, HDR_KR)
        polite()
        if html is None or html == "__CF__":
            if page == 1:
                first_page_dump(label, url, html)
            break
        soup = BeautifulSoup(html, "html.parser")
        found = 0
        for a in soup.find_all("a", href=True):
            h = a["href"]
            # 详情链接形如 view.php?id=freeboard&divpage=...&no=12345
            if "view.php" in h and "id=freeboard" in h and "no=" in h:
                full = urljoin(base + "/", h)
                if full not in detail_urls:
                    detail_urls.append(full)
                    found += 1
        if page == 1 and found == 0:
            first_page_dump(label, url, html)
        print(f"  [{label}] p{page} +{found}", file=sys.stderr)
        if found == 0:
            break

    detail_urls = detail_urls[:200]
    for url in detail_urls:
        m = re.search(r"no=(\d+)", url)
        rid_raw = f"freeboard/{m.group(1)}" if m else url
        rid = md5_16("ppomppu", rid_raw)
        if rid in seen:
            continue
        html = get(url, HDR_KR)
        polite()
        if html is None or html == "__CF__":
            continue
        soup = BeautifulSoup(html, "html.parser")
        # ppomppu 旧版表格化 layout：标题在 td.han 或 font 里
        title_el = soup.select_one("td.han, .view_title, h1, font[size]")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        body_el = soup.select_one("td.han + tr, .board-contents, .view-contents, table.bbs_view")
        if not body_el:
            body_el = soup.select_one("table") or soup.body
        body = body_el.get_text(" ", strip=True) if body_el else ""
        if not has_kw(title + " " + body, KW_KR):
            continue
        kw = next((k for k in KW_KR if k in (title + body)), "")
        obj = {
            "id": rid, "raw_id": rid_raw, "platform": "ppomppu", "lang": "ko",
            "title": title[:300], "body": body[:5000], "author": "",
            "url": url, "country_hint": "KR",
            "matched_keyword": kw,
            "engagement": {"score": 0, "comments": 0, "views": None},
            "crawled_at": now_iso(),
        }
        append(out, obj); seen.add(rid); n += 1
    print(f"[{label}] DONE +{n} -> {out}")
    return out, n


# ============================================================
# KR - Saramin 招聘列表（含工资）
# ============================================================

def crawl_saramin():
    label = "saramin"
    out = RAW_DIR / f"saramin_native_{DAY}.jsonl"
    seen = load_seen(out)
    n = 0
    base = "https://www.saramin.co.kr"
    queries = ["연봉", "프리랜서", "월급", "개발자", "디자이너"]
    detail_urls = []
    for qi, q in enumerate(queries):
        url = f"{base}/zf_user/jobs/recruit/list.php?searchword={quote(q)}"
        html = get(url, HDR_KR)
        polite()
        if html is None or html == "__CF__":
            if qi == 0:
                first_page_dump(label, url, html)
            continue
        soup = BeautifulSoup(html, "html.parser")
        found = 0
        for a in soup.find_all("a", href=True):
            h = a["href"]
            # 招聘详情：/zf_user/jobs/relay/view?...rec_idx=...
            if "/zf_user/jobs/" in h and ("rec_idx=" in h or "/view" in h):
                full = urljoin(base + "/", h)
                if full not in detail_urls:
                    detail_urls.append(full)
                    found += 1
        if qi == 0 and found == 0:
            first_page_dump(label, url, html)
        print(f"  [{label}] q={q!r} +{found}", file=sys.stderr)

    detail_urls = detail_urls[:80]
    for url in detail_urls:
        m = re.search(r"rec_idx=(\d+)", url)
        rid_raw = m.group(1) if m else url
        rid = md5_16("saramin", rid_raw)
        if rid in seen:
            continue
        html = get(url, HDR_KR)
        polite()
        if html is None or html == "__CF__":
            continue
        soup = BeautifulSoup(html, "html.parser")
        title_el = soup.select_one("h1.tit_job, .tit_job, h1")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        company_el = soup.select_one(".company_nm, .company_name a, .corp_name")
        company = company_el.get_text(" ", strip=True) if company_el else ""
        body_el = soup.select_one(".jview, .wrap_jv_cont, .user_content, main")
        body = body_el.get_text(" ", strip=True) if body_el else soup.get_text(" ", strip=True)
        salary = ""
        ms = re.search(r"(연봉|월급)[^\n]{0,40}", body)
        if ms:
            salary = ms.group(0).strip()
        if not has_kw(title + " " + body, KW_KR):
            continue
        kw = next((k for k in KW_KR if k in (title + body)), "")
        obj = {
            "id": rid, "raw_id": rid_raw, "platform": "saramin", "lang": "ko",
            "title": title[:300], "body": body[:5000], "author": company,
            "url": url, "country_hint": "KR",
            "matched_keyword": kw,
            "engagement": {"score": 0, "comments": 0, "views": None},
            "salario": salary, "empresa": company,
            "crawled_at": now_iso(),
        }
        append(out, obj); seen.add(rid); n += 1
    print(f"[{label}] DONE +{n} -> {out}")
    return out, n


# ============================================================
# KR - JobPlanet 搜索
# ============================================================

def crawl_jobplanet():
    label = "jobplanet"
    out = RAW_DIR / f"jobplanet_native_{DAY}.jsonl"
    seen = load_seen(out)
    n = 0
    base = "https://www.jobplanet.co.kr"
    queries = ["연봉", "월급", "프리랜서", "보너스"]
    detail_urls = []
    for qi, q in enumerate(queries):
        url = f"{base}/search?query={quote(q)}"
        html = get(url, HDR_KR)
        polite()
        if html is None or html == "__CF__":
            if qi == 0:
                first_page_dump(label, url, html)
            continue
        soup = BeautifulSoup(html, "html.parser")
        found = 0
        for a in soup.find_all("a", href=True):
            h = a["href"]
            # JobPlanet 公司评论详情：/companies/<id>/reviews/...
            if re.search(r"/companies/\d+/(reviews|salaries|info)", h):
                full = urljoin(base + "/", h.split("?")[0])
                if full not in detail_urls:
                    detail_urls.append(full)
                    found += 1
        if qi == 0 and found == 0:
            first_page_dump(label, url, html)
        print(f"  [{label}] q={q!r} +{found}", file=sys.stderr)

    detail_urls = detail_urls[:80]
    for url in detail_urls:
        rid_raw = url.replace(base, "").lstrip("/")
        rid = md5_16("jobplanet", rid_raw)
        if rid in seen:
            continue
        html = get(url, HDR_KR)
        polite()
        if html is None or html == "__CF__":
            continue
        soup = BeautifulSoup(html, "html.parser")
        title_el = soup.select_one("h1, h2") or soup.select_one("title")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        main_el = soup.select_one("main") or soup.select_one("article") or soup.body or soup
        body = main_el.get_text(" ", strip=True) if main_el else ""
        if not has_kw(title + " " + body, KW_KR):
            continue
        kw = next((k for k in KW_KR if k in (title + body)), "")
        obj = {
            "id": rid, "raw_id": rid_raw, "platform": "jobplanet", "lang": "ko",
            "title": title[:300], "body": body[:5000], "author": "",
            "url": url, "country_hint": "KR",
            "matched_keyword": kw,
            "engagement": {"score": 0, "comments": 0, "views": None},
            "crawled_at": now_iso(),
        }
        append(out, obj); seen.add(rid); n += 1
    print(f"[{label}] DONE +{n} -> {out}")
    return out, n


# ============================================================
# 主驱动
# ============================================================

CRAWLERS = [
    ("opensalary", crawl_opensalary),
    ("anond", crawl_anond),
    ("note_jp", crawl_note_jp),
    ("5ch", crawl_5ch),
    ("mynavi", crawl_mynavi),
    ("clien", crawl_clien),
    ("ppomppu", crawl_ppomppu),
    ("saramin", crawl_saramin),
    ("jobplanet", crawl_jobplanet),
]


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


def main():
    results = []
    for label, fn in CRAWLERS:
        print(f"\n>>> START {label}")
        try:
            path, n = fn()
            results.append((label, path, n))
        except Exception as e:
            import traceback
            print(f"[{label}] FATAL {e}", file=sys.stderr)
            traceback.print_exc()
            results.append((label, None, 0))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    total = 0
    for label, path, n_added in results:
        if path and path.exists():
            file_n = print_samples(path, label, k=2)
        else:
            file_n = 0
            print(f"[{label}] no output file")
        total += file_n
    print(f"\n=== GRAND TOTAL across files: {total} lines ===")


if __name__ == "__main__":
    main()
