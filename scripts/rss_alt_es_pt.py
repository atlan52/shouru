#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rss_alt_es_pt.py
================
ES (西语) + PT (葡语圈) 收入帖抓取，替代被反爬挡住的 rankia/infomoney。
走公开 RSS feed -> 关键词过滤 -> 抓正文 -> JSONL 输出。

用法（在主 agent 跑，不要在 sandbox 跑——sandbox 无网络）：
    .venv/bin/python scripts/rss_alt_es_pt.py
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# feedparser 优先；不在则用 bs4 xml 解析
try:
    import feedparser  # type: ignore
    HAS_FEEDPARSER = True
except Exception:
    HAS_FEEDPARSER = False


# -----------------------------------------------------------------------------
# 配置
# -----------------------------------------------------------------------------

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/rss+xml, application/xml, text/xml, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,pt-BR;q=0.8,pt;q=0.7,en;q=0.5",
}

TIMEOUT = 15
SLEEP_BETWEEN_ITEMS = 1.2  # 1.0–1.5 之间，礼貌
MAX_BODY = 5000

# ES 西语 feed
ES_FEEDS = [
    # (feed_name, feed_url, country_hint_default)
    ("elblogsalmon",       "https://www.elblogsalmon.com/index.xml",            "ES"),
    ("expansion",          "https://www.expansion.com/rss/portada.xml",         "ES"),
    ("eldiario",           "https://www.eldiario.es/rss/",                       "ES"),
    ("elpais_economia",    "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/economia/portada", "ES"),
    ("cincodias",          "https://cincodias.elpais.com/seccionrss/1000/portada", "ES"),
    ("invertirenbolsa",    "https://www.invertirenbolsa.info/rss.xml",          "ES"),
]

# PT 葡语圈 feed (BR / PT)
PT_FEEDS = [
    ("investidor10",       "https://www.investidor10.com.br/feed/",             "BR"),
    ("suno",               "https://www.suno.com.br/feed/",                     "BR"),
    ("valorinveste",       "https://valorinveste.globo.com/rss/feed.xml",       "BR"),
    ("exame",              "https://exame.com/feed/",                           "BR"),
    ("estadao_economia",   "https://www.estadao.com.br/economia/feed/",          "BR"),
    ("dinheirovivo",       "https://www.dinheirovivo.pt/feed/",                  "PT"),
    ("eco_sapo",           "https://eco.sapo.pt/feed/",                          "PT"),
]

# 关键词（小写匹配）
KW_ES = [
    "sueldo", "salario", "ganar ", "ingresos", "autónomo", "autonomo",
    "freelance", "jubilación", "jubilacion", "fire", "pensión", "pension",
    "nómina", "nomina", "renta", "trabajo", "programador sueldo",
    "médico salario", "medico salario", "ahorro", "ganancia", "cuánto gana",
    "cuanto gana", "cobra", "cobrar", "salario medio", "salario mínimo",
    "salario minimo",
]

KW_PT = [
    "salário", "salario", "ganhar", "renda", "mei ", " mei", "freelancer",
    "aposentadoria", "fire", "pensão", "pensao", "ordenado", "dividendos",
    "quanto ganha", "rendimento", "rendimentos", "remuneração", "remuneracao",
    "vencimento", "honorário", "honorario",
]


# -----------------------------------------------------------------------------
# 工具
# -----------------------------------------------------------------------------

def md5_16(*parts: str) -> str:
    h = hashlib.md5()
    for p in parts:
        h.update((p or "").encode("utf-8", errors="ignore"))
        h.update(b"\x1f")
    return h.hexdigest()[:16]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def country_hint_from_url(url: str, default: str) -> str:
    """从 URL 域名判断国家。.com.br -> BR; .pt -> PT; 其他 ES 默认 ES。"""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return default
    if host.endswith(".com.br") or host.endswith(".br"):
        return "BR"
    if host.endswith(".pt"):
        return "PT"
    if host.endswith(".mx") or host.endswith(".com.mx"):
        return "MX"
    if host.endswith(".ar") or host.endswith(".com.ar"):
        return "AR"
    if host.endswith(".cl") or host.endswith(".com.cl"):
        return "CL"
    return default


