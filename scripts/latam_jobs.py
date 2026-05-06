"""LATAM 9 国西语本地求职站工资数据抓取（非 Reddit）。

覆盖站点（每国 2-3 个，共 ~24 个）：
  MX: bumeran.com.mx, occ.com.mx, computrabajo.com.mx
  AR: bumeran.com.ar, zonajobs.com.ar, computrabajo.com.ar
  CL: trabajando.cl, bumeran.cl, computrabajo.com.cl
  CO: computrabajo.com.co, bumeran.com.co, elempleo.com
  PE: bumeran.com.pe, computrabajo.com.pe, aptitus.com
  VE: bumeran.com.ve, empleate.com
  UY: buscojobs.com.uy, bumeran.com.uy
  EC: computrabajo.com.ec, multitrabajos.com
  ES: infojobs.net, indeed.es, jobandtalent

输出：每国每站独立 jsonl 文件 data/raw/<site>_<cc>_native_<DAY>.jsonl
schema 与 mx_reddit_bumeran 一致：id/raw_id/platform/lang=es/title/body/
author/url/country_hint/matched_keyword/empresa/ubicacion/salario/crawled_at
"""
import json, hashlib, re, time, random, sys, traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, quote
import requests
from bs4 import BeautifulSoup

# ---- common --------------------------------------------------------------

UA_BROWSER = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
DAY = datetime.now().strftime("%Y%m%d")
OUT_DIR = Path("data/raw")

ROLES = ["ingeniero", "programador", "doctor", "contador", "vendedor", "diseñador"]

# 关键词（用于过滤一定要含数字 / 货币的内容）
SALARY_RE = re.compile(
    r"(?:\$|€|US\$|USD|MXN|ARS|CLP|COP|PEN|EUR|VES|UYU)\s?[\d\.,]+|"
    r"[\d\.,]+\s?(?:MXN|ARS|CLP|COP|PEN|EUR|USD|VES|UYU|pesos|soles|bolívares|euros|mensual|al mes|por hora)",
    re.I,
)
NUM_RE = re.compile(r"\d{3,}")

CURRENCY_HINT = {
    "MX": "MXN", "AR": "ARS", "CL": "CLP", "CO": "COP", "PE": "PEN",
    "VE": "VES", "UY": "UYU", "EC": "USD", "ES": "EUR",
}

