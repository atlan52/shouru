"""Deep Russian-language income scraper across non-Reddit major RU sites.

Targets:
  1. Hh.ru          — vacancies (8 roles x 3 pages -> detail page)
  2. Banki.ru forum — phpBB-style finance threads (FID=24 loans, FID=43 income)
  3. Sravni.ru     — text/forum search
  4. VC.ru search   — startup/tech/finance media
  5. DTF.ru search  — gaming/tech media w/ salary topics
  6. Pikabu        — community/Финансы + community/IT-programmirovanie, 5 pages each
  7. Yandex.Q       — Q&A loves channel search

Common rules:
  - UA Chrome/124, Accept-Language ru-RU
  - polite 1.5s between requests
  - russian keyword filter on title+body for non-vacancy sites
  - skip 4xx/5xx; on cloudflare challenge in body -> retreat from that site
  - schema same as r_mexico_native_*: id/raw_id/platform/lang/title/body/
    author/url/country_hint/matched_keyword/engagement/...
  - one output file per source: data/raw/<source>_native_<YYYYMMDD>.jsonl

NOTE (subagent constraint): only writes the script, does NOT execute it.
The user will run it via `.venv/bin/python scripts/ru_deep.py`.
"""
import datetime
import hashlib
import html as html_mod
import json
import os
import re
import sys
import time
from urllib.parse import quote, quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

OUT_DIR = "/Users/jan/sen/code/spider/shouru/data/raw"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
TIMEOUT = 25
SLEEP = 1.5
TODAY = datetime.datetime.now().strftime("%Y%m%d")

# Russian keywords that strongly signal income / earning content.
# Used to filter post-level pages on free-text sites (banki.ru, vc.ru, dtf.ru,
# pikabu, yandex.q). hh.ru vacancies are accepted unconditionally because every
# job posting is by definition income data.
RU_KEYWORDS = [
    "зарплат",       # salary stem
    "доход",         # income stem
    "заработ",       # earn stem (заработок / зарабатываю / заработать)
    "оклад",         # base salary
    "фриланс",       # freelance
    "FIRE",
    "пенси",         # pension stem
    "накоплен",      # savings stem
    "инвести",       # invest stem
    "руб",           # ruble symbol-ish (часто пишут "150к руб")
    "тысяч",         # "тысяч рублей"
    "млн",           # millions
    "к/мес",         # k/month shorthand
]

KW_RE = re.compile("|".join(re.escape(k) for k in RU_KEYWORDS), re.IGNORECASE)


def headers(referer: str = "") -> dict:
    h = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
        "Cache-Control": "no-cache",
    }
    if referer:
        h["Referer"] = referer
    return h


def make_id(prefix: str, raw_id: str) -> str:
    return hashlib.md5(f"{prefix}:{raw_id}".encode("utf-8")).hexdigest()[:16]


def fetch(url: str, params: dict | None = None, referer: str = "",
          label: str = "", session: requests.Session | None = None) -> str | None:
    sess = session or requests
    try:
        r = sess.get(url, headers=headers(referer), params=params,
                     timeout=TIMEOUT, allow_redirects=True)
    except Exception as e:
        print(f"  [fetch] err {label}: {e}", file=sys.stderr)
        return None
    if r.status_code in (403, 429) or r.status_code >= 500:
        print(f"  [fetch] HARD status {r.status_code} {label} url={r.url}",
              file=sys.stderr)
        return None
    if r.status_code >= 400:
        print(f"  [fetch] status {r.status_code} {label} url={r.url}",
              file=sys.stderr)
        return None
    txt = r.text or ""
    # Cloudflare challenge fingerprints
    low = txt.lower()
    if ("cf-chl" in low or "checking your browser" in low
            or "challenge-platform" in low or "cf_chl_opt" in low):
        print(f"  [fetch] CLOUDFLARE detected {label} url={r.url}", file=sys.stderr)
        return None
    return txt


def first_line(s: str, limit: int = 120) -> str:
    return re.sub(r"\s+", " ", s).strip()[:limit]


def looks_relevant(title: str, body: str) -> bool:
    blob = f"{title}\n{body}"
    return bool(KW_RE.search(blob))


