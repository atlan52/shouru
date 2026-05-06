"""CEE (中欧/东欧) 本地非 Reddit 论坛 + 求职大站收入帖原文抓取。

目标站点（每国母语关键词过滤）:
  PL: Wykop.pl (社区) + Pracuj.pl (求职) + Forsal.pl Forum
  CZ: Profesia.cz (求职) + Zarplaty.cz (工资库) + Diskuze.iDnes.cz (论坛)
  HU: Profession.hu (求职) + HVG Forum + Origo Forum
  RO: eJobs.ro + BestJobs.eu + Salariu.ro
  UA: Work.ua + DOU.ua + Rabota.ua
  BG: JobS.bg + Zaplata.bg
  HR: MojPosao.net
  RS: Poslovi.infostud.com
  SI: MojeDelo.com

输出多文件 (data/raw/<platform>_native_<YYYYMMDD>.jsonl)，schema 同 r_mexico_native。
4xx/5xx 跳过；cloudflare 退本站；polite ~1.5s。
"""
import json, hashlib, re, sys, time, random
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, quote
import requests
from bs4 import BeautifulSoup

UA_BROWSER = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def hdr(lang):
    return {
        "User-Agent": UA_BROWSER,
        "Accept-Language": lang,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Cache-Control": "no-cache",
    }


HDR = {
    "PL": hdr("pl-PL,pl;q=0.9,en;q=0.5"),
    "CZ": hdr("cs-CZ,cs;q=0.9,en;q=0.5"),
    "HU": hdr("hu-HU,hu;q=0.9,en;q=0.5"),
    "RO": hdr("ro-RO,ro;q=0.9,en;q=0.5"),
    "UA": hdr("uk-UA,uk;q=0.9,ru;q=0.6,en;q=0.4"),
    "BG": hdr("bg-BG,bg;q=0.9,en;q=0.5"),
    "HR": hdr("hr-HR,hr;q=0.9,en;q=0.5"),
    "RS": hdr("sr-RS,sr;q=0.9,sh;q=0.7,en;q=0.5"),
    "SI": hdr("sl-SI,sl;q=0.9,en;q=0.5"),
}

DAY = datetime.now().strftime("%Y%m%d")

KEYWORDS = {
    "PL": ["pensja", "zarobki", "wynagrodzenie", "dochód", "dochod", "freelance",
           "etat", "fire", "umowa", "stawka", "zarabiam", "zarabiać", "brutto",
           "netto", "wypłata", "wyplata", "b2b"],
    "CZ": ["plat", "mzda", "příjem", "prijem", "výdělek", "vydelek", "freelance",
           "osvč", "osvc", "fire", "hrubého", "hruba", "čistého", "ciste"],
    "HU": ["fizetés", "fizetes", "jövedelem", "jovedelem", "kereset",
           "szabadúszó", "szabaduszo", "fire", "bér", "ber", "bruttó", "brutto",
           "nettó", "netto"],
    "RO": ["salariu", "salariul", "venit", "freelance", "fire", "pfa",
           "câștig", "castig", "lefă", "lefa", "brut", "net"],
    "UA": ["зарплата", "зарплати", "дохід", "доход", "заробіт", "заробiт",
           "заробіток", "фрілансер", "фрилансер", "fire", "оклад", "ставка"],
    "BG": ["заплата", "заплати", "доход", "freelance", "възнаграждение",
           "хонорар", "брутно", "нетно"],
    "HR": ["plaća", "placa", "dohodak", "freelance", "primanja", "honorar",
           "bruto", "neto", "fire"],
    "RS": ["plata", "плата", "prihod", "приход", "freelance", "honorar",
           "хонорар", "bruto", "neto", "fire"],
    "SI": ["plača", "placa", "dohodek", "freelance", "prihodek", "honorar",
           "bruto", "neto", "fire"],
}

PAGES_LIST = 3  # 每个起点翻 3 页（求职大站 2-3 页足够）


# ---------------- helpers ----------------

def md5_16(*p):
    return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def polite():
    time.sleep(random.uniform(1.3, 1.7))


def load_seen(path):
    seen = set()
    if path.exists():
        for line in path.open():
            try:
                seen.add(json.loads(line)["id"])
            except Exception:
                pass
    return seen


