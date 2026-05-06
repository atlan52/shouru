"""36氪 + 雪球 中文收入数据抓取（无 cookie）。"""
import json
import hashlib
import time
import random
import re
from datetime import datetime, timezone
from pathlib import Path
import requests

OUT_36KR = Path("data/raw/36kr_native_" + datetime.now().strftime("%Y%m%d") + ".jsonl")
OUT_XUEQIU = Path("data/raw/xueqiu_native_" + datetime.now().strftime("%Y%m%d") + ".jsonl")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124"

def md5_16(*parts):
    return hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()[:16]

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def append(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def polite():
    time.sleep(random.uniform(1.0, 2.0))


# =========================
# 36kr API
# =========================
def crawl_36kr():
    keywords = ["月入十万", "月入5万", "副业收入", "财务自由", "我的收入构成",
                "年薪百万", "互联网大厂工资", "创业收入", "自由职业收入", "月入过万"]
    seen = set()
    if OUT_36KR.exists():
        for line in OUT_36KR.open(encoding="utf-8"):
            try: seen.add(json.loads(line)["id"])
            except: pass
    print(f"[36kr] start, seen={len(seen)}")
    headers = {
        "User-Agent": UA,
        "Referer": "https://www.36kr.com/",
        "Content-Type": "application/json",
        "Origin": "https://www.36kr.com",
    }
    n_added = 0
    for kw in keywords:
        for page in range(1, 4):  # 3 pages each
            payload = {
                "partner_id": "web",
                "timestamp": int(time.time() * 1000),
                "param": {
                    "searchType": "article",
                    "searchWord": kw,
                    "sortField": "score",
                    "searchTime": "all",
                    "pageSize": 40,
                    "pageEvent": page,
                    "pageCallback": "" if page == 1 else "",
                },
            }
            try:
                r = requests.post(
                    "https://gateway.36kr.com/api/mis/nav/search/resultbytype",
                    json=payload, headers=headers, timeout=20)
                j = r.json()
                items = (j.get("data") or {}).get("itemList") or []
                if not items:
                    print(f"[36kr] kw={kw} page={page} 0 items, code={j.get('code')}")
                    break
                for it in items:
                    tdata = it.get("templateMaterial") or it
                    aid = tdata.get("itemId") or it.get("itemId") or tdata.get("id")
                    if not aid:
                        continue
                    rid = md5_16("36kr", aid)
                    if rid in seen:
                        continue
                    title = tdata.get("widgetTitle") or tdata.get("title") or ""
                    body = tdata.get("widgetContent") or tdata.get("summary") or tdata.get("description") or ""
                    author = (tdata.get("authorName") or tdata.get("author") or "")
                    pv = tdata.get("statRead") or tdata.get("statPv") or 0
                    cmt = tdata.get("statComment") or 0
                    obj = {
                        "id": rid, "raw_id": str(aid), "platform": "36kr",
                        "lang": "zh", "title": title, "body": body[:2000],
                        "author": author, "url": f"https://www.36kr.com/p/{aid}",
                        "country_hint": "CN", "matched_keyword": kw,
                        "engagement": {"score": 0, "comments": int(cmt), "views": int(pv)},
                        "crawled_at": now_iso(),
                    }
                    append(OUT_36KR, obj)
                    seen.add(rid)
                    n_added += 1
            except Exception as e:
                print(f"[36kr] kw={kw} page={page} err: {e}")
                break
            polite()
    print(f"[36kr] DONE, +{n_added} items, total file: {sum(1 for _ in OUT_36KR.open()) if OUT_36KR.exists() else 0}")
    return n_added


# =========================
# Xueqiu (status timeline)
# =========================
def crawl_xueqiu():
    keywords = ["月入十万", "月入5万", "财务自由", "我的收入", "副业收入",
                "年薪百万", "创业收入", "投资收入", "月入过万", "工资构成"]
    seen = set()
    if OUT_XUEQIU.exists():
        for line in OUT_XUEQIU.open(encoding="utf-8"):
            try: seen.add(json.loads(line)["id"])
            except: pass
    print(f"[xueqiu] start, seen={len(seen)}")
    s = requests.Session()
    # Warm up to get cookies
    try:
        s.get("https://xueqiu.com/", headers={"User-Agent": UA}, timeout=15)
    except Exception as e:
        print(f"[xueqiu] warmup fail: {e}")
    headers = {
        "User-Agent": UA,
        "Referer": "https://xueqiu.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    n_added = 0
    for kw in keywords:
        for page in range(1, 4):
            try:
                r = s.get(
                    "https://xueqiu.com/query/v1/symbol/search/status.json",
                    params={"count": 20, "comment": 0, "symbol": "", "hl": 0,
                            "source": "user", "sort": "time", "page": page, "q": kw},
                    headers=headers, timeout=20)
                if r.status_code == 400 and "需要" in r.text:
                    print(f"[xueqiu] cookie required, stop")
                    return n_added
                j = r.json()
                items = j.get("list") or []
                if not items:
                    print(f"[xueqiu] kw={kw} page={page} 0 items")
                    break
                for it in items:
                    sid = str(it.get("id") or it.get("status_id") or "")
                    if not sid:
                        continue
                    rid = md5_16("xueqiu", sid)
                    if rid in seen:
                        continue
                    text = it.get("text") or it.get("description") or ""
                    text = re.sub(r"<[^>]+>", "", text)  # strip html
                    title = (it.get("title") or text[:80]).strip()
                    user = it.get("user") or {}
                    author = user.get("screen_name") or user.get("name") or ""
                    obj = {
                        "id": rid, "raw_id": sid, "platform": "xueqiu",
                        "lang": "zh", "title": title, "body": text[:2000],
                        "author": author,
                        "url": f"https://xueqiu.com/{user.get('id','')}/{sid}",
                        "country_hint": "CN", "matched_keyword": kw,
                        "engagement": {"score": int(it.get("like_count") or 0),
                                       "comments": int(it.get("reply_count") or 0),
                                       "views": int(it.get("view_count") or 0) or None},
                        "crawled_at": now_iso(),
                    }
                    append(OUT_XUEQIU, obj)
                    seen.add(rid)
                    n_added += 1
            except Exception as e:
                print(f"[xueqiu] kw={kw} page={page} err: {e}")
                break
            polite()
    print(f"[xueqiu] DONE, +{n_added} items")
    return n_added


if __name__ == "__main__":
    n1 = crawl_36kr()
    n2 = crawl_xueqiu()
    print(f"\n=== TOTAL: 36kr +{n1}, xueqiu +{n2} ===")
