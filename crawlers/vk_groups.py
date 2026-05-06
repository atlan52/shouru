"""VK public-wall search crawler — vk.com.

VK's Open API exposes `wall.search` for free-text search over public group
walls. We pass each Russian income keyword and harvest posts including:

  post_id, owner_id (negative for groups), group_name, text (body),
  likes / comments / reposts / views, date, URL
  https://vk.com/wall<owner_id>_<post_id>.

Auth: requires VK_TOKEN env var (a user or service token). If missing
we log a warning and abort cleanly.

API ref: https://dev.vk.com/method/wall.search
"""
import os
import time
import requests

from config import (
    INCOME_KEYWORDS, PER_PLATFORM_LIMIT, RAW_DIR, PLATFORM_TIME_BUDGET_SEC,
)
from crawlers.common import (
    append_jsonl, make_id, is_on_topic, polite_sleep, preload_seen,
    default_headers, TimeBudget,
)
from crawlers.state import State


PLATFORM = "vk_groups"
API = "https://api.vk.com/method"
API_VERSION = "5.131"
COUNT_PER_CALL = 100


class VKError(Exception):
    pass


def _headers() -> dict:
    h = default_headers(accept_lang="ru-RU,ru;q=0.9,en;q=0.6")
    h["Accept"] = "application/json"
    return h


def _api_call(method: str, params: dict, token: str, timeout: int = 25):
    p = dict(params)
    p["access_token"] = token
    p["v"] = API_VERSION
    url = f"{API}/{method}"
    try:
        r = requests.get(url, params=p, headers=_headers(), timeout=timeout)
    except Exception as e:
        raise VKError(f"net err {url}: {e}")
    if r.status_code != 200:
        raise VKError(f"status {r.status_code} on {url}")
    try:
        j = r.json()
    except Exception:
        raise VKError(f"non-JSON response on {url}")
    if "error" in j:
        err = j["error"] or {}
        code = err.get("error_code")
        msg = err.get("error_msg")
        raise VKError(f"VK API error {code}: {msg}")
    return j.get("response", {})


def _retry(method: str, params: dict, token: str):
    try:
        return _api_call(method, params, token)
    except VKError as e:
        msg = str(e)
        # Common retryable VK errors: 6 (too many requests), 9 (flood control)
        if " 6:" in msg or " 9:" in msg or "429" in msg:
            print(f"  [{PLATFORM}] backoff 30s on {method}")
            time.sleep(30)
            return _api_call(method, params, token)
        raise


def resolve_group_names(owner_ids: list[int], token: str) -> dict:
    """Map negative owner_ids → group screen_name/title via groups.getById."""
    out = {}
    if not owner_ids:
        return out
    # owner_ids for groups are negative — getById wants positive group ids
    group_ids = sorted({-oid for oid in owner_ids if isinstance(oid, int) and oid < 0})
    # API supports up to 500 ids per call
    for i in range(0, len(group_ids), 500):
        chunk = group_ids[i:i + 500]
        try:
            resp = _retry(
                "groups.getById",
                {"group_ids": ",".join(str(x) for x in chunk), "fields": "name"},
                token,
            )
        except VKError as e:
            print(f"  [{PLATFORM}] groups.getById err: {e}")
            continue
        # 5.131 returns a list of group objects directly
        groups = resp if isinstance(resp, list) else (resp.get("groups") or [])
        for g in groups:
            gid = g.get("id")
            if gid is not None:
                out[-int(gid)] = g.get("name") or g.get("screen_name") or ""
        polite_sleep(500, 1000)
    return out


