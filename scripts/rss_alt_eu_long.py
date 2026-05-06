"""欧洲长尾语种 RSS — CZ / HU / RO / UA / PT(本土) / BE-NL / DK / NO。

每语种独立 outfile，schema 同 r_mexico_native：
  id / raw_id / platform / lang / title / body / author / url
  country_hint / matched_keyword / engagement / crawled_at

subagent 不要直接 python 跑，主 agent 用 .venv/bin/python 调度。
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
SLEEP = (1.0, 1.5)

# (lang_tag, outfile_tag, country, keyword_regex, [(name, url, [selectors])])
LANG_CONFIGS = {
    "cs": (  # Czech — CZ
        "cs", "CZ",
        re.compile(
            r"plat|mzda|příjem|příjmu|výdělek|vydělá|freelance|OSVČ|důchod|FIRE|"
            r"výplata|odměna",
            re.IGNORECASE,
        ),
        [
            ("rss_idnes_eko", "https://www.idnes.cz/rss/ekonomika.aspx",
             ["article", ".art-full", ".art-text", ".bbtext"]),
            ("rss_denikn", "https://denikn.cz/feed/",
             ["article", ".a_single", ".entry-content"]),
            ("rss_e15_byznys", "https://e15.cz/feeds/byznys.xml",
             ["article", ".article-detail", ".entry-content"]),
            ("rss_aktualne_byznys", "https://www.aktualne.cz/rss/byznys/",
             ["article", ".article-content", ".text"]),
        ],
    ),
    "hu": (  # Hungarian — HU
        "hu", "HU",
        re.compile(
            r"fizetés|fizetését|jövedelem|jövedelmét|kereset|keres|"
            r"szabadúszó|FIRE|nyugdíj",
            re.IGNORECASE,
        ),
        [
            ("rss_hvg_gazdasag", "https://hvg.hu/rss/gazdasag",
             ["article", ".article-content", ".entry-content"]),
            ("rss_portfolio_penz", "https://www.portfolio.hu/rss/penz_uj.xml",
             ["article", ".overview-content", ".article-content"]),
            ("rss_index_gazdasag", "https://index.hu/24ora/gazdasag/rss/",
             ["article", ".cikk-torzs", ".content-text"]),
            ("rss_napi", "https://www.napi.hu/rss/feed/0/",
             ["article", ".article-content", ".article-body"]),
        ],
    ),
    "ro": (  # Romanian — RO
        "ro", "RO",
        re.compile(
            r"salariu|salarii|venit|venituri|câștigă|castiga|freelance|"
            r"pensie|FIRE|PFA",
            re.IGNORECASE,
        ),
        [
            ("rss_zf_economie", "https://www.zf.ro/rss/economie/",
             ["article", ".article-content", ".intro"]),
            ("rss_economica", "https://economica.net/feed/",
             ["article", ".entry-content", ".article-content"]),
            ("rss_bursa_economie", "https://www.bursa.ro/rss/economie.xml",
             ["article", ".text-article", ".article-body"]),
            ("rss_hotnews", "https://hotnews.ro/feed/",
             ["article", ".entry-content", ".article-content"]),
        ],
    ),
    "uk": (  # Ukrainian — UA  (注意：lang=uk 是 Ukrainian ISO 639-1)
        "uk", "UA",
        re.compile(
            r"зарплат|дохід|доходу|заробіт|заробляє|"
            r"фрілансер|пенсі|FIRE",
            re.IGNORECASE,
        ),
        [
            ("rss_epravda", "https://www.epravda.com.ua/rss/",
             ["article", ".post_content", ".post__text"]),
            ("rss_nv_biz", "https://nv.ua/biz.rss",
             ["article", ".article-content", ".content"]),
            ("rss_ukrinform_eco", "https://www.ukrinform.ua/rss/block-economics",
             ["article", ".newsBody", ".content"]),
            ("rss_lb_eco", "https://lb.ua/rss/ukr/economics.xml",
             ["article", ".text-article", ".article-content"]),
        ],
    ),
    "pt_be": (  # European Portuguese — PT
        "pt", "PT",
        re.compile(
            r"salário|salarios|ordenado|ganha|ganhos|freelancer|"
            r"reforma|FIRE",
            re.IGNORECASE,
        ),
        [
            ("rss_eco_sapo", "https://eco.sapo.pt/feed/",
             ["article", ".entry-content", ".post-content"]),
            ("rss_dinheirovivo", "https://www.dinheirovivo.pt/feed/",
             ["article", ".entry-content", ".article-content"]),
            ("rss_publico_eco", "https://www.publico.pt/rss/economia",
             ["article", ".story__body", ".story-body"]),
            ("rss_expresso_eco", "https://expresso.pt/rss-feed/economia",
             ["article", ".article-body", ".content"]),
        ],
    ),
    "nl_be": (  # Belgian Dutch — BE
        "nl", "BE",
        re.compile(
            r"salaris|salarissen|loon|lonen|inkomen|inkomsten|"
            r"freelancer|pensioen",
            re.IGNORECASE,
        ),
        [
            ("rss_demorgen_eco", "https://www.demorgen.be/economie/rss.xml",
             ["article", ".article__body", ".article-body"]),
            ("rss_standaard_eco", "https://www.standaard.be/cnt/economie/rss",
             ["article", ".article__body", ".article-body"]),
        ],
    ),
    "da": (  # Danish — DK
        "da", "DK",
        re.compile(
            r"løn|lønninger|indkomst|indkomster|freelance|pension|FIRE",
            re.IGNORECASE,
        ),
        [
            ("rss_politiken_business", "https://politiken.dk/rss/business.rss",
             ["article", ".article__body", ".article-body"]),
            ("rss_borsen", "https://borsen.dk/feed/articles",
             ["article", ".article-body", ".content"]),
            ("rss_berlingske_business", "https://www.berlingske.dk/business/rss",
             ["article", ".article-body", ".content"]),
        ],
    ),
    "no": (  # Norwegian — NO
        "no", "NO",
        re.compile(
            r"lønn|lønninger|inntekt|inntekter|freelance|pensjon",
            re.IGNORECASE,
        ),
        [
            ("rss_e24", "https://e24.no/rss",
             ["article", ".article-body", ".content"]),
            ("rss_aftenposten_okonomi", "https://www.aftenposten.no/rss/okonomi",
             ["article", ".article-body", ".content"]),
            ("rss_dn", "https://www.dn.no/rss",
             ["article", ".article-body", ".content"]),
        ],
    ),
}


def md5_16(*p): return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]
def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def polite(): time.sleep(random.uniform(*SLEEP))


ACCEPT_LANG = {
    "cs": "cs-CZ,cs;q=0.9,en;q=0.5",
    "hu": "hu-HU,hu;q=0.9,en;q=0.5",
    "ro": "ro-RO,ro;q=0.9,en;q=0.5",
    "uk": "uk-UA,uk;q=0.9,ru;q=0.6,en;q=0.5",
    "pt_be": "pt-PT,pt;q=0.9,en;q=0.5",
    "nl_be": "nl-BE,nl;q=0.9,fr;q=0.6,en;q=0.5",
    "da": "da-DK,da;q=0.9,en;q=0.5",
    "no": "nb-NO,no;q=0.9,nn;q=0.7,en;q=0.5",
}


def hdr(key: str):
    return {"User-Agent": UA, "Accept": "*/*", "Accept-Language": ACCEPT_LANG[key]}


def fetch(url: str, key: str, label: str = "") -> str | None:
    try:
        r = requests.get(url, headers=hdr(key), timeout=TIMEOUT, allow_redirects=True)
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
        p = it.find("pubDate") or it.find("published") or it.find("updated")
        title = t.get_text(strip=True) if t else ""
        if l:
            link = l.get("href") or l.get_text(strip=True) or ""
        else:
            link = ""
        guid = (g.get_text(strip=True) if g else "") or link
        desc = d.get_text(" ", strip=True) if d else ""
        author = a.get_text(strip=True) if a else ""
        pub = p.get_text(strip=True) if p else ""
        if title and link:
            out.append({
                "raw_id": guid, "title": title, "summary": desc,
                "link": link, "author": author, "pub": pub,
            })
    return out


def fetch_body(url: str, sel: list[str], key: str) -> str:
    html = fetch(url, key, label=f"body {urlparse(url).netloc}")
    if not html: return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "aside", "header", "footer"]):
        tag.decompose()
    for s in sel:
        try:
            el = soup.select_one(s)
        except Exception:
            el = None
        if el:
            txt = el.get_text(" ", strip=True)
            if len(txt) > 100:
                return txt[:5000]
    ps = [p.get_text(" ", strip=True) for p in soup.find_all("p")
          if len(p.get_text(strip=True)) > 20]
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


def crawl_key(key: str):
    lang_iso, country, kw_re, feeds = LANG_CONFIGS[key]
    out = Path(f"data/raw/rss_alt_{key}_native_{DAY}.jsonl")
    seen = load_seen(out)
    print(f"\n========== KEY={key} lang={lang_iso} country={country} ==========")
    print(f"  outfile: {out}")
    summary = []
    for name, url, sel in feeds:
        print(f"\n  --- {name} ({url}) ---")
        xml = fetch(url, key, label=name)
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
            body = fetch_body(it["link"], sel, key) or it["summary"]
            if not body or len(body) < 50: continue
            obj = {
                "id": rid,
                "raw_id": it["raw_id"],
                "platform": name,
                "lang": lang_iso,
                "title": it["title"][:300],
                "body": body[:5000],
                "author": it["author"],
                "url": it["link"],
                "country_hint": country,
                "matched_keyword": m.group(0),
                "pub_date": it.get("pub", ""),
                "engagement": {"score": 0, "comments": 0, "views": None},
                "crawled_at": now_iso(),
            }
            append(out, obj); seen.add(rid); written += 1
            polite()
        print(f"    matched={matched} written={written}")
        summary.append((name, len(items), matched, written))
        polite()
    final = sum(1 for _ in out.open(encoding="utf-8")) if out.exists() else 0
    print(f"\n  SUMMARY {key}:")
    for name, i, m, w in summary:
        print(f"    {name:<32} items={i:>4} matched={m:>4} written={w:>4}")
    print(f"  FILE TOTAL: {final}")
    return key, final, summary


def main():
    keys = ["cs", "hu", "ro", "uk", "pt_be", "nl_be", "da", "no"]
    totals = []
    grand = 0
    for k in keys:
        try:
            _, final, _ = crawl_key(k)
            totals.append((k, final))
            grand += final
        except Exception as e:
            print(f"[{k}] FATAL: {e}", file=sys.stderr)
            totals.append((k, 0))
    print(f"\n========== GRAND SUMMARY ==========")
    for k, n in totals:
        print(f"  {k:<8} -> {n}")
    print(f"  TOTAL: {grand}")


if __name__ == "__main__":
    main()