def hdr(country):
    al_map = {
        "MX": "es-MX,es;q=0.9,en;q=0.5",
        "AR": "es-AR,es;q=0.9,en;q=0.5",
        "CL": "es-CL,es;q=0.9,en;q=0.5",
        "CO": "es-CO,es;q=0.9,en;q=0.5",
        "PE": "es-PE,es;q=0.9,en;q=0.5",
        "VE": "es-VE,es;q=0.9,en;q=0.5",
        "UY": "es-UY,es;q=0.9,en;q=0.5",
        "EC": "es-EC,es;q=0.9,en;q=0.5",
        "ES": "es-ES,es;q=0.9,en;q=0.5",
    }
    return {
        "User-Agent": UA_BROWSER,
        "Accept-Language": al_map.get(country, "es-ES,es;q=0.9,en;q=0.5"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

def md5_16(*p):
    return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def append(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def polite():
    time.sleep(random.uniform(1.3, 1.8))

def load_seen(path):
    seen = set()
    if path.exists():
        for line in path.open():
            try:
                seen.add(json.loads(line)["id"])
            except Exception:
                pass
    return seen

def fetch(url, country, params=None, timeout=25, max_retry=2):
    for i in range(max_retry):
        try:
            r = requests.get(url, params=params, headers=hdr(country), timeout=timeout)
            if r.status_code == 200:
                # quick cloudflare detect
                if "Just a moment..." in r.text[:2000] or "cf-chl-bypass" in r.text[:2000]:
                    return None, "cloudflare"
                return r, "ok"
            if r.status_code in (403, 429, 503):
                if i + 1 < max_retry:
                    time.sleep(2 + i * 2)
                    continue
                return None, f"status_{r.status_code}"
            return None, f"status_{r.status_code}"
        except requests.RequestException as e:
            if i + 1 < max_retry:
                time.sleep(2)
                continue
            return None, f"err:{type(e).__name__}"
    return None, "exhausted"


def parse_jsonld_jobposting(soup):
    """Find first JobPosting JSON-LD on page; return dict with salario/empresa/ubicacion."""
    out = {"salario": "", "empresa": "", "ubicacion": "", "title": "", "description": ""}
    for s in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            txt = (s.string or s.get_text() or "").strip()
            if not txt:
                continue
            j = json.loads(txt)
        except Exception:
            continue
        candidates = j if isinstance(j, list) else [j]
        for c in candidates:
            if not isinstance(c, dict):
                continue
            t = c.get("@type")
            if isinstance(t, list):
                if "JobPosting" not in t:
                    continue
            elif t != "JobPosting":
                continue
            # title / desc
            if c.get("title") and not out["title"]:
                out["title"] = str(c.get("title"))[:200]
            if c.get("description") and not out["description"]:
                desc = re.sub(r"<[^>]+>", " ", str(c.get("description")))
                out["description"] = re.sub(r"\s+", " ", desc).strip()[:5000]
            bs = c.get("baseSalary") or {}
            if isinstance(bs, dict) and not out["salario"]:
                cu = bs.get("currency", "")
                v = bs.get("value", {})
                if isinstance(v, dict):
                    mn, mx, unit = v.get("minValue"), v.get("maxValue"), v.get("unitText", "")
                    if mn or mx:
                        out["salario"] = f"{mn or ''}-{mx or ''} {cu} {unit}".strip(" -")
                elif isinstance(v, (int, float, str)) and v:
                    out["salario"] = f"{v} {cu}".strip()
            org = c.get("hiringOrganization") or {}
            if isinstance(org, dict) and not out["empresa"]:
                out["empresa"] = str(org.get("name") or "")[:200]
            loc = c.get("jobLocation")
            if isinstance(loc, list) and loc:
                loc = loc[0]
            if isinstance(loc, dict) and not out["ubicacion"]:
                addr = loc.get("address") or {}
                if isinstance(addr, dict):
                    out["ubicacion"] = ", ".join(
                        x for x in [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")] if x
                    )[:200]
            return out
    return out


def has_money_signal(*texts):
    blob = " ".join(t or "" for t in texts)
    return bool(SALARY_RE.search(blob)) or bool(NUM_RE.search(blob))


# ---- generic listing crawler ---------------------------------------------

def harvest_listing_links(soup, base_url, link_filter):
    """Collect unique outbound job-detail links from a search results page."""
    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        full = urljoin(base_url, href)
        if not link_filter(full):
            continue
        if full in seen:
            continue
        seen.add(full)
        out.append(full)
    return out


def fetch_detail(url, country, base_domain):
    """Fetch detail page, return body + jsonld fields."""
    r, status = fetch(url, country)
    if r is None:
        return None, status
    soup = BeautifulSoup(r.text, "html.parser")
    jl = parse_jsonld_jobposting(soup)
    # description fallback: a large text block
    desc = jl.get("description") or ""
    if not desc:
        candidates = (
            soup.select_one("[class*=descripcion]")
            or soup.select_one("[class*=description]")
            or soup.select_one("[class*=detail]")
            or soup.select_one("section[class*=offer]")
            or soup.select_one("main")
        )
        if candidates:
            desc = re.sub(r"\s+", " ", candidates.get_text(" ", strip=True))[:5000]
        else:
            desc = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:5000]
    title = jl.get("title")
    if not title:
        h = soup.find(["h1", "h2"])
        if h:
            title = h.get_text(" ", strip=True)[:200]
    return {
        "title": title or "",
        "description": desc,
        "salario": jl.get("salario", ""),
        "empresa": jl.get("empresa", ""),
        "ubicacion": jl.get("ubicacion", ""),
    }, "ok"


def crawl_site(site_id, country, list_url_tpl, link_filter, out_path,
               role_param="palabra", max_per_role=8, max_total=120):
    """Generic listing → detail crawler.

    list_url_tpl: format string with {role} placeholder, OR just plain URL with
                  query params handled by `params` kwarg in caller. Here we
                  always inject role via tpl.
    link_filter:  callable(full_url) -> bool, decide whether the URL is a job
                  detail page (typically /empleos/<slug>, /trabajo/<id>, etc.)
    """
    seen = load_seen(out_path)
    n = 0
    for role in ROLES:
        if n >= max_total:
            break
        url = list_url_tpl.format(role=quote(role))
        r, status = fetch(url, country)
        if r is None:
            print(f"[{site_id}] role={role!r} list status={status}")
            polite()
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        links = harvest_listing_links(soup, url, link_filter)
        if not links:
            # Print HTML head for debugging
            head = re.sub(r"\s+", " ", r.text[:240])
            print(f"[{site_id}] role={role!r} 0 links. head={head}")
            polite()
            continue
        picked = 0
        for href in links:
            if picked >= max_per_role or n >= max_total:
                break
            raw_id = re.sub(r"^https?://[^/]+/", "", href).split("?")[0].split("#")[0]
            rid = md5_16(site_id, raw_id)
            if rid in seen:
                continue
            d, dstatus = fetch_detail(href, country, urlparse(href).netloc)
            polite()
            if d is None:
                continue
            title = d["title"]
            if not title or len(title) < 4:
                continue
            body = d["description"]
            if not has_money_signal(body, d["salario"], title):
                # 必须含数字 — JobPosting 多半 OK
                continue
            obj = {
                "id": rid,
                "raw_id": raw_id,
                "platform": site_id,
                "lang": "es",
                "title": title[:200],
                "body": body[:5000],
                "author": d["empresa"][:200] if d["empresa"] else "",
                "url": href,
                "country_hint": country,
                "matched_keyword": role,
                "engagement": {"score": 0, "comments": 0},
                "empresa": d["empresa"][:200] if d["empresa"] else "",
                "ubicacion": d["ubicacion"][:200] if d["ubicacion"] else "",
                "salario": d["salario"][:300] if d["salario"] else "",
                "currency_hint": CURRENCY_HINT.get(country, ""),
                "crawled_at": now_iso(),
            }
            append(out_path, obj)
            seen.add(rid)
            n += 1
            picked += 1
        print(f"[{site_id}] role={role!r} links={len(links)} picked={picked} total={n}")
        polite()
    print(f"[{site_id}] DONE +{n} -> {out_path}")
    return n


# ---- per-site link filters ----------------------------------------------

def lf_bumeran(host):
    return lambda u: host in u and "/empleos/" in u

def lf_zonajobs(u):
    return "zonajobs.com.ar" in u and ("/empleos/" in u or "/empleo/" in u)

def lf_computrabajo(host):
    return lambda u: host in u and ("/ofertas-de-trabajo/oferta-de-trabajo-de-" in u or "/oferta-de-trabajo-de-" in u or "/of-" in u or re.search(r"/[A-Z0-9]{16,}", u))

def lf_occ(u):
    return "occ.com.mx" in u and "/empleo/oferta/" in u

def lf_trabajando(u):
    return "trabajando.cl" in u and ("/empleos/" in u or "/empleo/" in u or "/trabajo/" in u or "/oferta/" in u)

def lf_elempleo(u):
    return "elempleo.com" in u and "/co/ofertas-trabajo/" in u

def lf_aptitus(u):
    return "aptitus.com" in u and ("/empleos/" in u or "/avisos/" in u)

def lf_empleate(u):
    return "empleate.com" in u and ("/empleo" in u or "/oferta" in u)

def lf_buscojobs(u):
    return "buscojobs.com.uy" in u and ("/empleos/" in u or "/oferta-" in u)

def lf_multitrabajos(u):
    return "multitrabajos.com" in u and ("/empleos/" in u or "/empleo/" in u)

def lf_infojobs(u):
    return "infojobs.net" in u and "/of-i" in u

def lf_indeed_es(u):
    return "indeed.es" in u and ("/rc/clk" in u or "/viewjob" in u or "/cmp/" not in u and "/q-" not in u and "/empleos" not in u and re.search(r"jk=", u))

def lf_jobandtalent(u):
    return "jobandtalent.com" in u and ("/oferta-trabajo/" in u or "/job-offer/" in u or "/empleo/" in u)


# ---- site definitions ----------------------------------------------------

SITES = [
    # (site_id, country, list_url_tpl, link_filter, out_filename)
    # MX
    ("bumeran_mx", "MX",
     "https://www.bumeran.com.mx/empleos-busqueda-{role}.html",
     lf_bumeran("bumeran.com.mx"), "bumeran_mx_native"),
    ("occ", "MX",
     "https://www.occ.com.mx/empleos/de-{role}/",
     lf_occ, "occ_native"),
    ("computrabajo_mx", "MX",
     "https://mx.computrabajo.com/trabajo-de-{role}",
     lf_computrabajo("mx.computrabajo.com"), "computrabajo_mx_native"),
    # AR
    ("bumeran_ar", "AR",
     "https://www.bumeran.com.ar/empleos-busqueda-{role}.html",
     lf_bumeran("bumeran.com.ar"), "bumeran_ar_native"),
    ("zonajobs", "AR",
     "https://www.zonajobs.com.ar/empleos-busqueda-{role}.html",
     lf_zonajobs, "zonajobs_native"),
    ("computrabajo_ar", "AR",
     "https://ar.computrabajo.com/trabajo-de-{role}",
     lf_computrabajo("ar.computrabajo.com"), "computrabajo_ar_native"),
    # CL
    ("trabajando_cl", "CL",
     "https://www.trabajando.cl/trabajo-empleo/buscar/?keyword={role}",
     lf_trabajando, "trabajando_cl_native"),
    ("bumeran_cl", "CL",
     "https://www.bumeran.cl/empleos-busqueda-{role}.html",
     lf_bumeran("bumeran.cl"), "bumeran_cl_native"),
    ("computrabajo_cl", "CL",
     "https://cl.computrabajo.com/trabajo-de-{role}",
     lf_computrabajo("cl.computrabajo.com"), "computrabajo_cl_native"),
    # CO
    ("computrabajo_co", "CO",
     "https://co.computrabajo.com/trabajo-de-{role}",
     lf_computrabajo("co.computrabajo.com"), "computrabajo_co_native"),
    ("bumeran_co", "CO",
     "https://www.bumeran.com.co/empleos-busqueda-{role}.html",
     lf_bumeran("bumeran.com.co"), "bumeran_co_native"),
    ("elempleo", "CO",
     "https://www.elempleo.com/co/ofertas-empleo/?Search={role}",
     lf_elempleo, "elempleo_native"),
    # PE
    ("bumeran_pe", "PE",
     "https://www.bumeran.com.pe/empleos-busqueda-{role}.html",
     lf_bumeran("bumeran.com.pe"), "bumeran_pe_native"),
    ("computrabajo_pe", "PE",
     "https://pe.computrabajo.com/trabajo-de-{role}",
     lf_computrabajo("pe.computrabajo.com"), "computrabajo_pe_native"),
    ("aptitus", "PE",
     "https://aptitus.com/empleos/buscar/?searchString={role}",
     lf_aptitus, "aptitus_native"),
    # VE
    ("bumeran_ve", "VE",
     "https://www.bumeran.com.ve/empleos-busqueda-{role}.html",
     lf_bumeran("bumeran.com.ve"), "bumeran_ve_native"),
    ("empleate", "VE",
     "https://empleate.com/empleos?keyword={role}",
     lf_empleate, "empleate_native"),
    # UY
    ("buscojobs_uy", "UY",
     "https://www.buscojobs.com.uy/empleos-busqueda-{role}.html",
     lf_buscojobs, "buscojobs_uy_native"),
    ("bumeran_uy", "UY",
     "https://www.bumeran.com.uy/empleos-busqueda-{role}.html",
     lf_bumeran("bumeran.com.uy"), "bumeran_uy_native"),
    # EC
    ("computrabajo_ec", "EC",
     "https://ec.computrabajo.com/trabajo-de-{role}",
     lf_computrabajo("ec.computrabajo.com"), "computrabajo_ec_native"),
    ("multitrabajos", "EC",
     "https://www.multitrabajos.com/empleos-busqueda-{role}.html",
     lf_multitrabajos, "multitrabajos_native"),
    # ES
    ("infojobs", "ES",
     "https://www.infojobs.net/jobsearch/search-results/list.xhtml?keyword={role}",
     lf_infojobs, "infojobs_native"),
    ("indeed_es", "ES",
     "https://es.indeed.com/jobs?q={role}",
     lf_indeed_es, "indeed_es_native"),
    ("jobandtalent_es", "ES",
     "https://www.jobandtalent.com/es/ofertas-trabajo?query={role}",
     lf_jobandtalent, "jobandtalent_es_native"),
]


def print_samples(path, label, k=2):
    if not path.exists():
        print(f"[{label}] file missing")
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    print(f"=== {label}: {path.name} | {len(lines)} lines ===")
    for ln in lines[:k]:
        try:
            o = json.loads(ln)
            t = (o.get("title") or "")[:90]
            sal = o.get("salario", "")
            emp = o.get("empresa", "")
            print(f"  - {t} | salario={sal!r} | empresa={emp!r}")
        except Exception as e:
            print(f"  parse err: {e}")
    return len(lines)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = {}
    only = set(sys.argv[1:])  # optional CLI filter: site_id list
    for site_id, country, tpl, lf, fname in SITES:
        if only and site_id not in only:
            continue
        out_path = OUT_DIR / f"{fname}_{DAY}.jsonl"
        print(f"\n###### {site_id} ({country}) -> {out_path}")
        try:
            n = crawl_site(site_id, country, tpl, lf, out_path)
        except Exception as e:
            print(f"[{site_id}] FATAL {e}")
            traceback.print_exc()
            n = 0
        results[site_id] = (out_path, n)

    print("\n\n========= SUMMARY =========")
    grand = 0
    for site_id, (path, n) in results.items():
        ln = print_samples(path, site_id)
        grand += ln
    print(f"\nTOTAL across {len(results)} sites: {grand} lines")


if __name__ == "__main__":
    main()
