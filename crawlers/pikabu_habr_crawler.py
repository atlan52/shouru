#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Crawl Pikabu and Habr (RU) for Russian-language income-related posts."""
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

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
}

OUT_DIR = "/Users/jan/sen/code/spider/shouru/data/raw"
DATESTR = datetime.datetime.now().strftime("%Y%m%d")
PIKABU_OUT = os.path.join(OUT_DIR, f"pikabu_native_{DATESTR}.jsonl")
HABR_OUT = os.path.join(OUT_DIR, f"habr_native_{DATESTR}.jsonl")

PIKABU_KEYWORDS = [
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

HABR_KEYWORDS = [
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


def make_id(platform: str, raw_id: str) -> str:
    return hashlib.md5(f"{platform}:{raw_id}".encode("utf-8")).hexdigest()


def safe_get(url, **kw):
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, **kw)
            if r.status_code == 200 and r.text:
                return r
            sys.stderr.write(f"[WARN] {url} -> HTTP {r.status_code}\n")
        except Exception as e:
            sys.stderr.write(f"[ERR] {url} -> {e}\n")
        time.sleep(2.0)
    return None


def clean_text(s: str, limit: int = 3000) -> str:
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


# ---------------- PIKABU ----------------

def parse_pikabu_search(html: str):
    """Return list of (post_url, post_id, slug) extracted from search results."""
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()
    # Pikabu story links look like /story/<slug>_<numeric_id>
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"/story/([a-z0-9_\-]+)_(\d+)$", href)
        if not m:
            continue
        slug, pid = m.group(1), m.group(2)
        if pid in seen:
            continue
        seen.add(pid)
        full = href if href.startswith("http") else urljoin("https://pikabu.ru", href)
        results.append((full, pid, slug))
    return results


def parse_pikabu_post(html: str, url: str, pid: str):
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    h = soup.find("h1") or soup.find("meta", attrs={"property": "og:title"})
    if h:
        if h.name == "meta":
            title = h.get("content", "").strip()
        else:
            title = h.get_text(" ", strip=True)
    # Body: pikabu story bodies are inside divs with class containing "story-block" or "story__content-inner"
    body_parts = []
    for sel in [
        ".story__content-inner",
        ".story-block_type_text",
        ".story__content",
        "article",
    ]:
        for el in soup.select(sel):
            txt = el.get_text(" ", strip=True)
            if txt and len(txt) > 30:
                body_parts.append(txt)
        if body_parts:
            break
    if not body_parts:
        og = soup.find("meta", attrs={"property": "og:description"})
        if og:
            body_parts.append(og.get("content", "").strip())
    body = clean_text(" ".join(body_parts), 3000)

    author = ""
    a = soup.find("a", class_=re.compile(r"user__nick|story__user-link"))
    if a:
        author = a.get_text(" ", strip=True)
    else:
        m = soup.find("meta", attrs={"name": "author"})
        if m:
            author = m.get("content", "").strip()

    # Engagement: rating + comments
    rating = None
    comments = None
    rt = soup.find(class_=re.compile(r"story__rating-count|story-rating__count"))
    if rt:
        try:
            rating = int(re.sub(r"[^\d-]", "", rt.get_text()) or "0")
        except Exception:
            rating = None
    cm = soup.find(class_=re.compile(r"story__comments-link-count|story__comments"))
    if cm:
        try:
            comments = int(re.sub(r"[^\d]", "", cm.get_text()) or "0")
        except Exception:
            comments = None

    return {
        "title": title,
        "body": body,
        "author": author,
        "rating": rating,
        "comments": comments,
    }


def crawl_pikabu():
    rows = []
    seen_ids = set()
    for kw in PIKABU_KEYWORDS:
        url = f"https://pikabu.ru/search?q={quote(kw)}&D=0&n=2&t=2"
        sys.stderr.write(f"[PIKABU] search '{kw}' -> {url}\n")
        r = safe_get(url)
        time.sleep(POLITE)
        if not r:
            continue
        results = parse_pikabu_search(r.text)
        sys.stderr.write(f"[PIKABU] '{kw}' results: {len(results)}\n")
        # Take first up to 10 results per keyword
        for full, pid, slug in results[:10]:
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            pr = safe_get(full)
            time.sleep(POLITE)
            if not pr:
                continue
            data = parse_pikabu_post(pr.text, full, pid)
            if not data["title"] and not data["body"]:
                continue
            rec = {
                "id": make_id("pikabu", pid),
                "raw_id": pid,
                "platform": "pikabu",
                "lang": "ru",
                "title": data["title"],
                "body": data["body"],
                "author": data["author"],
                "url": full,
                "country_hint": "RU",
                "matched_keyword": kw,
                "engagement": {
                    "score": data["rating"],
                    "comments": data["comments"],
                    "views": None,
                },
            }
            rows.append(rec)
            if len(rows) >= 60:
                break
        if len(rows) >= 60:
            break
    return rows


