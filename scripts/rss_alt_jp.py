"""JP 多渠道 — 日本经济/职场 RSS。

补充日语本地母语收入帖（hatena 已 759 但很多是泛技术，需要更财经向）。
目标：+ 100-200 条针对收入/年薪话题的原文。
"""
import json, hashlib, time, random, re, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

DAY = datetime.now().strftime("%Y%m%d")
OUT = Path(f"data/raw/rss_alt_jp_native_{DAY}.jsonl")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
HDR = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.5"}
TIMEOUT = 25
SLEEP = (1.2, 1.8)

KW_RE = re.compile(
    r"年収|月収|時給|手取り|給料|給与|ボーナス|賞与|副業|フリーランス|"
    r"FIRE|早期退職|老後資金|資産形成|不労所得|配当|投資|貯金|起業|"
    r"プログラマー年収|エンジニア年収|医師年収|個人事業主|会社員",
)

FEEDS = [
    ("rss_diamond", "https://diamond.jp/list/feed/rss/dol", [".article-body", "article", ".main-text"]),
    ("rss_toyokeizai", "https://toyokeizai.net/list/feed/rss", [".article-body", "article", "#article-body"]),
    ("rss_nikkei_busi", "https://www.nikkei.com/rss/topic/business.rdf", [".article", "article"]),
    ("rss_president", "https://president.jp/list/articles/feed", ["article", ".content-detail"]),
    ("rss_zuuonline", "https://zuuonline.com/feed", ["article", ".article-body"]),
    ("rss_moneyplus", "https://media.moneyforward.com/feed", ["article", ".article-body", ".post-content"]),
    ("rss_lifehacker", "https://www.lifehacker.jp/feed/index.xml", [".article-body", "article", ".post-content"]),
    ("rss_gigazine", "https://gigazine.net/news/rss_2.0/", [".cont", "article", ".article-body"]),
    ("rss_anonymous", "https://anond.hatelabo.jp/rss", [".section", "article", ".body"]),
]


def md5_16(*p): return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]
def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def polite(): time.sleep(random.uniform(*SLEEP))


def append(obj):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def load_seen():
    seen = set()
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            try: seen.add(json.loads(line)["id"])
            except Exception: pass
    return seen


def fetch(url: str, label: str = "") -> str | None:
    try:
        r = requests.get(url, headers=HDR, timeout=TIMEOUT)
    except Exception as e:
        print(f"  [{label}] err: {e}", file=sys.stderr)
        return None
    if r.status_code != 200:
        print(f"  [{label}] status={r.status_code}", file=sys.stderr)
        return None
    return r.text


def parse_rss(xml: str):
    soup = BeautifulSoup(xml, "xml")
    items = soup.find_all("item") or soup.find_all("entry")
    out = []
    for it in items:
        t = it.find("title"); l = it.find("link"); g = it.find("guid") or it.find("id")
        d = it.find("description") or it.find("summary") or it.find("content")
        a = it.find("author") or it.find("dc:creator")
        title = t.get_text(strip=True) if t else ""
        link = (l.get("href") or l.get_text(strip=True) or "") if l else ""
        guid = (g.get_text(strip=True) if g else "") or link
        desc = d.get_text(" ", strip=True) if d else ""
        author = a.get_text(strip=True) if a else ""
        if title and link:
            out.append({"raw_id": guid, "title": title, "summary": desc, "link": link, "author": author})
    return out


def fetch_body(url: str, selectors: list[str]) -> str:
    html = fetch(url, label=f"body {urlparse(url).netloc}")
    if not html: return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "aside", "header", "footer"]):
        tag.decompose()
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            txt = el.get_text(" ", strip=True)
            if len(txt) > 100: return txt[:5000]
    ps = [p.get_text(" ", strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 20]
    return " ".join(ps)[:5000]


def crawl_feed(name: str, url: str, sel: list[str], seen: set):
    print(f"\n=== {name} ({url}) ===")
    xml = fetch(url, label=name)
    if not xml: return (0, 0, 0)
    items = parse_rss(xml)
    print(f"  items={len(items)}")
    matched = 0; written = 0
    for it in items:
        text = it["title"] + " " + it["summary"]
        m = KW_RE.search(text)
        if not m: continue
        matched += 1
        rid = md5_16(name, it["raw_id"])
        if rid in seen: continue
        body = fetch_body(it["link"], sel) or it["summary"]
        if not body or len(body) < 50: continue
        obj = {
            "id": rid, "raw_id": it["raw_id"], "platform": name, "lang": "ja",
            "title": it["title"][:300], "body": body[:5000], "author": it["author"],
            "url": it["link"], "country_hint": "JP", "matched_keyword": m.group(0),
            "engagement": {"score": 0, "comments": 0, "views": None},
            "crawled_at": now_iso(),
        }
        append(obj); seen.add(rid); written += 1
        polite()
    print(f"  matched={matched} written={written}")
    return (len(items), matched, written)


def main():
    seen = load_seen()
    print(f"resume: seen={len(seen)}")
    summary = []
    for name, url, sel in FEEDS:
        try: i, m, w = crawl_feed(name, url, sel, seen)
        except Exception as e:
            print(f"[{name}] err: {e}", file=sys.stderr); i, m, w = 0, 0, 0
        summary.append((name, i, m, w))
        polite()
    print(f"\n=== SUMMARY ===")
    for name, i, m, w in summary:
        print(f"  {name:<24} items={i:>4} matched={m:>4} written={w:>4}")
    final = sum(1 for _ in OUT.open()) if OUT.exists() else 0
    print(f"=== FILE TOTAL: {final} ===")


if __name__ == "__main__":
    main()
