"""Bilibili crawler via web-interface search + CC-subtitle endpoint.

Uses:
  * `GET https://www.bilibili.com/` first to seed buvid cookies (bilibili
    refuses the search API without them).
  * `x/web-interface/search/type` for keyword search, paginated.
  * `x/player/wbi/v2?bvid=...&cid=...` to discover CC subtitle URLs, then
    fetches the JSON subtitle body (sum of `body[*].content`).

Chinese-only (`lang="zh"`), filtered with `is_on_topic(..., lang="zh")`.
"""
import re
import time
import requests
from config import (
    INCOME_KEYWORDS, PER_PLATFORM_LIMIT, PER_KEYWORD_LIMIT,
    PAGES_PER_QUERY, UA, RAW_DIR,
)
from crawlers.common import (
    append_jsonl, make_id, is_on_topic, preload_seen, polite_sleep,
)
from crawlers.state import State


PLATFORM = "bilibili"
SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/type"
VIEW_URL = "https://api.bilibili.com/x/web-interface/view"
PLAYER_V2_URL = "https://api.bilibili.com/x/player/wbi/v2"

HEADERS = {
    "User-Agent": UA,
    "Referer": "https://www.bilibili.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Origin": "https://www.bilibili.com",
}


def warm_cookies() -> dict:
    """Hit the homepage so bilibili hands out buvid/SESSDATA-ish cookies."""
    try:
        r = requests.get("https://www.bilibili.com/", headers=HEADERS, timeout=15)
        cookies = r.cookies.get_dict()
        if cookies:
            print(f"[bili] warmed cookies: {list(cookies.keys())}")
        return cookies
    except Exception as e:
        print(f"[bili] cookie warmup err: {e}")
        return {}


def search(kw: str, page: int, cookies: dict):
    """Return (results, ok).  ok=False => retryable (network / 412 block)."""
    params = {
        "search_type": "video",
        "keyword": kw,
        "page": page,
        "order": "totalrank",
        "page_size": 20,
    }
    try:
        r = requests.get(
            SEARCH_URL, params=params, headers=HEADERS, cookies=cookies, timeout=20,
        )
        if r.status_code != 200:
            print(f"  [bili] '{kw}' p{page} status {r.status_code}")
            return [], False
        j = r.json()
        code = j.get("code")
        if code == -412:
            print(f"  [bili] '{kw}' p{page} blocked (code -412), backing off")
            return [], False
        if code != 0:
            # Non-retryable: malformed / banned keyword etc.
            return [], True
        return (j.get("data") or {}).get("result") or [], True
    except Exception as e:
        print(f"  [bili] search err '{kw}' p{page}: {e}")
        return [], False


def get_view(bvid: str, cookies: dict) -> dict:
    """Fetch `view` for the first-page cid + full description."""
    try:
        r = requests.get(
            VIEW_URL, params={"bvid": bvid}, headers=HEADERS,
            cookies=cookies, timeout=15,
        )
        j = r.json()
        if j.get("code") == 0:
            return j.get("data") or {}
    except Exception:
        pass
    return {}


def get_subtitle_text(bvid: str, cid: int, cookies: dict) -> str:
    """Retrieve CC subtitle JSON (if any) and concat `body[*].content`."""
    try:
        r = requests.get(
            PLAYER_V2_URL,
            params={"bvid": bvid, "cid": cid},
            headers=HEADERS,
            cookies=cookies,
            timeout=15,
        )
        j = r.json()
        subs = (((j.get("data") or {}).get("subtitle") or {}).get("subtitles")) or []
        if not subs:
            return ""
        # Prefer zh-CN / ai-zh, then first available
        chosen = None
        for s in subs:
            lan = (s.get("lan") or "").lower()
            if lan.startswith("zh") or lan.startswith("ai-zh"):
                chosen = s
                break
        if chosen is None:
            chosen = subs[0]

        sub_url = chosen.get("subtitle_url") or ""
        if sub_url.startswith("//"):
            sub_url = "https:" + sub_url
        if not sub_url:
            return ""
        rs = requests.get(sub_url, headers=HEADERS, timeout=15)
        body = (rs.json() or {}).get("body") or []
        return " ".join((seg.get("content") or "") for seg in body)
    except Exception as e:
        print(f"    [bili] subtitle err {bvid}: {str(e)[:100]}")
        return ""


