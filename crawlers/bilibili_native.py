"""Standalone Bilibili public-search scraper for income-related Chinese videos.

Per task spec:
  * Public search/all/v2 endpoint, no cookie strictly required
  * 12 Chinese keywords, 1-3 pages each
  * Polite sleep 1.5-2 s
  * Optional top-20 hot comment enrichment
  * Output: data/raw/bilibili_native_<YYYYMMDD>.jsonl

Run:  python -m crawlers.bilibili_native
"""
import json
import time
import random
import hashlib
import re
import sys
from datetime import datetime
from pathlib import Path
import urllib.request
import urllib.parse
import urllib.error


OUT_DIR = Path("/Users/jan/sen/code/spider/shouru/data/raw")
OUT_DIR.mkdir(parents=True, exist_ok=True)
STAMP = datetime.now().strftime("%Y%m%d")
OUT_PATH = OUT_DIR / f"bilibili_native_{STAMP}.jsonl"

KEYWORDS = [
    "月入过万", "月入十万", "副业 月入", "程序员 收入", "互联网大厂 工资",
    "月入5万", "自由职业 收入", "创业 月入", "我月入", "晒工资",
    "财务自由 经历", "程序员 涨薪",
]

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Referer": "https://www.bilibili.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Origin": "https://www.bilibili.com",
}

SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/all/v2"
COMMENTS_URL = "https://api.bilibili.com/x/v2/reply/main"

_HTML_RE = re.compile(r"<[^>]+>")


def clean_html(s: str) -> str:
    return _HTML_RE.sub("", s or "")


def make_id(*parts) -> str:
    h = hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()
    return h[:16]


def http_get_json(url: str, params: dict | None = None, timeout: int = 20):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"  [http {e.code}] {url[:100]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  [err] {type(e).__name__}: {str(e)[:120]}", file=sys.stderr)
        return None


def warm_cookies():
    """Hit the homepage so any subsequent request looks normal. Best-effort."""
    try:
        req = urllib.request.Request("https://www.bilibili.com/", headers=HEADERS)
        urllib.request.urlopen(req, timeout=15).read()
    except Exception:
        pass


def search_videos(keyword: str, page: int):
    """Return the list of video objects from the search/all/v2 endpoint."""
    j = http_get_json(SEARCH_URL, {"keyword": keyword, "page": page})
    if not j:
        return []
    if j.get("code") != 0:
        print(f"  [bili] code={j.get('code')} msg={j.get('message')}",
              file=sys.stderr)
        return []
    result = (j.get("data") or {}).get("result") or []
    if isinstance(result, list):
        for grp in result:
            if isinstance(grp, dict) and grp.get("result_type") == "video":
                return grp.get("data") or []
    return []


def get_comments(aid: int, top_n: int = 5):
    j = http_get_json(COMMENTS_URL, {"type": 1, "oid": aid, "mode": 3})
    if not j or j.get("code") != 0:
        return []
    replies = (j.get("data") or {}).get("replies") or []
    out = []
    for r in replies[:top_n]:
        msg = ((r.get("content") or {}).get("message") or "").strip()
        if msg:
            out.append(msg)
    return out


def build_record(d: dict, keyword: str):
    bvid = d.get("bvid") or ""
    if not bvid:
        return None
    title = clean_html(d.get("title") or "")
    desc = clean_html(d.get("description") or "")
    body = desc.strip() if desc.strip() else title
    return {
        "id": make_id("bilibili", bvid),
        "raw_id": bvid,
        "platform": "bilibili",
        "lang": "zh",
        "title": title,
        "body": body,
        "author": d.get("author") or "",
        "url": f"https://www.bilibili.com/video/{bvid}",
        "country_hint": "CN",
        "matched_keyword": keyword,
        "engagement": {
            "score": int(d.get("like") or 0),
            "comments": int(d.get("review") or d.get("video_review") or 0),
            "views": int(d.get("play") or 0),
        },
        "_aid": d.get("aid"),
    }


def polite_sleep():
    time.sleep(random.uniform(1.5, 2.0))


def main():
    print(f"[bili-native] output -> {OUT_PATH}")
    warm_cookies()
    time.sleep(1.0)

    seen_ids = set()
    records = []

    for kw in KEYWORDS:
        print(f"[bili-native] keyword: {kw}")
        for page in range(1, 4):
            videos = search_videos(kw, page)
            if not videos:
                print(f"  p{page}: no results")
                polite_sleep()
                break
            kept = 0
            for d in videos:
                rec = build_record(d, kw)
                if not rec:
                    continue
                if rec["id"] in seen_ids:
                    continue
                seen_ids.add(rec["id"])
                records.append(rec)
                kept += 1
            print(f"  p{page}: +{kept} (total {len(records)})")
            polite_sleep()

    # Top-20 by views -> comment enrichment
    records.sort(key=lambda r: r["engagement"]["views"], reverse=True)
    top20 = records[:20]
    print(f"[bili-native] enriching top-{len(top20)} videos with comments")
    for r in top20:
        aid = r.get("_aid")
        if not aid:
            continue
        try:
            cmts = get_comments(int(aid), top_n=5)
        except Exception:
            cmts = []
        if cmts:
            joined = " || ".join(cmts)
            r["body"] = (r["body"] + "\n\n[top_comments] " + joined)[:5000]
            r["top_comments"] = cmts
        polite_sleep()

    with OUT_PATH.open("w", encoding="utf-8") as f:
        for r in records:
            r.pop("_aid", None)
            r["crawled_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"[bili-native] wrote {len(records)} records to {OUT_PATH}")
    print("--- sample titles ---")
    for r in records[:5]:
        print(f"  {r['title']}  (views={r['engagement']['views']})")


if __name__ == "__main__":
    main()
