"""Habr crawler — habr.com (articles + RSS) and career.habr.com (salaries).

Three intake paths:

  (a) https://career.habr.com/salaries — self-reported Russian-tech salary
      database. Each row is { role, experience, region, year, salary_rub,
      currency, gender, age }. We walk the public listing pages.

  (b) https://habr.com/ru/search/?q=<kw>&target_type=posts — articles
      search; for each Russian income keyword we paginate and pick up
      article cards (title, snippet, score, comments, author).

  (c) https://habr.com/ru/rss/all/all/?fl=ru — RSS feed fallback for
      broad coverage when search rate-limits us.

No auth. Pure requests + BS4 + feedparser.
Country = "RU" (career.habr.com salaries are dominated by RU but include
some BY/UA/KZ; we keep the RU default and let the LLM extractor decide).
"""
import re
import time
import requests
from urllib.parse import quote_plus, urljoin
from bs4 import BeautifulSoup
try:
    import feedparser
except ImportError:
    feedparser = None

from config import (
    INCOME_KEYWORDS, PER_PLATFORM_LIMIT, PAGES_PER_QUERY, RAW_DIR,
    PLATFORM_TIME_BUDGET_SEC,
)
from crawlers.common import (
    append_jsonl, make_id, is_on_topic, polite_sleep, preload_seen,
    default_headers, random_ua, TimeBudget,
)
from crawlers.state import State


PLATFORM = "habr"
HABR_BASE = "https://habr.com"
CAREER_BASE = "https://career.habr.com"
SALARIES_URL = CAREER_BASE + "/salaries"
SEARCH_URL = HABR_BASE + "/ru/search/?q={kw}&target_type=posts"
RSS_FEEDS = [
    "https://habr.com/ru/rss/all/all/?fl=ru",
    "https://habr.com/ru/rss/best/?fl=ru",
]

BOT_MARKERS = (
    "captcha", "проверка", "запрос заблокирован", "доступ ограничен",
    "are you a human", "access denied", "cf-browser-verification",
)


class HabrError(Exception):
    pass


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _headers() -> dict:
    h = default_headers(accept_lang="ru-RU,ru;q=0.9,en;q=0.6")
    h["User-Agent"] = random_ua()
    h["Referer"] = HABR_BASE + "/"
    return h


def fetch_html(url: str, timeout: int = 30) -> str:
    try:
        r = requests.get(url, headers=_headers(), timeout=timeout, allow_redirects=True)
    except Exception as e:
        raise HabrError(f"net err {url}: {e}")
    if r.status_code in (403, 429):
        raise HabrError(f"{r.status_code} on {url}")
    if r.status_code != 200:
        raise HabrError(f"status {r.status_code} on {url}")
    body = r.text or ""
    low = body.lower()
    if any(m in low for m in BOT_MARKERS):
        raise HabrError("bot-block / captcha")
    return body


def fetch_with_retry(url: str) -> str:
    try:
        return fetch_html(url)
    except HabrError as e:
        msg = str(e)
        if "403" in msg or "429" in msg:
            print(f"  [{PLATFORM}] backoff 30s on {url}")
            time.sleep(30)
            return fetch_html(url)
        raise


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
def _text_of(el) -> str:
    if not el:
        return ""
    return el.get_text(" ", strip=True)


def _parse_int(s: str) -> int:
    if not s:
        return 0
    s = s.replace("\xa0", "").replace(",", "").replace(" ", "").strip().lower()
    m = re.match(r"(-?[\d.]+)\s*([kкmм]?)", s)
    if not m:
        return 0
    try:
        v = float(m.group(1))
    except ValueError:
        return 0
    suf = m.group(2)
    if suf in ("k", "к"):
        v *= 1_000
    elif suf in ("m", "м"):
        v *= 1_000_000
    return int(v)