def is_cloudflare(html, status):
    if status in (403, 503) and re.search(
        r"cloudflare|cf-ray|attention required|just a moment", html, re.I
    ):
        return True
    low = html.lower()
    if "cf-chl" in low or "checking your browser" in low or "challenge-platform" in low:
        return True
    return False


def matched_kw(text, country):
    low = text.lower()
    for kw in KEYWORDS.get(country, []):
        if kw.lower() in low:
            return kw
    return None


def fetch(url, country, timeout=25):
    try:
        r = requests.get(url, headers=HDR[country], timeout=timeout)
    except Exception as e:
        return None, 0, str(e)
    return r, r.status_code, None


def text_of(el):
    return el.get_text(" ", strip=True) if el else ""


# ---------------- generic page-handler ----------------

def crawl_site(
    label, country, list_urls, parse_links, parse_detail, out_path,
    platform, max_threads_per_listing=40,
):
    """通用循环：listing → 链接 → 详情 → 关键词过滤 → 写盘。"""
    seen = load_seen(out_path)
    n_total = 0
    for list_url in list_urls:
        r, status, err = fetch(list_url, country)
        if err:
            print(f"[{label}] list err {list_url}: {err}")
            polite()
            continue
        if is_cloudflare(r.text, status):
            print(f"[{label}] {list_url} CLOUDFLARE — abort site", file=sys.stderr)
            return n_total
        if status >= 400:
            print(f"[{label}] list status={status} skip {list_url}")
            polite()
            continue
        links = parse_links(r.text, list_url)
        print(f"[{label}] list {list_url} -> {len(links)} links")
        if not links:
            sys.stderr.write(f"[{label}] 0 links from {list_url} — HTML head:\n")
            sys.stderr.write(r.text[:600] + "\n")
            sys.stderr.flush()
        polite()
        added = 0
        for tid, turl, ltitle in links[:max_threads_per_listing]:
            rid = md5_16(platform, tid)
            if rid in seen:
                continue
            rt, st, e2 = fetch(turl, country)
            if e2:
                print(f"[{label}] detail err {turl}: {e2}")
                polite()
                continue
            if is_cloudflare(rt.text, st):
                print(f"[{label}] detail CLOUDFLARE — abort site", file=sys.stderr)
                return n_total
            if st >= 400:
                polite()
                continue
            title, body, author = parse_detail(rt.text)
            if not title:
                title = ltitle
            combined = (title + " " + body).lower()
            kw = matched_kw(combined, country)
            if not kw:
                polite()
                continue
            obj = {
                "id": rid,
                "raw_id": tid,
                "platform": platform,
                "lang": country.lower(),
                "title": title[:500],
                "body": body[:5000],
                "author": author,
                "url": turl,
                "country_hint": country,
                "matched_keyword": kw,
                "engagement": {"score": 0, "comments": 0, "views": 0},
                "source_list": list_url,
                "crawled_at": now_iso(),
            }
            append(out_path, obj)
            seen.add(rid)
            n_total += 1
            added += 1
            polite()
        print(f"[{label}] {list_url} +{added} (total {n_total})")
    print(f"[{label}] DONE +{n_total}")
    return n_total


# =================================================================
# PL — Wykop.pl
# =================================================================

def wykop_links(html, base):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.select("a[href*='/wpis/']") + soup.select("a[href*='/link/']"):
        href = a.get("href", "")
        m = re.search(r"/(wpis|link)/(\d+)", href)
        if not m:
            continue
        tid = m.group(1) + ":" + m.group(2)
        if tid in seen:
            continue
        seen.add(tid)
        title = text_of(a)
        if len(title) < 4:
            continue
        out.append((tid, urljoin("https://wykop.pl/", href), title))
    return out


def wykop_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one("h1") or soup.select_one("h2")
    title = text_of(h1)
    body_el = (
        soup.select_one("article")
        or soup.select_one(".content")
        or soup.select_one("main")
    )
    body = text_of(body_el)
    author_el = soup.select_one("a[href*='/ludzie/']") or soup.select_one(".author")
    return title, body, text_of(author_el)


