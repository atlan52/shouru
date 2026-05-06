"""法语 + 意大利语本地 forum (非 Reddit) 收入帖直接抓取。

FR sites: forum.hardware.fr, doctissimo.fr, boursorama.com forum, jeuxvideo.com forum, lavieimmo.com
IT sites: finanzaonline.com, investireoggi.it, forum.tomshw.it, money.it forum
"""
import json, hashlib, re, time, random
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HDR_FR = {
    "User-Agent": UA,
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
HDR_IT = {
    "User-Agent": UA,
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

DAY = datetime.now().strftime("%Y%m%d")
RAW = Path("data/raw")

KW_FR = [
    "salaire", "rémunération", "remuneration", "smic", "gagne", "gagner",
    "freelance", "indépendant", "independant", "retraite", "FIRE",
    "livret A", "prime", "revenu", "revenus", "patrimoine", "épargne",
    "rente", "dividende", "dividendes", "loyer", "loyers", "auto-entrepreneur",
]
KW_IT = [
    "stipendio", "stipendi", "salario", "guadagn", "RAL", "freelance",
    "partita IVA", "pensione", "FIRE", "dividendi", "rendita", "reddito",
    "redditi", "affitto", "affitti", "investiment", "risparmio",
]

# regex versions for matching (case-insensitive)
RE_FR = re.compile("|".join(re.escape(k) for k in KW_FR), re.I)
RE_IT = re.compile("|".join(re.escape(k) for k in KW_IT), re.I)


def md5_16(*p): return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]
def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def append(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
def polite(a=1.2, b=1.8): time.sleep(random.uniform(a, b))


def load_seen(path):
    seen = set()
    if path.exists():
        for line in path.open():
            try: seen.add(json.loads(line)["id"])
            except: pass
    return seen


def safe_get(url, hdr, timeout=25):
    """Returns (status, text). Cloudflare/4xx/5xx returns (status, '')."""
    try:
        r = requests.get(url, headers=hdr, timeout=timeout)
        text = r.text or ""
        # cloudflare detection
        if r.status_code in (403, 503) and ("cloudflare" in text.lower() or "cf-ray" in (r.headers.get("server", "") + "").lower()):
            return ("cf", "")
        if r.status_code >= 400:
            return (r.status_code, "")
        return (200, text)
    except Exception as e:
        return (-1, str(e))


def make_obj(platform, lang, country, raw_id, title, body, url, author, kw, extra=None):
    rid = md5_16(platform, raw_id)
    obj = {
        "id": rid,
        "raw_id": raw_id,
        "platform": platform,
        "lang": lang,
        "title": title,
        "body": (body or "")[:5000],
        "author": author or "",
        "url": url,
        "country_hint": country,
        "matched_keyword": kw,
        "engagement": {"score": 0, "comments": 0, "views": None},
        "crawled_at": now_iso(),
    }
    if extra:
        obj.update(extra)
    return rid, obj


# =========================================================================
# 1. forum.hardware.fr
# =========================================================================
def crawl_hardware_fr():
    out = RAW / f"forum_hardware_fr_native_{DAY}.jsonl"
    seen = load_seen(out)
    n = 0
    cats = [
        ("Discussions", "Argent"),
        ("Discussions", "Boulot"),
    ]
    first_dump_done = False
    for parent, sub in cats:
        for page in range(1, 4):
            list_url = f"https://forum.hardware.fr/hfr/{parent}/{sub}/liste_sujet-{page}.htm"
            st, html = safe_get(list_url, HDR_FR)
            if st != 200:
                print(f"[hardware.fr] list {parent}/{sub} p={page} status={st}; skip")
                polite(); continue
            soup = BeautifulSoup(html, "html.parser")
            # thread links: <a class="cCatTopic" href="/hfr/Discussions/Argent/...-id.htm">
            links = soup.select("a.cCatTopic, td.sujetCase3 a, a[href*='-sujet']")
            uniq = []
            seen_u = set()
            for a in links:
                href = a.get("href", "") or ""
                if not href: continue
                full = urljoin(list_url, href)
                if "forum.hardware.fr" not in full: continue
                if "liste_sujet" in full: continue
                if full in seen_u: continue
                seen_u.add(full)
                uniq.append((a.get_text(" ", strip=True), full))
            if not uniq and not first_dump_done and page == 1:
                print(f"[hardware.fr] {parent}/{sub} p1 ZERO threads. HTML dump:")
                print(html[:800])
                first_dump_done = True
            print(f"[hardware.fr] {parent}/{sub} p={page} threads={len(uniq)}")
            picked = 0
            for tt, turl in uniq[:25]:
                # KW filter on title; if no match, still fetch a sample (limit) — but to keep relevant skip non-match
                if tt and not RE_FR.search(tt):
                    continue
                # fetch detail
                st2, html2 = safe_get(turl, HDR_FR)
                polite()
                if st2 != 200:
                    continue
                s2 = BeautifulSoup(html2, "html.parser")
                title = (s2.find("title").get_text(" ", strip=True) if s2.find("title") else tt) or tt
                # First post body
                msg = (
                    s2.select_one(".messagetable .MessageContent")
                    or s2.select_one(".MessageContent")
                    or s2.select_one(".message")
                    or s2.select_one("td.messCase2")
                )
                body = msg.get_text(" ", strip=True) if msg else ""
                if not body or len(body) < 30:
                    # fallback: any cell with text
                    body = s2.get_text(" ", strip=True)[:3000]
                if not RE_FR.search(title + " " + body[:1500]):
                    continue
                m = re.search(r"/(\d+)\.htm", turl) or re.search(r"-(\d+)_\d+\.htm", turl)
                raw_id = m.group(1) if m else turl
                rid, obj = make_obj("forum_hardware_fr", "fr", "FR", raw_id, title, body, turl, "", "", extra={"section": f"{parent}/{sub}"})
                if rid in seen: continue
                kw_match = RE_FR.search(title + " " + body[:1500])
                obj["matched_keyword"] = kw_match.group(0) if kw_match else ""
                append(out, obj); seen.add(rid); n += 1; picked += 1
            print(f"[hardware.fr] {parent}/{sub} p={page} picked={picked} total={n}")
            polite()
    print(f"[hardware.fr] DONE +{n}")
    return n, out


# =========================================================================
# 2. doctissimo.fr forum (Société > Argent finances)
# =========================================================================
def crawl_doctissimo():
    out = RAW / f"doctissimo_native_{DAY}.jsonl"
    seen = load_seen(out)
    n = 0
    base = "https://forum.doctissimo.fr"
    pages = [
        f"{base}/societe/argent-finances-2-1-list.htm",
        f"{base}/societe/argent-finances-2-2-list.htm",
        f"{base}/societe/argent-finances-2-3-list.htm",
    ]
    first_dump_done = False
    for i, list_url in enumerate(pages, start=1):
        st, html = safe_get(list_url, HDR_FR)
        if st != 200:
            print(f"[doctissimo] p={i} status={st}; skip")
            polite(); continue
        soup = BeautifulSoup(html, "html.parser")
        # thread links: typical pattern /societe/<slug>-sujet_xxx_1.htm
        links = soup.select("a[href*='sujet_']")
        uniq = []
        seen_u = set()
        for a in links:
            href = a.get("href", "") or ""
            full = urljoin(list_url, href)
            if "forum.doctissimo.fr" not in full: continue
            if full in seen_u: continue
            seen_u.add(full)
            uniq.append((a.get_text(" ", strip=True), full))
        if not uniq and not first_dump_done and i == 1:
            print(f"[doctissimo] p1 ZERO threads. HTML dump:")
            print(html[:800]); first_dump_done = True
        print(f"[doctissimo] p={i} threads={len(uniq)}")
        picked = 0
        for tt, turl in uniq[:25]:
            if tt and not RE_FR.search(tt):
                continue
            st2, html2 = safe_get(turl, HDR_FR)
            polite()
            if st2 != 200: continue
            s2 = BeautifulSoup(html2, "html.parser")
            title = (s2.find("title").get_text(" ", strip=True) if s2.find("title") else tt) or tt
            msg = (
                s2.select_one(".message-text")
                or s2.select_one(".MessageContent")
                or s2.select_one(".message")
                or s2.select_one("article")
            )
            body = msg.get_text(" ", strip=True) if msg else s2.get_text(" ", strip=True)[:3000]
            if not RE_FR.search(title + " " + body[:1500]):
                continue
            m = re.search(r"sujet_(\d+)", turl)
            raw_id = m.group(1) if m else turl
            rid, obj = make_obj("doctissimo", "fr", "FR", raw_id, title, body, turl, "", "")
            if rid in seen: continue
            kw_match = RE_FR.search(title + " " + body[:1500])
            obj["matched_keyword"] = kw_match.group(0) if kw_match else ""
            append(out, obj); seen.add(rid); n += 1; picked += 1
        print(f"[doctissimo] p={i} picked={picked} total={n}")
        polite()
    print(f"[doctissimo] DONE +{n}")
    return n, out


# =========================================================================
# 3. boursorama.com forum
# =========================================================================
def crawl_boursorama():
    out = RAW / f"boursorama_native_{DAY}.jsonl"
    seen = load_seen(out)
    n = 0
    base = "https://www.boursorama.com"
    # Try a few entry pages
    pages = [
        f"{base}/forum/",
        f"{base}/forum/2/",
        f"{base}/forum/3/",
    ]
    first_dump_done = False
    for i, list_url in enumerate(pages, start=1):
        st, html = safe_get(list_url, HDR_FR)
        if st != 200:
            print(f"[boursorama] p={i} status={st}; skip")
            polite(); continue
        soup = BeautifulSoup(html, "html.parser")
        # Boursorama forum threads typically /forum-message/...-XXXXXX
        links = soup.select("a[href*='/forum-']")
        uniq = []
        seen_u = set()
        for a in links:
            href = a.get("href", "") or ""
            full = urljoin(list_url, href)
            if "boursorama.com" not in full: continue
            if "/forum/" in full and "/forum-" not in full: continue
            if full in seen_u: continue
            seen_u.add(full)
            uniq.append((a.get_text(" ", strip=True), full))
        if not uniq and not first_dump_done and i == 1:
            print(f"[boursorama] p1 ZERO threads. HTML dump:")
            print(html[:800]); first_dump_done = True
        print(f"[boursorama] p={i} threads={len(uniq)}")
        picked = 0
        for tt, turl in uniq[:25]:
            if tt and not RE_FR.search(tt):
                # boursorama titles often include ticker — fetch anyway if obvious salary topic
                continue
            st2, html2 = safe_get(turl, HDR_FR)
            polite()
            if st2 != 200: continue
            s2 = BeautifulSoup(html2, "html.parser")
            title = (s2.find("title").get_text(" ", strip=True) if s2.find("title") else tt) or tt
            msg = (
                s2.select_one(".c-faq__answer")
                or s2.select_one("[class*=forum-message]")
                or s2.select_one("article")
                or s2.select_one("main")
            )
            body = msg.get_text(" ", strip=True) if msg else s2.get_text(" ", strip=True)[:3000]
            if not RE_FR.search(title + " " + body[:1500]):
                continue
            m = re.search(r"-(\d+)/?$", turl) or re.search(r"/(\d+)$", turl)
            raw_id = m.group(1) if m else turl
            rid, obj = make_obj("boursorama", "fr", "FR", raw_id, title, body, turl, "", "")
            if rid in seen: continue
            kw_match = RE_FR.search(title + " " + body[:1500])
            obj["matched_keyword"] = kw_match.group(0) if kw_match else ""
            append(out, obj); seen.add(rid); n += 1; picked += 1
        print(f"[boursorama] p={i} picked={picked} total={n}")
        polite()
    print(f"[boursorama] DONE +{n}")
    return n, out


# =========================================================================
# 4. jeuxvideo.com forum 18-25
# =========================================================================
def crawl_jvc():
    out = RAW / f"jvc_native_{DAY}.jsonl"
    seen = load_seen(out)
    n = 0
    base = "https://www.jeuxvideo.com"
    pages = [
        f"{base}/forums/0-51-0-1-0-1-0-blabla-18-25-ans.htm",
        f"{base}/forums/0-51-0-1-0-2-0-blabla-18-25-ans.htm",
        f"{base}/forums/0-51-0-1-0-3-0-blabla-18-25-ans.htm",
    ]
    first_dump_done = False
    for i, list_url in enumerate(pages, start=1):
        st, html = safe_get(list_url, HDR_FR)
        if st != 200:
            print(f"[jvc] p={i} status={st}; skip")
            polite(); continue
        soup = BeautifulSoup(html, "html.parser")
        # JVC thread links: /forums/42-51-XXX-1-0-1-0-...htm
        links = soup.select("a[href*='/forums/42-']")
        uniq = []
        seen_u = set()
        for a in links:
            href = a.get("href", "") or ""
            full = urljoin(list_url, href)
            if "jeuxvideo.com" not in full: continue
            if full in seen_u: continue
            seen_u.add(full)
            uniq.append((a.get_text(" ", strip=True), full))
        if not uniq and not first_dump_done and i == 1:
            print(f"[jvc] p1 ZERO threads. HTML dump:")
            print(html[:800]); first_dump_done = True
        print(f"[jvc] p={i} threads={len(uniq)}")
        picked = 0
        for tt, turl in uniq[:30]:
            if tt and not RE_FR.search(tt):
                continue
            st2, html2 = safe_get(turl, HDR_FR)
            polite()
            if st2 != 200: continue
            s2 = BeautifulSoup(html2, "html.parser")
            title = (s2.find("title").get_text(" ", strip=True) if s2.find("title") else tt) or tt
            msg = (
                s2.select_one(".bloc-contenu .txt-msg")
                or s2.select_one(".txt-msg")
                or s2.select_one(".bloc-message-forum-msg")
                or s2.select_one("article")
            )
            body = msg.get_text(" ", strip=True) if msg else s2.get_text(" ", strip=True)[:3000]
            if not RE_FR.search(title + " " + body[:1500]):
                continue
            m = re.search(r"/forums/42-51-(\d+)", turl)
            raw_id = m.group(1) if m else turl
            rid, obj = make_obj("jvc", "fr", "FR", raw_id, title, body, turl, "", "")
            if rid in seen: continue
            kw_match = RE_FR.search(title + " " + body[:1500])
            obj["matched_keyword"] = kw_match.group(0) if kw_match else ""
            append(out, obj); seen.add(rid); n += 1; picked += 1
        print(f"[jvc] p={i} picked={picked} total={n}")
        polite()
    print(f"[jvc] DONE +{n}")
    return n, out


# =========================================================================
# 5. lavieimmo.com (salaires immobilier)
# =========================================================================
def crawl_lavieimmo():
    out = RAW / f"lavieimmo_native_{DAY}.jsonl"
    seen = load_seen(out)
    n = 0
    # entry candidates
    pages = [
        "https://www.lavieimmo.com/forum/",
        "https://www.lavieimmo.com/forum/index.php",
        "https://www.lavieimmo.com/forum/?page=2",
    ]
    first_dump_done = False
    for i, list_url in enumerate(pages, start=1):
        st, html = safe_get(list_url, HDR_FR)
        if st != 200:
            print(f"[lavieimmo] p={i} status={st}; skip")
            polite(); continue
        soup = BeautifulSoup(html, "html.parser")
        links = soup.select("a[href*='/forum/']")
        uniq = []
        seen_u = set()
        for a in links:
            href = a.get("href", "") or ""
            full = urljoin(list_url, href)
            if "lavieimmo.com" not in full: continue
            if full.rstrip("/").endswith("/forum"): continue
            if full in seen_u: continue
            seen_u.add(full)
            uniq.append((a.get_text(" ", strip=True), full))
        if not uniq and not first_dump_done and i == 1:
            print(f"[lavieimmo] p1 ZERO threads. HTML dump:")
            print(html[:800]); first_dump_done = True
        print(f"[lavieimmo] p={i} threads={len(uniq)}")
        picked = 0
        for tt, turl in uniq[:25]:
            if tt and not RE_FR.search(tt):
                continue
            st2, html2 = safe_get(turl, HDR_FR)
            polite()
            if st2 != 200: continue
            s2 = BeautifulSoup(html2, "html.parser")
            title = (s2.find("title").get_text(" ", strip=True) if s2.find("title") else tt) or tt
            msg = (
                s2.select_one(".message-content")
                or s2.select_one(".post-content")
                or s2.select_one("article")
                or s2.select_one("main")
            )
            body = msg.get_text(" ", strip=True) if msg else s2.get_text(" ", strip=True)[:3000]
            if not RE_FR.search(title + " " + body[:1500]):
                continue
            raw_id = urlparse(turl).path
            rid, obj = make_obj("lavieimmo", "fr", "FR", raw_id, title, body, turl, "", "")
            if rid in seen: continue
            kw_match = RE_FR.search(title + " " + body[:1500])
            obj["matched_keyword"] = kw_match.group(0) if kw_match else ""
            append(out, obj); seen.add(rid); n += 1; picked += 1
        print(f"[lavieimmo] p={i} picked={picked} total={n}")
        polite()
    print(f"[lavieimmo] DONE +{n}")
    return n, out


# =========================================================================
# 6. finanzaonline.com
# =========================================================================
def crawl_finanzaonline():
    out = RAW / f"finanzaonline_native_{DAY}.jsonl"
    seen = load_seen(out)
    n = 0
    base = "https://www.finanzaonline.com"
    # the forum index lists subforums; we crawl 'recenti' (latest) + a few subforums
    pages = [
        f"{base}/forum/",
        f"{base}/forum/forums/economia-e-politica.51/",
        f"{base}/forum/forums/risparmio-pensioni-e-fondi.5/",
    ]
    first_dump_done = False
    for i, list_url in enumerate(pages, start=1):
        st, html = safe_get(list_url, HDR_IT)
        if st != 200:
            print(f"[finanzaonline] p={i} status={st}; skip")
            polite(); continue
        soup = BeautifulSoup(html, "html.parser")
        # XenForo: a.PreviewTooltip / a.structItem-title / a[data-tp-primary="on"]
        links = soup.select("a[href*='/forum/threads/']")
        uniq = []
        seen_u = set()
        for a in links:
            href = a.get("href", "") or ""
            full = urljoin(list_url, href)
            if "finanzaonline.com" not in full: continue
            if "/page-" in full or "/post-" in full: continue
            if full in seen_u: continue
            seen_u.add(full)
            uniq.append((a.get_text(" ", strip=True), full))
        if not uniq and not first_dump_done and i == 1:
            print(f"[finanzaonline] p1 ZERO threads. HTML dump:")
            print(html[:800]); first_dump_done = True
        print(f"[finanzaonline] p={i} threads={len(uniq)}")
        picked = 0
        for tt, turl in uniq[:25]:
            if tt and not RE_IT.search(tt):
                continue
            st2, html2 = safe_get(turl, HDR_IT)
            polite()
            if st2 != 200: continue
            s2 = BeautifulSoup(html2, "html.parser")
            title = (s2.find("title").get_text(" ", strip=True) if s2.find("title") else tt) or tt
            msg = (
                s2.select_one(".bbWrapper")
                or s2.select_one(".message-body")
                or s2.select_one(".messageContent")
                or s2.select_one("article")
            )
            body = msg.get_text(" ", strip=True) if msg else s2.get_text(" ", strip=True)[:3000]
            if not RE_IT.search(title + " " + body[:1500]):
                continue
            m = re.search(r"/threads/([^/]+)", turl)
            raw_id = m.group(1) if m else turl
            rid, obj = make_obj("finanzaonline", "it", "IT", raw_id, title, body, turl, "", "")
            if rid in seen: continue
            kw_match = RE_IT.search(title + " " + body[:1500])
            obj["matched_keyword"] = kw_match.group(0) if kw_match else ""
            append(out, obj); seen.add(rid); n += 1; picked += 1
        print(f"[finanzaonline] p={i} picked={picked} total={n}")
        polite()
    print(f"[finanzaonline] DONE +{n}")
    return n, out


# =========================================================================
# 7. investireoggi.it
# =========================================================================
def crawl_investireoggi():
    out = RAW / f"investireoggi_native_{DAY}.jsonl"
    seen = load_seen(out)
    n = 0
    base = "https://www.investireoggi.it"
    pages = [
        f"{base}/forum/",
        f"{base}/forum/forums/lavoro-e-pensioni.121/",
        f"{base}/forum/forums/economia.45/",
    ]
    first_dump_done = False
    for i, list_url in enumerate(pages, start=1):
        st, html = safe_get(list_url, HDR_IT)
        if st != 200:
            print(f"[investireoggi] p={i} status={st}; skip")
            polite(); continue
        soup = BeautifulSoup(html, "html.parser")
        links = soup.select("a[href*='/forum/threads/'], a[href*='/forum/topic']")
        uniq = []
        seen_u = set()
        for a in links:
            href = a.get("href", "") or ""
            full = urljoin(list_url, href)
            if "investireoggi.it" not in full: continue
            if "/page-" in full or "/post-" in full: continue
            if full in seen_u: continue
            seen_u.add(full)
            uniq.append((a.get_text(" ", strip=True), full))
        if not uniq and not first_dump_done and i == 1:
            print(f"[investireoggi] p1 ZERO threads. HTML dump:")
            print(html[:800]); first_dump_done = True
        print(f"[investireoggi] p={i} threads={len(uniq)}")
        picked = 0
        for tt, turl in uniq[:25]:
            if tt and not RE_IT.search(tt):
                continue
            st2, html2 = safe_get(turl, HDR_IT)
            polite()
            if st2 != 200: continue
            s2 = BeautifulSoup(html2, "html.parser")
            title = (s2.find("title").get_text(" ", strip=True) if s2.find("title") else tt) or tt
            msg = (
                s2.select_one(".bbWrapper")
                or s2.select_one(".message-body")
                or s2.select_one(".messageContent")
                or s2.select_one("article")
            )
            body = msg.get_text(" ", strip=True) if msg else s2.get_text(" ", strip=True)[:3000]
            if not RE_IT.search(title + " " + body[:1500]):
                continue
            m = re.search(r"/threads/([^/]+)", turl)
            raw_id = m.group(1) if m else turl
            rid, obj = make_obj("investireoggi", "it", "IT", raw_id, title, body, turl, "", "")
            if rid in seen: continue
            kw_match = RE_IT.search(title + " " + body[:1500])
            obj["matched_keyword"] = kw_match.group(0) if kw_match else ""
            append(out, obj); seen.add(rid); n += 1; picked += 1
        print(f"[investireoggi] p={i} picked={picked} total={n}")
        polite()
    print(f"[investireoggi] DONE +{n}")
    return n, out


# =========================================================================
# 8. forum.tomshw.it  Lavoro/Freelance/Stipendi
# =========================================================================
def crawl_tomshw_it():
    out = RAW / f"tomshw_it_native_{DAY}.jsonl"
    seen = load_seen(out)
    n = 0
    base = "https://forum.tomshw.it"
    pages = [
        f"{base}/forums/lavoro-freelance-stipendi/",
        f"{base}/forums/lavoro-freelance-stipendi/page-2",
        f"{base}/forums/lavoro-freelance-stipendi/page-3",
    ]
    first_dump_done = False
    for i, list_url in enumerate(pages, start=1):
        st, html = safe_get(list_url, HDR_IT)
        if st != 200:
            print(f"[tomshw_it] p={i} status={st}; skip")
            polite(); continue
        soup = BeautifulSoup(html, "html.parser")
        links = soup.select("a[href*='/threads/']")
        uniq = []
        seen_u = set()
        for a in links:
            href = a.get("href", "") or ""
            full = urljoin(list_url, href)
            if "forum.tomshw.it" not in full: continue
            if "/page-" in full or "/post-" in full: continue
            if full in seen_u: continue
            seen_u.add(full)
            uniq.append((a.get_text(" ", strip=True), full))
        if not uniq and not first_dump_done and i == 1:
            print(f"[tomshw_it] p1 ZERO threads. HTML dump:")
            print(html[:800]); first_dump_done = True
        print(f"[tomshw_it] p={i} threads={len(uniq)}")
        picked = 0
        for tt, turl in uniq[:30]:
            # this section is ALL about jobs/salary so we relax kw filter on title
            st2, html2 = safe_get(turl, HDR_IT)
            polite()
            if st2 != 200: continue
            s2 = BeautifulSoup(html2, "html.parser")
            title = (s2.find("title").get_text(" ", strip=True) if s2.find("title") else tt) or tt
            msg = (
                s2.select_one(".bbWrapper")
                or s2.select_one(".message-body")
                or s2.select_one(".messageContent")
                or s2.select_one("article")
            )
            body = msg.get_text(" ", strip=True) if msg else s2.get_text(" ", strip=True)[:3000]
            if not RE_IT.search(title + " " + body[:2000]):
                continue
            m = re.search(r"/threads/([^/]+)", turl)
            raw_id = m.group(1) if m else turl
            rid, obj = make_obj("tomshw_it", "it", "IT", raw_id, title, body, turl, "", "")
            if rid in seen: continue
            kw_match = RE_IT.search(title + " " + body[:2000])
            obj["matched_keyword"] = kw_match.group(0) if kw_match else ""
            append(out, obj); seen.add(rid); n += 1; picked += 1
        print(f"[tomshw_it] p={i} picked={picked} total={n}")
        polite()
    print(f"[tomshw_it] DONE +{n}")
    return n, out


# =========================================================================
# 9. money.it forum/articoli
# =========================================================================
def crawl_money_it():
    out = RAW / f"money_it_native_{DAY}.jsonl"
    seen = load_seen(out)
    n = 0
    # money.it doesn't really run a forum but has "forum" search results & community pages.
    # Try the forum tag URLs and the q&a section.
    pages = [
        "https://www.money.it/forum",
        "https://www.money.it/forum/",
        "https://www.money.it/-Community-?page=1",
        "https://www.money.it/-Community-?page=2",
    ]
    first_dump_done = False
    for i, list_url in enumerate(pages, start=1):
        st, html = safe_get(list_url, HDR_IT)
        if st != 200:
            print(f"[money.it] p={i} status={st}; skip")
            polite(); continue
        soup = BeautifulSoup(html, "html.parser")
        # Just grab any internal article-style link
        links = soup.select("a[href]")
        uniq = []
        seen_u = set()
        for a in links:
            href = a.get("href", "") or ""
            if not href: continue
            full = urljoin(list_url, href)
            if "money.it" not in full: continue
            # filter by likely article paths
            path = urlparse(full).path
            if not (path.endswith(".html") or "/forum/" in path or "/community" in path.lower()): continue
            if full in seen_u: continue
            seen_u.add(full)
            txt = a.get_text(" ", strip=True)
            if not txt or len(txt) < 8: continue
            uniq.append((txt, full))
        if not uniq and not first_dump_done and i == 1:
            print(f"[money.it] p1 ZERO threads. HTML dump:")
            print(html[:800]); first_dump_done = True
        print(f"[money.it] p={i} threads={len(uniq)}")
        picked = 0
        for tt, turl in uniq[:25]:
            if tt and not RE_IT.search(tt):
                continue
            st2, html2 = safe_get(turl, HDR_IT)
            polite()
            if st2 != 200: continue
            s2 = BeautifulSoup(html2, "html.parser")
            title = (s2.find("title").get_text(" ", strip=True) if s2.find("title") else tt) or tt
            msg = (
                s2.select_one("article")
                or s2.select_one(".article-body")
                or s2.select_one(".content")
                or s2.select_one("main")
            )
            body = msg.get_text(" ", strip=True) if msg else s2.get_text(" ", strip=True)[:3000]
            if not RE_IT.search(title + " " + body[:1500]):
                continue
            raw_id = urlparse(turl).path
            rid, obj = make_obj("money_it", "it", "IT", raw_id, title, body, turl, "", "")
            if rid in seen: continue
            kw_match = RE_IT.search(title + " " + body[:1500])
            obj["matched_keyword"] = kw_match.group(0) if kw_match else ""
            append(out, obj); seen.add(rid); n += 1; picked += 1
        print(f"[money.it] p={i} picked={picked} total={n}")
        polite()
    print(f"[money.it] DONE +{n}")
    return n, out


def print_samples(path, label, k=3):
    if not path.exists():
        print(f"[{label}] file missing: {path}")
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    print(f"\n=== {label}: {path} | {len(lines)} lines ===")
    for ln in lines[:k]:
        try:
            o = json.loads(ln)
            t = (o.get("title") or "").replace("\n", " ")[:120]
            b = (o.get("body") or "").replace("\n", " ")[:200]
            print(f"  - kw={o.get('matched_keyword')!r} | {t}")
            print(f"    body: {b}...")
        except Exception as e:
            print(f"  parse err: {e}")
    return len(lines)


if __name__ == "__main__":
    results = []
    for fn, label in [
        (crawl_hardware_fr, "hardware.fr"),
        (crawl_doctissimo, "doctissimo"),
        (crawl_boursorama, "boursorama"),
        (crawl_jvc, "jvc"),
        (crawl_lavieimmo, "lavieimmo"),
        (crawl_finanzaonline, "finanzaonline"),
        (crawl_investireoggi, "investireoggi"),
        (crawl_tomshw_it, "tomshw_it"),
        (crawl_money_it, "money_it"),
    ]:
        try:
            n, path = fn()
            results.append((label, n, path))
        except Exception as e:
            print(f"[{label}] FATAL: {e}")
            results.append((label, 0, None))

    print("\n\n========== SUMMARY ==========")
    total = 0
    for label, n, path in results:
        if path is not None:
            ln = print_samples(path, label)
        else:
            ln = 0
        print(f"  {label:18s}  +{n:4d}  file={ln}")
        total += n
    print(f"\n=== TOTAL added this run: {total} ===")