def normalize(p: dict, kw: str, group_names: dict):
    owner_id = p.get("owner_id")
    post_id = p.get("id")
    if owner_id is None or post_id is None:
        return None
    rid = f"{owner_id}_{post_id}"
    text = p.get("text") or ""

    likes = (p.get("likes") or {}).get("count", 0) if isinstance(p.get("likes"), dict) else 0
    comments = (p.get("comments") or {}).get("count", 0) if isinstance(p.get("comments"), dict) else 0
    reposts = (p.get("reposts") or {}).get("count", 0) if isinstance(p.get("reposts"), dict) else 0
    views = (p.get("views") or {}).get("count", 0) if isinstance(p.get("views"), dict) else 0

    group_name = group_names.get(owner_id, "")
    title = (text[:120] + ("…" if len(text) > 120 else "")) if text else f"VK post {rid}"

    return {
        "id": make_id(PLATFORM, rid),
        "raw_id": rid,
        "platform": PLATFORM,
        "subtype": "wall_post",
        "lang": "ru",
        "country_hint": "RU",
        "title": title,
        "body": text[:5000],
        "author": group_name,
        "owner_id": owner_id,
        "post_id": post_id,
        "group_name": group_name,
        "url": f"https://vk.com/wall{owner_id}_{post_id}",
        "engagement": {
            "score": likes,
            "comments": comments,
            "reposts": reposts,
            "views": views,
        },
        "matched_keyword": kw,
        "created_utc": p.get("date"),
    }


def run():
    token = (os.environ.get("VK_TOKEN") or "").strip()
    if not token:
        print(f"[{PLATFORM}] WARN: VK_TOKEN env var not set — aborting cleanly")
        return

    state = State(PLATFORM)
    preload_seen(state, PLATFORM, key_field="id")
    budget = TimeBudget(PLATFORM_TIME_BUDGET_SEC)
    items_added = 0

    try:
        for kw in INCOME_KEYWORDS["ru"]:
            if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                break
            if state.is_kw_done(kw):
                continue

            print(f"[{PLATFORM}] kw {kw}")
            had_error = False

            try:
                resp = _retry(
                    "wall.search",
                    {"q": kw, "count": COUNT_PER_CALL, "extended": 0},
                    token,
                )
            except VKError as e:
                msg = str(e)
                # The newsfeed/wall.search on community walls may require elevated
                # permissions; fall through to newsfeed.search which is broader.
                print(f"  [{PLATFORM}] wall.search {kw} err: {e}")
                if "5:" in msg or "15:" in msg or "wall" in msg.lower():
                    try:
                        resp = _retry(
                            "newsfeed.search",
                            {"q": kw, "count": COUNT_PER_CALL, "extended": 0},
                            token,
                        )
                    except VKError as e2:
                        print(f"  [{PLATFORM}] newsfeed.search {kw} err: {e2}")
                        had_error = True
                        resp = {}
                else:
                    had_error = True
                    resp = {}

            items = resp.get("items") if isinstance(resp, dict) else None
            if not items:
                if not had_error:
                    state.mark_kw_done(kw)
                state.save()
                polite_sleep(1500, 2500)
                continue

            owner_ids = [it.get("owner_id") for it in items if isinstance(it, dict)]
            group_names = resolve_group_names(owner_ids, token)

            for p in items:
                if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                    break
                if not isinstance(p, dict):
                    continue
                try:
                    it = normalize(p, kw, group_names)
                except Exception as e:
                    print(f"  [{PLATFORM}] normalize err: {e}")
                    continue
                if not it:
                    continue
                if state.is_seen(it["id"]):
                    continue
                # Light topic filter (we already searched by kw, but trust nothing)
                if not is_on_topic(it["title"], it["body"], lang="ru"):
                    state.mark_seen(it["id"])
                    continue
                append_jsonl(it, PLATFORM, RAW_DIR)
                state.mark_seen(it["id"])
                items_added += 1
                if items_added % 25 == 0:
                    print(f"  [{PLATFORM}] +{items_added} so far")
                state.maybe_save(every=10)

            if not had_error:
                state.mark_kw_done(kw)
            state.save()
            polite_sleep(1500, 2500)
    finally:
        state.save(force=True)

    print(f"[{PLATFORM}] done, +{items_added} items this run")


if __name__ == "__main__":
    run()