def crawl_wykop():
    starts = [f"https://wykop.pl/wpis/list/aktywne?page={p}" for p in range(1, 6)]
    starts += [f"https://wykop.pl/tag/zarobki/strona/{p}" for p in range(1, 4)]
    starts += [f"https://wykop.pl/tag/wynagrodzenie/strona/{p}" for p in range(1, 4)]
    starts += [f"https://wykop.pl/tag/pensja/strona/{p}" for p in range(1, 3)]
    out = Path(f"data/raw/wykop_native_{DAY}.jsonl")
    return crawl_site(
        "wykop", "PL", starts, wykop_links, wykop_detail, out, "wykop",
    )


# =================================================================
# PL — Pracuj.pl  (求职 listing)
# =================================================================

def pracuj_links(html, base):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.select("a[href*='/praca/'], a[href*='oferta']"):
        href = a.get("href", "")
        if "/praca/" not in href:
            continue
        m = re.search(r"/praca/[^?#]+,oferta,(\d+)", href)
        tid = m.group(1) if m else href
        tid = re.sub(r"\W+", "_", tid)[:60]
        if tid in seen:
            continue
        seen.add(tid)
        title = text_of(a)
        if len(title) < 5:
            continue
        out.append((tid, urljoin("https://www.pracuj.pl/", href), title))
    return out


def pracuj_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one("h1")
    title = text_of(h1)
    body_el = (
        soup.select_one("[data-test='offer-description']")
        or soup.select_one("[data-test='section-description']")
        or soup.select_one("article")
        or soup.select_one("main")
    )
    body = text_of(body_el)
    return title, body, ""


def crawl_pracuj():
    roles = ["programista", "lekarz", "nauczyciel", "kierowca", "ksiegowa",
             "specjalista", "sprzedawca", "manager"]
    starts = [
        f"https://www.pracuj.pl/praca/{r};kw?pn={p}"
        for r in roles for p in range(1, PAGES_LIST + 1)
    ]
    out = Path(f"data/raw/pracuj_native_{DAY}.jsonl")
    return crawl_site(
        "pracuj", "PL", starts, pracuj_links, pracuj_detail, out, "pracuj",
        max_threads_per_listing=15,
    )


# =================================================================
# PL — Forsal.pl Forum
# =================================================================

def forsal_links(html, base):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.select("a[href*='/forum/'], a[href*='wiadomosci'], a[href*='artykuly']"):
        href = a.get("href", "")
        if not (href.startswith("/") or "forsal.pl" in href):
            continue
        title = text_of(a)
        if len(title) < 6:
            continue
        tid = re.sub(r"\W+", "_", href)[-60:]
        if tid in seen:
            continue
        seen.add(tid)
        out.append((tid, urljoin("https://forsal.pl/", href), title))
    return out


def forsal_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one("h1")
    body_el = soup.select_one("article") or soup.select_one("main")
    return text_of(h1), text_of(body_el), ""


def crawl_forsal():
    starts = [
        "https://forsal.pl/praca",
        "https://forsal.pl/finanse",
        "https://forsal.pl/twoje-pieniadze",
    ]
    out = Path(f"data/raw/forsal_native_{DAY}.jsonl")
    return crawl_site(
        "forsal", "PL", starts, forsal_links, forsal_detail, out, "forsal",
        max_threads_per_listing=20,
    )


# =================================================================
# CZ — Profesia.cz (求职)
# =================================================================

def profesia_links(html, base):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.select("a[href*='/praca/'], a[href*='/ponuka/']"):
        href = a.get("href", "")
        m = re.search(r"/(praca|ponuka)/[^?#]+/O(\d+)", href) or \
            re.search(r"/(praca|ponuka)/(\d+)", href)
        tid = re.sub(r"\W+", "_", href)[-60:]
        if tid in seen:
            continue
        seen.add(tid)
        title = text_of(a)
        if len(title) < 5:
            continue
        out.append((tid, urljoin(base, href), title))
    return out


def profesia_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one("h1")
    body_el = (
        soup.select_one(".job-detail")
        or soup.select_one("article")
        or soup.select_one("main")
    )
    return text_of(h1), text_of(body_el), ""


def crawl_profesia():
    starts_cz = [f"https://www.profesia.cz/prace/?page_num={p}" for p in range(1, 4)]
    starts_sk = [f"https://www.profesia.sk/praca/?page_num={p}" for p in range(1, 3)]
    out = Path(f"data/raw/profesia_native_{DAY}.jsonl")
    return crawl_site(
        "profesia", "CZ", starts_cz + starts_sk, profesia_links, profesia_detail,
        out, "profesia", max_threads_per_listing=15,
    )


