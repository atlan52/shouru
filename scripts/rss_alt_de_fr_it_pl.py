"""DE / FR / IT / PL 多源 RSS — 欧洲多语种收入帖批量补充。

输出 4 个文件：rss_alt_de/fr/it/pl_native_<DAY>.jsonl
"""
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

# (lang, country, KW_RE pattern, [(name, feed_url, selectors)])
LANG_CONFIGS = {
    "de": (
        "DE",
        re.compile(
            r"Gehalt|Einkommen|Lohn|Verdienst|Selbstständig|Freelance|"
            r"Rente|Pension|Frührente|FIRE|Nebenjob|Honorar|Boni|Bonus",
            re.IGNORECASE,
        ),
        [
            ("rss_handelsblatt", "https://www.handelsblatt.com/contentexport/feed/karriere", ["article", ".vhb-article-body"]),
            ("rss_zeit_wirtschaft", "https://newsfeed.zeit.de/wirtschaft/index", ["article", ".article-body", ".article__item"]),
            ("rss_spiegel_karriere", "https://www.spiegel.de/karriere/index.rss", ["article", ".article-section", ".RichText"]),
            ("rss_finanztip", "https://www.finanztip.de/feed/", ["article", ".content-text", ".post-content"]),
            ("rss_sueddeutsche_karriere", "https://rss.sueddeutsche.de/rss/Karriere", ["article", ".sz-article-body"]),
            ("rss_madame_moneypenny", "https://madamemoneypenny.de/feed/", [".entry-content", "article"]),
        ],
    ),
    "fr": (
        "FR",
        re.compile(
            r"salaire|revenu|gagne|rémunération|smic|prime|bonus|"
            r"freelance|indépendant|retraite|FIRE|investiss",
            re.IGNORECASE,
        ),
        [
            ("rss_lemonde_eco", "https://www.lemonde.fr/economie/rss_full.xml", ["article", ".article__content"]),
            ("rss_lefigaro_eco", "https://www.lefigaro.fr/rss/figaro_economie.xml", ["article", ".fig-content-body"]),
            ("rss_capital", "https://www.capital.fr/rss", ["article", ".article-body"]),
            ("rss_lesechos", "https://services.lesechos.fr/rss/les-echos-economie.xml", ["article", ".article-body"]),
            ("rss_jdd", "https://www.lejdd.fr/rss.xml", ["article", ".article-body"]),
            ("rss_journaldunet", "https://www.journaldunet.com/rss/", ["article", ".app_article_content"]),
        ],
    ),
    "it": (
        "IT",
        re.compile(
            r"stipendio|salario|guadagn|reddito|busta paga|RAL|"
            r"freelance|partita IVA|pensione|FIRE|investimento|risparmi",
            re.IGNORECASE,
        ),
        [
            ("rss_repubblica_eco", "https://www.repubblica.it/rss/economia/rss2.0.xml", ["article", ".story__text"]),
            ("rss_corriere_eco", "https://xml2.corriereobjects.it/rss/economia.xml", ["article", ".bck-media-news-text"]),
            ("rss_ilsole24ore", "https://www.ilsole24ore.com/rss/lavoro--lavoro.xml", ["article", ".atom-text-block"]),
            ("rss_money_it", "https://www.money.it/feed/rss/", ["article", ".entry-content"]),
            ("rss_milanofinanza", "https://www.milanofinanza.it/news/rss", ["article", ".article-body"]),
        ],
    ),
    "pl": (
        "PL",
        re.compile(
            r"pensja|zarobki|wynagrodzenie|dochód|emerytura|FIRE|"
            r"freelance|samozatrudni|premia|inwestycj|oszczędn",
            re.IGNORECASE,
        ),
        [
            ("rss_money_pl", "https://www.money.pl/rss/", ["article", ".art-content"]),
            ("rss_bankier", "https://www.bankier.pl/rss/wiadomosci.xml", ["article", ".articleContent"]),
            ("rss_pulshr", "https://www.pulshr.pl/rss/wynagrodzenia.xml", ["article", ".articleContent"]),
            ("rss_forbes_pl", "https://www.forbes.pl/feed", ["article", ".article-body"]),
            ("rss_subiektywnie", "https://subiektywnieofinansach.pl/feed/", [".entry-content", "article"]),
            ("rss_jakoszczedzac", "https://jakoszczedzacpieniadze.pl/feed", [".entry-content", "article"]),
        ],
    ),
}


def md5_16(*p): return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]
def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def polite(): time.sleep(random.uniform(*SLEEP))


def hdr(lang: str):
    accept = {
        "de": "de-DE,de;q=0.9,en;q=0.5",
        "fr": "fr-FR,fr;q=0.9,en;q=0.5",
        "it": "it-IT,it;q=0.9,en;q=0.5",
        "pl": "pl-PL,pl;q=0.9,en;q=0.5",
    }[lang]
    return {"User-Agent": UA, "Accept": "*/*", "Accept-Language": accept}


def fetch(url: str, lang: str, label: str = "") -> str | None:
    try:
        r = requests.get(url, headers=hdr(lang), timeout=TIMEOUT)
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
    for tag in soup(["script", "style", "nav", "aside", "header", "footer"]):
        tag.decompose()
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
    for lang in ["de", "fr", "it", "pl"]:
        try:
            grand += crawl_lang(lang)
        except Exception as e:
            print(f"[{lang}] err: {e}", file=sys.stderr)
    print(f"\n=== GRAND TOTAL across DE/FR/IT/PL: {grand} ===")


if __name__ == "__main__":
    main()