# ---------------- HABR ----------------

def parse_habr_search(html: str):
    """Return list of (post_url, post_id) from habr.com search."""
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # article URLs: /ru/articles/<id>/ or /ru/companies/<x>/articles/<id>/ or /ru/post/<id>/
        m = re.search(r"/(?:articles|post)/(\d+)/?$", href)
        if not m:
            m = re.search(r"/ru/companies/[^/]+/articles/(\d+)/?$", href)
        if not m:
            continue
        pid = m.group(1)
        if pid in seen:
            continue
        seen.add(pid)
        full = href if href.startswith("http") else urljoin("https://habr.com", href)
        results.append((full, pid))
    return results


def parse_habr_post(html: str, url: str, pid: str):
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(" ", strip=True)
    if not title:
        m = soup.find("meta", attrs={"property": "og:title"})
        if m:
            title = m.get("content", "").strip()

    body = ""
    sel_candidates = [
        "div#post-content-body",
        "div.tm-article-body",
        "div.article-formatted-body",
        "div.tm-article-presenter__body",
    ]
    for sel in sel_candidates:
        el = soup.select_one(sel)
        if el:
            body = clean_text(el.get_text(" ", strip=True), 3000)
            if body:
                break
    if not body:
        og = soup.find("meta", attrs={"property": "og:description"})
        if og:
            body = clean_text(og.get("content", ""), 3000)

    author = ""
    a = soup.find("a", class_=re.compile(r"tm-user-info__username|user-info__nickname"))
    if a:
        author = a.get_text(" ", strip=True)
    if not author:
        m = soup.find("meta", attrs={"name": "author"})
        if m:
            author = m.get("content", "").strip()

    score = None
    comments = None
    views = None
    sc = soup.find(class_=re.compile(r"tm-votes-meter__value|voting-wjt__counter"))
    if sc:
        try:
            score = int(re.sub(r"[^\d-]", "", sc.get_text()) or "0")
        except Exception:
            score = None
    cm = soup.find(class_=re.compile(r"tm-article-comments-counter|comments-section__head-counter"))
    if cm:
        try:
            comments = int(re.sub(r"[^\d]", "", cm.get_text()) or "0")
        except Exception:
            comments = None
    vw = soup.find(class_=re.compile(r"tm-icon-counter__value"))
    if vw:
        t = vw.get_text(" ", strip=True)
        # Habr views may look like "12K"
        n = re.sub(r"[^\d.,KkКк]", "", t)
        try:
            if "K" in n.upper() or "К" in n:
                base = float(re.sub(r"[^\d.]", "", n) or "0")
                views = int(base * 1000)
            else:
                views = int(re.sub(r"[^\d]", "", n) or "0")
        except Exception:
            views = None

    return {
        "title": title,
        "body": body,
        "author": author,
        "score": score,
        "comments": comments,
        "views": views,
    }


def crawl_habr():
    rows = []
    seen_ids = set()
    for kw in HABR_KEYWORDS:
        url = f"https://habr.com/ru/search/?q={quote(kw)}&target_type=posts&order=relevance"
        sys.stderr.write(f"[HABR] search '{kw}' -> {url}\n")
        r = safe_get(url)
        time.sleep(POLITE)
        if not r:
            continue
        results = parse_habr_search(r.text)
        sys.stderr.write(f"[HABR] '{kw}' results: {len(results)}\n")
        for full, pid in results[:10]:
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            pr = safe_get(full)
            time.sleep(POLITE)
            if not pr:
                continue
            data = parse_habr_post(pr.text, full, pid)
            if not data["title"] and not data["body"]:
                continue
            rec = {
                "id": make_id("habr", pid),
                "raw_id": pid,
                "platform": "habr",
                "lang": "ru",
                "title": data["title"],
                "body": data["body"],
                "author": data["author"],
                "url": full,
                "country_hint": "RU",
                "matched_keyword": kw,
                "engagement": {
                    "score": data["score"],
                    "comments": data["comments"],
                    "views": data["views"],
                },
            }
            rows.append(rec)
            if len(rows) >= 50:
                break
        if len(rows) >= 50:
            break
    return rows


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    pikabu_rows = crawl_pikabu()
    habr_rows = crawl_habr()
    write_jsonl(PIKABU_OUT, pikabu_rows)
    write_jsonl(HABR_OUT, habr_rows)
    sys.stderr.write(f"[DONE] pikabu={len(pikabu_rows)} habr={len(habr_rows)}\n")
    print(json.dumps({"pikabu_count": len(pikabu_rows), "habr_count": len(habr_rows),
                      "pikabu_path": PIKABU_OUT, "habr_path": HABR_OUT}))


if __name__ == "__main__":
    main()