# =================================================================
# CZ — Zarplaty.cz (工资数据库)
# =================================================================

def zarplaty_links(html, base):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.select("a[href*='/pozice/'], a[href*='/firma/'], a[href]"):
        href = a.get("href", "")
        if not href.startswith("/") and "zarplaty.cz" not in href:
            continue
        if "/pozice/" not in href and "/firma/" not in href and "/odvetvi/" not in href:
            continue
        tid = re.sub(r"\W+", "_", href)[-60:]
        if tid in seen:
            continue
        seen.add(tid)
        title = text_of(a)
        if len(title) < 5:
            continue
        out.append((tid, urljoin("https://www.zarplaty.cz/", href), title))
    return out


def zarplaty_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one("h1")
    body_el = (
        soup.select_one(".profession-detail")
        or soup.select_one("article")
        or soup.select_one("main")
        or soup.select_one(".content")
    )
    return text_of(h1), text_of(body_el), ""


def crawl_zarplaty():
    starts = [
        "https://www.zarplaty.cz/",
        "https://www.zarplaty.cz/pozice/",
        "https://www.zarplaty.cz/odvetvi/",
    ]
    out = Path(f"data/raw/zarplaty_native_{DAY}.jsonl")
    return crawl_site(
        "zarplaty", "CZ", starts, zarplaty_links, zarplaty_detail, out, "zarplaty",
        max_threads_per_listing=25,
    )


# =================================================================
# CZ — Diskuze.iDnes.cz
# =================================================================

def idnes_links(html, base):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.select("a[href*='diskuze']") + soup.select("a"):
        href = a.get("href", "")
        if "diskuze" not in href:
            continue
        m = re.search(r"diskuze[^/]*\.idnes\.cz/.+", href)
        if not m and "diskuze.idnes.cz" not in href:
            continue
        tid = re.sub(r"\W+", "_", href)[-60:]
        if tid in seen:
            continue
        seen.add(tid)
        title = text_of(a)
        if len(title) < 6:
            continue
        out.append((tid, urljoin("https://diskuze.idnes.cz/", href), title))
    return out


def idnes_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one("h1")
    body_el = soup.select_one("article") or soup.select_one(".diskuse") or soup.select_one("main")
    return text_of(h1), text_of(body_el), ""


def crawl_idnes():
    starts = [
        "https://diskuze.idnes.cz/",
        "https://www.idnes.cz/finance",
        "https://www.idnes.cz/finance/prace",
    ]
    out = Path(f"data/raw/idnes_native_{DAY}.jsonl")
    return crawl_site(
        "idnes", "CZ", starts, idnes_links, idnes_detail, out, "idnes",
        max_threads_per_listing=25,
    )


# =================================================================
# HU — Profession.hu (求职)
# =================================================================

def profession_links(html, base):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.select("a[href*='/allas/'], a[href*='/allasok/']"):
        href = a.get("href", "")
        tid = re.sub(r"\W+", "_", href)[-60:]
        if tid in seen:
            continue
        seen.add(tid)
        title = text_of(a)
        if len(title) < 5:
            continue
        out.append((tid, urljoin("https://www.profession.hu/", href), title))
    return out


def profession_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one("h1")
    body_el = (
        soup.select_one(".job-description")
        or soup.select_one("article")
        or soup.select_one("main")
    )
    return text_of(h1), text_of(body_el), ""


def crawl_profession():
    starts = [
        f"https://www.profession.hu/allasok/{p}/0,,,," for p in range(1, 4)
    ] + [
        f"https://www.profession.hu/allasok?page={p}" for p in range(1, 3)
    ]
    out = Path(f"data/raw/profession_native_{DAY}.jsonl")
    return crawl_site(
        "profession", "HU", starts, profession_links, profession_detail,
        out, "profession", max_threads_per_listing=20,
    )


# =================================================================
# HU — HVG / Origo Forum
# =================================================================

