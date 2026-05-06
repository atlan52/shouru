"""note.com crawler — Japanese paid-creator platform.

Strategy:
  - JSON search API: https://note.com/api/v3/searches/notes?q={kw}&page=N
    returns paginated note metadata (title, body excerpt, author, like count).
  - Hashtag fallback: https://note.com/api/v2/hashtags/{tag}/notes (income tags).
  - Build the human URL from author username + noteId:
       https://note.com/{user_name}/n/{key}
  - Country JP, lang ja. requests + JSON only (no Playwright needed).
"""
import time
import requests
from urllib.parse import quote_plus

from config import (
    INCOME_KEYWORDS, PER_PLATFORM_LIMIT, PER_KEYWORD_LIMIT, RAW_DIR,
    PLATFORM_TIME_BUDGET_SEC,
)
from crawlers.common import (
    append_jsonl, make_id, is_on_topic, preload_seen, polite_sleep,
    default_headers, TimeBudget,
)
from crawlers.state import State


SEARCH_URL = "https://note.com/api/v3/searches/notes"
HASHTAG_URL = "https://note.com/api/v2/hashtags/{tag}/notes"
NOTE_DETAIL_URL = "https://note.com/api/v3/notes/{key}"
PAGES_PER_QUERY = 4 if PER_PLATFORM_LIMIT >= 200 else 1
PER_PAGE = 20

INCOME_HASHTAGS = [
    "副業", "年収", "フリーランス収入", "FIRE", "不労所得", "サラリーマン",
    "脱サラ", "個人事業主",
]

REQUEST_TIMEOUT = 25


class NoteError(Exception):
    pass


def _headers() -> dict:
    h = default_headers(accept_lang="ja-JP,ja;q=0.9,en;q=0.5")
    h["Accept"] = "application/json, text/plain, */*"
    h["Referer"] = "https://note.com/"
    return h


def fetch_json(url: str, params=None) -> dict:
    try:
        r = requests.get(url, headers=_headers(), params=params, timeout=REQUEST_TIMEOUT)
    except Exception as e:
        raise NoteError(str(e))
    if r.status_code in (429, 403):
        raise NoteError(f"{r.status_code} on {url}")
    if r.status_code != 200:
        raise NoteError(f"status {r.status_code} on {url}")
    try:
        return r.json()
    except Exception:
        raise NoteError(f"non-JSON on {url}")


