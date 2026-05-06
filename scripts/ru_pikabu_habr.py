"""Pikabu + Habr — 俄语收入帖直接 HTML 抓取。"""
import json, hashlib, re, time, random
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124"
HDR = {"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5"}
DAY = datetime.now().strftime("%Y%m%d")
OUT_PIKABU = Path(f"data/raw/pikabu_native_{DAY}.jsonl")
OUT_HABR = Path(f"data/raw/habr_native_{DAY}.jsonl")

def md5_16(*p): return hashlib.md5("|".join(map(str,p)).encode()).hexdigest()[:16]
def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def append(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f: f.write(json.dumps(obj, ensure_ascii=False)+"\n")
def polite(): time.sleep(random.uniform(1.0, 2.0))


def crawl_pikabu():
    keywords = ["зарплата", "доход", "сколько зарабатываете",
                "пассивный доход", "фриланс доход", "подработка",
                "как заработать", "финансовая независимость",
                "удаленная работа доход", "бизнес доход"]
    seen = set()
    if OUT_PIKABU.exists():
        for line in OUT_PIKABU.open():
            try: seen.add(json.loads(line)["id"])
            except: pass
    n = 0
    for kw in keywords:
        for page in range(1, 4):
            try:
                r = requests.get("https://pikabu.ru/search",
                                params={"q": kw, "D": "0", "n": "2", "t": "2", "page": str(page)},
                                headers=HDR, timeout=20)
                if r.status_code != 200:
                    print(f"[pikabu] {kw} p{page} status={r.status_code}")
                    break
                soup = BeautifulSoup(r.text, "html.parser")
                stories = soup.select("article.story") or soup.select("div.story") or soup.select("[class*=story_]")
                if not stories:
                    # try alternative json output
                    print(f"[pikabu] {kw} p{page} no stories selector matches")
                    # debug: dump first 500 chars
                    if page == 1: print(f"  HTML head: {r.text[:200]}...")
                    break
                for s in stories:
                    try:
                        title_el = s.select_one("h2 a, .story__title-link, a.story__title")
                        if not title_el: continue
                        title = title_el.get_text(" ", strip=True)
                        url = title_el.get("href","")
                        if url and not url.startswith("http"): url = "https://pikabu.ru"+url
                        m = re.search(r"/story/[^/]+_(\d+)", url)
                        if not m: continue
                        sid = m.group(1)
                        rid = md5_16("pikabu", sid)
                        if rid in seen: continue
                        body_el = s.select_one(".story-block_type_text, .story__content-inner, [class*=text-block]")
                        body = body_el.get_text(" ", strip=True) if body_el else ""
                        author_el = s.select_one(".user__nick, .story__user a")
                        author = author_el.get_text(strip=True) if author_el else ""
                        rating_el = s.select_one(".story__rating-count, [class*=rating]")
                        rating = 0
                        if rating_el:
                            rt = re.search(r"-?\d+", rating_el.get_text())
                            rating = int(rt.group(0)) if rt else 0
                        comments_el = s.select_one(".story__comments-link-count, [class*=comments]")
                        comments = 0
                        if comments_el:
                            ct = re.search(r"\d+", comments_el.get_text())
                            comments = int(ct.group(0)) if ct else 0
                        obj = {"id": rid, "raw_id": sid, "platform": "pikabu",
                               "lang": "ru", "title": title, "body": body[:3000],
                               "author": author, "url": url, "country_hint": "RU",
                               "matched_keyword": kw,
                               "engagement": {"score": rating, "comments": comments, "views": None},
                               "crawled_at": now_iso()}
                        append(OUT_PIKABU, obj); seen.add(rid); n += 1
                    except Exception as e:
                        print(f"  parse err: {e}")
                print(f"[pikabu] {kw} p{page} +parsed {len(stories)}, +new so far {n}")
            except Exception as e:
                print(f"[pikabu] {kw} p{page} err: {e}")
                break
            polite()
    print(f"[pikabu] DONE +{n}")
    return n


def crawl_habr():
    """Habr posts via search."""
    keywords = ["зарплата", "доход разработчика", "сколько зарабатывает",
                "сколько получает", "стоимость разработчика"]
    seen = set()
    if OUT_HABR.exists():
        for line in OUT_HABR.open():
            try: seen.add(json.loads(line)["id"])
            except: pass
    n = 0
    # First, salaries page (structured data)
    try:
        r = requests.get("https://career.habr.com/salaries", headers=HDR, timeout=20)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            # Salary records — they have a chart with role data
            # We'll just grab the page summary as one record + titles of links
            text = soup.get_text(" ", strip=True)[:3000]
            rid = md5_16("habr", "career_salaries_landing")
            if rid not in seen:
                obj = {"id": rid, "raw_id": "career_salaries_landing", "platform": "habr",
                       "lang": "ru", "title": "Habr Career Зарплаты IT-специалистов",
                       "body": text, "author": "habr.com",
                       "url": "https://career.habr.com/salaries",
                       "country_hint": "RU", "matched_keyword": "зарплата",
                       "engagement": {"score": 0, "comments": 0, "views": None},
                       "crawled_at": now_iso()}
                append(OUT_HABR, obj); seen.add(rid); n += 1
    except Exception as e:
        print(f"[habr] career page err: {e}")
    # Also habr.com posts search
    for kw in keywords:
        for page in range(1, 4):
            try:
                r = requests.get("https://habr.com/ru/search/",
                                params={"q": kw, "target_type": "posts", "order": "relevance", "page": str(page)},
                                headers=HDR, timeout=20)
                if r.status_code != 200:
                    print(f"[habr] {kw} p{page} status={r.status_code}")
                    break
                soup = BeautifulSoup(r.text, "html.parser")
                articles = soup.select("article.tm-articles-list__item, article")
                if not articles:
                    print(f"[habr] {kw} p{page} no article")
                    break
                for a in articles:
                    title_el = a.select_one("h2 a, a.tm-title__link")
                    if not title_el: continue
                    title = title_el.get_text(" ", strip=True)
                    href = title_el.get("href","")
                    if href and not href.startswith("http"): href = "https://habr.com"+href
                    m = re.search(r"/articles/(\d+)", href)
                    if not m: continue
                    aid = m.group(1)
                    rid = md5_16("habr", aid)
                    if rid in seen: continue
                    body_el = a.select_one("[class*=snippet], .article-formatted-body")
                    body = body_el.get_text(" ", strip=True) if body_el else ""
                    author_el = a.select_one("[class*=user-info__nickname], .tm-user-info__username")
                    author = author_el.get_text(strip=True) if author_el else ""
                    score_el = a.select_one("[class*=votes-meter], [class*=rating]")
                    score = 0
                    if score_el:
                        st = re.search(r"-?\d+", score_el.get_text())
                        score = int(st.group(0)) if st else 0
                    obj = {"id": rid, "raw_id": aid, "platform": "habr",
                           "lang": "ru", "title": title, "body": body[:3000],
                           "author": author, "url": href, "country_hint": "RU",
                           "matched_keyword": kw,
                           "engagement": {"score": score, "comments": 0, "views": None},
                           "crawled_at": now_iso()}
                    append(OUT_HABR, obj); seen.add(rid); n += 1
                print(f"[habr] {kw} p{page} +parsed {len(articles)}, total {n}")
            except Exception as e:
                print(f"[habr] {kw} p{page} err: {e}")
                break
            polite()
    print(f"[habr] DONE +{n}")
    return n


if __name__ == "__main__":
    n_p = crawl_pikabu()
    n_h = crawl_habr()
    print(f"\n=== TOTAL: pikabu +{n_p}, habr +{n_h} ===")