_HTML_RE = re.compile(r"<[^>]+>")


def clean_html(s: str) -> str:
    return _HTML_RE.sub("", s or "")


def build_item(d: dict, cookies: dict) -> dict | None:
    bvid = d.get("bvid") or ""
    if not bvid:
        return None
    title = clean_html(d.get("title") or "")
    desc_short = d.get("description") or ""
    tag = d.get("tag") or ""

    # quick pre-filter on easy-access fields; full filter happens after enrichment
    play = int(d.get("play") or 0)
    danmaku = int(d.get("video_review") or 0)
    favorites = int(d.get("favorites") or 0)

    # Enrichment: view page + subtitles
    view = get_view(bvid, cookies)
    cid = view.get("cid")
    desc_full = (view.get("desc") or desc_short or "")[:4000]
    subs = ""
    if cid:
        subs = get_subtitle_text(bvid, cid, cookies)

    if not is_on_topic(title, desc_full, tag, subs, lang="zh"):
        return None

    body = (desc_full.strip() + ("\n\n" + subs if subs else ""))[:5000]
    duration_raw = d.get("duration") or ""
    duration_sec = None
    # "mm:ss" or "h:mm:ss" strings from search results
    try:
        parts = [int(p) for p in str(duration_raw).split(":") if p.isdigit()]
        if len(parts) == 2:
            duration_sec = parts[0] * 60 + parts[1]
        elif len(parts) == 3:
            duration_sec = parts[0] * 3600 + parts[1] * 60 + parts[2]
    except Exception:
        duration_sec = None

    return {
        "id": make_id(PLATFORM, bvid),
        "raw_id": bvid,
        "platform": PLATFORM,
        "lang": "zh",
        "country_hint": "CN",
        "title": title,
        "author": d.get("author") or "",
        "url": f"https://www.bilibili.com/video/{bvid}",
        "body": body,
        "engagement": {
            "views": play,
            "likes": favorites,
            "comments": danmaku,
        },
        "duration_sec": duration_sec,
        "created_utc": d.get("pubdate"),
    }


def run():
    state = State(PLATFORM)
    preload_seen(state, PLATFORM, key_field="id")
    items_added = 0

    cookies = warm_cookies()
    if not cookies:
        # One retry — some regions need a second handshake
        time.sleep(2)
        cookies = warm_cookies()

    try:
        for kw in INCOME_KEYWORDS["zh"]:
            if state.is_kw_done(kw):
                continue
            print(f"[bili] '{kw}'")
            start_page = state.get_cursor(kw, 1)
            had_error = False
            per_kw = 0

            for page in range(start_page, PAGES_PER_QUERY + 1):
                results, ok = search(kw, page, cookies)
                if not ok:
                    had_error = True
                    time.sleep(15)
                    # Re-warm cookies — buvid may have rotated
                    cookies = warm_cookies() or cookies
                    break
                if not results:
                    break

                for d in results:
                    bvid = d.get("bvid") or ""
                    if not bvid:
                        continue
                    id_ = make_id(PLATFORM, bvid)
                    if state.is_seen(id_):
                        continue

                    item = build_item(d, cookies)
                    state.mark_seen(id_)
                    if item is None:
                        polite_sleep()
                        continue

                    append_jsonl(item, PLATFORM, RAW_DIR)
                    items_added += 1
                    per_kw += 1
                    if items_added % 20 == 0:
                        print(f"  [bili] +{items_added} so far")
                    state.maybe_save(every=5)
                    polite_sleep()

                    if items_added >= PER_PLATFORM_LIMIT:
                        break
                    if per_kw >= PER_KEYWORD_LIMIT:
                        break

                state.set_cursor(kw, page + 1)
                if items_added >= PER_PLATFORM_LIMIT or per_kw >= PER_KEYWORD_LIMIT:
                    break
                time.sleep(1.5)

            if not had_error:
                state.mark_kw_done(kw)
            state.save()
            if items_added >= PER_PLATFORM_LIMIT:
                print(f"[bili] hit PER_PLATFORM_LIMIT={PER_PLATFORM_LIMIT}")
                break
    finally:
        state.save(force=True)

    print(f"[bili] done, +{items_added} items this run")


if __name__ == "__main__":
    run()
