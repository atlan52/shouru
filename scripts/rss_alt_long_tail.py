"""长尾语种补充 — AR/HI/SV/FI/SE/EL/CS RSS。"""
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
    "ar": (  # Arabic — SA / EG / AE
        "AR",
        re.compile(
            r"راتب|دخل|أجر|مكافأة|تقاعد|معاش|عمل حر|مستقل|"
            r"استثمار|توفير|FIRE|أعمال|كسب"
        ),
        [
            ("rss_alarabiya_eco", "https://www.alarabiya.net/aswaq/rss.xml", ["article", ".body-text"]),
            ("rss_aljazeera_eco", "https://www.aljazeera.net/aljazeerarss/aljazeera-business.xml", ["article", ".wysiwyg"]),
            ("rss_argaam", "https://www.argaam.com/ar/rss/news", ["article", ".article-body"]),
            ("rss_almasryalyoum", "https://www.almasryalyoum.com/rss/economy.xml", ["article", ".article-content"]),
            ("rss_youm7", "https://www.youm7.com/rss/SectionRss?SectionID=297", ["article", ".articleCont"]),
        ],
    ),
    "hi": (  # Hindi — IN
        "IN",
        re.compile(
            r"वेतन|आय|कमाई|बोनस|पेंशन|सेवानिवृत्ति|"
            r"फ्रीलांस|FIRE|निवेश|बचत|सैलरी"
        ),
        [
            ("rss_navbharat_business", "https://navbharattimes.indiatimes.com/rssfeedsdefault.cms?cms=Hindi+Business", ["article", ".story-content"]),
            ("rss_jagran_business", "https://www.jagran.com/rss/news/business.xml", ["article", ".article-body"]),
            ("rss_amarujala", "https://www.amarujala.com/rss/business.xml", ["article", ".articleBody"]),
            ("rss_hindi_indiatv", "https://www.indiatv.in/rssnews/topstory-business-2.xml", ["article", ".content"]),
        ],
    ),
    "sv": (  # Swedish — SE
        "SE",
        re.compile(
            r"lön|inkomst|tjänar|bonus|pension|"
            r"frilans|FIRE|spara|investera|löneutveckling",
            re.IGNORECASE,
        ),
        [
            ("rss_dn_ekonomi", "https://www.dn.se/ekonomi/rss/", ["article", ".article__content"]),
            ("rss_di", "https://www.di.se/rss", ["article", ".article-content"]),
            ("rss_svd_naring", "https://www.svd.se/rss/naringsliv.xml", ["article", ".article-body"]),
            ("rss_aftonbladet_eko", "https://www.aftonbladet.se/rss.xml?section=ekonomi", ["article", ".article-body"]),
            ("rss_expressen_dinapengar", "https://feeds.expressen.se/dinapengar/", ["article", ".article-body"]),
        ],
    ),
    "fi": (  # Finnish — FI
        "FI",
        re.compile(
            r"palkka|tulo|ansio|bonus|eläke|"
            r"freelance|FIRE|sijoittaa|säästää",
            re.IGNORECASE,
        ),
        [
            ("rss_yle_talous", "https://feeds.yle.fi/uutiset/v1/majorHeadlines/YLE_TALOUS.rss", ["article", ".yle__article__content"]),
            ("rss_hs_talous", "https://www.hs.fi/rss/talous.xml", ["article", ".article-body"]),
            ("rss_iltalehti_talous", "https://www.iltalehti.fi/rss/talous.xml", ["article", ".article-body"]),
            ("rss_taloussanomat", "https://www.is.fi/rss/taloussanomat.xml", ["article", ".article-body"]),
        ],
    ),
    "el": (  # Greek — GR
        "GR",
        re.compile(
            r"μισθός|εισόδημα|κερδίζ|μπόνους|σύνταξη|"
            r"ελεύθερος επαγγελματίας|FIRE|επένδυση|αποταμίευση"
        ),
        [
            ("rss_kathimerini_eco", "https://www.kathimerini.gr/rss/economy/", ["article", ".article__main-text"]),
            ("rss_protothema_eco", "https://www.protothema.gr/rss/economics/", ["article", ".article-body"]),
            ("rss_in_gr_eco", "https://www.in.gr/feed/oikonomia/", ["article", ".content"]),
            ("rss_naftemporiki", "https://www.naftemporiki.gr/rss/economy", ["article", ".article-body"]),
        ],
    ),
}


def md5_16(*p): return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]
def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def polite(): time.sleep(random.uniform(*SLEEP))


def hdr(lang: str):
    accept = {
        "ar": "ar,en;q=0.5",
        "hi": "hi-IN,hi;q=0.9,en;q=0.5",
        "sv": "sv-SE,sv;q=0.9,en;q=0.5",
        "fi": "fi-FI,fi;q=0.9,en;q=0.5",
        "el": "el-GR,el;q=0.9,en;q=0.5",
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
        print(f"    {name:<30} items={i:>4} matched={m:>4} written={w:>4}")
    print(f"  FILE TOTAL: {final}")
    return final


def main():
    grand = 0
    for lang in ["ar", "hi", "sv", "fi", "el"]:
        try: grand += crawl_lang(lang)
        except Exception as e: print(f"[{lang}] err: {e}", file=sys.stderr)
    print(f"\n=== GRAND TOTAL across AR/HI/SV/FI/EL: {grand} ===")


if __name__ == "__main__":
    main()