# ---------------------------------------------------------------------------
# (a) career.habr.com /salaries — self-reported salary rows
# ---------------------------------------------------------------------------
def parse_salaries_page(html: str):
    """Extract salary rows from the career.habr.com/salaries listing.

    Each row is a card with role title, experience tag, region, salary.
    Habr Career renders rows as `.salary_graph__row` or `tr` in older
    layouts; we sweep multiple selectors.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    cards = (soup.select(".salary_graph__row, .salary-graph__row, .salaries__row")
             or soup.select("tr.salaries-graph__row, tr[class*='salary']"))
    for c in cards:
        role = _text_of(c.select_one(".salary_graph__role, .role, [class*='role']"))
        if not role:
            tds = c.find_all("td")
            if tds:
                role = _text_of(tds[0])
        if not role:
            continue
        experience = _text_of(c.select_one("[class*='experience'], .experience"))
        region = _text_of(c.select_one("[class*='region'], .region, [class*='city']"))
        salary_text = _text_of(c.select_one("[class*='salary'], .salary"))
        salary_rub = _parse_int(salary_text)
        rows.append({
            "role": role,
            "experience": experience,
            "region": region,
            "salary_text": salary_text,
            "salary_rub": salary_rub,
        })
    return rows


def crawl_salaries(state: State, budget: TimeBudget, items_added_so_far: int) -> int:
    """Walk a few /salaries pages. Each unique row becomes a JSONL item."""
    added = 0
    label = "salaries:listing"
    if state.is_kw_done(label):
        return 0

    pages = max(1, min(PAGES_PER_QUERY, 3))
    start_page = state.get_cursor(label, 1) or 1
    had_error = False

    for page in range(start_page, start_page + pages):
        if budget.expired() or (items_added_so_far + added) >= PER_PLATFORM_LIMIT:
            break
        url = SALARIES_URL if page == 1 else f"{SALARIES_URL}?page={page}"
        try:
            html = fetch_with_retry(url)
        except HabrError as e:
            print(f"  [{PLATFORM}] salaries p{page} err: {e}")
            had_error = True
            break
        rows = parse_salaries_page(html)
        if not rows:
            break

        for row in rows:
            if budget.expired() or (items_added_so_far + added) >= PER_PLATFORM_LIMIT:
                break
            rid = f"{row['role']}|{row['experience']}|{row['region']}|{row['salary_text']}"
            our_id = make_id(PLATFORM, "salary", rid)
            if state.is_seen(our_id):
                continue
            title = f"{row['role']} — {row['region']} — {row['experience']}"
            body = (
                f"Роль: {row['role']}\n"
                f"Опыт: {row['experience']}\n"
                f"Регион: {row['region']}\n"
                f"Зарплата: {row['salary_text']} (RUB {row['salary_rub']})"
            )
            item = {
                "id": our_id,
                "raw_id": rid,
                "platform": PLATFORM,
                "subtype": "career_salary",
                "lang": "ru",
                "country_hint": "RU",
                "title": title,
                "body": body,
                "author": "",
                "url": SALARIES_URL,
                "engagement": {"score": 0, "comments": 0},
                "salary": {
                    "role": row["role"],
                    "experience": row["experience"],
                    "region": row["region"],
                    "salary_rub": row["salary_rub"],
                    "currency": "RUB",
                    "raw": row["salary_text"],
                },
                "matched_keyword": label,
            }
            append_jsonl(item, PLATFORM, RAW_DIR)
            state.mark_seen(our_id)
            added += 1
            state.maybe_save(every=10)

        state.set_cursor(label, page + 1)
        polite_sleep(1500, 2500)

    if not had_error:
        state.mark_kw_done(label)
    state.save()
    return added


# ---------------------------------------------------------------------------
# (b) habr.com search — articles
# ---------------------------------------------------------------------------
_ARTICLE_HREF_RE = re.compile(r"/ru/(?:articles|companies/[^/]+/articles|post)/(\d+)")


def parse_search_results(html: str):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()
    for art in soup.select("article.tm-articles-list__item, article"):
        a = (art.select_one("a.tm-title__link")
             or art.select_one("h2 a")
             or art.select_one("a[href*='/articles/']")
             or art.select_one("a[href*='/post/']"))
        if not a or not a.get("href"):
            continue
        href = a["href"]
        m = _ARTICLE_HREF_RE.search(href)
        if not m:
            continue
        rid = m.group(1)
        if rid in seen:
            continue
        seen.add(rid)
        title = _text_of(a)
        snippet = _text_of(art.select_one(".tm-article-body, .article-formatted-body, .tm-article-snippet"))
        author = _text_of(art.select_one("a.tm-user-info__username, .tm-user-info a"))
        score = 0
        sc = art.select_one(".tm-votes-meter__value, [class*='votes-meter__value']")
        if sc:
            score = _parse_int(_text_of(sc))
        comments = 0
        cm = art.select_one("[class*='comments'] [class*='counter'], a[href*='comments']")
        if cm:
            comments = _parse_int(_text_of(cm))
        url = href if href.startswith("http") else urljoin(HABR_BASE, href)
        out.append({
            "post_id": rid,
            "url": url,
            "title": title,
            "snippet": snippet,
            "author": author,
            "score": score,
            "comments": comments,
        })
    return out


def fetch_article_body(url: str) -> str:
    try:
        html = fetch_with_retry(url)
    except HabrError:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for sel in ("div.tm-article-body", "div.article-formatted-body",
                "div#post-content-body", "div.post__text"):
        el = soup.select_one(sel)
        if el:
            return _text_of(el)[:5000]
    return ""


def search_url(kw: str, page: int) -> str:
    base = SEARCH_URL.format(kw=quote_plus(kw))
    if page > 1:
        return f"{base}&page={page}"
    return base


def crawl_articles(state: State, budget: TimeBudget, items_added_so_far: int) -> int:
    added = 0
    pages = max(1, min(PAGES_PER_QUERY, 3))

    for kw in INCOME_KEYWORDS["ru"]:
        if budget.expired() or (items_added_so_far + added) >= PER_PLATFORM_LIMIT:
            break
        label = f"search:{kw}"
        if state.is_kw_done(label):
            continue

        print(f"[{PLATFORM}] search {kw}")
        start_page = state.get_cursor(label, 1) or 1
        had_error = False

        for page in range(start_page, start_page + pages):
            if budget.expired() or (items_added_so_far + added) >= PER_PLATFORM_LIMIT:
                break
            url = search_url(kw, page)
            try:
                html = fetch_with_retry(url)
            except HabrError as e:
                print(f"  [{PLATFORM}] {kw} p{page} err: {e}")
                had_error = True
                break

            hits = parse_search_results(html)
            if not hits:
                break

            for h in hits:
                if budget.expired() or (items_added_so_far + added) >= PER_PLATFORM_LIMIT:
                    break
                rid = h["post_id"]
                our_id = make_id(PLATFORM, "article", rid)
                if state.is_seen(our_id):
                    continue
                title = h["title"]
                body = h["snippet"]
                if len(body) < 300:
                    full = fetch_article_body(h["url"])
                    if full:
                        body = full
                    polite_sleep(1500, 2500)

                if not is_on_topic(title, body, lang="ru"):
                    state.mark_seen(our_id)
                    continue

                item = {
                    "id": our_id,
                    "raw_id": rid,
                    "platform": PLATFORM,
                    "subtype": "article",
                    "lang": "ru",
                    "country_hint": "RU",
                    "title": title,
                    "body": body[:5000],
                    "author": h["author"],
                    "url": h["url"],
                    "engagement": {
                        "score": h["score"],
                        "comments": h["comments"],
                    },
                    "matched_keyword": kw,
                }
                append_jsonl(item, PLATFORM, RAW_DIR)
                state.mark_seen(our_id)
                added += 1
                if (items_added_so_far + added) % 25 == 0:
                    print(f"  [{PLATFORM}] +{items_added_so_far + added} so far")
                state.maybe_save(every=10)

            state.set_cursor(label, page + 1)
            polite_sleep(1500, 2500)

        if not had_error:
            state.mark_kw_done(label)
        state.save()
        polite_sleep(1500, 2500)

    return added


# ---------------------------------------------------------------------------
# (c) RSS fallback
# ---------------------------------------------------------------------------
def crawl_rss(state: State, budget: TimeBudget, items_added_so_far: int) -> int:
    if feedparser is None:
        return 0
    added = 0
    for feed_url in RSS_FEEDS:
        if budget.expired() or (items_added_so_far + added) >= PER_PLATFORM_LIMIT:
            break
        label = f"rss:{feed_url}"
        if state.is_kw_done(label):
            continue
        print(f"[{PLATFORM}] rss {feed_url}")
        try:
            fp = feedparser.parse(feed_url, request_headers=_headers())
        except Exception as e:
            print(f"  [{PLATFORM}] rss err {feed_url}: {e}")
            continue
        for entry in (getattr(fp, "entries", []) or []):
            if budget.expired() or (items_added_so_far + added) >= PER_PLATFORM_LIMIT:
                break
            link = entry.get("link", "") or ""
            m = _ARTICLE_HREF_RE.search(link)
            rid = m.group(1) if m else (entry.get("id") or link)
            our_id = make_id(PLATFORM, "rss", rid)
            if state.is_seen(our_id):
                continue
            title = entry.get("title", "")
            summary = entry.get("summary", "") or entry.get("description", "")
            # Strip HTML from summary
            try:
                summary = BeautifulSoup(summary, "html.parser").get_text(" ", strip=True)
            except Exception:
                pass
            body = summary
            if len(body) < 300 and link:
                full = fetch_article_body(link)
                if full:
                    body = full
                polite_sleep(1500, 2500)
            if not is_on_topic(title, body, lang="ru"):
                state.mark_seen(our_id)
                continue
            author = ""
            if "author" in entry:
                author = entry.get("author", "")
            item = {
                "id": our_id,
                "raw_id": str(rid),
                "platform": PLATFORM,
                "subtype": "rss",
                "lang": "ru",
                "country_hint": "RU",
                "title": title,
                "body": body[:5000],
                "author": author,
                "url": link,
                "engagement": {"score": 0, "comments": 0},
                "matched_keyword": feed_url,
                "created_utc": entry.get("published"),
            }
            append_jsonl(item, PLATFORM, RAW_DIR)
            state.mark_seen(our_id)
            added += 1
            state.maybe_save(every=10)
        state.mark_kw_done(label)
        state.save()
        polite_sleep(1500, 2500)
    return added


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run():
    state = State(PLATFORM)
    preload_seen(state, PLATFORM, key_field="id")
    budget = TimeBudget(PLATFORM_TIME_BUDGET_SEC)
    items_added = 0

    try:
        # (a) salaries — small but high-signal numeric corpus
        try:
            items_added += crawl_salaries(state, budget, items_added)
        except Exception as e:
            print(f"[{PLATFORM}] salaries fatal: {e}")

        # (b) keyword article search
        if not budget.expired() and items_added < PER_PLATFORM_LIMIT:
            try:
                items_added += crawl_articles(state, budget, items_added)
            except Exception as e:
                print(f"[{PLATFORM}] articles fatal: {e}")

        # (c) RSS fallback
        if not budget.expired() and items_added < PER_PLATFORM_LIMIT:
            try:
                items_added += crawl_rss(state, budget, items_added)
            except Exception as e:
                print(f"[{PLATFORM}] rss fatal: {e}")
    finally:
        state.save(force=True)

    print(f"[{PLATFORM}] done, +{items_added} items this run")


if __name__ == "__main__":
    run()