def hvg_origo_links(html, base):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        if not href:
            continue
        # 只挑文章式深路径
        if not re.search(r"/\d{8,}", href) and not re.search(r"/(gazdasag|forum|allas|karrier)", href):
            continue
        tid = re.sub(r"\W+", "_", href)[-60:]
        if tid in seen:
            continue
        title = text_of(a)
        if len(title) < 8:
            continue
        seen.add(tid)
        out.append((tid, urljoin(base, href), title))
    return out


def article_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one("h1")
    body_el = soup.select_one("article") or soup.select_one("main") or soup.select_one(".article")
    return text_of(h1), text_of(body_el), ""


def crawl_hvg():
    starts = [
        "https://hvg.hu/gazdasag",
        "https://hvg.hu/karrier",
        "https://hvg.hu/gazdasag.allas",
    ]
    out = Path(f"data/raw/hvg_native_{DAY}.jsonl")
    return crawl_site(
        "hvg", "HU", starts, hvg_origo_links, article_detail, out, "hvg",
        max_threads_per_listing=25,
    )


def crawl_origo():
    starts = [
        "https://www.origo.hu/gazdasag/index.html",
        "https://www.origo.hu/allas/index.html",
    ]
    out = Path(f"data/raw/origo_native_{DAY}.jsonl")
    return crawl_site(
        "origo", "HU", starts, hvg_origo_links, article_detail, out, "origo",
        max_threads_per_listing=25,
    )


# =================================================================
# RO — eJobs.ro / BestJobs.eu / Salariu.ro
# =================================================================

def ejobs_links(html, base):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.select("a[href*='/loc-de-munca/'], a[href*='/locuri-de-munca/']"):
        href = a.get("href", "")
        tid = re.sub(r"\W+", "_", href)[-60:]
        if tid in seen:
            continue
        seen.add(tid)
        title = text_of(a)
        if len(title) < 5:
            continue
        out.append((tid, urljoin("https://www.ejobs.ro/", href), title))
    return out


def crawl_ejobs():
    starts = [f"https://www.ejobs.ro/locuri-de-munca/?page={p}" for p in range(1, 4)]
    out = Path(f"data/raw/ejobs_native_{DAY}.jsonl")
    return crawl_site(
        "ejobs", "RO", starts, ejobs_links, article_detail, out, "ejobs",
        max_threads_per_listing=20,
    )


def bestjobs_links(html, base):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.select("a[href*='/locuri-de-munca/'], a[href*='/anunt/'], a[href*='/jobs/']"):
        href = a.get("href", "")
        tid = re.sub(r"\W+", "_", href)[-60:]
        if tid in seen:
            continue
        seen.add(tid)
        title = text_of(a)
        if len(title) < 5:
            continue
        out.append((tid, urljoin("https://www.bestjobs.eu/", href), title))
    return out


def crawl_bestjobs():
    starts = [f"https://www.bestjobs.eu/ro/locuri-de-munca?page={p}" for p in range(1, 4)]
    out = Path(f"data/raw/bestjobs_native_{DAY}.jsonl")
    return crawl_site(
        "bestjobs", "RO", starts, bestjobs_links, article_detail, out, "bestjobs",
        max_threads_per_listing=20,
    )


def salariu_links(html, base):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        if not (re.search(r"/(profesie|industrie|salarii|salariu)/", href) or
                "salariu" in href):
            continue
        tid = re.sub(r"\W+", "_", href)[-60:]
        if tid in seen:
            continue
        title = text_of(a)
        if len(title) < 5:
            continue
        seen.add(tid)
        out.append((tid, urljoin(base, href), title))
    return out


def crawl_salariu_ro():
    starts = [
        "https://www.salariu.ro/",
        "https://www.salariu.ro/salarii-pe-profesii/",
        "https://www.salariu.ro/salarii-pe-industrie/",
    ]
    out = Path(f"data/raw/salariu_ro_native_{DAY}.jsonl")
    return crawl_site(
        "salariu_ro", "RO", starts, salariu_links, article_detail, out, "salariu_ro",
        max_threads_per_listing=25,
    )


# =================================================================
# UA — Work.ua / DOU.ua / rabota.ua
# =================================================================

def workua_links(html, base):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.select("a[href*='/jobs/']"):
        href = a.get("href", "")
        m = re.search(r"/jobs/(\d+)", href)
        if not m:
            continue
        tid = m.group(1)
        if tid in seen:
            continue
        seen.add(tid)
        title = text_of(a)
        if len(title) < 5:
            continue
        out.append((tid, urljoin("https://www.work.ua/", href), title))
    return out


