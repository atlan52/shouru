"""ReclameAqui crawler — Brazilian consumer-complaint board (P2).

ReclameAqui is the largest BR consumer-grievance platform: users post
public complaints against companies (employers, banks, telcos, services).
Many complaints disclose income context — e.g. "Empresa X me deve R$15k em
horas extras", "fui demitido sem receber rescisão de R$8.000", "PJ recebia
R$12k/mês mas não pagaram último mês". This is high-signal Brazilian
employer-themed income data that won't appear on conventional pay sites.

Strategy:
  - Search URL: https://www.reclameaqui.com.br/busca/?q={kw}
    (HTML-rendered list of complaint cards.)
  - Each card links to /<empresa>/<slug>_<id>/ — fetch detail for body,
    author, date, status, target company.
  - Pure requests + BeautifulSoup. No auth.
  - Filter: must mention an explicit money amount (R$, mil, milhões, k)
    AND hit a Portuguese income/topic keyword. Pure complaints with no
    money mention drop out.
  - Country: BR, lang: pt.
"""
import json
import re
import time
from urllib.parse import quote_plus, urljoin

import requests
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from config import (
    INCOME_KEYWORDS, PER_PLATFORM_LIMIT, PAGES_PER_QUERY, RAW_DIR,
    PLATFORM_TIME_BUDGET_SEC,
)
from crawlers.common import (
    append_jsonl, make_id, polite_sleep, preload_seen,
    default_headers, random_ua, is_on_topic, has_amount, TimeBudget,
)
from crawlers.state import State


PLATFORM = "reclame_aqui"
BASE = "https://www.reclameaqui.com.br"
SEARCH_URL = BASE + "/busca/?q={kw}"

# Brazilian-employer-themed terms layered on top of pt INCOME_KEYWORDS.
# These surface complaints that often quote unpaid salaries / overtime / FGTS /
# severance amounts — rich for income context.
EMPLOYER_TERMS_PT = [
    "salário atrasado",
    "demissão",
    "rescisão",
    "horas extras",
    "PJ",
    "CLT",
    "FGTS",
    "13º salário",
    "verbas rescisórias",
    "salário não pago",
]

# Compose final keyword list. dedupe while preserving order.
_seen: set[str] = set()
KEYWORDS: list[str] = []
for kw in (INCOME_KEYWORDS.get("pt") or []) + EMPLOYER_TERMS_PT:
    if kw and kw not in _seen:
        _seen.add(kw)
        KEYWORDS.append(kw)
del _seen


BOT_MARKERS = (
    "captcha", "are you a human", "access denied", "unusual traffic",
    "cf-browser-verification", "checking your browser",
)


class ReclameError(Exception):
    pass


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _ra_headers() -> dict:
    h = default_headers(accept_lang="pt-BR,pt;q=0.9,en;q=0.8")
    h["User-Agent"] = random_ua()
    h["Referer"] = BASE + "/"
    return h


def fetch_html(url: str, timeout: int = 30) -> str:
    try:
        r = requests.get(url, headers=_ra_headers(), timeout=timeout, allow_redirects=True)
    except Exception as e:
        raise ReclameError(f"net err {url}: {e}")
    if r.status_code in (403, 429):
        raise ReclameError(f"{r.status_code} on {url}")
    if r.status_code == 404:
        raise ReclameError(f"404 on {url}")
    if r.status_code != 200:
        raise ReclameError(f"status {r.status_code} on {url}")
    body = r.text or ""
    low = body.lower()
    if any(m in low for m in BOT_MARKERS):
        raise ReclameError("bot-block / captcha")
    return body


def fetch_with_retry(url: str) -> str:
    """One retry with 30s backoff on 403/429."""
    try:
        return fetch_html(url)
    except ReclameError as e:
        msg = str(e)
        if "403" in msg or "429" in msg:
            print(f"  [{PLATFORM}] backoff 30s on {url}")
            time.sleep(30)
            return fetch_html(url)
        raise


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
# Complaint URL pattern: /<empresa-slug>/<title-slug>_<numericId>/ or
# /reclamacao/<id>/ — be permissive.
_COMPLAINT_HREF_RE = re.compile(
    r"/(?:[a-z0-9\-]+/)?(?:reclamacao/)?[a-z0-9\-]+[_\-](\d{5,})(?:/|$)",
    re.I,
)
# Numeric tail extractor (we only need the id digits as raw_id)
_ID_TAIL_RE = re.compile(r"(\d{5,})/?(?:[?#].*)?$")


def _text(el) -> str:
    if not el:
        return ""
    return el.get_text(" ", strip=True)


