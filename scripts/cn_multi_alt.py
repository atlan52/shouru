"""CN 多渠道补充 — sspai / 简书 / 虎扑 / segmentfault / solidot / caixin RSS + HTML.

补充中文本地母语收入帖原文。当前 CN 数据仅 bilibili 656，36kr/雪球/知乎/小红书全 0。
目标 200-500 条。
"""
import json, hashlib, time, random, re, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

DAY = datetime.now().strftime("%Y%m%d")
OUT = Path(f"data/raw/cn_multi_alt_native_{DAY}.jsonl")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HDR = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
}
TIMEOUT = 25
SLEEP = (1.3, 1.8)

KW_RE = re.compile(
    r"工资|月薪|年薪|月入|年入|收入|挣到|挣了|赚到|赚了|副业|自由职业|存款|理财|"
    r"裸辞|FIRE|财务自由|被动收入|分红|租金|股息|奖金|提成|创业|月薪过万|年薪百万|"
    r"睡后收入|存到|存了|攒到|攒了|时薪|日薪|周薪|薪水|薪资|挣钱|赚钱|工时"
)

FEEDS = [
    ("rss_sspai", "https://sspai.com/feed", [".article-body", ".article-content", "article", ".content"]),
    ("rss_jianshu_finance", "https://www.jianshu.com/rss/c/V2CqjW", [".show-content", "article", ".article"]),
    ("rss_solidot", "https://www.solidot.org/index.rss", [".p_content", "article", ".article"]),
    ("rss_segmentfault", "https://segmentfault.com/feeds/blog", [".article-content", "article", ".answer__content"]),
    ("rss_caixin", "https://www.caixin.com/rss/", ["#Main_Content_Val", ".content-text", "article", ".article"]),
    ("rss_huxiu", "https://www.huxiu.com/rss/0.xml", [".article-content-wrap", "article", ".content"]),
    ("rss_36kr_alt", "https://36kr.com/feed", ["article", ".article-content", ".content"]),
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
            try:
                seen.add(json.loads(line)["id"])
            except Exception:
                pass
    return seen


def fetch(url: str, label: str = "") -> str | None:
    try:
        r = requests.get(url, headers=HDR, timeout=TIMEOUT)
    except Exception as e:
        print(f"  [{label}] err: {e}", file=sys.stderr)
        return None
    if r.status_code != 200:
        print(f"  [{label}] status={r.status_code} url={url}", file=sys.stderr)
        return None
    return r.text


def parse_rss(xml: str):
    soup = BeautifulSoup(xml, "xml")
    items = soup.find_all("item")
    if not items:
        items = soup.find_all("entry")
    out = []
    for it in items:
        title_el = it.find("title")
        link_el = it.find("link")
        guid_el = it.find("guid") or it.find("id")
        desc_el = it.find("description") or it.find("summary") or it.find("content")
        author_el = it.find("author") or it.find("dc:creator")
        pub_el = it.find("pubDate") or it.find("published") or it.find("updated")

        title = title_el.get_text(strip=True) if title_el else ""
        if link_el:
            link = link_el.get("href") or link_el.get_text(strip=True) or ""
        else:
            link = ""
        guid = (guid_el.get_text(strip=True) if guid_el else "") or link
        desc = desc_el.get_text(" ", strip=True) if desc_el else ""
        author = author_el.get_text(strip=True) if author_el else ""
        pub = pub_el.get_text(strip=True) if pub_el else ""

        if title and link:
            out.append({
                "raw_id": guid, "title": title, "summary": desc,
                "link": link, "author": author, "pub": pub,
            })
    return out


def fetch_body(url: str, selectors: list[str]) -> str:
    html = fetch(url, label=f"body {urlparse(url).netloc}")
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "aside", "header", "footer"]):
        tag.decompose()
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            txt = el.get_text(" ", strip=True)
            if len(txt) > 100:
                return txt[:5000]
    ps = [p.get_text(" ", strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 20]
    return " ".join(ps)[:5000]


def crawl_feed(name: str, feed_url: str, body_selectors: list[str], seen: set):
    print(f"\n=== {name} ({feed_url}) ===")
    xml = fetch(feed_url, label=name)
    if not xml:
        return (0, 0, 0)
    items = parse_rss(xml)
    print(f"  items={len(items)}")
    matched = 0
    written = 0
    for it in items:
        text = it["title"] + " " + it["summary"]
        m = KW_RE.search(text)
        if not m:
            continue
        matched += 1
        rid = md5_16(name, it["raw_id"])
        if rid in seen:
            continue
        body = fetch_body(it["link"], body_selectors) or it["summary"]
        if not body or len(body) < 50:
            continue
        obj = {
            "id": rid,
            "raw_id": it["raw_id"],
            "platform": name,
            "lang": "zh",
            "title": it["title"][:300],
            "body": body[:5000],
            "author": it["author"],
            "url": it["link"],
            "country_hint": "CN",
            "matched_keyword": m.group(0),
            "engagement": {"score": 0, "comments": 0, "views": None},
            "crawled_at": now_iso(),
            "pub": it["pub"],
        }
        append(obj)
        seen.add(rid)
        written += 1
        polite()
    print(f"  matched={matched} written={written}")
    return (len(items), matched, written)


def main():
    seen = load_seen()
    print(f"resume: seen={len(seen)}")
    summary = []
    for name, url, sel in FEEDS:
        try:
            i, m, w = crawl_feed(name, url, sel, seen)
        except Exception as e:
            print(f"[{name}] crawl err: {e}", file=sys.stderr)
            i, m, w = 0, 0, 0
        summary.append((name, i, m, w))
        polite()

    print(f"\n=== SUMMARY {OUT} ===")
    for name, i, m, w in summary:
        print(f"  {name:<28}  items={i:>4} matched={m:>4} written={w:>4}")
    total = sum(w for _, _, _, w in summary)
    final = 0
    if OUT.exists():
        with OUT.open(encoding="utf-8") as f:
            final = sum(1 for _ in f)
    print(f"\n=== TOTAL written this run: {total}; file final lines: {final} ===")


if __name__ == "__main__":
    main()
