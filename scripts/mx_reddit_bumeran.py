"""r/mexico (Reddit JSON) + Bumeran.com.mx — 墨西哥西班牙语收入/职位数据直接抓取。"""
import json, hashlib, re, time, random
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

UA_BROWSER = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
UA_REDDIT = "shouru-research/1.0"
HDR_REDDIT = {"User-Agent": UA_REDDIT, "Accept": "application/json"}
HDR_HTML = {
    "User-Agent": UA_BROWSER,
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
DAY = datetime.now().strftime("%Y%m%d")
OUT_REDDIT = Path(f"data/raw/r_mexico_native_{DAY}.jsonl")
OUT_BUMERAN = Path(f"data/raw/bumeran_native_{DAY}.jsonl")


def md5_16(*p): return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]
def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def append(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
def polite(): time.sleep(random.uniform(1.2, 1.8))


def load_seen(path):
    seen = set()
    if path.exists():
        for line in path.open():
            try: seen.add(json.loads(line)["id"])
            except: pass
    return seen


def crawl_r_mexico():
    keywords = [
        "sueldo", "salario", "cuánto ganan", "sueldo programador", "sueldo ingeniero",
        "sueldo doctor", "freelance ingresos", "mi sueldo", "ganancias mensuales",
        "empleo bien pagado",
    ]
    seen = load_seen(OUT_REDDIT)
    n = 0
    for kw in keywords:
        url = "https://www.reddit.com/r/mexico/search.json"
        params = {"q": kw, "restrict_sr": "on", "limit": "100", "t": "year"}
        try:
            r = requests.get(url, params=params, headers=HDR_REDDIT, timeout=25)
            if r.status_code != 200:
                print(f"[r/mexico] {kw} status={r.status_code}")
                polite(); continue
            data = r.json()
            children = data.get("data", {}).get("children", [])
            if not children:
                print(f"[r/mexico] {kw} no results")
                polite(); continue
            added = 0
            for c in children:
                d = c.get("data", {})
                rid_raw = d.get("id") or d.get("name", "")
                if not rid_raw: continue
                rid = md5_16("r_mexico", rid_raw)
                if rid in seen: continue
                title = d.get("title", "") or ""
                body = d.get("selftext", "") or ""
                author = d.get("author", "") or ""
                permalink = d.get("permalink", "") or ""
                full_url = f"https://www.reddit.com{permalink}" if permalink else (d.get("url", "") or "")
                obj = {
                    "id": rid,
                    "raw_id": rid_raw,
                    "platform": "r_mexico",
                    "lang": "es",
                    "title": title,
                    "body": body[:5000],
                    "author": author,
                    "url": full_url,
                    "country_hint": "MX",
                    "matched_keyword": kw,
                    "engagement": {
                        "score": int(d.get("score", 0) or 0),
                        "comments": int(d.get("num_comments", 0) or 0),
                        "upvote_ratio": d.get("upvote_ratio"),
                    },
                    "subreddit": d.get("subreddit", ""),
                    "created_utc": d.get("created_utc"),
                    "crawled_at": now_iso(),
                }
                append(OUT_REDDIT, obj); seen.add(rid); n += 1; added += 1
            print(f"[r/mexico] kw={kw!r} children={len(children)} new={added} total={n}")
        except Exception as e:
            print(f"[r/mexico] {kw} err: {e}")
        polite()
    print(f"[r/mexico] DONE +{n}")
    return n


def parse_bumeran_listing(soup):
    """Try multiple selectors for Bumeran job cards."""
    # Bumeran uses Next.js — typical containers vary. Try several.
    cards = (
        soup.select("a[href*='/empleos/']") +
        soup.select("[class*=jobItem]") +
        soup.select("[class*=job-card]") +
        soup.select("article")
    )
    # de-dup by element id
    seen_ids = set()
    uniq = []
    for c in cards:
        eid = id(c)
        if eid in seen_ids: continue
        seen_ids.add(eid)
        uniq.append(c)
    return uniq


def extract_bumeran_card(card):
    """Return (title, url, empresa, ubicacion, salario) from a card-ish element."""
    title = ""
    href = ""
    # title link
    if card.name == "a" and card.get("href"):
        href = card.get("href", "")
        h_el = card.select_one("h1,h2,h3,[class*=title]") or card
        title = h_el.get_text(" ", strip=True)
    else:
        a = card.select_one("a[href*='/empleos/']") or card.select_one("a")
        if a:
            href = a.get("href", "")
            t_el = a.select_one("h1,h2,h3,[class*=title]") or a
            title = t_el.get_text(" ", strip=True)
    if href and not href.startswith("http"):
        href = "https://www.bumeran.com.mx" + href
    text = card.get_text(" ", strip=True)
    # try to pull salary, company, location patterns
    salario = ""
    m = re.search(r"\$\s?[\d\.,]+(?:\s?(?:a|-|al|por)\s?\$?\s?[\d\.,]+)?\s?(?:MXN|mensual|mensuales|al mes|por hora|MN|pesos)?", text, re.I)
    if m: salario = m.group(0).strip()
    # Company often appears as a sibling/nested span
    empresa_el = card.select_one("[class*=company], [class*=empresa], h3 + *")
    empresa = empresa_el.get_text(" ", strip=True) if empresa_el else ""
    ubic_el = card.select_one("[class*=location], [class*=ubicacion]")
    ubicacion = ubic_el.get_text(" ", strip=True) if ubic_el else ""
    return title, href, empresa, ubicacion, salario, text


def fetch_bumeran_detail(url):
    """Fetch a job detail page and extract description + structured fields."""
    try:
        r = requests.get(url, headers=HDR_HTML, timeout=25)
        if r.status_code != 200:
            return {"description": "", "status": r.status_code}
        soup = BeautifulSoup(r.text, "html.parser")
        # Try main description
        desc_el = (
            soup.select_one("[class*=descripcion]")
            or soup.select_one("[class*=description]")
            or soup.select_one("section[class*=detail]")
            or soup.select_one("main")
        )
        desc = desc_el.get_text(" ", strip=True) if desc_el else soup.get_text(" ", strip=True)
        # Look for JSON-LD JobPosting
        salario_jsonld = ""
        empresa_jsonld = ""
        ubic_jsonld = ""
        for s in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                j = json.loads(s.string or "{}")
                if isinstance(j, list):
                    for it in j:
                        if isinstance(it, dict) and it.get("@type") == "JobPosting":
                            j = it; break
                if isinstance(j, dict) and j.get("@type") == "JobPosting":
                    bs = j.get("baseSalary") or {}
                    if isinstance(bs, dict):
                        v = bs.get("value") or {}
                        if isinstance(v, dict):
                            mn = v.get("minValue"); mx = v.get("maxValue"); cu = bs.get("currency", "")
                            if mn or mx:
                                salario_jsonld = f"{mn or ''}-{mx or ''} {cu}".strip(" -")
                    org = j.get("hiringOrganization") or {}
                    if isinstance(org, dict):
                        empresa_jsonld = org.get("name", "") or ""
                    loc = j.get("jobLocation") or {}
                    if isinstance(loc, list) and loc: loc = loc[0]
                    if isinstance(loc, dict):
                        addr = loc.get("address") or {}
                        if isinstance(addr, dict):
                            ubic_jsonld = ", ".join(
                                v for v in [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")] if v
                            )
            except Exception:
                continue
        return {
            "description": desc[:5000],
            "salario_jsonld": salario_jsonld,
            "empresa_jsonld": empresa_jsonld,
            "ubicacion_jsonld": ubic_jsonld,
            "status": 200,
        }
    except Exception as e:
        return {"description": "", "status": -1, "error": str(e)}


def crawl_bumeran():
    roles = [
        "desarrollador", "programador", "ingeniero", "contador", "abogado",
        "enfermera", "médico", "vendedor", "marketing", "gerente",
    ]
    seen = load_seen(OUT_BUMERAN)
    n = 0
    for role in roles:
        url = "https://www.bumeran.com.mx/empleos.html"
        try:
            r = requests.get(url, params={"palabra": role}, headers=HDR_HTML, timeout=25)
            if r.status_code != 200:
                print(f"[bumeran] role={role} status={r.status_code}")
                polite(); continue
            soup = BeautifulSoup(r.text, "html.parser")
            cards = parse_bumeran_listing(soup)
            if not cards:
                print(f"[bumeran] role={role} no cards. HTML head: {r.text[:200]}...")
                polite(); continue
            # We want roughly 5-10 jobs per role, dedupe by URL
            seen_url = set()
            picked = 0
            for card in cards:
                if picked >= 6: break
                title, href, empresa, ubicacion, salario, raw_text = extract_bumeran_card(card)
                if not href or "/empleos/" not in href: continue
                if href in seen_url: continue
                seen_url.add(href)
                if not title or len(title) < 5: continue
                m = re.search(r"/empleos/([^?#]+)", href)
                raw_id = m.group(1) if m else href
                rid = md5_16("bumeran", raw_id)
                if rid in seen: continue
                # Fetch detail page
                detail = fetch_bumeran_detail(href)
                polite()
                description = detail.get("description", "")
                # prefer JSON-LD if we got it
                if detail.get("salario_jsonld"): salario = detail["salario_jsonld"]
                if detail.get("empresa_jsonld") and not empresa: empresa = detail["empresa_jsonld"]
                if detail.get("ubicacion_jsonld") and not ubicacion: ubicacion = detail["ubicacion_jsonld"]
                obj = {
                    "id": rid,
                    "raw_id": raw_id,
                    "platform": "bumeran",
                    "lang": "es",
                    "title": title,
                    "body": description or raw_text[:1500],
                    "author": empresa,
                    "url": href,
                    "country_hint": "MX",
                    "matched_keyword": role,
                    "engagement": {"score": 0, "comments": 0, "views": None},
                    "empresa": empresa,
                    "ubicacion": ubicacion,
                    "salario": salario,
                    "crawled_at": now_iso(),
                }
                append(OUT_BUMERAN, obj); seen.add(rid); n += 1; picked += 1
            print(f"[bumeran] role={role!r} cards={len(cards)} picked={picked} total={n}")
        except Exception as e:
            print(f"[bumeran] role={role} err: {e}")
        polite()
    print(f"[bumeran] DONE +{n}")
    return n


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
            extra = ""
            if o.get("salario"): extra = f" | salario={o['salario']}"
            print(f"  - kw={o.get('matched_keyword')!r} | {t}{extra}")
            print(f"    body: {b}...")
        except Exception as e:
            print(f"  parse err: {e}")
    return len(lines)


if __name__ == "__main__":
    n_r = crawl_r_mexico()
    n_b = crawl_bumeran()
    lr = print_samples(OUT_REDDIT, "r/mexico")
    lb = print_samples(OUT_BUMERAN, "bumeran")
    print(f"\n=== TOTAL: r/mexico +{n_r} (file {lr}), bumeran +{n_b} (file {lb}) ===")