def _abs(href: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return urljoin(BASE + "/", href)


def _looks_like_complaint_href(href: str) -> bool:
    """Heuristic: is this href a per-complaint detail page?"""
    if not href:
        return False
    if "/busca" in href or "/empresa/" in href:
        return False
    return bool(_COMPLAINT_HREF_RE.search(href))


def parse_search_results(html: str) -> list[dict]:
    """Pull complaint cards from /busca/?q=<kw> page.

    Cards expose title + snippet + company target + a link to the detail
    page. We're tolerant of layout drift: any anchor that points at a path
    with a trailing numeric id is treated as a candidate complaint.
    """
    if BeautifulSoup is None or not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    seen_ids: set[str] = set()

    # Try Next.js __NEXT_DATA__ blob first — RA is a Next.js app and often
    # ships search results as JSON for SEO.
    nd = soup.find("script", id="__NEXT_DATA__")
    if nd and nd.string:
        try:
            blob = json.loads(nd.string)
            for hit in _walk_next_data_for_complaints(blob):
                rid = hit.get("complaint_id")
                if not rid or rid in seen_ids:
                    continue
                seen_ids.add(rid)
                out.append(hit)
        except Exception:
            pass

    # DOM sweep — covers SSR HTML and any cards not in __NEXT_DATA__.
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not _looks_like_complaint_href(href):
            continue
        m = _ID_TAIL_RE.search(href.rstrip("/"))
        if not m:
            continue
        rid = m.group(1)
        if rid in seen_ids:
            continue
        title = _text(a)
        if not title or len(title) < 6:
            # Climb up: maybe the title sits in a sibling/parent
            parent = a.find_parent(["article", "li", "div", "section"])
            if parent:
                t_el = parent.find(["h2", "h3", "h4"])
                if t_el:
                    title = _text(t_el)
        if not title:
            continue
        seen_ids.add(rid)
        out.append({
            "complaint_id": rid,
            "title": title[:300],
            "snippet": "",
            "company": "",
            "url": _abs(href.split("?")[0]),
        })
    return out


def _walk_next_data_for_complaints(obj, depth: int = 0):
    """Yield {complaint_id, title, snippet, company, url} from __NEXT_DATA__.

    RA's search payload tends to nest hits under
    props.pageProps.complaints / .results / .hits — but we don't depend on
    a specific path; instead we recurse and pick anything that looks like
    a complaint object.
    """
    if depth > 10:
        return
    if isinstance(obj, dict):
        rid = obj.get("id") or obj.get("complaintId") or obj.get("complaint_id")
        title = obj.get("title") or obj.get("subject") or ""
        body = obj.get("description") or obj.get("body") or obj.get("text") or ""
        company_el = obj.get("companyName") or obj.get("company") or ""
        if isinstance(company_el, dict):
            company_el = company_el.get("name") or company_el.get("displayName") or ""
        url = obj.get("url") or ""
        if rid and isinstance(rid, (str, int)) and title:
            try:
                rid_str = str(int(rid)) if isinstance(rid, int) else str(rid)
                if rid_str.isdigit() and len(rid_str) >= 5:
                    yield {
                        "complaint_id": rid_str,
                        "title": str(title)[:300],
                        "snippet": str(body)[:500],
                        "company": str(company_el)[:200],
                        "url": _abs(str(url)) if url else "",
                    }
            except Exception:
                pass
        for v in obj.values():
            yield from _walk_next_data_for_complaints(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_next_data_for_complaints(v, depth + 1)


def parse_complaint_detail(html: str) -> dict:
    """Pull title, body, author, status, posted_date, company from detail page."""
    if BeautifulSoup is None or not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title_el = (
        soup.select_one("h1[class*='complaint-title']")
        or soup.select_one("h1[class*='title']")
        or soup.select_one("h1")
    )
    title = _text(title_el)

    # Body
    body = ""
    for sel in (
        "[class*='complaint-detail-description']",
        "[class*='description']",
        "[itemprop='description']",
        "p[class*='complaint']",
        "section[class*='complaint']",
    ):
        el = soup.select_one(sel)
        if el:
            t = _text(el)
            if len(t) > len(body):
                body = t

    # Author
    author = ""
    for sel in (
        "[class*='complaint-user-info'] strong",
        "[class*='user-name']",
        "[class*='username']",
        "[class*='nickname']",
    ):
        el = soup.select_one(sel)
        if el:
            author = _text(el)
            if author:
                break

    # Status (Respondida / Não respondida / Resolvida / Não resolvida)
    status = ""
    for sel in (
        "[class*='complaint-status']",
        "[class*='status-tag']",
        "[class*='Status']",
    ):
        el = soup.select_one(sel)
        if el:
            t = _text(el)
            if t:
                status = t[:80]
                break

    # Posted date — look for time tags or text like "01/05/2024"
    posted_date = ""
    t_el = soup.find("time")
    if t_el:
        posted_date = (t_el.get("datetime") or _text(t_el))[:40]
    if not posted_date:
        m = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", html)
        if m:
            posted_date = m.group(1)

    # Company target
    company = ""
    for sel in (
        "[class*='company-name']",
        "[class*='CompanyName']",
        "a[class*='company']",
        "[itemprop='name']",
    ):
        el = soup.select_one(sel)
        if el:
            company = _text(el)
            if company:
                break

    # Try __NEXT_DATA__ for cleaner fields
    nd = soup.find("script", id="__NEXT_DATA__")
    if nd and nd.string:
        try:
            blob = json.loads(nd.string)
            for hit in _walk_next_data_for_complaints(blob):
                if hit.get("title") and not title:
                    title = hit["title"]
                if hit.get("snippet") and len(hit["snippet"]) > len(body):
                    body = hit["snippet"]
                if hit.get("company") and not company:
                    company = hit["company"]
                break  # first hit on detail page is usually the page's complaint
        except Exception:
            pass

    return {
        "title": title,
        "body": body,
        "author": author,
        "status": status,
        "posted_date": posted_date,
        "company": company,
    }


# ---------------------------------------------------------------------------
# Per-keyword runner
# ---------------------------------------------------------------------------
def search_url(kw: str, page: int) -> str:
    base = SEARCH_URL.format(kw=quote_plus(kw))
    if page > 1:
        return f"{base}&pagina={page}"
    return base


def process_complaint(meta: dict, kw: str, state: State) -> bool:
    """Fetch detail, validate income/amount filter, emit jsonl. Returns True if written."""
    rid = meta["complaint_id"]
    our_id = make_id(PLATFORM, rid)
    if state.is_seen(our_id):
        return False

    detail_url = meta.get("url") or ""
    detail: dict = {}
    if detail_url:
        try:
            html = fetch_with_retry(detail_url)
        except ReclameError as e:
            print(f"  [{PLATFORM}] complaint {rid} err: {e}")
            state.mark_seen(our_id)
            return False
        detail = parse_complaint_detail(html)

    title = detail.get("title") or meta.get("title", "")
    body = detail.get("body") or meta.get("snippet", "")
    company = detail.get("company") or meta.get("company", "")

    # Income-signal filter: must contain an explicit money amount AND match
    # an on-topic token (Portuguese pt or generic). This is the key filter
    # that drops pure complaints with no income context.
    blob = " ".join([title, body])
    if not has_amount(blob):
        state.mark_seen(our_id)
        return False
    if not is_on_topic(title, body, lang="pt"):
        state.mark_seen(our_id)
        return False

    item = {
        "id": our_id,
        "raw_id": rid,
        "platform": PLATFORM,
        "lang": "pt",
        "country_hint": "BR",
        "kind": "complaint",
        "title": (title or "")[:300],
        "body": (body or "")[:5000],
        "author": detail.get("author", "")[:120],
        "company_target": company[:200],
        "status": detail.get("status", ""),
        "posted_date": detail.get("posted_date", ""),
        "url": detail_url or f"{BASE}/reclamacao/{rid}/",
        "matched_keyword": kw,
        "engagement": {"score": 0, "comments": 0, "views": None},
    }
    append_jsonl(item, PLATFORM, RAW_DIR)
    state.mark_seen(our_id)
    return True


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------
def run():
    state = State(PLATFORM)
    preload_seen(state, PLATFORM, key_field="id")
    budget = TimeBudget(PLATFORM_TIME_BUDGET_SEC)
    items_added = 0

    try:
        for kw in KEYWORDS:
            if budget.expired():
                print(f"[{PLATFORM}] time budget expired")
                break
            if state.is_kw_done(kw):
                continue
            if items_added >= PER_PLATFORM_LIMIT:
                break

            print(f"[{PLATFORM}] kw {kw!r}")
            start_page = state.get_cursor(kw, 1) or 1
            had_error = False

            for page in range(start_page, start_page + PAGES_PER_QUERY):
                if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                    break
                url = search_url(kw, page)
                try:
                    html = fetch_with_retry(url)
                except ReclameError as e:
                    print(f"  [{PLATFORM}] search {kw!r} p{page} err: {e}")
                    had_error = True
                    break

                hits = parse_search_results(html)
                if not hits:
                    break

                for meta in hits:
                    if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                        break
                    try:
                        if process_complaint(meta, kw, state):
                            items_added += 1
                            if items_added % 25 == 0:
                                print(f"  [{PLATFORM}] +{items_added} so far")
                    except ReclameError as e:
                        print(f"  [{PLATFORM}] process err: {e}")
                    state.maybe_save(every=10)
                    polite_sleep()

                state.set_cursor(kw, page + 1)
                polite_sleep()

            if not had_error:
                state.mark_kw_done(kw)
            state.save()
            polite_sleep()
    finally:
        state.save(force=True)

    print(f"[{PLATFORM}] done, +{items_added} items this run")


if __name__ == "__main__":
    run()