def _extract_notes(payload) -> list[dict]:
    """note.com API payload may be nested as data.notes / data.contents / notes."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data") or payload
    for key in ("notes", "contents", "results"):
        if key in data and isinstance(data[key], list):
            return data[key]
    # Sometimes wraps differently
    if isinstance(data, list):
        return data
    return []


def _user_field(note: dict, *keys) -> str:
    user = note.get("user") or note.get("author") or {}
    if not isinstance(user, dict):
        return ""
    for k in keys:
        v = user.get(k)
        if v:
            return str(v)
    return ""


def normalize(note: dict, kw: str) -> dict | None:
    if not isinstance(note, dict):
        return None
    key = note.get("key") or note.get("id") or note.get("note_id") or note.get("noteId")
    if not key:
        return None
    raw_id = str(key)
    title = note.get("name") or note.get("title") or ""
    # body excerpt — note.com gives "body" plaintext on some endpoints, "description"
    # on others; "highlight" on search.
    body = (
        note.get("body")
        or note.get("description")
        or note.get("highlight")
        or note.get("excerpt")
        or ""
    )
    if isinstance(body, dict):
        body = body.get("text") or body.get("html") or ""
    body = str(body or "")
    if not is_on_topic(title, body, lang="ja"):
        return None
    user_name = _user_field(note, "urlname", "username", "name") or ""
    author_disp = _user_field(note, "nickname", "name", "username") or user_name
    if user_name:
        url = f"https://note.com/{user_name}/n/{raw_id}"
    else:
        url = note.get("note_url") or f"https://note.com/notes/{raw_id}"
    like_count = (
        note.get("like_count")
        or note.get("likeCount")
        or note.get("likes_count")
        or 0
    )
    comments_count = note.get("comment_count") or note.get("commentCount") or 0
    price = note.get("price") or 0
    return {
        "id": make_id("note_jp", raw_id),
        "raw_id": raw_id,
        "platform": "note_jp",
        "lang": "ja",
        "country_hint": "JP",
        "title": title[:300],
        "author": author_disp,
        "url": url,
        "body": body[:5000],
        "matched_keyword": kw,
        "engagement": {
            "score": int(like_count or 0),
            "comments": int(comments_count or 0),
            "views": None,
        },
        "price_jpy": int(price or 0) if isinstance(price, (int, float)) else 0,
        "created_utc": note.get("publish_at") or note.get("published_at") or note.get("created_at"),
    }


def _pull_search(state: State, kw: str, budget: TimeBudget,
                 items_added_ref: list[int]) -> int:
    added = 0
    start_page = state.get_cursor(f"q:{kw}", 1) or 1
    for page in range(start_page, start_page + PAGES_PER_QUERY):
        if budget.expired():
            return added
        try:
            payload = fetch_json(SEARCH_URL, params={
                "q": kw, "size": PER_PAGE, "page": page, "context": "note",
            })
        except NoteError as e:
            print(f"  [note_jp] kw={kw!r} p{page} err: {e}")
            time.sleep(3)
            break
        notes = _extract_notes(payload)
        if not notes:
            break
        for n in notes:
            it = normalize(n, kw)
            if not it:
                continue
            if state.is_seen(it["id"]):
                continue
            append_jsonl(it, "note_jp", RAW_DIR)
            state.mark_seen(it["id"])
            added += 1
            items_added_ref[0] += 1
            if items_added_ref[0] >= PER_PLATFORM_LIMIT:
                return added
            if added >= PER_KEYWORD_LIMIT:
                state.set_cursor(f"q:{kw}", page + 1)
                state.maybe_save(every=5)
                return added
        state.set_cursor(f"q:{kw}", page + 1)
        state.maybe_save(every=5)
        polite_sleep()
    return added


def _pull_hashtag(state: State, tag: str, budget: TimeBudget,
                  items_added_ref: list[int]) -> int:
    added = 0
    start_page = state.get_cursor(f"tag:{tag}", 1) or 1
    for page in range(start_page, start_page + PAGES_PER_QUERY):
        if budget.expired():
            return added
        url = HASHTAG_URL.format(tag=quote_plus(tag))
        try:
            payload = fetch_json(url, params={"page": page, "size": PER_PAGE})
        except NoteError as e:
            print(f"  [note_jp] tag={tag!r} p{page} err: {e}")
            time.sleep(3)
            break
        notes = _extract_notes(payload)
        if not notes:
            break
        for n in notes:
            it = normalize(n, f"#{tag}")
            if not it:
                continue
            if state.is_seen(it["id"]):
                continue
            append_jsonl(it, "note_jp", RAW_DIR)
            state.mark_seen(it["id"])
            added += 1
            items_added_ref[0] += 1
            if items_added_ref[0] >= PER_PLATFORM_LIMIT:
                return added
            if added >= PER_KEYWORD_LIMIT:
                state.set_cursor(f"tag:{tag}", page + 1)
                state.maybe_save(every=5)
                return added
        state.set_cursor(f"tag:{tag}", page + 1)
        state.maybe_save(every=5)
        polite_sleep()
    return added


def run():
    state = State("note_jp")
    preload_seen(state, "note_jp", key_field="id")
    items_added = [0]
    budget = TimeBudget(PLATFORM_TIME_BUDGET_SEC)

    ja_kws = INCOME_KEYWORDS.get("ja", [])
    try:
        # Pass 1: keyword search
        for kw in ja_kws:
            if budget.expired():
                print("[note_jp] time budget expired")
                break
            label = f"q:{kw}"
            if state.is_kw_done(label):
                continue
            print(f"[note_jp] search kw={kw!r}")
            try:
                _pull_search(state, kw, budget, items_added)
                state.mark_kw_done(label)
            except Exception as e:
                print(f"  [note_jp] kw={kw!r} fatal: {e}")
            state.save()
            polite_sleep()
            if items_added[0] >= PER_PLATFORM_LIMIT:
                print(f"[note_jp] hit PER_PLATFORM_LIMIT={PER_PLATFORM_LIMIT}")
                break

        # Pass 2: hashtag pages
        if items_added[0] < PER_PLATFORM_LIMIT:
            for tag in INCOME_HASHTAGS:
                if budget.expired():
                    break
                label = f"tag:{tag}"
                if state.is_kw_done(label):
                    continue
                print(f"[note_jp] hashtag #{tag}")
                try:
                    _pull_hashtag(state, tag, budget, items_added)
                    state.mark_kw_done(label)
                except Exception as e:
                    print(f"  [note_jp] tag={tag!r} fatal: {e}")
                state.save()
                polite_sleep()
                if items_added[0] >= PER_PLATFORM_LIMIT:
                    break
    finally:
        state.save(force=True)

    print(f"[note_jp] done, +{items_added[0]} items this run")


if __name__ == "__main__":
    run()