def crawl_workua():
    roles = ["programmer", "lekar", "voditel", "buhgalter", "menedzher",
             "uchitel", "prodavets"]
    starts = [
        f"https://www.work.ua/jobs-{r}/?page={p}"
        for r in roles for p in range(1, PAGES_LIST + 1)
    ]
    starts += [f"https://www.work.ua/jobs/?page={p}" for p in range(1, 3)]
    out = Path(f"data/raw/workua_native_{DAY}.jsonl")
    return crawl_site(
        "workua", "UA", starts, workua_links, article_detail, out, "workua",
        max_threads_per_listing=15,
    )


def dou_links(html, base):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.select("a[href*='dou.ua']") + soup.select("a[href^='/lenta/']") + soup.select("a[href^='/forums/']") + soup.select("a[href^='/forum/']"):
        href = a.get("href", "")
        if not (("/lenta/" in href) or ("/forums/" in href) or ("/forum/" in href) or ("/columns/" in href) or ("/articles/" in href)):
            continue
        tid = re.sub(r"\W+", "_", href)[-60:]
        if tid in seen:
            continue
        title = text_of(a)
        if len(title) < 8:
            continue
        seen.add(tid)
        out.append((tid, urljoin("https://dou.ua/", href), title))
    return out


def crawl_dou():
    starts = [
        f"https://dou.ua/lenta/?page={p}" for p in range(1, 4)
    ] + [
        "https://dou.ua/lenta/articles/",
        "https://dou.ua/lenta/columns/",
        "https://dou.ua/forums/",
    ]
    out = Path(f"data/raw/dou_native_{DAY}.jsonl")
    return crawl_site(
        "dou", "UA", starts, dou_links, article_detail, out, "dou",
        max_threads_per_listing=25,
    )


def rabotaua_links(html, base):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.select("a[href*='/company'], a[href*='/notice'], a[href*='/zapros']"):
        href = a.get("href", "")
        tid = re.sub(r"\W+", "_", href)[-60:]
        if tid in seen:
            continue
        title = text_of(a)
        if len(title) < 5:
            continue
        seen.add(tid)
        out.append((tid, urljoin("https://rabota.ua/", href), title))
    return out


def crawl_rabotaua():
    starts = [
        f"https://rabota.ua/zapros/all?pg={p}" for p in range(1, 4)
    ] + [
        "https://rabota.ua/zapros/it",
        "https://rabota.ua/zapros/medicine",
    ]
    out = Path(f"data/raw/rabotaua_native_{DAY}.jsonl")
    return crawl_site(
        "rabotaua", "UA", starts, rabotaua_links, article_detail, out, "rabotaua",
        max_threads_per_listing=20,
    )


# =================================================================
# BG — JobS.bg / Zaplata.bg
# =================================================================

def jobsbg_links(html, base):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.select("a[href*='ad/'], a[href*='/job/'], a[href*='preview']"):
        href = a.get("href", "")
        tid = re.sub(r"\W+", "_", href)[-60:]
        if tid in seen:
            continue
        title = text_of(a)
        if len(title) < 5:
            continue
        seen.add(tid)
        out.append((tid, urljoin("https://www.jobs.bg/", href), title))
    return out


def crawl_jobsbg():
    starts = [
        "https://www.jobs.bg/",
        "https://www.jobs.bg/front_job_search.php",
    ] + [f"https://www.jobs.bg/front_job_search.php?p={p}" for p in range(1, 4)]
    out = Path(f"data/raw/jobsbg_native_{DAY}.jsonl")
    return crawl_site(
        "jobsbg", "BG", starts, jobsbg_links, article_detail, out, "jobsbg",
        max_threads_per_listing=20,
    )


def zaplata_links(html, base):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        if not ("/job/" in href or "/obyava" in href or "/profesia" in href or "/category" in href):
            continue
        tid = re.sub(r"\W+", "_", href)[-60:]
        if tid in seen:
            continue
        title = text_of(a)
        if len(title) < 5:
            continue
        seen.add(tid)
        out.append((tid, urljoin("https://www.zaplata.bg/", href), title))
    return out


