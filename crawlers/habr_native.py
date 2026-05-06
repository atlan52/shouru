"""Habr native crawler — inline requests + BS4, custom output filename.

Outputs JSONL to: data/raw/habr_native_<YYYYMMDD>.jsonl

Search URL: https://habr.com/ru/search/?q=<kw>&target_type=posts
Polite 1.5s. Accept-Language: ru-RU,ru;q=0.9.
"""
from __future__ import annotations

import os
import re
import sys
import json
import time
import hashlib
import datetime
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup


UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

OUT_DIR = "/Users/jan/sen/code/spider/shouru/data/raw"
DATESTR = datetime.datetime.now().strftime("%Y%m%d")
OUT_PATH = os.path.join(OUT_DIR, f"habr_native_{DATESTR}.jsonl")

KEYWORDS = [
    "зарплата",
    "доход",
    "сколько зарабатываете",
    "пассивный доход",
    "фриланс доход",
    "программист зарплата",
    "разработчик зарплата",
    "инженер зарплата",
    "менеджер зарплата",
    "аналитик зарплата",
]

POLITE = 1.5
TIMEOUT = 25
PER_KW_LIMIT = 10
TOTAL_LIMIT = 50


def _id(raw: str) -> str:
    return hashlib.md5(f"habr:{raw}".encode("utf-8")).hexdigest()


def _clean(s: str, lim: int = 3000) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()[:lim]


def _get(url: str):
    for _ in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code == 200 and r.text:
                return r
            print(f"  [habr_native] {url} -> HTTP {r.status_code}", flush=True)
        except Exception as e:
            print(f"  [habr_native] {url} -> {e}", flush=True)
        time.sleep(2.0)
    return None


_ARTICLE_RES = [
    re.compile(r"/(?:articles|post)/(\d+)/?$"),
    re.compile(r"/ru/companies/[^/]+/articles/(\d+)/?$"),
    re.compile(r"/ru/(?:articles|post)/(\d+)/?$"),
]


def parse_search(html: str):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].split("#")[0].split("?")[0]
        pid = None
        for rgx in _ARTICLE_RES:
            m = rgx.search(href)
            if m:
                pid = m.group(1)
                break
        if not pid:
            continue
        if pid in seen:
            continue
        seen.add(pid)
        full = href if href.startswith("http") else urljoin("https://habr.com", href)
        out.append((full, pid))
    return out


def _to_int(s: str):
    if not s:
        return None
    s = s.strip().replace("\xa0", "").replace(",", ".")
    m = re.match(r"(-?[\d.]+)\s*([KkКк]?)", s)
    if not m:
        return None
    try:
        v = float(m.group(1))
    except Exception:
        return None
    if m.group(2) in ("K", "k", "К", "к"):
        v *= 1000
    return int(v)


def parse_post(html: str):
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(" ", strip=True)
    if not title:
        og = soup.find("meta", attrs={"property": "og:title"})
        if og:
            title = og.get("content", "").strip()

    body = ""
    for sel in [
        "div#post-content-body",
        "div.tm-article-body",
        "div.article-formatted-body",
        "div.tm-article-presenter__body",
        "article",
    ]:
        el = soup.select_one(sel)
        if el:
            body = _clean(el.get_text(" ", strip=True), 3000)
            if body:
                break
    if not body:
        og = soup.find("meta", attrs={"property": "og:description"})
        if og:
            body = _clean(og.get("content", ""), 3000)

    author = ""
    a = soup.find("a", class_=re.compile(r"tm-user-info__username|user-info__nickname|tm-user-card__username"))
    if a:
        author = a.get_text(" ", strip=True)
    if not author:
        m = soup.find("meta", attrs={"name": "author"})
        if m:
            author = m.get("content", "").strip()

    score = None
    sc = soup.find(class_=re.compile(r"tm-votes-meter__value|voting-wjt__counter|tm-votes-lever__score-counter"))
    if sc:
        score = _to_int(sc.get_text(" ", strip=True))

    comments = None
    cm = soup.find(class_=re.compile(r"tm-article-comments-counter|comments-section__head-counter|tm-article-comments-counter-link__value"))
    if cm:
        comments = _to_int(cm.get_text(" ", strip=True))

    views = None
    vw = soup.find(class_=re.compile(r"tm-icon-counter__value"))
    if vw:
        views = _to_int(vw.get_text(" ", strip=True))

    return {
        "title": title,
        "body": body,
        "author": author,
        "score": score,
        "comments": comments,
        "views": views,
    }


def run():
    os.makedirs(OUT_DIR, exist_ok=True)
    rows = []
    seen_ids = set()
    print(f"[habr_native] writing -> {OUT_PATH}", flush=True)

    for kw in KEYWORDS:
        if len(rows) >= TOTAL_LIMIT:
            break
        url = f"https://habr.com/ru/search/?q={quote(kw)}&target_type=posts&order=relevance"
        print(f"[habr_native] kw='{kw}' -> {url}", flush=True)
        r = _get(url)
        time.sleep(POLITE)
        if not r:
            continue
        results = parse_search(r.text)
        print(f"  [habr_native] '{kw}' results: {len(results)}", flush=True)
        added = 0
        for full, pid in results:
            if added >= PER_KW_LIMIT or len(rows) >= TOTAL_LIMIT:
                break
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            pr = _get(full)
            time.sleep(POLITE)
            if not pr:
                continue
            d = parse_post(pr.text)
            if not d["title"] and not d["body"]:
                continue
            rec = {
                "id": _id(pid),
                "raw_id": pid,
                "platform": "habr",
                "lang": "ru",
                "title": d["title"],
                "body": d["body"],
                "author": d["author"],
                "url": full,
                "country_hint": "RU",
                "matched_keyword": kw,
                "engagement": {
                    "score": d["score"],
                    "comments": d["comments"],
                    "views": d["views"],
                },
            }
            rows.append(rec)
            added += 1

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[habr_native] done count={len(rows)} -> {OUT_PATH}", flush=True)


if __name__ == "__main__":
    run()
