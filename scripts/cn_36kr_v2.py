"""36氪 (36kr.com) — Chinese income-related articles scraper, v2.

v1 failure: the gateway POST `https://gateway.36kr.com/api/mis/nav/search/resultbytype`
with `partner_id="web"` returned `{"code":..., "msg":"站点id为空"}`. The real web
client uses a different partner_id (likely tied to a signed token + traceId),
so we drop the search-API path entirely.

v2 strategy — *multiple* fallbacks, in order. Each one is cumulative; we keep
collecting until we hit the target or run out of options. Goal: 25+ items.

  STRATEGY 1 — SSR HTML for the public search page (verified 200):
      https://www.36kr.com/search/articles/<keyword>
    Try to pull JSON out of:
      - <script id="__NUXT_DATA__"> ... </script>     (current Nuxt 3 marker)
      - window.initialState = "..."                    (legacy Vue state)
      - <script id="__NEXT_DATA__"> ... </script>      (just in case)
    For Nuxt-style payloads, the Chinese text is sometimes UTF-8-escaped or
    base64-ish; fall back to a regex sweep over the raw HTML for article-id
    patterns plus title/abstract strings.

  STRATEGY 2 — Information board listings (server-rendered):
      https://www.36kr.com/information/web_zhichang/   (职场)
      https://www.36kr.com/information/web_finance/    (创投/金融)
      https://www.36kr.com/information/web_news/       (general feed)
      https://www.36kr.com/                            (homepage)
    Pull article ids/links/titles, then fetch each article page
    `https://www.36kr.com/p/<id>` and extract title+body. Filter the union
    of (title+body) by the income keyword regex.

  STRATEGY 3 — last-resort gateway probes (cheap, single call each, just so
  we surface their actual error if anything ever changes):
      https://api.36kr.com/v2/search/article?q=<kw>
      https://gateway.36kr.com/api/mis/wave/search/article?searchWord=<kw>

Polite pacing: ~1.5s between requests. UA: Chrome/124. Accept-Language: zh-CN.

Output:  data/raw/36kr_native_<YYYYMMDD>.jsonl
Schema:
  {"id":..., "raw_id":"<article-id>", "platform":"36kr",
   "lang":"zh", "title":..., "body":..., "author":..., "url":...,
   "country_hint":"CN", "matched_keyword":...,
   "engagement":{"score":..., "comments":..., "views":...}}
"""
import datetime
import hashlib
import html as html_mod
import json
import os
import re
import sys
import time
from urllib.parse import quote

import requests

OUT_DIR = "/Users/jan/sen/code/spider/shouru/data/raw"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")
TIMEOUT = 25
SLEEP = 1.5
TARGET_TOTAL = 25

KEYWORDS = [
    "月入十万", "月入5万", "副业收入", "财务自由", "我的收入构成",
    "年薪百万", "互联网大厂工资", "创业收入", "自由职业收入", "月入过万",
]

# Income-related Chinese tokens for STRATEGY 2 filter (title OR body must hit
# at least one). Kept loose on purpose; downstream pipelines do strict scoring.
INCOME_REGEX = re.compile(
    r"(月入|年薪|年收|年收入|月收入|工资|薪水|薪资|收入|赚到|挣到|"
    r"副业|外快|兼职|自由职业|创业|大厂|百万|过万|十万|五万|"
    r"财务自由|睡后收入|被动收入|月薪|时薪|提成|奖金)"
)

INFORMATION_BOARDS = [
    ("zhichang", "https://www.36kr.com/information/web_zhichang/"),
    ("finance",  "https://www.36kr.com/information/web_finance/"),
    ("news",     "https://www.36kr.com/information/web_news/"),
]

HOMEPAGE = "https://www.36kr.com/"

# Cap on STRATEGY-2 article-detail fetches to keep the run bounded.
MAX_DETAIL_FETCHES = 80