def write_record(out, rec: dict, seen: set) -> bool:
    rid = rec.get("id")
    if not rid or rid in seen:
        return False
    seen.add(rid)
    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
    out.flush()
    return True


# ---------------------------------------------------------------------------
# 1. Hh.ru — Russia's biggest job board
# ---------------------------------------------------------------------------

HH_ROLES = [
    "программист",
    "инженер",
    "врач",
    "учитель",
    "продавец",
    "бухгалтер",
    "дизайнер",
    "аналитик",
]
HH_PAGES = 3


def hh_parse_list(html: str) -> list[str]:
    """Return vacancy detail URLs from a list page."""
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    seen = set()
    for a in soup.select("a[data-qa=serp-item__title], a.serp-item__title, "
                         "a.bloko-link[href*='/vacancy/'], a[href*='/vacancy/']"):
        href = (a.get("href") or "").split("?")[0]
        m = re.search(r"/vacancy/(\d+)", href)
        if not m:
            continue
        vid = m.group(1)
        if vid in seen:
            continue
        seen.add(vid)
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = "https://hh.ru" + href
        urls.append(href)
    return urls


def hh_parse_vacancy(html: str, url: str, role: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    title_el = (soup.select_one("[data-qa=vacancy-title]")
                or soup.select_one("h1.vacancy-title")
                or soup.select_one("h1"))
    title = title_el.get_text(" ", strip=True) if title_el else ""

    salary_el = (soup.select_one("[data-qa=vacancy-salary]")
                 or soup.select_one("[data-qa=vacancy-salary-compensation-type-net]")
                 or soup.select_one(".vacancy-salary"))
    salary_text = salary_el.get_text(" ", strip=True) if salary_el else ""

    desc_el = (soup.select_one("[data-qa=vacancy-description]")
               or soup.select_one(".vacancy-description")
               or soup.select_one(".g-user-content"))
    desc_text = desc_el.get_text(" ", strip=True) if desc_el else ""

    company_el = (soup.select_one("[data-qa=vacancy-company-name]")
                  or soup.select_one("a[data-qa=vacancy-company-name]")
                  or soup.select_one(".vacancy-company-name"))
    company = company_el.get_text(" ", strip=True) if company_el else ""

    location_el = (soup.select_one("[data-qa=vacancy-view-location]")
                   or soup.select_one("[data-qa=vacancy-view-raw-address]"))
    location = location_el.get_text(" ", strip=True) if location_el else ""

    if not title:
        return None

    m = re.search(r"/vacancy/(\d+)", url)
    raw_id = m.group(1) if m else url
    body = " | ".join(x for x in [salary_text, location, desc_text] if x)

    return {
        "id": make_id("hh", raw_id),
        "raw_id": raw_id,
        "platform": "hh_ru",
        "lang": "ru",
        "title": title[:300],
        "body": body[:5000],
        "author": company[:200],
        "url": url,
        "country_hint": "RU",
        "matched_keyword": role,
        "engagement": {
            "score": None,
            "comments": None,
            "views": None,
        },
        "salary_text": salary_text[:300],
        "location": location[:200],
        "crawled_at": datetime.datetime.utcnow().isoformat() + "+00:00",
    }


def crawl_hh(out, seen: set) -> int:
    added = 0
    sess = requests.Session()
    sess.headers.update(headers("https://hh.ru/"))
    for role in HH_ROLES:
        role_added = 0
        for page in range(0, HH_PAGES):  # hh uses 0-indexed page param
            label = f"hh.ru list role={role!r} p{page}"
            print(f"[hh] {label}", flush=True)
            html = fetch(
                "https://hh.ru/search/vacancy",
                params={"text": role, "page": page, "L_save_area": "true"},
                referer="https://hh.ru/",
                label=label,
                session=sess,
            )
            if not html:
                time.sleep(SLEEP)
                continue
            urls = hh_parse_list(html)
            if not urls and page == 0:
                sys.stderr.write(f"  [hh] PAGE LOOKS LIKE: {first_line(html)}\n")
                sys.stderr.write("  [hh] HTML[:800]>>>\n" + html[:800] + "\n<<<\n")
                sys.stderr.flush()
            print(f"  -> {len(urls)} vacancy urls", flush=True)
            for vurl in urls:
                time.sleep(SLEEP)
                vhtml = fetch(vurl, referer="https://hh.ru/search/vacancy",
                              label=f"hh detail {vurl[-25:]}", session=sess)
                if not vhtml:
                    continue
                rec = hh_parse_vacancy(vhtml, vurl, role)
                if not rec:
                    continue
                if write_record(out, rec, seen):
                    added += 1
                    role_added += 1
            time.sleep(SLEEP)
        print(f"  [hh] role={role} added {role_added} (total {added})", flush=True)
    return added


# ---------------------------------------------------------------------------
# 2. Banki.ru forum
# ---------------------------------------------------------------------------

BANKI_FIDS = [
    ("24", "loans"),     # Кредиты
    ("43", "income"),    # Зарплата / доходы (если активен)
]
BANKI_PAGES = 5


def banki_parse_list(html: str) -> list[tuple[str, str]]:
    """Return (thread_url, thread_title) from FID list."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, str]] = []
    seen = set()
    for a in soup.select("a[href*='PAGE_NAME=read'][href*='TID=']"):
        href = a.get("href") or ""
        m = re.search(r"TID=(\d+)", href)
        if not m:
            continue
        tid = m.group(1)
        if tid in seen:
            continue
        seen.add(tid)
        title = a.get_text(" ", strip=True)
        if href.startswith("/"):
            href = "https://www.banki.ru" + href
        elif not href.startswith("http"):
            href = urljoin("https://www.banki.ru/forum/", href)
        out.append((href, title))
    return out


def banki_parse_thread(html: str, url: str, fid_label: str,
                       list_title: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    title_el = (soup.select_one("h1")
                or soup.select_one(".forum-thread-title")
                or soup.select_one(".content-title"))
    title = (title_el.get_text(" ", strip=True) if title_el else list_title)[:300]

    msgs = soup.select(".forum-message, .b-forum-message__text, "
                       ".forum-post__message, .forum-post-text")
    if not msgs:
        # fallback: any block plausibly the OP body
        msgs = soup.select(".forum-thread__post-message, .forum-thread__post")
    body_text = ""
    if msgs:
        body_text = msgs[0].get_text(" ", strip=True)
    if not body_text:
        # last resort: meta description
        md = soup.select_one("meta[name=description]")
        if md:
            body_text = md.get("content") or ""

    if not title and not body_text:
        return None

    m = re.search(r"TID=(\d+)", url)
    raw_id = m.group(1) if m else url

    if not looks_relevant(title, body_text):
        return None

    return {
        "id": make_id("banki", raw_id),
        "raw_id": raw_id,
        "platform": "banki_ru_forum",
        "lang": "ru",
        "title": title,
        "body": body_text[:5000],
        "author": "",
        "url": url,
        "country_hint": "RU",
        "matched_keyword": f"FID={fid_label}",
        "engagement": {"score": None, "comments": None, "views": None},
        "crawled_at": datetime.datetime.utcnow().isoformat() + "+00:00",
    }


def crawl_banki(out, seen: set) -> int:
    added = 0
    sess = requests.Session()
    for fid, label in BANKI_FIDS:
        for page in range(1, BANKI_PAGES + 1):
            list_label = f"banki.ru FID={fid} ({label}) p{page}"
            print(f"[banki] {list_label}", flush=True)
            html = fetch(
                "https://www.banki.ru/forum/",
                params={"PAGE_NAME": "list", "FID": fid, "PAGEN_1": page},
                referer="https://www.banki.ru/forum/",
                label=list_label,
                session=sess,
            )
            if not html:
                time.sleep(SLEEP)
                continue
            threads = banki_parse_list(html)
            if not threads and page == 1:
                sys.stderr.write(f"  [banki] PAGE LOOKS LIKE: {first_line(html)}\n")
                sys.stderr.write("  [banki] HTML[:800]>>>\n" + html[:800] + "\n<<<\n")
                sys.stderr.flush()
            print(f"  -> {len(threads)} threads", flush=True)
            for turl, ttitle in threads:
                time.sleep(SLEEP)
                thtml = fetch(turl,
                              referer="https://www.banki.ru/forum/",
                              label=f"banki thread {turl[-25:]}",
                              session=sess)
                if not thtml:
                    continue
                rec = banki_parse_thread(thtml, turl, label, ttitle)
                if not rec:
                    continue
                if write_record(out, rec, seen):
                    added += 1
            time.sleep(SLEEP)
        print(f"  [banki] FID={fid} cumulative {added}", flush=True)
    return added


# ---------------------------------------------------------------------------
# 3. Sravni.ru forum (text/forum). Best-effort -- if redirect or 404, skip.
# ---------------------------------------------------------------------------

SRAVNI_PAGES = 3


def sravni_parse_list(html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[tuple[str, str]] = []
    seen = set()
    # Generic: any anchor pointing into forum thread that has /text/forum/<slug>
    for a in soup.select("a[href*='/text/forum/'], a[href*='/forum/thread/'], "
                         "a[href*='/q/']"):
        href = a.get("href") or ""
        if href.startswith("/"):
            href = "https://www.sravni.ru" + href
        elif not href.startswith("http"):
            continue
        # filter out the index URL itself
        if href.rstrip("/") in ("https://www.sravni.ru/text/forum",
                                "https://www.sravni.ru/forum"):
            continue
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 8:
            continue
        if href in seen:
            continue
        seen.add(href)
        items.append((href, title))
    return items


def sravni_parse_thread(html: str, url: str, list_title: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("h1")
    title = (title_el.get_text(" ", strip=True) if title_el else list_title)[:300]
    body_el = (soup.select_one("article")
               or soup.select_one(".question-body")
               or soup.select_one("[class*='QuestionBody']")
               or soup.select_one("main"))
    body = body_el.get_text(" ", strip=True)[:5000] if body_el else ""
    if not body:
        md = soup.select_one("meta[name=description]")
        if md:
            body = (md.get("content") or "")[:5000]
    if not title and not body:
        return None
    if not looks_relevant(title, body):
        return None
    raw_id = url
    return {
        "id": make_id("sravni", raw_id),
        "raw_id": raw_id,
        "platform": "sravni_forum",
        "lang": "ru",
        "title": title,
        "body": body,
        "author": "",
        "url": url,
        "country_hint": "RU",
        "matched_keyword": "sravni_forum",
        "engagement": {"score": None, "comments": None, "views": None},
        "crawled_at": datetime.datetime.utcnow().isoformat() + "+00:00",
    }


def crawl_sravni(out, seen: set) -> int:
    added = 0
    sess = requests.Session()
    base_urls = [
        "https://www.sravni.ru/text/forum/",
        "https://www.sravni.ru/forum/",
    ]
    for base in base_urls:
        for page in range(1, SRAVNI_PAGES + 1):
            label = f"sravni list {base} p{page}"
            print(f"[sravni] {label}", flush=True)
            params = {"page": page} if page > 1 else None
            html = fetch(base, params=params, referer="https://www.sravni.ru/",
                         label=label, session=sess)
            if not html:
                time.sleep(SLEEP)
                continue
            threads = sravni_parse_list(html)
            if not threads and page == 1:
                sys.stderr.write(f"  [sravni] PAGE LOOKS LIKE: {first_line(html)}\n")
                sys.stderr.write("  [sravni] HTML[:600]>>>\n" + html[:600] + "\n<<<\n")
                sys.stderr.flush()
            print(f"  -> {len(threads)} threads", flush=True)
            for turl, ttitle in threads[:25]:  # cap per page
                time.sleep(SLEEP)
                thtml = fetch(turl, referer=base,
                              label=f"sravni thread {turl[-25:]}", session=sess)
                if not thtml:
                    continue
                rec = sravni_parse_thread(thtml, turl, ttitle)
                if not rec:
                    continue
                if write_record(out, rec, seen):
                    added += 1
            time.sleep(SLEEP)
            if not threads and page == 1:
                break
    return added


# ---------------------------------------------------------------------------
# 4. VC.ru search
# ---------------------------------------------------------------------------

VC_QUERIES = ["зарплата", "доход", "заработок", "фриланс", "пенсия"]
VC_PAGES = 3


def vc_parse_list(html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[tuple[str, str]] = []
    seen = set()
    for a in soup.select("a.content-link, a.feed__content__link, a[href*='vc.ru/'], "
                         "a[href^='/']"):
        href = a.get("href") or ""
        if not href:
            continue
        if href.startswith("/"):
            href = "https://vc.ru" + href
        if not href.startswith("https://vc.ru/"):
            continue
        if not re.search(r"/\d+-", href):  # vc article URLs end in -id pattern
            continue
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 10:
            continue
        if href in seen:
            continue
        seen.add(href)
        items.append((href, title))
    return items


def vc_parse_article(html: str, url: str, list_title: str, kw: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("h1") or soup.select_one(".content-title")
    title = (title_el.get_text(" ", strip=True) if title_el else list_title)[:300]
    body_el = (soup.select_one(".content--full")
               or soup.select_one(".l-island-a")
               or soup.select_one("article")
               or soup.select_one("[class*='content--']"))
    body = body_el.get_text(" ", strip=True)[:5000] if body_el else ""
    if not body:
        md = soup.select_one("meta[name=description]")
        if md:
            body = (md.get("content") or "")[:5000]
    if not title and not body:
        return None
    if not looks_relevant(title, body):
        return None
    m = re.search(r"/(\d+)-", url)
    raw_id = m.group(1) if m else url
    return {
        "id": make_id("vc", raw_id),
        "raw_id": raw_id,
        "platform": "vc_ru",
        "lang": "ru",
        "title": title,
        "body": body,
        "author": "",
        "url": url,
        "country_hint": "RU",
        "matched_keyword": kw,
        "engagement": {"score": None, "comments": None, "views": None},
        "crawled_at": datetime.datetime.utcnow().isoformat() + "+00:00",
    }


def crawl_vc(out, seen: set) -> int:
    added = 0
    sess = requests.Session()
    for q in VC_QUERIES:
        for page in range(1, VC_PAGES + 1):
            label = f"vc.ru q={q!r} p{page}"
            print(f"[vc] {label}", flush=True)
            params = {"q": q}
            if page > 1:
                params["page"] = page
            html = fetch("https://vc.ru/search/v2/content",
                         params=params, referer="https://vc.ru/",
                         label=label, session=sess)
            if not html:
                # fallback: legacy search URL
                html = fetch("https://vc.ru/search",
                             params=params, referer="https://vc.ru/",
                             label=label + " (fallback)", session=sess)
            if not html:
                time.sleep(SLEEP)
                continue
            articles = vc_parse_list(html)
            if not articles and page == 1:
                sys.stderr.write(f"  [vc] PAGE LOOKS LIKE: {first_line(html)}\n")
                sys.stderr.write("  [vc] HTML[:600]>>>\n" + html[:600] + "\n<<<\n")
                sys.stderr.flush()
            print(f"  -> {len(articles)} articles", flush=True)
            for aurl, atitle in articles[:30]:
                time.sleep(SLEEP)
                ahtml = fetch(aurl, referer=f"https://vc.ru/search?q={quote(q)}",
                              label=f"vc article {aurl[-25:]}", session=sess)
                if not ahtml:
                    continue
                rec = vc_parse_article(ahtml, aurl, atitle, q)
                if not rec:
                    continue
                if write_record(out, rec, seen):
                    added += 1
            time.sleep(SLEEP)
            if not articles and page == 1:
                break
    return added


# ---------------------------------------------------------------------------
# 5. DTF.ru search
# ---------------------------------------------------------------------------

DTF_QUERIES = ["зарплата", "доход", "заработок", "фриланс"]
DTF_PAGES = 3


def dtf_parse_list(html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[tuple[str, str]] = []
    seen = set()
    for a in soup.select("a[href*='dtf.ru/'], a[href^='/']"):
        href = a.get("href") or ""
        if href.startswith("/"):
            href = "https://dtf.ru" + href
        if not href.startswith("https://dtf.ru/"):
            continue
        if not re.search(r"/\d+-", href):
            continue
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 10:
            continue
        if href in seen:
            continue
        seen.add(href)
        items.append((href, title))
    return items


def dtf_parse_article(html: str, url: str, list_title: str, kw: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("h1") or soup.select_one(".content-title")
    title = (title_el.get_text(" ", strip=True) if title_el else list_title)[:300]
    body_el = (soup.select_one(".content--full")
               or soup.select_one("article")
               or soup.select_one("[class*='content--']"))
    body = body_el.get_text(" ", strip=True)[:5000] if body_el else ""
    if not body:
        md = soup.select_one("meta[name=description]")
        if md:
            body = (md.get("content") or "")[:5000]
    if not title and not body:
        return None
    if not looks_relevant(title, body):
        return None
    m = re.search(r"/(\d+)-", url)
    raw_id = m.group(1) if m else url
    return {
        "id": make_id("dtf", raw_id),
        "raw_id": raw_id,
        "platform": "dtf_ru",
        "lang": "ru",
        "title": title,
        "body": body,
        "author": "",
        "url": url,
        "country_hint": "RU",
        "matched_keyword": kw,
        "engagement": {"score": None, "comments": None, "views": None},
        "crawled_at": datetime.datetime.utcnow().isoformat() + "+00:00",
    }


def crawl_dtf(out, seen: set) -> int:
    added = 0
    sess = requests.Session()
    for q in DTF_QUERIES:
        for page in range(1, DTF_PAGES + 1):
            label = f"dtf.ru q={q!r} p{page}"
            print(f"[dtf] {label}", flush=True)
            # `/search/+<q>` or `/search?q=<q>` -- try both
            html = fetch(f"https://dtf.ru/search/+{quote(q)}",
                         params={"page": page} if page > 1 else None,
                         referer="https://dtf.ru/", label=label, session=sess)
            if not html:
                html = fetch("https://dtf.ru/search",
                             params={"q": q, "page": page} if page > 1 else {"q": q},
                             referer="https://dtf.ru/",
                             label=label + " (fallback)", session=sess)
            if not html:
                time.sleep(SLEEP)
                continue
            articles = dtf_parse_list(html)
            if not articles and page == 1:
                sys.stderr.write(f"  [dtf] PAGE LOOKS LIKE: {first_line(html)}\n")
                sys.stderr.write("  [dtf] HTML[:600]>>>\n" + html[:600] + "\n<<<\n")
                sys.stderr.flush()
            print(f"  -> {len(articles)} articles", flush=True)
            for aurl, atitle in articles[:30]:
                time.sleep(SLEEP)
                ahtml = fetch(aurl, referer=f"https://dtf.ru/search/+{quote(q)}",
                              label=f"dtf article {aurl[-25:]}", session=sess)
                if not ahtml:
                    continue
                rec = dtf_parse_article(ahtml, aurl, atitle, q)
                if not rec:
                    continue
                if write_record(out, rec, seen):
                    added += 1
            time.sleep(SLEEP)
            if not articles and page == 1:
                break
    return added


# ---------------------------------------------------------------------------
# 6. Pikabu communities (deeper sweep)
# ---------------------------------------------------------------------------

PIKABU_COMMUNITIES = ["Финансы", "IT-programmirovanie"]
PIKABU_PAGES = 5


def pikabu_parse_stories(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    stories = []
    seen_ids = set()
    candidates = (soup.select("article.story") + soup.select("article[data-story-id]")
                  + soup.select("div.story") + soup.select("[data-story-id]"))
    for s in candidates:
        if id(s) in seen_ids:
            continue
        seen_ids.add(id(s))
        title_el = (s.select_one("a.story__title-link")
                    or s.select_one("h2.story__title a")
                    or s.select_one("h2 a"))
        if not title_el:
            continue
        url = (title_el.get("href") or "").strip()
        title = title_el.get_text(" ", strip=True)
        if not url or not title:
            continue
        if not url.startswith("http"):
            url = "https://pikabu.ru" + url
        sid = s.get("data-story-id") or ""
        if not sid:
            m = re.search(r"/story/[^/?#]+_(\d+)", url)
            if m:
                sid = m.group(1)
        if not sid:
            sid = url
        body_el = (s.select_one(".story-block_type_text")
                   or s.select_one(".story__content-block"))
        body = body_el.get_text(" ", strip=True) if body_el else ""
        author_el = s.select_one(".user__nick") or s.select_one("a.user")
        author = author_el.get_text(strip=True) if author_el else ""
        rating = 0
        rating_el = s.select_one(".story__rating-count")
        if rating_el:
            mt = re.search(r"-?\d+", rating_el.get_text(" ", strip=True))
            if mt:
                try:
                    rating = int(mt.group(0))
                except ValueError:
                    pass
        comments = 0
        comments_el = s.select_one(".story__comments-link-count")
        if comments_el:
            mc = re.search(r"\d+", comments_el.get_text(" ", strip=True))
            if mc:
                try:
                    comments = int(mc.group(0))
                except ValueError:
                    pass
        stories.append({
            "raw_id": str(sid),
            "url": url,
            "title": title,
            "body": body,
            "author": author,
            "rating": rating,
            "comments": comments,
        })
    return stories


def crawl_pikabu(out, seen: set) -> int:
    added = 0
    sess = requests.Session()
    for slug in PIKABU_COMMUNITIES:
        base = "https://pikabu.ru/community/" + quote_plus(slug, safe="-_")
        for page in range(1, PIKABU_PAGES + 1):
            label = f"pikabu community={slug} p{page}"
            print(f"[pikabu_deep] {label}", flush=True)
            html = fetch(base,
                         params={"page": page} if page > 1 else None,
                         referer="https://pikabu.ru/",
                         label=label, session=sess)
            if not html:
                time.sleep(SLEEP)
                continue
            stories = pikabu_parse_stories(html)
            if not stories and page == 1:
                sys.stderr.write(f"  [pikabu_deep] PAGE LOOKS LIKE: {first_line(html)}\n")
                sys.stderr.write("  [pikabu_deep] HTML[:600]>>>\n" + html[:600] + "\n<<<\n")
                sys.stderr.flush()
            kept = 0
            for s in stories:
                if not looks_relevant(s["title"], s["body"]):
                    continue
                rec = {
                    "id": make_id("pikabu_deep", s["raw_id"]),
                    "raw_id": s["raw_id"],
                    "platform": "pikabu_finance",
                    "lang": "ru",
                    "title": s["title"][:300],
                    "body": s["body"][:5000],
                    "author": s["author"],
                    "url": s["url"],
                    "country_hint": "RU",
                    "matched_keyword": f"community:{slug}",
                    "engagement": {
                        "score": int(s["rating"]),
                        "comments": int(s["comments"]),
                        "views": None,
                    },
                    "crawled_at": datetime.datetime.utcnow().isoformat() + "+00:00",
                }
                if write_record(out, rec, seen):
                    added += 1
                    kept += 1
            print(f"  -> stories={len(stories)} kept_relevant={kept} (total {added})",
                  flush=True)
            time.sleep(SLEEP)
            if not stories and page == 1:
                break
    return added


# ---------------------------------------------------------------------------
# 7. Yandex.Q deep retry
# ---------------------------------------------------------------------------

YQ_QUERIES = ["зарплата", "доход", "заработок", "фриланс", "пенсия", "оклад"]
YQ_PAGES = 3


def yq_parse_list(html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[tuple[str, str]] = []
    seen_local = set()
    # yandex.q renders cards via JS but URLs sometimes leak via SSR
    for a in soup.select("a[href*='/q/question/'], a[href*='/q/loves/'], "
                         "a[href*='yandex.ru/q/']"):
        href = a.get("href") or ""
        if not href.startswith("http"):
            href = urljoin("https://yandex.ru", href)
        if "/q/question/" not in href and "/q/loves/" not in href:
            continue
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 8:
            continue
        if href in seen_local:
            continue
        seen_local.add(href)
        items.append((href, title))
    return items


def yq_parse_question(html: str, url: str, list_title: str, kw: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("h1") or soup.select_one("[class*='QuestionTitle']")
    title = (title_el.get_text(" ", strip=True) if title_el else list_title)[:300]
    body_el = (soup.select_one("[class*='QuestionBody']")
               or soup.select_one("[class*='question-body']")
               or soup.select_one("main"))
    body = body_el.get_text(" ", strip=True)[:5000] if body_el else ""
    if not body:
        md = soup.select_one("meta[name=description]")
        if md:
            body = (md.get("content") or "")[:5000]
    if not title and not body:
        return None
    if not looks_relevant(title, body):
        return None
    m = re.search(r"/q/[^/]+/([\w-]+)", url)
    raw_id = m.group(1) if m else url
    return {
        "id": make_id("yq", raw_id),
        "raw_id": raw_id,
        "platform": "yandex_q_deep",
        "lang": "ru",
        "title": title,
        "body": body,
        "author": "",
        "url": url,
        "country_hint": "RU",
        "matched_keyword": kw,
        "engagement": {"score": None, "comments": None, "views": None},
        "crawled_at": datetime.datetime.utcnow().isoformat() + "+00:00",
    }


def crawl_yandex_q(out, seen: set) -> int:
    added = 0
    sess = requests.Session()
    for q in YQ_QUERIES:
        for page in range(1, YQ_PAGES + 1):
            label = f"yandex.q q={q!r} p{page}"
            print(f"[yq] {label}", flush=True)
            params = {"lr": "213", "type": "question", "search": q}
            if page > 1:
                params["p"] = page
            html = fetch("https://yandex.ru/q/loves/",
                         params=params, referer="https://yandex.ru/q/",
                         label=label, session=sess)
            if not html:
                time.sleep(SLEEP)
                continue
            qs = yq_parse_list(html)
            if not qs and page == 1:
                sys.stderr.write(f"  [yq] PAGE LOOKS LIKE: {first_line(html)}\n")
                sys.stderr.write("  [yq] HTML[:600]>>>\n" + html[:600] + "\n<<<\n")
                sys.stderr.flush()
            print(f"  -> {len(qs)} questions", flush=True)
            for qurl, qtitle in qs[:25]:
                time.sleep(SLEEP)
                qhtml = fetch(qurl, referer="https://yandex.ru/q/",
                              label=f"yq question {qurl[-25:]}", session=sess)
                if not qhtml:
                    continue
                rec = yq_parse_question(qhtml, qurl, qtitle, q)
                if not rec:
                    continue
                if write_record(out, rec, seen):
                    added += 1
            time.sleep(SLEEP)
            if not qs and page == 1:
                break
    return added


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

SOURCES = [
    ("hh_ru_deep",       crawl_hh),
    ("banki_ru_forum",   crawl_banki),
    ("sravni_forum",     crawl_sravni),
    ("vc_ru_search",     crawl_vc),
    ("dtf_search",       crawl_dtf),
    ("pikabu_finance",   crawl_pikabu),
    ("yandex_q_deep",    crawl_yandex_q),
]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    summary: list[tuple[str, int, str]] = []
    for name, crawler in SOURCES:
        out_path = os.path.join(OUT_DIR, f"{name}_native_{TODAY}.jsonl")
        seen: set[str] = set()
        n = 0
        try:
            with open(out_path, "w", encoding="utf-8") as out:
                n = crawler(out, seen)
        except Exception as e:
            print(f"[{name}] CRASH: {e}", file=sys.stderr)
        # count file lines
        actual = 0
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                for _ in f:
                    actual += 1
        except FileNotFoundError:
            pass
        print(f"[{name}] DONE added={n} file_lines={actual} -> {out_path}",
              flush=True)
        summary.append((name, actual, out_path))

    # Final summary
    print("\n=== ru_deep summary ===", flush=True)
    grand = 0
    for name, n, path in summary:
        grand += n
        print(f"  {name:18s}  lines={n:5d}  {path}")
    print(f"  TOTAL_LINES = {grand}")


if __name__ == "__main__":
    main()
