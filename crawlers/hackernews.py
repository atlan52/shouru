"""Hacker News crawler via Algolia public search API (no key required).

hn.algolia.com/api is the canonical search endpoint Y Combinator themselves
use; it returns up to 1000 hits per query with `page` pagination.
Comments are fetched from the Firebase item endpoint for the top stories.
"""
import time
import requests
from config import (
    INCOME_KEYWORDS, PER_PLATFORM_LIMIT, HN_HITS_PER_QUERY,
    PAGES_PER_QUERY, UA, RAW_DIR,
)
from crawlers.common import (
    append_jsonl, make_id, is_on_topic, preload_seen, polite_sleep,
)
from crawlers.state import State

ALGOLIA = "https://hn.algolia.com/api/v1/search"
FIREBASE = "https://hacker-news.firebaseio.com/v0"
HEADERS = {"User-Agent": UA}
HN_PAGES_PER_QUERY = max(PAGES_PER_QUERY, 1)
TOP_COMMENT_COUNT = 5


class HNError(Exception):
    pass


def fetch_search(query: str, page: int = 0):
    params = {
        "query": query,
        "hitsPerPage": HN_HITS_PER_QUERY,
        "page": page,
        "tags": "(story,comment)",  # both top-level stories and standalone comments
    }
    try:
        r = requests.get(ALGOLIA, headers=HEADERS, params=params, timeout=25)
        if r.status_code != 200:
            raise HNError(f"algolia status {r.status_code}")
        return r.json()
    except HNError:
        raise
    except Exception as e:
        raise HNError(str(e))


def fetch_item(item_id: int):
    """Fetch a single HN item from Firebase (used to collect top comments)."""
    try:
        r = requests.get(f"{FIREBASE}/item/{item_id}.json", headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def fetch_top_comments(item_id: int, n: int = TOP_COMMENT_COUNT):
    parent = fetch_item(item_id)
    if not parent or not isinstance(parent, dict):
        return []
    kids = parent.get("kids") or []
    out = []
    for kid in kids[: n * 2]:  # fetch a few extra, skip deleted/empty
        c = fetch_item(kid)
        if not c or c.get("deleted") or c.get("dead"):
            continue
        body = (c.get("text") or "").strip()
        if not body or len(body) < 30:
            continue
        out.append({"body": body[:1500], "score": c.get("score", 0) or 0})
        if len(out) >= n:
            break
    return out


def normalize(hit):
    is_story = "story" in (hit.get("_tags") or [])
    is_comment = "comment" in (hit.get("_tags") or [])
    if not (is_story or is_comment):
        return None
    rid = str(hit.get("objectID", ""))
    if not rid:
        return None
    title = hit.get("title") or hit.get("story_title") or ""
    body = hit.get("story_text") or hit.get("comment_text") or ""
    url = hit.get("url") or f"https://news.ycombinator.com/item?id={rid}"
    points = hit.get("points") or 0
    num_comments = hit.get("num_comments") or 0
    if is_story and points < 5:  # HN is low-volume per story
        return None
    if not is_on_topic(title, body, lang="en"):
        return None
    return {
        "id": make_id("hackernews", rid),
        "raw_id": rid,
        "platform": "hackernews",
        "lang": "en",
        "country_hint": "??",
        "title": title,
        "author": hit.get("author", ""),
        "url": url,
        "hn_url": f"https://news.ycombinator.com/item?id={rid}",
        "body": (body or "")[:5000],
        "kind": "story" if is_story else "comment",
        "engagement": {
            "score": points,
            "comments": num_comments,
            "views": None,
        },
        "created_utc": hit.get("created_at_i"),
    }


def run():
    state = State("hackernews")
    preload_seen(state, "hackernews", key_field="id")
    items_added = 0

    try:
        for kw in INCOME_KEYWORDS["en"]:
            if state.is_kw_done(kw):
                continue
            print(f"[hn] search: {kw}")
            start_page = state.get_cursor(kw, 0) or 0
            had_error = False
            for page in range(start_page, start_page + HN_PAGES_PER_QUERY):
                try:
                    j = fetch_search(kw, page=page)
                except HNError as e:
                    print(f"  [hn] {kw} page {page} err: {e}")
                    had_error = True
                    time.sleep(5)
                    break
                hits = j.get("hits") or []
                if not hits:
                    break
                for hit in hits:
                    it = normalize(hit)
                    if not it:
                        continue
                    if state.is_seen(it["id"]):
                        continue
                    if it["kind"] == "story":
                        try:
                            it["top_comments"] = fetch_top_comments(int(it["raw_id"]), TOP_COMMENT_COUNT)
                        except Exception:
                            it["top_comments"] = []
                    append_jsonl(it, "hackernews", RAW_DIR)
                    state.mark_seen(it["id"])
                    items_added += 1
                    if items_added % 25 == 0:
                        print(f"  [hn] +{items_added} so far")
                state.set_cursor(kw, page + 1)
                state.maybe_save(every=5)
                polite_sleep()
                if page + 1 >= (j.get("nbPages") or 1):
                    break
                if items_added >= PER_PLATFORM_LIMIT:
                    break
            if not had_error:
                state.mark_kw_done(kw)
            state.save()
            if items_added >= PER_PLATFORM_LIMIT:
                print(f"[hn] hit PER_PLATFORM_LIMIT={PER_PLATFORM_LIMIT}")
                break
    finally:
        state.save(force=True)

    print(f"[hn] done, +{items_added} items this run")


if __name__ == "__main__":
    run()
