"""Yahoo!知恵袋 (chiebukuro.yahoo.co.jp) crawler — Yahoo Answers JP.

Strategy:
  - Search: https://chiebukuro.yahoo.co.jp/search?p={kw}&type=question
    Paginate with &b=1, 11, 21, ... (10 results/page).
  - Each result links to a question detail page:
        https://detail.chiebukuro.yahoo.co.jp/qa/question_detail/qXXXXX
  - On the detail page extract: title, body, asker, best_answer body,
    other top answers (capped at 2).
  - Country JP, lang ja. requests + BeautifulSoup.
"""
import re
import time
import requests
from urllib.parse import quote_plus

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from config import (
    INCOME_KEYWORDS, PER_PLATFORM_LIMIT, PER_KEYWORD_LIMIT, RAW_DIR,
    PLATFORM_TIME_BUDGET_SEC,
)
from crawlers.common import (
    append_jsonl, make_id, is_on_topic, preload_seen, polite_sleep,
    default_headers, TimeBudget,
)
from crawlers.state import State


SEARCH_URL = "https://chiebukuro.yahoo.co.jp/search"
QA_BASE = "https://detail.chiebukuro.yahoo.co.jp/qa/question_detail/q"
PAGES_PER_QUERY = 3 if PER_PLATFORM_LIMIT >= 200 else 1
PER_PAGE = 10
REQUEST_TIMEOUT = 25


class ChieError(Exception):
    pass


def _headers() -> dict:
    return default_headers(accept_lang="ja-JP,ja;q=0.9,en;q=0.5")


def _get(url: str, params=None) -> str:
    try:
        r = requests.get(url, headers=_headers(), params=params, timeout=REQUEST_TIMEOUT)
    except Exception as e:
        raise ChieError(str(e))
    if r.status_code in (429, 403):
        raise ChieError(f"{r.status_code} on {url}")
    if r.status_code != 200:
        raise ChieError(f"status {r.status_code} on {url}")
    # Yahoo!JP serves UTF-8 for chiebukuro
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


_QID_RE = re.compile(r"/q(?:uestion_detail/q)?(\d{8,})")


def _extract_qid(href: str) -> str:
    if not href:
        return ""
    m = re.search(r"q(\d{8,})", href)
    if m:
        return m.group(1)
    return ""


def _text(el) -> str:
    if el is None:
        return ""
    return el.get_text(" ", strip=True)


def parse_search(html: str) -> list[tuple[str, str]]:
    """Return list of (qid, title) from a search results page."""
    if not html or BeautifulSoup is None:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()
    # Search anchors that look like question detail links
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "question_detail" not in href and "/qa/question_detail" not in href:
            # Some search variants use /q12345 paths
            if not re.search(r"/q\d{8,}", href):
                continue
        qid = _extract_qid(href)
        if not qid or qid in seen:
            continue
        title = _text(a)
        if not title or len(title) < 5:
            continue
        seen.add(qid)
        out.append((qid, title))
    return out


def parse_detail(html: str) -> dict:
    """Pull title/body/asker/best_answer/other_answers from question detail."""
    if not html or BeautifulSoup is None:
        return {}
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title = ""
    h = soup.find(["h1", "h2"])
    if h:
        title = _text(h)
    if not title:
        t = soup.find("title")
        if t:
            title = _text(t)
            # Trim "- Yahoo!知恵袋" suffix
            title = re.sub(r"\s*[-|]\s*Yahoo.*$", "", title).strip()

    # Question body — chiebukuro uses class names that vary; try several.
    body = ""
    body_candidates = [
        soup.select_one(".ClapLv1TextBlock__text"),
        soup.select_one("[class*='QuestionText']"),
        soup.select_one("[class*='Question__']"),
        soup.select_one("p.gA_jc"),
    ]
    for c in body_candidates:
        if c and _text(c):
            body = _text(c)
            break
    if not body:
        # fallback: largest <p> in main content
        ps = sorted((p for p in soup.find_all("p") if _text(p)),
                    key=lambda p: len(_text(p)), reverse=True)
        if ps:
            body = _text(ps[0])

    # Asker
    asker = ""
    a_el = soup.select_one("[class*='UserName'] a, [class*='userName'] a, .userName")
    if a_el:
        asker = _text(a_el)

    # Best answer block
    best_answer = ""
    ba_el = (
        soup.select_one("[class*='BestAnswer'] [class*='Text']")
        or soup.select_one("[class*='best_answer'] [class*='text']")
        or soup.select_one("[class*='ba_body']")
    )
    if ba_el:
        best_answer = _text(ba_el)

    # Other answers (cap at 2)
    other_answers = []
    for sel in [
        "[class*='AnswerItem'] [class*='Text']",
        "[class*='answer_item'] [class*='text']",
        "[class*='answerBody']",
    ]:
        elems = soup.select(sel)
        if elems:
            for e in elems:
                t = _text(e)
                if t and t != best_answer and len(t) > 20:
                    other_answers.append(t[:2000])
                if len(other_answers) >= 2:
                    break
        if other_answers:
            break

    return {
        "title": title,
        "body": body,
        "asker": asker,
        "best_answer": best_answer,
        "other_answers": other_answers,
    }


