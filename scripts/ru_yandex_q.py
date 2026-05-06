"""Yandex Q (yandex.ru/q) — 俄语 income 问答直接 HTML 抓取。

入口：https://yandex.ru/q/search?key=<keyword>
跟进每个 question URL → 拿全文 + top1 答案文本。
"""
import json, hashlib, re, time, random, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, quote
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HDR = {
    "User-Agent": UA,
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
DAY = datetime.now().strftime("%Y%m%d")
OUT = Path(f"data/raw/yandex_q_native_{DAY}.jsonl")
BASE = "https://yandex.ru"
SEARCH = "https://yandex.ru/q/search"

KEYWORDS = [
    "зарплата",
    "доход",
    "сколько зарабатываете",
    "фриланс",
    "удаленная работа сколько",
    "IT зарплата",
    "разработчик зарплата",
    "бизнес доход",
]


def md5_16(*p): return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]
def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def polite(): time.sleep(random.uniform(1.2, 1.8))


def load_seen():
    seen = set()
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            try:
                seen.add(json.loads(line)["id"])
            except Exception:
                pass
    return seen


# ---------- search page parsing ----------

QUESTION_HREF_RE = re.compile(r"/q/question/[A-Za-z0-9_\-а-яА-Я%]+")
QUESTION_ID_RE = re.compile(r"/q/question/(?:[^/?#]+_)?([0-9a-f]{6,}|[A-Za-z0-9]+)/?$")


def extract_question_links(html):
    """Return list of (full_url, title, snippet) tuples extracted from search page.

    Uses multiple selector fallbacks; final fallback is regex over raw HTML.
    """
    soup = BeautifulSoup(html, "html.parser")
    items = []
    seen_urls = set()

    # 1) Card-style selectors
    selectors = [
        "article[class*=question]",
        "article[class*=Question]",
        "[class*=Question_]",
        "[class*=QuestionSnippet]",
        "[class*=question-snippet]",
        ".question",
        "div[class*=SearchResult]",
        "li[class*=search-result]",
    ]
    cards = []
    for sel in selectors:
        cards = soup.select(sel)
        if cards:
            break

    for c in cards:
        a = c.select_one("a[href*='/q/question/']")
        if not a:
            continue
        href = a.get("href", "")
        if not href:
            continue
        url = urljoin(BASE, href.split("?")[0])
        if url in seen_urls:
            continue
        seen_urls.add(url)
        # title
        title_el = c.select_one("h2 a, h2, [class*=title], [class*=Title]") or a
        title = title_el.get_text(" ", strip=True)
        # snippet
        snip_el = c.select_one("[class*=text], [class*=Text], [class*=snippet], [class*=Snippet], p")
        snippet = snip_el.get_text(" ", strip=True) if snip_el else ""
        items.append((url, title, snippet))

    # 2) If no cards, fallback: grab every <a href contains /q/question/>
    if not items:
        for a in soup.select("a[href*='/q/question/']"):
            href = a.get("href", "")
            url = urljoin(BASE, href.split("?")[0])
            if url in seen_urls:
                continue
            seen_urls.add(url)
            title = a.get_text(" ", strip=True)
            if not title or len(title) < 5:
                continue
            items.append((url, title, ""))

    # 3) Regex over raw HTML as last resort
    if not items:
        for m in QUESTION_HREF_RE.findall(html):
            url = urljoin(BASE, m)
            if url in seen_urls:
                continue
            seen_urls.add(url)
            items.append((url, "", ""))

    return items


# ---------- question detail page parsing ----------

