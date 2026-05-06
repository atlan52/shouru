"""One-off DCInside Korean income post scraper.

Outputs JSONL to data/raw/dcinside_native_<YYYYMMDD>.jsonl
Targets 30+ items.
"""
import os
import re
import sys
import json
import time
import hashlib
import datetime
import requests
from urllib.parse import quote, urlparse, parse_qs
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.6",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

KEYWORDS = [
    "연봉", "월급", "부업", "수입",
    "재테크", "프리랜서 수입", "자영업 수입", "부수입",
]

GALLERIES = [
    "stock_new1",       # 주식
    "programming",      # 프로그래밍
    "baseball_new10",   # 야구
    "motor",            # 자동차
    "startup",          # 스타트업
]

BASE = "https://gall.dcinside.com"
SEARCH_URL = "https://search.dcinside.com/post/q/{kw}"
VIEW_RE = re.compile(r"/board/view/?\?id=([A-Za-z0-9_]+)&[^\"']*?no=(\d+)")

OUT_DIR = "/Users/jan/sen/code/spider/shouru/data/raw"
TODAY = datetime.datetime.now().strftime("%Y%m%d")
OUT_PATH = os.path.join(OUT_DIR, f"dcinside_native_{TODAY}.jsonl")


def md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def decode(r):
    declared = (r.encoding or "").lower()
    if not declared or declared in ("iso-8859-1",):
        try:
            r.encoding = r.apparent_encoding or "utf-8"
        except Exception:
            r.encoding = "utf-8"
    text = r.text or ""
    if "�" in text and declared not in ("euc-kr", "ks_c_5601-1987", "cp949"):
        try:
            text = r.content.decode("euc-kr", errors="replace")
        except Exception:
            pass
    return text


def get(url, referer=None, timeout=25):
    h = dict(HEADERS)
    if referer:
        h["Referer"] = referer
    try:
        r = requests.get(url, headers=h, timeout=timeout, allow_redirects=True)
    except Exception as e:
        print(f"  net err {url}: {e}", file=sys.stderr)
        return None
    if r.status_code != 200:
        print(f"  status {r.status_code} {url}", file=sys.stderr)
        return None
    body = decode(r)
    low = body.lower()
    if "차단되었습니다" in body or "비정상적인 접근" in body or "captcha" in low:
        print(f"  bot-blocked {url}", file=sys.stderr)
        return None
    return body


def parse_int(s):
    if not s:
        return 0
    s = s.replace(",", "").strip()
    m = re.search(r"(\d+)", s)
    if not m:
        return 0
    try:
        return int(m.group(1))
    except ValueError:
        return 0


def parse_search(html):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        gid = no = None
        m = VIEW_RE.search(href)
        if m:
            gid, no = m.group(1), m.group(2)
        else:
            try:
                p = urlparse(href)
                if "dcinside.com" in (p.netloc or "") and "view" in (p.path or ""):
                    qs = parse_qs(p.query or "")
                    gid = (qs.get("id") or [""])[0]
                    no = (qs.get("no") or [""])[0]
            except Exception:
                continue
        if not gid or not no:
            continue
        key = f"{gid}/{no}"
        if key in seen:
            continue
        seen.add(key)
        title = a.get_text(" ", strip=True)
        out.append({
            "gallery": gid,
            "post_id": no,
            "url": f"{BASE}/board/view/?id={gid}&no={no}",
            "title": title,
        })
    return out


def parse_gallery_list(html):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()
    for tr in soup.select("tr.us-post, tr.ub-content"):
        a = tr.select_one("td.gall_tit a, .gall_tit a")
        if not a:
            continue
        href = a.get("href", "")
        m = VIEW_RE.search(href)
        if not m:
            continue
        gid, no = m.group(1), m.group(2)
        key = f"{gid}/{no}"
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "gallery": gid,
            "post_id": no,
            "url": f"{BASE}/board/view/?id={gid}&no={no}",
            "title": a.get_text(" ", strip=True),
        })
    if not out:
        for a in soup.find_all("a", href=True):
            m = VIEW_RE.search(a["href"])
            if not m:
                continue
            gid, no = m.group(1), m.group(2)
            key = f"{gid}/{no}"
            if key in seen:
                continue
            seen.add(key)
            t = a.get_text(" ", strip=True)
            if not t:
                continue
            out.append({
                "gallery": gid,
                "post_id": no,
                "url": f"{BASE}/board/view/?id={gid}&no={no}",
                "title": t,
            })
    return out


def text_of(el):
    return el.get_text(" ", strip=True) if el else ""