def crawl_zaplata():
    starts = [
        "https://www.zaplata.bg/",
    ] + [f"https://www.zaplata.bg/index.php?stranica={p}" for p in range(1, 3)]
    out = Path(f"data/raw/zaplata_native_{DAY}.jsonl")
    return crawl_site(
        "zaplata", "BG", starts, zaplata_links, article_detail, out, "zaplata",
        max_threads_per_listing=20,
    )


# =================================================================
# HR — MojPosao.net / RS — Poslovi.infostud.com / SI — MojeDelo.com
# =================================================================

def generic_job_links(html, base, must_contain):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        if not any(m in href for m in must_contain):
            continue
        tid = re.sub(r"\W+", "_", href)[-60:]
        if tid in seen:
            continue
        title = text_of(a)
        if len(title) < 5:
            continue
        seen.add(tid)
        out.append((tid, urljoin(base, href), title))
    return out


def crawl_mojposao():
    starts = [
        f"https://www.moj-posao.net/Pretraga-Poslova/?page={p}" for p in range(1, 4)
    ] + ["https://www.moj-posao.net/Pretraga-Poslova/"]
    out = Path(f"data/raw/mojposao_native_{DAY}.jsonl")

    def links(html, base):
        return generic_job_links(html, base, ["/Posao/", "/posao/", "/Pretraga"])

    return crawl_site(
        "mojposao", "HR", starts, links, article_detail, out, "mojposao",
        max_threads_per_listing=20,
    )


def crawl_infostud():
    starts = [
        f"https://poslovi.infostud.com/oglasi-za-posao/?page={p}" for p in range(1, 4)
    ] + ["https://poslovi.infostud.com/"]
    out = Path(f"data/raw/infostud_native_{DAY}.jsonl")

    def links(html, base):
        return generic_job_links(html, base, ["/oglas-za-posao/", "/posao/", "/oglasi"])

    return crawl_site(
        "infostud", "RS", starts, links, article_detail, out, "infostud",
        max_threads_per_listing=20,
    )


def crawl_mojedelo():
    starts = [
        f"https://www.mojedelo.com/prosta-iskanja/?stran={p}" for p in range(1, 4)
    ] + ["https://www.mojedelo.com/"]
    out = Path(f"data/raw/mojedelo_native_{DAY}.jsonl")

    def links(html, base):
        return generic_job_links(html, base, ["/delo/", "/prosto-delo/", "/iskanja"])

    return crawl_site(
        "mojedelo", "SI", starts, links, article_detail, out, "mojedelo",
        max_threads_per_listing=20,
    )


# =================================================================
# main
# =================================================================

CRAWLERS = [
    ("wykop", crawl_wykop),
    ("pracuj", crawl_pracuj),
    ("forsal", crawl_forsal),
    ("profesia", crawl_profesia),
    ("zarplaty", crawl_zarplaty),
    ("idnes", crawl_idnes),
    ("profession", crawl_profession),
    ("hvg", crawl_hvg),
    ("origo", crawl_origo),
    ("ejobs", crawl_ejobs),
    ("bestjobs", crawl_bestjobs),
    ("salariu_ro", crawl_salariu_ro),
    ("workua", crawl_workua),
    ("dou", crawl_dou),
    ("rabotaua", crawl_rabotaua),
    ("jobsbg", crawl_jobsbg),
    ("zaplata", crawl_zaplata),
    ("mojposao", crawl_mojposao),
    ("infostud", crawl_infostud),
    ("mojedelo", crawl_mojedelo),
]


def count_lines(p):
    if not p.exists():
        return 0
    return sum(1 for _ in p.open(encoding="utf-8"))


if __name__ == "__main__":
    results = []
    for name, fn in CRAWLERS:
        try:
            n = fn()
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"[{name}] FATAL: {e}", file=sys.stderr)
            n = 0
        results.append((name, n))

    print("\n" + "=" * 60)
    print("CEE forums summary")
    print("=" * 60)
    grand = 0
    for name, n in results:
        path = Path(f"data/raw/{name}_native_{DAY}.jsonl")
        lines = count_lines(path)
        grand += n
        print(f"  {name:14s}  +{n:4d} new   (file total {lines})")
    print(f"GRAND TOTAL new rows: {grand}")
