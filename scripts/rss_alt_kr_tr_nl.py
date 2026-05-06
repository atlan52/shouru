"""KR / TR / NL 多源 RSS — 韩/土/荷 收入帖。"""
import json, hashlib, time, random, re, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

DAY = datetime.now().strftime("%Y%m%d")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
TIMEOUT = 25
SLEEP = (1.2, 1.8)

LANG_CONFIGS = {
    "ko": (
        "KR",
        re.compile(
            r"연봉|월급|월소득|소득|급여|보너스|프리랜서|부업|"
            r"FIRE|은퇴|연금|배당|투자|저축|자영업"
        ),
        [
            ("rss_hankyung", "https://www.hankyung.com/feed/economy", ["article", "#articletxt"]),
            ("rss_chosun_economy", "https://www.chosun.com/arc/outboundfeeds/rss/category/economy/?outputType=xml", ["article", ".article-body"]),
            ("rss_mk", "https://www.mk.co.kr/rss/30000001/", ["article", "#article_body"]),
            ("rss_kbs_economy", "http://world.kbs.co.kr/rss/rss_news.htm?lang=k&id=Ec", ["article", ".article-body"]),
            ("rss_yna_economy", "https://www.yna.co.kr/rss/economy.xml", ["article", "#articleWrap"]),
            ("rss_ohmynews", "http://rss.ohmynews.com/rss/ohmynews.xml", ["article", "#articleBody"]),
        ],
    ),
    "tr": (
        "TR",
        re.compile(
            r"maaş|gelir|kazan|asgari ücret|prim|bonus|emekli|"
            r"freelance|serbest meslek|FIRE|yatırım|tasarruf",
            re.IGNORECASE,
        ),
        [
            ("rss_hurriyet_eko", "https://www.hurriyet.com.tr/rss/ekonomi", ["article", ".news-detail-text"]),
            ("rss_milliyet_eko", "https://www.milliyet.com.tr/rss/rssNew/ekonomiRss.xml", ["article", ".article__content"]),
            ("rss_haberturk_eko", "https://www.haberturk.com/rss/ekonomi.xml", ["article", ".content"]),
            ("rss_sabah_eko", "https://www.sabah.com.tr/rss/ekonomi.xml", ["article", ".newsBox"]),
            ("rss_dunya", "https://www.dunya.com/rss?dunya=ekonomi", ["article", ".articleContent"]),
            ("rss_ekonomim", "https://www.ekonomim.com/rss", ["article", ".article-body"]),
        ],
    ),
    "nl": (
        "NL",
        re.compile(
            r"salaris|inkomen|verdien|loon|bonus|premie|"
            r"zzp|freelance|pensioen|FIRE|spaargeld|investering",
            re.IGNORECASE,
        ),
        [
            ("rss_nu_economie", "https://www.nu.nl/rss/Economie", ["article", ".block-content"]),
            ("rss_volkskrant", "https://www.volkskrant.nl/economie/rss.xml", ["article", ".artstyle__text"]),
            ("rss_fd", "https://fd.nl/?widget=rssfeed&view=feed&contentId=10000-fd", ["article", ".article__content"]),
            ("rss_nrc_economie", "https://www.nrc.nl/rss/economie/", ["article", ".article__content"]),
            ("rss_bnr", "https://www.bnr.nl/rss", ["article", ".article-body"]),
            ("rss_ad_economie", "https://www.ad.nl/economie/rss.xml", ["article", ".article__body"]),
        ],
    ),
}


def md5_16(*p): return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]
def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def polite(): time.sleep(random.uniform(*SLEEP))


def hdr(lang: str):
    accept = {
        "ko": "ko-KR,ko;q=0.9,en;q=0.5",
        "tr": "tr-TR,tr;q=0.9,en;q=0.5",
        "nl": "nl-NL,nl;q=0.9,en;q=0.5",
    }[lang]
    return {"User-Agent": UA, "Accept": "*/*", "Accept-Language": accept}


def fetch(url: str, lang: str, label: str = "") -> str | None:
    try: r = requests.get(url, headers=hdr(lang), timeout=TIMEOUT)
    except Exception as e:
        print(f"  [{label}] err: {e}", file=sys.stderr); return None
    if r.status_code != 200:
        print(f"  [{label}] status={r.status_code}", file=sys.stderr); return None
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


def fetch_body(url: str, sel: list[str], lang: str) -> str:
    html = fetch(url, lang, label=f"body {urlparse(url).netloc}")
    if not html: return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "aside", "header", "footer"]): tag.decompose()
    for s in sel:
        el = soup.select_one(s)
        if el:
            txt = el.get_text(" ", strip=True)
            if len(txt) > 100: return txt[:5000]
    ps = [p.get_text(" ", strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 20]
    return " ".join(ps)[:5000]


def append(out_path: Path, obj: dict):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def load_seen(out_path: Path) -> set:
    seen = set()
    if out_path.exists():
        for line in out_path.open(encoding="utf-8"):
            try: seen.add(json.loads(line)["id"])
            except Exception: pass
    return seen


def crawl_lang(lang: str):
    country, kw_re, feeds = LANG_CONFIGS[lang]
    out = Path(f"data/raw/rss_alt_{lang}_native_{DAY}.jsonl")
    seen = load_seen(out)
    print(f"\n========== LANG={lang} country={country} ==========")
    summary = []
    for name, url, sel in feeds:
        print(f"\n  --- {name} ({url}) ---")
        xml = fetch(url, lang, label=name)
        if not xml:
            summary.append((name, 0, 0, 0)); continue
        items = parse_rss(xml)
        print(f"    items={len(items)}")
        matched = 0; written = 0
        for it in items:
            text = it["title"] + " " + it["summary"]
            m = kw_re.search(text)
            if not m: continue
            matched += 1
            rid = md5_16(name, it["raw_id"])
            if rid in seen: continue
            body = fetch_body(it["link"], sel, lang) or it["summary"]
            if not body or len(body) < 50: continue
            obj = {
                "id": rid, "raw_id": it["raw_id"], "platform": name, "lang": lang,
                "title": it["title"][:300], "body": body[:5000], "author": it["author"],
                "url": it["link"], "country_hint": country, "matched_keyword": m.group(0),
                "engagement": {"score": 0, "comments": 0, "views": None},
                "crawled_at": now_iso(),
            }
            append(out, obj); seen.add(rid); written += 1
            polite()
        print(f"    matched={matched} written={written}")
        summary.append((name, len(items), matched, written))
        polite()
    final = sum(1 for _ in out.open()) if out.exists() else 0
    print(f"\n  SUMMARY {lang}:")
    for name, i, m, w in summary:
        print(f"    {name:<26} items={i:>4} matched={m:>4} written={w:>4}")
    print(f"  FILE TOTAL: {final}")
    return final


def main():
    grand = 0
    for lang in ["ko", "tr", "nl"]:
        try:
            grand += crawl_lang(lang)
        except Exception as e:
            print(f"[{lang}] err: {e}", file=sys.stderr)
    print(f"\n=== GRAND TOTAL across KR/TR/NL: {grand} ===")


if __name__ == "__main__":
    main()