def parse_post(html):
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    for sel in (".title_subject", ".view_subject", "h3.title", ".gallview_head .title"):
        el = soup.select_one(sel)
        if el:
            title = text_of(el)
            if title:
                break

    body_el = (soup.select_one(".write_div")
               or soup.select_one(".gallview_contents .inner")
               or soup.select_one(".view_content_wrap"))
    body = text_of(body_el)

    author = ""
    for sel in (".gall_writer", ".nickname", ".user_id"):
        el = soup.select_one(sel)
        if el:
            txt = text_of(el)
            if txt:
                author = txt.split()[0] if txt.split() else txt
                break

    view_count = upvotes = downvotes = comment_count = 0
    for el in soup.select(".gall_count, .gall_comment, .gall_reply_num, .view_count, .recom_count, .nonrecom_count"):
        txt = text_of(el)
        if not txt:
            continue
        low = txt.replace(" ", "")
        if "조회" in low and not view_count:
            view_count = parse_int(txt)
        elif "댓글" in low and not comment_count:
            comment_count = parse_int(txt)
        elif "추천" in low and "비추천" not in low and not upvotes:
            upvotes = parse_int(txt)
        elif "비추천" in low and not downvotes:
            downvotes = parse_int(txt)

    for sel, key in (
        (".up_num", "up"), ("#recommend_view_up", "up"),
        (".down_num", "down"), ("#recommend_view_down", "down"),
    ):
        el = soup.select_one(sel)
        if el:
            v = parse_int(text_of(el))
            if key == "up" and not upvotes:
                upvotes = v
            elif key == "down" and not downvotes:
                downvotes = v

    if not comment_count:
        crows = soup.select(".cmt_list li, ul.cmt_list > li, .cmt_box li.ub-content")
        if crows:
            comment_count = len(crows)

    return {
        "title": title,
        "body": body,
        "author": author,
        "view_count": view_count,
        "comment_count": comment_count,
        "upvotes": upvotes,
        "downvotes": downvotes,
    }


def has_korean_income_term(text):
    if not text:
        return False
    for kw in KEYWORDS:
        if kw in text:
            return True
    # Looser tokens
    tokens = ["연봉", "월급", "수입", "부업", "재테크", "프리랜서", "자영업", "부수입", "급여", "소득"]
    return any(t in text for t in tokens)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    seen_ids = set()
    items = []

    def emit(meta, kw, parsed):
        rid = f"{meta['gallery']}/{meta['post_id']}"
        our_id = md5(f"dcinside:{rid}")
        if our_id in seen_ids:
            return False
        title = parsed["title"] or meta.get("title", "")
        body = parsed["body"] or ""
        if not (has_korean_income_term(title) or has_korean_income_term(body)):
            return False
        item = {
            "id": our_id,
            "raw_id": rid,
            "platform": "dcinside",
            "lang": "ko",
            "title": title,
            "body": body[:2000],
            "author": parsed["author"],
            "url": meta["url"],
            "country_hint": "KR",
            "matched_keyword": kw,
            "engagement": {
                "score": int(parsed["upvotes"]) - int(parsed["downvotes"]),
                "comments": int(parsed["comment_count"]),
                "views": int(parsed["view_count"]),
            },
        }
        items.append(item)
        seen_ids.add(our_id)
        return True

    target = 35

    # Phase 1: cross-gallery search
    for kw in KEYWORDS:
        if len(items) >= target:
            break
        print(f"[search] kw={kw!r}", file=sys.stderr)
        for page in range(1, 4):
            if len(items) >= target:
                break
            url = SEARCH_URL.format(kw=quote(kw))
            if page > 1:
                url = url + f"/p/{page}"
            html = get(url)
            if not html:
                break
            hits = parse_search(html)
            print(f"  p{page}: {len(hits)} hits", file=sys.stderr)
            if not hits:
                break
            for meta in hits:
                if len(items) >= target:
                    break
                # Pre-filter on title to save fetches
                if not has_korean_income_term(meta.get("title", "")):
                    continue
                phtml = get(meta["url"], referer=url)
                if not phtml:
                    time.sleep(1.0)
                    continue
                parsed = parse_post(phtml)
                added = emit(meta, kw, parsed)
                if added:
                    print(f"  + [{len(items)}] {parsed['title'][:60]}", file=sys.stderr)
                time.sleep(0.8)
            time.sleep(1.0)

    # Phase 2: gallery lists fallback
    if len(items) < target:
        for gallery in GALLERIES:
            if len(items) >= target:
                break
            print(f"[gallery] {gallery}", file=sys.stderr)
            for page in range(1, 4):
                if len(items) >= target:
                    break
                url = f"{BASE}/board/lists/?id={gallery}" + (f"&page={page}" if page > 1 else "")
                html = get(url)
                if not html:
                    break
                rows = parse_gallery_list(html)
                print(f"  p{page}: {len(rows)} rows", file=sys.stderr)
                cands = [r for r in rows if has_korean_income_term(r["title"])]
                for meta in cands:
                    if len(items) >= target:
                        break
                    phtml = get(meta["url"], referer=url)
                    if not phtml:
                        time.sleep(1.0)
                        continue
                    parsed = parse_post(phtml)
                    added = emit(meta, f"gallery:{gallery}", parsed)
                    if added:
                        print(f"  + [{len(items)}] {parsed['title'][:60]}", file=sys.stderr)
                    time.sleep(0.8)
                time.sleep(1.0)

    # Write JSONL
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")

    print(f"WROTE {len(items)} items -> {OUT_PATH}")
    print("---SAMPLES---")
    for it in items[:5]:
        print(it.get("title", ""))


if __name__ == "__main__":
    main()
