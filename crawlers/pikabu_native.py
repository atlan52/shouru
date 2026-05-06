"""Pikabu native crawler — inline requests + BS4, custom output filename.

Outputs JSONL to: data/raw/pikabu_native_<YYYYMMDD>.jsonl

Search URL: https://pikabu.ru/search?q=<kw>&D=0&n=2&t=2
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
OUT_PATH = os.path.join(OUT_DIR, f"pikabu_native_{DATESTR}.jsonl")

KEYWORDS = [
    "зарплата",
    "доход",
    "сколько зарабатываете",
    "пассивный доход",
    "фриланс доход",
    "подработка",
    "как заработать",
    "финансовая независимость",
    "удаленная работа доход",
    "бизнес доход",
]

POLITE = 1.5
TIMEOUT = 25
PER_KW_LIMIT = 10
TOTAL_LIMIT = 60


def _id(raw: str) -> str:
    return hashlib.md5(f"pikabu:{raw}".encode("utf-8")).hexdigest()


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
            print(f"  [pikabu_native] {url} -> HTTP {r.status_code}", flush=True)
        except Exception as e:
            print(f"  [pikabu_native] {url} -> {e}", flush=True)
        time.sleep(2.0)
    return None


_STORY_RE = re.compile(r"/story/([a-zA-Z0-9_\-]+)_(\d+)/?(?:[?#].*)?$")


def parse_search(html: str):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = _STORY_RE.search(href)
        if not m:
            continue
        slug, pid = m.group(1), m.group(2)
        if pid in seen:
            continue
        seen.add(pid)
        full = href if href.startswith("http") else urljoin("https://pikabu.ru", href.split("?")[0])
        out.append((full, pid, slug))
    return out


def parse_story(html: str):
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(" ", strip=True)
    if not title:
        og = soup.find("meta", attrs={"property": "og:title"})
        if og:
            title = og.get("content", "").strip()

    body_parts = []
    for sel in [".story-block_type_text", ".story__content-inner", ".story__main", "article"]:
        for el in soup.select(sel):
            t = el.get_text(" ", strip=True)
            if t and len(t) > 30:
                body_parts.append(t)
        if body_parts:
            break
    if not body_parts:
        og = soup.find("meta", attrs={"property": "og:description"})
        if og:
            body_parts.append(og.get("content", "").strip())
    body = _clean(" ".join(body_parts), 3000)

    author = ""
    a = soup.find("a", class_=re.compile(r"user__nick|story__user-link"))
    if a:
        author = a.get_text(" ", strip=True)
    if not author:
        m = soup.find("meta", attrs={"name": "author"})
        if m:
            author = m.get("content", "").strip()

    rating = None
    rt = soup.find(class_=re.compile(r"story__rating-count|story-rating__count"))
    if rt:
        try:
            rating = int(re.sub(r"[^\d-]", "", rt.get_text()) or "0")
        except Exception:
            rating = None

    comments = None
    cm = soup.find(class_=re.compile(r"story__comments-link-count|story__comments"))
    if cm:
        try:
            comments = int(re.sub(r"[^\d]", "", cm.get_text()) or "0")
        except Exception:
            comments = None

    return {"title": title, "body": body, "author": author,
            "rating": rating, "comments": comments}


def run():
    os.makedirs(OUT_DIR, exist_ok=True)
    rows = []
    seen_ids = set()
    print(f"[pikabu_native] writing -> {OUT_PATH}", flush=True)

    for kw in KEYWORDS:
        if len(rows) >= TOTAL_LIMIT:
            break
        url = f"https://pikabu.ru/search?q={quote(kw)}&D=0&n=2&t=2"
        print(f"[pikabu_native] kw='{kw}' -> {url}", flush=True)
        r = _get(url)
        time.sleep(POLITE)
        if not r:
            continue
        results = parse_search(r.text)
        print(f"  [pikabu_native] '{kw}' results: {len(results)}", flush=True)
        added_for_kw = 0
        for full, pid, slug in results:
            if added_for_kw >= PER_KW_LIMIT or len(rows) >= TOTAL_LIMIT:
                break
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            pr = _get(full)
            time.sleep(POLITE)
            if not pr:
                continue
            d = parse_story(pr.text)
            if not d["title"] and not d["body"]:
                continue
            rec = {
                "id": _id(pid),
                "raw_id": pid,
                "platform": "pikabu",
                "lang": "ru",
                "title": d["title"],
                "body": d["body"],
                "author": d["author"],
                "url": full,
                "country_hint": "RU",
                "matched_keyword": kw,
                "engagement": {
                    "score": d["rating"],
                    "comments": d["comments"],
                    "views": None,
                },
            }
            rows.append(rec)
            added_for_kw += 1

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[pikabu_native] done count={len(rows)} -> {OUT_PATH}", flush=True)


if __name__ == "__main__":
    run()