def fetch_question(qid: str) -> dict:
    url = f"{QA_BASE}{qid}"
    html = _get(url)
    detail = parse_detail(html)
    detail["url"] = url
    detail["raw_id"] = qid
    return detail


def _search_keyword(state: State, kw: str, budget: TimeBudget,
                    items_added_ref: list[int]) -> int:
    added = 0
    start_b = state.get_cursor(kw, 1) or 1
    for page in range(PAGES_PER_QUERY):
        if budget.expired():
            return added
        b = start_b + page * PER_PAGE
        try:
            html = _get(SEARCH_URL, params={
                "p": kw, "type": "question", "b": b,
            })
        except ChieError as e:
            print(f"  [chiebukuro] kw={kw!r} b={b} err: {e}")
            time.sleep(3)
            break
        results = parse_search(html)
        if not results:
            break
        for qid, list_title in results:
            if budget.expired():
                return added
            item_id = make_id("yahoo_chiebukuro", qid)
            if state.is_seen(item_id):
                continue
            # Quick title filter to avoid spending a request on off-topic Qs
            if not is_on_topic(list_title, lang="ja"):
                # Still mark seen so we don't fetch again
                state.mark_seen(item_id)
                continue
            try:
                detail = fetch_question(qid)
            except ChieError as e:
                print(f"    [chiebukuro] q{qid} err: {e}")
                time.sleep(2)
                continue
            polite_sleep()
            title = detail.get("title") or list_title
            body = detail.get("body") or ""
            best = detail.get("best_answer") or ""
            others = detail.get("other_answers") or []
            blob = " ".join([title, body, best] + others)
            if not is_on_topic(blob, lang="ja"):
                state.mark_seen(item_id)
                continue
            item = {
                "id": item_id,
                "raw_id": qid,
                "platform": "yahoo_chiebukuro",
                "lang": "ja",
                "country_hint": "JP",
                "title": title[:300],
                "author": detail.get("asker") or "",
                "url": detail.get("url") or f"{QA_BASE}{qid}",
                "body": body[:5000],
                "best_answer": best[:5000],
                "other_answers": others,
                "matched_keyword": kw,
                "engagement": {
                    "score": 0,
                    "comments": len(others) + (1 if best else 0),
                    "views": None,
                },
            }
            append_jsonl(item, "yahoo_chiebukuro", RAW_DIR)
            state.mark_seen(item_id)
            added += 1
            items_added_ref[0] += 1
            if items_added_ref[0] % 25 == 0:
                print(f"    [chiebukuro] +{items_added_ref[0]} so far")
            if items_added_ref[0] >= PER_PLATFORM_LIMIT:
                return added
            if added >= PER_KEYWORD_LIMIT:
                state.set_cursor(kw, b + PER_PAGE)
                state.maybe_save(every=5)
                return added
        state.set_cursor(kw, b + PER_PAGE)
        state.maybe_save(every=5)
        polite_sleep()
    return added


def run():
    state = State("yahoo_chiebukuro")
    preload_seen(state, "yahoo_chiebukuro", key_field="id")
    items_added = [0]
    budget = TimeBudget(PLATFORM_TIME_BUDGET_SEC)

    if BeautifulSoup is None:
        print("[chiebukuro] bs4 not installed — aborting")
        return

    ja_kws = INCOME_KEYWORDS.get("ja", [])
    try:
        for kw in ja_kws:
            if budget.expired():
                print("[chiebukuro] time budget expired")
                break
            if state.is_kw_done(kw):
                continue
            print(f"[chiebukuro] kw={kw!r}")
            had_error = False
            try:
                _search_keyword(state, kw, budget, items_added)
            except Exception as e:
                print(f"  [chiebukuro] kw={kw!r} fatal: {e}")
                had_error = True
            if not had_error:
                state.mark_kw_done(kw)
            state.save()
            polite_sleep()
            if items_added[0] >= PER_PLATFORM_LIMIT:
                print(f"[chiebukuro] hit PER_PLATFORM_LIMIT={PER_PLATFORM_LIMIT}")
                break
    finally:
        state.save(force=True)

    print(f"[chiebukuro] done, +{items_added[0]} items this run")


if __name__ == "__main__":
    run()