def headers(referer: str = "https://www.36kr.com/") -> dict:
    return {
        "User-Agent": UA,
        "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "image/avif,image/webp,*/*;q=0.8"),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
        "Referer": referer,
        "Cache-Control": "no-cache",
    }


def make_id(raw_id: str) -> str:
    return hashlib.md5(("36kr:" + str(raw_id)).encode("utf-8")).hexdigest()[:16]


def fetch(url: str, label: str = "", referer: str | None = None) -> str | None:
    try:
        r = requests.get(url, headers=headers(referer or "https://www.36kr.com/"),
                         timeout=TIMEOUT)
    except Exception as e:
        print(f"  [36kr] fetch err {label}: {e}", file=sys.stderr)
        return None
    if r.status_code != 200:
        print(f"  [36kr] status {r.status_code} {label} url={r.url}",
              file=sys.stderr)
        return None
    # 36kr serves UTF-8; force it.
    r.encoding = "utf-8"
    return r.text


def _strip_tags(s: str) -> str:
    s = re.sub(r"<script[^>]*>.*?</script>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<style[^>]*>.*?</style>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_mod.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _decode_unicode_escapes(s: str) -> str:
    """Turn `\\u6708\\u5165` literal escape sequences into real chars.
    Safe on already-decoded text (no-op)."""
    if "\\u" not in s:
        return s
    try:
        return s.encode("utf-8").decode("unicode_escape")
    except Exception:
        return s


# ---------------------------------------------------------------------------
# STRATEGY 1: search SSR
# ---------------------------------------------------------------------------

# Article id patterns on 36kr:
#   /p/3001234567   (numeric, 9-10 digits)
#   /p/2342345      (numeric, older)
#   "itemId":"3001234567"
#   "id":"3001234567"  inside JSON blobs
ARTICLE_ID_REGEX = re.compile(r'/p/(\d{6,12})')
ITEM_ID_JSON_REGEX = re.compile(r'"itemId"\s*:\s*"?(\d{6,12})"?')


def _extract_nuxt_payload(html: str) -> str | None:
    m = re.search(
        r'<script[^>]+id="__NUXT_DATA__"[^>]*>(.*?)</script>',
        html, flags=re.S)
    if m:
        return m.group(1)
    m = re.search(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html, flags=re.S)
    if m:
        return m.group(1)
    m = re.search(
        r'window\.initialState\s*=\s*(?:"|`)(.*?)(?:"|`)\s*[;<]',
        html, flags=re.S)
    if m:
        return m.group(1)
    m = re.search(
        r'window\.__NUXT__\s*=\s*(\{.*?\});\s*</script>',
        html, flags=re.S)
    if m:
        return m.group(1)
    return None


def parse_search_html(html: str, kw: str) -> list[dict]:
    """Best-effort: pull article ids + nearby title/abstract strings out of
    whatever serialized payload the page embeds. Falls back to plain link
    extraction when JSON is unrecoverable."""
    items: list[dict] = []
    seen_ids: set[str] = set()

    # 1) Try to find structured JSON.
    payload = _extract_nuxt_payload(html)
    if payload:
        decoded = _decode_unicode_escapes(payload)
        # Iterate over rough article objects: any block keyed by an itemId
        # adjacent to a title/widgetTitle string.
        # Typical Nuxt 3 payload is a big array; we don't try to fully parse
        # it (the structure is heavily compressed) — instead we sweep with
        # regex.
        # Pattern: "itemId":"<id>", ..., "widgetTitle":"<title>" within ~2000 chars
        # (keep it bounded so we don't cross article boundaries).
        for m in ITEM_ID_JSON_REGEX.finditer(decoded):
            aid = m.group(1)
            if aid in seen_ids:
                continue
            window_text = decoded[m.start(): m.start() + 2500]
            title_m = (re.search(r'"widgetTitle"\s*:\s*"([^"]{2,200})"', window_text)
                       or re.search(r'"title"\s*:\s*"([^"]{2,200})"', window_text)
                       or re.search(r'"articleTitle"\s*:\s*"([^"]{2,200})"', window_text))
            body_m = (re.search(r'"widgetContent"\s*:\s*"([^"]{2,3000})"', window_text)
                      or re.search(r'"summary"\s*:\s*"([^"]{2,3000})"', window_text)
                      or re.search(r'"description"\s*:\s*"([^"]{2,3000})"', window_text))
            author_m = (re.search(r'"authorName"\s*:\s*"([^"]{1,80})"', window_text)
                        or re.search(r'"author"\s*:\s*"([^"]{1,80})"', window_text))
            pv_m = re.search(r'"statRead"\s*:\s*"?(\d+)"?', window_text)
            cmt_m = re.search(r'"statComment"\s*:\s*"?(\d+)"?', window_text)

            if not title_m:
                continue
            title = _decode_unicode_escapes(title_m.group(1)).strip()
            body = _decode_unicode_escapes(body_m.group(1)).strip() if body_m else ""
            author = _decode_unicode_escapes(author_m.group(1)).strip() if author_m else ""
            views = int(pv_m.group(1)) if pv_m else 0
            comments = int(cmt_m.group(1)) if cmt_m else 0
            seen_ids.add(aid)
            items.append({
                "raw_id": aid,
                "title": title[:300],
                "body": body[:3000],
                "author": author,
                "url": f"https://www.36kr.com/p/{aid}",
                "matched_keyword": kw,
                "engagement": {"score": 0, "comments": comments, "views": views},
            })

    # 2) Fallback: bare URL sweep over the whole HTML.
    for m in ARTICLE_ID_REGEX.finditer(html):
        aid = m.group(1)
        if aid in seen_ids:
            continue
        # Walk back ~400 chars from the link to find a nearby title-ish
        # string. SSR pages often render an <a ...>title</a>.
        start = max(0, m.start() - 600)
        ctx = html[start: m.end() + 300]
        # title: anchor text adjacent to the matched URL
        title_m = re.search(
            r'<a[^>]+href="[^"]*?/p/' + aid + r'"[^>]*>([^<]{4,200})</a>',
            ctx, flags=re.I)
        if not title_m:
            continue
        title = _strip_tags(title_m.group(1)).strip()
        if not title:
            continue
        seen_ids.add(aid)
        items.append({
            "raw_id": aid,
            "title": title[:300],
            "body": "",
            "author": "",
            "url": f"https://www.36kr.com/p/{aid}",
            "matched_keyword": kw,
            "engagement": {"score": 0, "comments": 0, "views": 0},
        })

    return items


def crawl_search(out, seen_ids: set) -> int:
    added = 0
    for kw in KEYWORDS:
        url = f"https://www.36kr.com/search/articles/{quote(kw)}"
        label = f"search kw={kw!r}"
        print(f"[36kr] {label}", flush=True)
        html = fetch(url, label=label)
        if not html:
            time.sleep(SLEEP)
            continue
        entries = parse_search_html(html, kw)
        if not entries:
            payload_present = _extract_nuxt_payload(html) is not None
            print(
                f"  [36kr] PAGE LOOKS LIKE: payload_marker={payload_present} "
                f"len={len(html)} first200={_strip_tags(html[:1500])[:200]!r}",
                file=sys.stderr,
            )
        new_here = 0
        for it in entries:
            obj = _to_record(it)
            if obj["id"] in seen_ids:
                continue
            seen_ids.add(obj["id"])
            out.write(json.dumps(obj, ensure_ascii=False) + "\n")
            out.flush()
            added += 1
            new_here += 1
        print(f"  -> parsed {len(entries)}, new_this_kw {new_here}, "
              f"total {added}", flush=True)
        time.sleep(SLEEP)
    return added


def _to_record(it: dict) -> dict:
    raw = it["raw_id"]
    return {
        "id": make_id(raw),
        "raw_id": str(raw),
        "platform": "36kr",
        "lang": "zh",
        "title": it.get("title", "")[:300],
        "body": it.get("body", "")[:3000],
        "author": it.get("author", ""),
        "url": it.get("url", f"https://www.36kr.com/p/{raw}"),
        "country_hint": "CN",
        "matched_keyword": it.get("matched_keyword", ""),
        "engagement": {
            "score": int((it.get("engagement") or {}).get("score") or 0),
            "comments": int((it.get("engagement") or {}).get("comments") or 0),
            "views": int((it.get("engagement") or {}).get("views") or 0),
        },
    }


# ---------------------------------------------------------------------------
# STRATEGY 2: information boards + article-detail fetch
# ---------------------------------------------------------------------------

def _harvest_article_links(html: str) -> list[tuple[str, str]]:
    """Return (article_id, anchor_text) tuples."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in re.finditer(
        r'<a[^>]+href="(?:https?://www\.36kr\.com)?/p/(\d{6,12})[^"]*"[^>]*>([^<]{2,200})</a>',
        html, flags=re.I,
    ):
        aid, anchor = m.group(1), _strip_tags(m.group(2)).strip()
        if not anchor or aid in seen:
            continue
        seen.add(aid)
        out.append((aid, anchor))
    return out


def parse_article_page(html: str) -> dict:
    """Pull title + body + author out of an article detail page."""
    # title
    title = ""
    m = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]{2,300})"',
                  html, flags=re.I)
    if m:
        title = html_mod.unescape(m.group(1)).strip()
    if not title:
        m = re.search(r'<title>([^<]{2,300})</title>', html, flags=re.I)
        if m:
            title = html_mod.unescape(m.group(1)).strip()
            # Strip "_36氪" suffix if present
            title = re.sub(r"\s*[-_|]+\s*36(?:氪|kr).*$", "", title, flags=re.I)

    # body — prefer og:description; else summary; else strip article container
    body = ""
    m = re.search(
        r'<meta[^>]+property="og:description"[^>]+content="([^"]{2,3000})"',
        html, flags=re.I)
    if m:
        body = html_mod.unescape(m.group(1)).strip()
    if not body:
        m = re.search(
            r'<meta[^>]+name="description"[^>]+content="([^"]{2,3000})"',
            html, flags=re.I)
        if m:
            body = html_mod.unescape(m.group(1)).strip()
    if not body:
        # Last resort: pluck the article body container.
        m = re.search(
            r'<div[^>]+class="[^"]*articleDetailContent[^"]*"[^>]*>(.*?)</div>\s*<div[^>]+class="[^"]*article-bottom',
            html, flags=re.S | re.I)
        if not m:
            m = re.search(
                r'<div[^>]+class="[^"]*common-width[^"]*content[^"]*"[^>]*>(.*?)</div>',
                html, flags=re.S | re.I)
        if m:
            body = _strip_tags(m.group(1))[:3000]

    # author
    author = ""
    m = (re.search(r'"authorName"\s*:\s*"([^"]{1,80})"', html)
         or re.search(r'<meta[^>]+name="author"[^>]+content="([^"]{1,120})"',
                      html, flags=re.I))
    if m:
        author = html_mod.unescape(m.group(1)).strip()

    # views/comments — best effort from embedded payload
    views = 0
    comments = 0
    m = re.search(r'"statRead"\s*:\s*"?(\d+)"?', html)
    if m:
        try:
            views = int(m.group(1))
        except ValueError:
            pass
    m = re.search(r'"statComment"\s*:\s*"?(\d+)"?', html)
    if m:
        try:
            comments = int(m.group(1))
        except ValueError:
            pass

    return {
        "title": title,
        "body": body,
        "author": author,
        "engagement": {"score": 0, "comments": comments, "views": views},
    }


def crawl_boards(out, seen_ids: set, budget: int) -> int:
    """Strategy 2 loop. Stops once we exhaust budget OR hit MAX_DETAIL_FETCHES.
    Filters article-detail by INCOME_REGEX over (title + body)."""
    added = 0
    detail_fetches = 0
    candidates: list[tuple[str, str, str]] = []  # (board, aid, anchor)

    pages_to_try: list[tuple[str, str]] = [("home", HOMEPAGE)]
    for slug, url in INFORMATION_BOARDS:
        pages_to_try.append((slug, url))

    for board, list_url in pages_to_try:
        label = f"board:{board}"
        print(f"[36kr] {label}", flush=True)
        html = fetch(list_url, label=label)
        if not html:
            time.sleep(SLEEP)
            continue
        links = _harvest_article_links(html)
        print(f"  -> {len(links)} article links found on {board}", flush=True)
        for aid, anchor in links:
            candidates.append((board, aid, anchor))
        time.sleep(SLEEP)

    # Dedup candidates by aid; preserve first-seen order.
    dedup: list[tuple[str, str, str]] = []
    seen_aid: set[str] = set()
    for board, aid, anchor in candidates:
        if aid in seen_aid:
            continue
        seen_aid.add(aid)
        dedup.append((board, aid, anchor))
    print(f"[36kr] board-stage: {len(dedup)} unique candidate articles",
          flush=True)

    # Pre-filter by anchor text — saves detail fetches for articles whose
    # title alone can already match. Anything where the anchor *might*
    # be income-related, fetch the detail page and re-check against body.
    for board, aid, anchor in dedup:
        if added >= budget:
            print(f"[36kr] hit budget={budget}, stop board scan", flush=True)
            break
        if detail_fetches >= MAX_DETAIL_FETCHES:
            print(f"[36kr] hit detail-fetch cap={MAX_DETAIL_FETCHES}, stop",
                  flush=True)
            break

        rid = make_id(aid)
        if rid in seen_ids:
            continue

        anchor_hits = bool(INCOME_REGEX.search(anchor))
        url = f"https://www.36kr.com/p/{aid}"

        # Heuristic: if anchor doesn't match, only fetch detail with a small
        # probability — but since we have a lot of budget left, fetch
        # liberally up to MAX_DETAIL_FETCHES. The income-regex applied to
        # detail body/title will still gate insertion.
        page = fetch(url, label=f"detail aid={aid}", referer=HOMEPAGE)
        detail_fetches += 1
        time.sleep(SLEEP)
        if not page:
            continue
        info = parse_article_page(page)
        title = info.get("title") or anchor
        body = info.get("body", "")
        text_blob = (title + " " + body)
        if not (anchor_hits or INCOME_REGEX.search(text_blob)):
            continue

        # Pick the matched keyword that actually appears (best effort).
        matched_kw = ""
        for kw in KEYWORDS:
            if kw in text_blob:
                matched_kw = kw
                break
        if not matched_kw:
            matched_kw = f"board:{board}"

        rec = _to_record({
            "raw_id": aid,
            "title": title,
            "body": body,
            "author": info.get("author", ""),
            "url": url,
            "matched_keyword": matched_kw,
            "engagement": info.get("engagement", {}),
        })
        if rec["id"] in seen_ids:
            continue
        seen_ids.add(rec["id"])
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out.flush()
        added += 1
        print(f"  + [{added}/{budget}] kept aid={aid} kw={matched_kw} "
              f"title={title[:60]!r}", flush=True)

    print(f"[36kr] boards added={added} (detail_fetches={detail_fetches})",
          flush=True)
    return added


# ---------------------------------------------------------------------------
# STRATEGY 3: gateway probes (just diagnostic)
# ---------------------------------------------------------------------------

def probe_gateways() -> None:
    probes = [
        ("api.36kr.com/v2",
         "https://api.36kr.com/v2/search/article?q=" + quote("月入十万")),
        ("gateway.wave",
         "https://gateway.36kr.com/api/mis/wave/search/article?searchWord="
         + quote("月入十万")),
    ]
    for label, url in probes:
        try:
            r = requests.get(url, headers=headers(), timeout=TIMEOUT)
            snippet = (r.text or "")[:200].replace("\n", " ")
            print(f"[36kr] probe {label} status={r.status_code} body={snippet!r}")
        except Exception as e:
            print(f"[36kr] probe {label} err: {e}")
        time.sleep(SLEEP)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    today = datetime.datetime.now().strftime("%Y%m%d")
    out_path = os.path.join(OUT_DIR, f"36kr_native_{today}.jsonl")

    seen_ids: set[str] = set()
    # Resume support: pre-load any ids already on disk so re-runs append
    # rather than dup. Open append-mode.
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    seen_ids.add(json.loads(line)["id"])
                except Exception:
                    pass
        print(f"[36kr] resume: {len(seen_ids)} ids already in {out_path}")

    n_search = 0
    n_boards = 0
    with open(out_path, "a", encoding="utf-8") as out:
        # STRATEGY 1
        n_search = crawl_search(out, seen_ids)
        # STRATEGY 2 — top up to TARGET_TOTAL
        deficit = max(0, TARGET_TOTAL - (len(seen_ids)))
        # If we haven't hit target, run boards with a generous budget.
        budget = max(deficit, 30)
        n_boards = crawl_boards(out, seen_ids, budget=budget)

    # STRATEGY 3: diagnostic probes (cheap, don't write to file)
    print("[36kr] gateway probes (diagnostic only):")
    probe_gateways()

    total_added = n_search + n_boards
    print(f"[36kr] DONE added_this_run={total_added} "
          f"(search={n_search}, boards={n_boards}) file={out_path}")

    # Final stats: line count + 5 Chinese samples
    line_count = 0
    samples: list[dict] = []
    with open(out_path, "r", encoding="utf-8") as f:
        for line in f:
            line_count += 1
            if len(samples) < 5:
                try:
                    samples.append(json.loads(line))
                except Exception:
                    pass
    print(f"[36kr] LINES IN FILE: {line_count}")
    print("[36kr] SAMPLES:")
    for s in samples:
        eng = s.get("engagement") or {}
        print(
            f"  - {s.get('title','')[:90]}  "
            f"[views={eng.get('views')}, comments={eng.get('comments')}]  "
            f"kw={s.get('matched_keyword','')}  {s.get('url','')}"
        )


if __name__ == "__main__":
    main()