def extract_question_detail(html, url):
    """Return dict with: title, question_body, top_answer, author, votes, n_answers, qid."""
    soup = BeautifulSoup(html, "html.parser")
    out = {"title": "", "question_body": "", "top_answer": "", "author": "",
           "votes": 0, "n_answers": 0, "qid": ""}

    # qid from URL
    m = re.search(r"/q/question/([^/?#]+)", url)
    if m:
        slug = m.group(1)
        # try trailing _<id> chunk
        idm = re.search(r"_([0-9a-f]{6,}|[A-Za-z0-9]{6,})$", slug)
        out["qid"] = idm.group(1) if idm else slug[:32]

    # Title
    h1 = soup.select_one("h1") or soup.select_one("[class*=question-header]") or soup.select_one("[class*=QuestionHeader]")
    if h1:
        out["title"] = h1.get_text(" ", strip=True)
    if not out["title"]:
        ogt = soup.select_one("meta[property='og:title']")
        if ogt:
            out["title"] = ogt.get("content", "").strip()
    if not out["title"]:
        t = soup.select_one("title")
        if t:
            out["title"] = re.sub(r"\s*[—\-|]\s*Яндекс.*$", "", t.get_text(" ", strip=True)).strip()

    # Question body — usually right under header
    body_candidates = [
        "[class*=question-body]", "[class*=QuestionBody]",
        "[class*=question-text]", "[class*=QuestionText]",
        "[class*=question__text]",
        "div[itemprop=text]",
    ]
    for sel in body_candidates:
        el = soup.select_one(sel)
        if el:
            txt = el.get_text(" ", strip=True)
            if txt and txt != out["title"]:
                out["question_body"] = txt
                break
    if not out["question_body"]:
        ogd = soup.select_one("meta[property='og:description']")
        if ogd:
            out["question_body"] = ogd.get("content", "").strip()

    # Answers — pick first
    ans_selectors = [
        "[class*=answer-text]", "[class*=AnswerText]",
        "[class*=answer-body]", "[class*=AnswerBody]",
        "[class*=answer__text]",
        "article[class*=answer]",
        "div[itemtype*='Answer']",
        "[class*=Answer_]",
    ]
    answers = []
    for sel in ans_selectors:
        answers = soup.select(sel)
        if answers:
            break
    if answers:
        # first answer text
        first = answers[0]
        out["top_answer"] = first.get_text(" ", strip=True)
        out["n_answers"] = len(answers)
        # author of first answer
        au = first.select_one("[class*=author], [class*=Author], [class*=user-name], [class*=UserName]")
        if au:
            out["author"] = au.get_text(" ", strip=True)
        # votes / score on first answer
        sc = first.select_one("[class*=vote], [class*=Vote], [class*=score], [class*=Score], [class*=likes], [class*=Likes]")
        if sc:
            sm = re.search(r"-?\d+", sc.get_text(" ", strip=True))
            if sm:
                out["votes"] = int(sm.group(0))

    # Fallback n_answers from header text "N ответов"
    if not out["n_answers"]:
        head_text = soup.get_text(" ", strip=True)[:5000]
        am = re.search(r"(\d+)\s+ответ", head_text)
        if am:
            out["n_answers"] = int(am.group(1))

    return out


# ---------- main crawl ----------

def crawl():
    seen = load_seen()
    session = requests.Session()
    session.headers.update(HDR)
    n_total = 0

    for kw in KEYWORDS:
        try:
            r = session.get(SEARCH, params={"key": kw}, timeout=25)
        except Exception as e:
            print(f"[search] '{kw}' err: {e}")
            polite(); continue
        if r.status_code != 200:
            print(f"[search] '{kw}' status={r.status_code}")
            polite(); continue

        items = extract_question_links(r.text)
        print(f"[search] '{kw}' found {len(items)} question links")
        if not items:
            # hint: dump first 200 chars of HTML for debugging once
            print(f"  HTML head sample: {r.text[:200]!r}")

        kept = 0
        for (url, sr_title, sr_snip) in items:
            qid_m = re.search(r"/q/question/([^/?#]+)", url)
            if not qid_m:
                continue
            slug = qid_m.group(1)
            idm = re.search(r"_([0-9a-f]{6,}|[A-Za-z0-9]{6,})$", slug)
            qid = idm.group(1) if idm else slug[:32]
            rid = md5_16("yandex_q", qid)
            if rid in seen:
                continue

            polite()
            try:
                rq = session.get(url, timeout=25)
            except Exception as e:
                print(f"  [q] {url} err: {e}")
                continue
            if rq.status_code != 200:
                print(f"  [q] {url} status={rq.status_code}")
                continue

            d = extract_question_detail(rq.text, url)
            title = d["title"] or sr_title
            if not title:
                continue
            qbody = d["question_body"] or sr_snip
            top_ans = d["top_answer"]
            # body = question + top answer
            parts = []
            if qbody:
                parts.append(qbody)
            if top_ans:
                parts.append("Ответ: " + top_ans)
            body = " ".join(parts).strip()[:3000]

            obj = {
                "id": rid,
                "raw_id": qid,
                "platform": "yandex_q",
                "lang": "ru",
                "title": title[:500],
                "body": body,
                "author": d["author"],
                "url": url,
                "country_hint": "RU",
                "matched_keyword": kw,
                "engagement": {
                    "score": d["votes"],
                    "comments": d["n_answers"],
                    "views": None,
                },
                "crawled_at": now_iso(),
            }
            append(OUT, obj)
            seen.add(rid)
            n_total += 1
            kept += 1

        print(f"[search] '{kw}' kept new={kept}, total so far={n_total}")
        polite()

    print(f"\n[yandex_q] DONE total +{n_total}")
    return n_total


def print_samples():
    if not OUT.exists():
        print("no output file")
        return
    rows = []
    for line in OUT.open(encoding="utf-8"):
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    print(f"\n=== rows in {OUT}: {len(rows)} ===")
    for r in rows[:5]:
        title = r.get("title", "")[:120]
        body = (r.get("body") or "")[:200]
        print(f"\n--- {r.get('matched_keyword')} | {r.get('url')}")
        print(f"T: {title}")
        print(f"B: {body}")


if __name__ == "__main__":
    crawl()
    print_samples()
