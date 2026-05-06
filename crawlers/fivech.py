"""5ch.net crawler — Japan's largest forum (formerly 2ch).

Strategy:
  - Pull the active thread list per board via subject.txt (Shift_JIS).
  - Filter thread titles for INCOME_KEYWORDS["ja"] (年収, 月収, 副業, 手取り...)
  - For each matching thread, fetch the dat: each line is
        name<>email<>date<>body<>title
    (newline = post separator). Body emit one item per post (anonymous-heavy).
  - Country JP, lang ja. 5ch is fragile — keep delays generous.
"""
import re
import time
import requests

try:
    import chardet
except ImportError:
    chardet = None

from config import (
    INCOME_KEYWORDS, PER_PLATFORM_LIMIT, PER_KEYWORD_LIMIT, RAW_DIR,
    PLATFORM_TIME_BUDGET_SEC,
)
from crawlers.common import (
    append_jsonl, make_id, is_on_topic, preload_seen, polite_sleep,
    default_headers, TimeBudget,
)
from crawlers.state import State


# Boards relevant to income / careers / business
BOARDS = [
    # (subdomain, board_slug, hint)
    ("egg", "job", "求人/転職"),
    ("egg", "money", "お金"),
    ("matsuri2", "news4biz", "ビジネスニュース"),
    ("egg", "economy", "経済"),
]

SUBJECT_URL = "https://{sub}.5ch.net/{board}/subject.txt"
DAT_URL = "https://{sub}.5ch.net/{board}/dat/{tid}.dat"
THREAD_URL = "https://{sub}.5ch.net/test/read.cgi/{board}/{tid}/"

REQUEST_TIMEOUT = 25
SLEEP_LO_MS = 2000
SLEEP_HI_MS = 3500
MAX_THREADS_PER_BOARD = 6 if PER_PLATFORM_LIMIT < 200 else 30
MAX_POSTS_PER_THREAD = 30 if PER_PLATFORM_LIMIT < 200 else 200


def _decode(content: bytes) -> str:
    """Decode Shift_JIS-ish 5ch bytes; tolerate noise."""
    if not content:
        return ""
    if chardet is not None:
        try:
            guess = chardet.detect(content)
            enc = (guess.get("encoding") or "").lower()
            if enc and enc not in ("ascii",):
                try:
                    return content.decode(enc, errors="replace")
                except Exception:
                    pass
        except Exception:
            pass
    # Default 5ch is Shift_JIS
    try:
        return content.decode("shift_jis", errors="replace")
    except Exception:
        return content.decode("utf-8", errors="replace")


def _strip_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    s = s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return s.strip()


def fetch_subject_txt(sub: str, board: str) -> list[tuple[str, str, int]]:
    """Return list of (thread_id, title, n_posts) from subject.txt."""
    url = SUBJECT_URL.format(sub=sub, board=board)
    headers = default_headers(accept_lang="ja-JP,ja;q=0.9,en;q=0.5")
    try:
        r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    except Exception as e:
        print(f"  [fivech] subject {board} err: {e}")
        return []
    if r.status_code != 200:
        print(f"  [fivech] subject {board} status={r.status_code}")
        return []
    text = _decode(r.content)
    out = []
    # subject.txt lines: "<thread_id>.dat<>Title (n_posts)"
    for line in text.splitlines():
        line = line.strip()
        if not line or "<>" not in line:
            continue
        try:
            left, rest = line.split("<>", 1)
        except ValueError:
            continue
        m = re.match(r"^(\d+)\.dat$", left)
        if not m:
            continue
        tid = m.group(1)
        # rest typically ends with " (NNN)" — number of posts
        n_posts = 0
        m2 = re.search(r"\((\d+)\)\s*$", rest)
        if m2:
            try:
                n_posts = int(m2.group(1))
            except ValueError:
                n_posts = 0
            title = rest[:m2.start()].strip()
        else:
            title = rest.strip()
        out.append((tid, title, n_posts))
    return out


def fetch_thread_dat(sub: str, board: str, tid: str) -> list[dict]:
    """Return list of post dicts for a single thread.

    Each .dat line: name<>email<>date_with_id<>body<>title (title only on #1).
    Returns posts in order with 1-based post numbers.
    """
    url = DAT_URL.format(sub=sub, board=board, tid=tid)
    headers = default_headers(accept_lang="ja-JP,ja;q=0.9,en;q=0.5")
    try:
        r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    except Exception as e:
        print(f"    [fivech] dat {tid} err: {e}")
        return []
    if r.status_code != 200:
        print(f"    [fivech] dat {tid} status={r.status_code}")
        return []
    text = _decode(r.content)
    posts = []
    for idx, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split("<>")
        if len(parts) < 4:
            continue
        name = _strip_html(parts[0])
        email = parts[1].strip()
        date_field = _strip_html(parts[2])
        body = _strip_html(parts[3])
        title = _strip_html(parts[4]) if len(parts) >= 5 else ""
        posts.append({
            "post_no": idx,
            "name": name,
            "email": email,
            "date": date_field,
            "body": body,
            "title": title,
        })
    return posts