def match_keyword(text: str, kws: list[str]) -> str | None:
    """返回首个命中的关键词，否则 None。"""
    if not text:
        return None
    low = text.lower()
    for kw in kws:
        if kw in low:
            return kw.strip()
    return None


def strip_html(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml" if "lxml" in _available_parsers() else "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


_PARSER_CACHE: list[str] | None = None


def _available_parsers() -> list[str]:
    global _PARSER_CACHE
    if _PARSER_CACHE is not None:
        return _PARSER_CACHE
    parsers = ["html.parser"]
    try:
        import lxml  # noqa: F401
        parsers.insert(0, "lxml")
    except Exception:
        pass
    _PARSER_CACHE = parsers
    return parsers


# -----------------------------------------------------------------------------
# RSS 解析（feedparser 或 bs4 xml）
# -----------------------------------------------------------------------------

def fetch_feed(feed_url: str) -> list[dict]:
    """返回 [{title, summary, link, guid, author}, ...]，失败返回 []."""
    try:
        r = requests.get(feed_url, headers=HEADERS, timeout=TIMEOUT)
    except Exception as e:
        print(f"[FEED ERR] {feed_url}: {type(e).__name__}: {e}", file=sys.stderr)
        return []
    if r.status_code != 200:
        print(f"[FEED HTTP {r.status_code}] {feed_url}", file=sys.stderr)
        return []
    text = r.text

    items: list[dict] = []

    if HAS_FEEDPARSER:
        try:
            parsed = feedparser.parse(text)
            for ent in parsed.entries:
                items.append({
                    "title":   getattr(ent, "title", "") or "",
                    "summary": getattr(ent, "summary", "")
                              or getattr(ent, "description", "") or "",
                    "link":    getattr(ent, "link", "") or "",
                    "guid":    getattr(ent, "id", "") or getattr(ent, "guid", "") or "",
                    "author":  getattr(ent, "author", "") or "",
                })
            return items
        except Exception as e:
            print(f"[FEEDPARSER ERR] {feed_url}: {e}", file=sys.stderr)

    # fallback: bs4 xml
    try:
        soup = BeautifulSoup(text, "xml")
        # RSS 2.0
        for item in soup.find_all("item"):
            items.append({
                "title":   (item.title.get_text() if item.title else "").strip(),
                "summary": (item.description.get_text() if item.description else "").strip(),
                "link":    (item.link.get_text() if item.link else "").strip(),
                "guid":    (item.guid.get_text() if item.guid else "").strip(),
                "author":  (item.author.get_text() if item.author else "").strip(),
            })
        # Atom
        if not items:
            for entry in soup.find_all("entry"):
                link_tag = entry.find("link")
                link = ""
                if link_tag is not None:
                    link = link_tag.get("href", "") or link_tag.get_text() or ""
                items.append({
                    "title":   (entry.title.get_text() if entry.title else "").strip(),
                    "summary": (entry.summary.get_text() if entry.summary
                                else (entry.find("content").get_text()
                                      if entry.find("content") else "")).strip(),
                    "link":    link.strip(),
                    "guid":    (entry.id.get_text() if entry.id else "").strip(),
                    "author":  (entry.author.get_text() if entry.author else "").strip(),
                })
    except Exception as e:
        print(f"[XML PARSE ERR] {feed_url}: {e}", file=sys.stderr)
        return []

    return items


# -----------------------------------------------------------------------------
# 文章正文抓取
# -----------------------------------------------------------------------------

ARTICLE_SELECTORS = [
    "article",
    ".entry-content",
    ".post-content",
    ".article-body",
    ".article__content",
    ".article-content",
    ".content-article",
    ".td-post-content",
    "main article",
    ".story-body",
    ".post__content",
]


def fetch_article_body(url: str) -> str:
    if not url:
        return ""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    except Exception as e:
        print(f"[ART ERR] {url}: {type(e).__name__}", file=sys.stderr)
        return ""
    if r.status_code != 200:
        return ""

    parser = _available_parsers()[0]
    try:
        soup = BeautifulSoup(r.text, parser)
    except Exception:
        soup = BeautifulSoup(r.text, "html.parser")

    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
        tag.decompose()

    for sel in ARTICLE_SELECTORS:
        node = soup.select_one(sel)
        if node:
            text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
            if len(text) >= 200:
                return text

    # fallback：拼所有 <p>
    paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    paras = [p for p in paras if p and len(p) > 20]
    return re.sub(r"\s+", " ", " ".join(paras)).strip()


# -----------------------------------------------------------------------------
# 主流程
# -----------------------------------------------------------------------------

def crawl_feeds(
    feeds: list[tuple[str, str, str]],
    lang: str,
    keywords: list[str],
    out_path: str,
) -> tuple[int, dict]:
    """返回 (总写入行数, 每 feed 统计 dict)。"""
    stats: dict[str, dict] = {}
    total = 0

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(out_path, "a", encoding="utf-8") as fout:
        for feed_name, feed_url, default_country in feeds:
            stat = {"feed_url": feed_url, "items": 0, "matched": 0, "ok": 0, "reason": ""}
            stats[feed_name] = stat

            print(f"\n=== [{lang.upper()}] {feed_name} :: {feed_url} ===", flush=True)
            try:
                items = fetch_feed(feed_url)
            except Exception as e:
                stat["reason"] = f"fetch_feed crashed: {e}"
                print(f"[CRASH] {feed_name}: {e}", file=sys.stderr)
                traceback.print_exc()
                continue

            stat["items"] = len(items)
            if not items:
                stat["reason"] = stat["reason"] or "feed empty / blocked"
                continue

            for it in items:
                title = (it.get("title") or "").strip()
                summary_html = it.get("summary") or ""
                summary = strip_html(summary_html)
                link = (it.get("link") or "").strip()
                guid = (it.get("guid") or link).strip()
                author = (it.get("author") or "").strip()

                blob = f"{title}\n{summary}"
                kw = match_keyword(blob, keywords)
                if not kw:
                    continue
                stat["matched"] += 1

                # 抓正文
                body = ""
                if link:
                    try:
                        body = fetch_article_body(link)
                    except Exception as e:
                        print(f"[ART CRASH] {link}: {e}", file=sys.stderr)

                if not body:
                    body = summary  # 至少留 summary

                # body 太短就跳
                if len(body) < 80:
                    continue

                ch = country_hint_from_url(link or feed_url, default_country)
                rec = {
                    "id": md5_16(feed_url, guid or link or title),
                    "raw_id": guid or link,
                    "platform": f"rss_{feed_name}",
                    "lang": lang,
                    "title": title,
                    "body": body[:MAX_BODY],
                    "author": author,
                    "url": link,
                    "country_hint": ch,
                    "matched_keyword": kw,
                    "engagement": {"score": 0, "comments": 0, "views": None},
                    "crawled_at": now_iso(),
                }
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fout.flush()
                stat["ok"] += 1
                total += 1

                time.sleep(SLEEP_BETWEEN_ITEMS)

            if stat["ok"] == 0 and not stat["reason"]:
                if stat["matched"] == 0:
                    stat["reason"] = f"no kw match in {stat['items']} items"
                else:
                    stat["reason"] = f"matched {stat['matched']} but bodies too short / fetch failed"

    return total, stats


def main() -> int:
    day = today_str()
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw")
    es_out = os.path.join(base, f"rss_alt_es_native_{day}.jsonl")
    pt_out = os.path.join(base, f"rss_alt_pt_native_{day}.jsonl")

    print(f"[OUT ES] {es_out}")
    print(f"[OUT PT] {pt_out}")
    print(f"[FEEDPARSER] available={HAS_FEEDPARSER}")

    es_total, es_stats = crawl_feeds(ES_FEEDS, "es", KW_ES, es_out)
    pt_total, pt_stats = crawl_feeds(PT_FEEDS, "pt", KW_PT, pt_out)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    print(f"\n[ES] total written: {es_total}  -> {es_out}")
    for name, st in es_stats.items():
        print(f"  - {name:22s} items={st['items']:4d}  matched={st['matched']:3d}  "
              f"ok={st['ok']:3d}  reason={st['reason']}")

    print(f"\n[PT] total written: {pt_total}  -> {pt_out}")
    for name, st in pt_stats.items():
        print(f"  - {name:22s} items={st['items']:4d}  matched={st['matched']:3d}  "
              f"ok={st['ok']:3d}  reason={st['reason']}")

    grand = es_total + pt_total
    print(f"\n[GRAND TOTAL] {grand} rows  (ES={es_total}, PT={pt_total})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