def run():
    state = State("fivech")
    preload_seen(state, "fivech", key_field="id")
    items_added = 0
    budget = TimeBudget(PLATFORM_TIME_BUDGET_SEC)

    ja_kws = INCOME_KEYWORDS.get("ja", [])

    try:
        for sub, board, board_hint in BOARDS:
            if budget.expired():
                print("[fivech] time budget expired")
                break
            label = f"{sub}/{board}"
            if state.is_kw_done(label):
                continue
            print(f"[fivech] board {label} ({board_hint})")
            try:
                threads = fetch_subject_txt(sub, board)
            except Exception as e:
                print(f"  [fivech] {label} subject err: {e}")
                threads = []
            polite_sleep(SLEEP_LO_MS, SLEEP_HI_MS)
            if not threads:
                state.save()
                continue

            # Filter threads by income keywords in title
            matching = []
            for tid, title, n_posts in threads:
                if not title:
                    continue
                hit = any(kw in title for kw in ja_kws) or is_on_topic(title, lang="ja")
                if hit:
                    matching.append((tid, title, n_posts))
            print(f"  [fivech] {label} threads={len(threads)} matching={len(matching)}")

            kw_added = 0
            had_error = False
            for tid, title, n_posts in matching[:MAX_THREADS_PER_BOARD]:
                if budget.expired():
                    print("  [fivech] time budget expired mid-board")
                    break
                if items_added >= PER_PLATFORM_LIMIT:
                    break
                if kw_added >= PER_KEYWORD_LIMIT:
                    break
                thread_url = THREAD_URL.format(sub=sub, board=board, tid=tid)
                print(f"  [fivech] thread {tid} title={title[:60]!r} posts~{n_posts}")
                try:
                    posts = fetch_thread_dat(sub, board, tid)
                except Exception as e:
                    print(f"    [fivech] thread {tid} err: {e}")
                    had_error = True
                    posts = []
                if not posts:
                    polite_sleep(SLEEP_LO_MS, SLEEP_HI_MS)
                    continue

                # Thread-level title fallback
                thread_title = posts[0].get("title") or title
                for post in posts[:MAX_POSTS_PER_THREAD]:
                    body = post["body"]
                    if not body or len(body) < 20:
                        continue
                    # Filter: must be on-topic in JA (or contain a JA money token)
                    if not is_on_topic(thread_title, body, lang="ja"):
                        continue
                    raw_id = f"{board}_{tid}_{post['post_no']}"
                    item_id = make_id("fivech", raw_id)
                    if state.is_seen(item_id):
                        continue
                    item = {
                        "id": item_id,
                        "raw_id": raw_id,
                        "platform": "fivech",
                        "lang": "ja",
                        "country_hint": "JP",
                        "title": thread_title[:300],
                        "author": post["name"] or "名無しさん",
                        "url": thread_url,
                        "body": body[:5000],
                        "post_no": post["post_no"],
                        "post_date": post["date"],
                        "board": f"{sub}/{board}",
                        "thread_id": tid,
                        "engagement": {
                            "score": 0,
                            "comments": n_posts,
                            "views": None,
                        },
                    }
                    append_jsonl(item, "fivech", RAW_DIR)
                    state.mark_seen(item_id)
                    items_added += 1
                    kw_added += 1
                    if items_added % 25 == 0:
                        print(f"    [fivech] +{items_added} so far")
                    if items_added >= PER_PLATFORM_LIMIT:
                        break
                    if kw_added >= PER_KEYWORD_LIMIT:
                        break
                state.maybe_save(every=10)
                polite_sleep(SLEEP_LO_MS, SLEEP_HI_MS)

            if not had_error:
                state.mark_kw_done(label)
            state.save()
            if items_added >= PER_PLATFORM_LIMIT:
                print(f"[fivech] hit PER_PLATFORM_LIMIT={PER_PLATFORM_LIMIT}")
                break
    finally:
        state.save(force=True)

    print(f"[fivech] done, +{items_added} items this run")


if __name__ == "__main__":
    run()
