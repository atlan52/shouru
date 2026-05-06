"""vagas.com.br crawler — Brazilian job board with salary disclosure (P1).

vagas.com.br is one of the largest Brazilian recruitment portals. ~30% of
Brazilian postings disclose a concrete salary range (BRL/month), which is
unusually high vs. global average — making this a high-signal source for
income-by-profession data.

Strategy:
  - Search URL: https://www.vagas.com.br/vagas-de-{kw} for a curated set of
    Brazilian profession slugs (developer / nurse / accountant / driver / ...).
  - Pagination via ?pagina={n}.
  - Per listing card: vacancyId, title, company, location, salary range,
    employment type (CLT / PJ / estágio / temporário), short description.
  - Skip listings without a disclosed salary range — those become noise
    for income analysis.
  - Pure requests + BeautifulSoup. No auth, no JS required (server-rendered).
  - Country: BR, lang: pt.
"""
import re
import time
from urllib.parse import urljoin

import requests
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from config import (
    PER_PLATFORM_LIMIT, PAGES_PER_QUERY, RAW_DIR, PLATFORM_TIME_BUDGET_SEC,
)
from crawlers.common import (
    append_jsonl, make_id, polite_sleep, preload_seen,
    default_headers, random_ua, TimeBudget,
)
from crawlers.state import State


PLATFORM = "vagas_br"
BASE = "https://www.vagas.com.br"
SEARCH_URL = BASE + "/vagas-de-{kw}"

# Profession slugs covering tech / finance / health / education / blue-collar
# / sales / driving / law / design / management / nursing / accounting /
# engineering / marketing / HR — matches the canonical list of BR job verticals.
KEYWORDS = [
    "desenvolvedor-de-software",
    "analista-financeiro",
    "medico",
    "professor",
    "vendedor",
    "motorista",
    "advogado",
    "designer",
    "gerente-de-projetos",
    "enfermeiro",
    "contador",
    "engenheiro",
    "marketing",
    "rh",
]

BOT_MARKERS = (
    "captcha", "are you a human", "access denied", "unusual traffic",
    "cf-browser-verification", "checking your browser",
)


class VagasError(Exception):
    pass


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _vagas_headers() -> dict:
    h = default_headers(accept_lang="pt-BR,pt;q=0.9,en;q=0.8")
    h["User-Agent"] = random_ua()
    h["Referer"] = BASE + "/"
    return h


def fetch_html(url: str, timeout: int = 30) -> str:
    try:
        r = requests.get(url, headers=_vagas_headers(), timeout=timeout, allow_redirects=True)
    except Exception as e:
        raise VagasError(f"net err {url}: {e}")
    if r.status_code in (403, 429):
        raise VagasError(f"{r.status_code} on {url}")
    if r.status_code == 404:
        raise VagasError(f"404 on {url}")
    if r.status_code != 200:
        raise VagasError(f"status {r.status_code} on {url}")
    body = r.text or ""
    low = body.lower()
    if any(m in low for m in BOT_MARKERS):
        raise VagasError("bot-block / captcha")
    return body


def fetch_with_retry(url: str) -> str:
    """One retry with 30s backoff on 403/429."""
    try:
        return fetch_html(url)
    except VagasError as e:
        msg = str(e)
        if "403" in msg or "429" in msg:
            print(f"  [{PLATFORM}] backoff 30s on {url}")
            time.sleep(30)
            return fetch_html(url)
        raise


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
# Vacancy URL pattern: /vagas/v<digits>/<slug> or /vagas/v<digits>
_VAC_HREF_RE = re.compile(r"/vagas/v(\d+)")

# Salary-range hints. vagas.com.br exposes salary in either:
#   "Salário: A partir de R$ 5.000,00"
#   "Salário: De R$ 3.000,00 a R$ 4.500,00"
#   "Faixa salarial: R$ 8.000 - R$ 12.000"
#   "Salário a combinar"  ← skip
_SALARY_BAD_RE = re.compile(
    r"sal[aá]rio[\s:]*a[\s]+combinar|sal[aá]rio[\s:]*compat[ií]vel|"
    r"a\s+combinar|n[ãa]o\s+informado",
    re.I,
)
_SALARY_AMOUNT_RE = re.compile(
    r"R\$\s*[\d\.,]+", re.I,
)

# Employment-type hints
_EMP_TYPE_TERMS = (
    "clt", "pj", "estágio", "estagio", "temporário", "temporario",
    "freelancer", "autônomo", "autonomo", "trainee", "aprendiz",
    "efetivo", "terceirizado", "home office", "híbrido", "hibrido",
    "presencial", "remoto",
)


def _text(el) -> str:
    if not el:
        return ""
    return el.get_text(" ", strip=True)


def _abs(href: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return urljoin(BASE + "/", href)


def parse_listing_cards(html: str) -> list[dict]:
    """Pull vacancy cards from a /vagas-de-{kw} page.

    Each card carries title, company, location, and (sometimes) a salary blurb
    visible in the listing without opening the detail page.
    """
    if BeautifulSoup is None or not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    seen_ids: set[str] = set()

    # Common card container classes seen on vagas.com.br over time.
    selectors = (
        "li.vaga", "article.vaga", "div.vaga",
        "li[class*='vaga']", "article[class*='vaga']",
        "[data-id]", "[data-codigo]",
    )
    cards = []
    for sel in selectors:
        cards = soup.select(sel)
        if cards:
            break
    if not cards:
        # Fallback: walk every link to /vagas/v<digits>/...
        for a in soup.find_all("a", href=True):
            m = _VAC_HREF_RE.search(a["href"])
            if not m:
                continue
            vid = m.group(1)
            if vid in seen_ids:
                continue
            seen_ids.add(vid)
            title = _text(a)
            if not title or len(title) < 4:
                continue
            out.append({
                "vacancy_id": vid,
                "title": title[:300],
                "company": "",
                "location": "",
                "salary_raw": "",
                "snippet": "",
                "url": f"{BASE}/vagas/v{vid}",
            })
        return out

    for c in cards:
        # vacancy id — try data-id first, fall back to first /vagas/v<digits> link
        vid = (
            c.get("data-id")
            or c.get("data-codigo")
            or c.get("data-vaga")
            or ""
        )
        if not vid:
            for a in c.find_all("a", href=True):
                m = _VAC_HREF_RE.search(a["href"])
                if m:
                    vid = m.group(1)
                    break
        if not vid or vid in seen_ids:
            continue
        seen_ids.add(vid)

        # Title + URL
        title_el = c.select_one(
            "h2 a, h3 a, a.link-detalhes-vaga, a[class*='cargo'], a[href*='/vagas/v']"
        )
        title = _text(title_el)
        href = title_el.get("href") if title_el else ""
        url = _abs(href) if href else f"{BASE}/vagas/v{vid}"

        # Company
        comp_el = c.select_one(
            ".emprVaga, .empresa, [class*='empresa'], [class*='company']"
        )
        company = _text(comp_el)

        # Location
        loc_el = c.select_one(
            ".vaga-local, .local, [class*='local'], [class*='cidade']"
        )
        location = _text(loc_el)

        # Salary blurb (often absent in card view; we'll re-check on detail page)
        sal_el = c.select_one(
            "[class*='salar'], [class*='Salar'], .vaga-faixa-salarial, .faixaSalarial"
        )
        salary_raw = _text(sal_el)

        # Snippet
        snip_el = c.select_one(
            ".vaga-detalhes, .detalhes-vaga, .descricao-vaga, "
            "[class*='detalhe'], [class*='descric']"
        )
        snippet = _text(snip_el)[:1000]

        out.append({
            "vacancy_id": str(vid),
            "title": (title or "")[:300],
            "company": company,
            "location": location,
            "salary_raw": salary_raw,
            "snippet": snippet,
            "url": url,
        })

    return out


def parse_vacancy_detail(html: str) -> dict:
    """Pull richer fields off the per-vacancy detail page.

    Detail page carries a longer description body, the salary-range field,
    employment type, and benefits — much more reliable than card fields.
    """
    if BeautifulSoup is None or not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title_el = (
        soup.select_one("h1.job-shortdescription__title")
        or soup.select_one("h1[class*='cargo']")
        or soup.select_one("h1")
    )
    title = _text(title_el)

    # Company
    comp_el = (
        soup.select_one(".job-shortdescription__company")
        or soup.select_one("[class*='empresa']")
        or soup.select_one("a[class*='company']")
    )
    company = _text(comp_el)

    # Location
    loc_el = (
        soup.select_one(".job-shortdescription__local")
        or soup.select_one("[class*='local']")
    )
    location = _text(loc_el)

    # Salary — vagas exposes this in a labeled list (definition list / table)
    salary_raw = ""
    for el in soup.select(
        ".job-detalhe__salario, .info-vaga li, .job-detalhe li, "
        "dl.job-detalhe dd, [class*='alar']"
    ):
        txt = _text(el)
        if not txt:
            continue
        if "salário" in txt.lower() or "salario" in txt.lower() or "R$" in txt:
            salary_raw = txt[:200]
            if "R$" in salary_raw:
                break

    # Body / description
    body_parts: list[str] = []
    for sel in (
        ".job-description",
        ".job-detalhe__descricao",
        "section[class*='descricao']",
        "div[class*='descricao']",
        ".vaga-descricao",
    ):
        el = soup.select_one(sel)
        if el:
            body_parts.append(_text(el))
            break
    if not body_parts:
        # Fall back: the longest <section>/<article>/<div> on the page
        candidates = soup.find_all(["section", "article", "div"])
        best = ""
        for c in candidates:
            t = _text(c)
            if 200 < len(t) < 8000 and len(t) > len(best):
                best = t
        if best:
            body_parts.append(best)

    body = "\n\n".join(body_parts)[:5000]

    # Employment type — sniff from the body / labeled fields
    employment_type = ""
    blob_low = (title + " " + body).lower()
    for term in _EMP_TYPE_TERMS:
        if term in blob_low:
            employment_type = term.upper() if term in ("clt", "pj") else term
            break

    return {
        "title": title,
        "company": company,
        "location": location,
        "salary_raw": salary_raw,
        "body": body,
        "employment_type": employment_type,
    }


def _has_real_salary(s: str) -> bool:
    """Does the salary blurb actually disclose an amount (not 'a combinar')?"""
    if not s:
        return False
    if _SALARY_BAD_RE.search(s):
        return False
    return bool(_SALARY_AMOUNT_RE.search(s))


# ---------------------------------------------------------------------------
# Per-keyword runner
# ---------------------------------------------------------------------------
def search_url(kw: str, page: int) -> str:
    base = SEARCH_URL.format(kw=kw)
    if page > 1:
        return f"{base}?pagina={page}"
    return base


def process_vacancy(meta: dict, kw: str, state: State) -> bool:
    """Fetch detail, validate salary disclosure, emit jsonl. Returns True if written."""
    vid = meta["vacancy_id"]
    our_id = make_id(PLATFORM, vid)
    if state.is_seen(our_id):
        return False

    # Quick early-skip: if the card already showed "salário a combinar", drop now.
    if meta.get("salary_raw") and _SALARY_BAD_RE.search(meta["salary_raw"]):
        state.mark_seen(our_id)
        return False

    detail_url = meta["url"]
    try:
        html = fetch_with_retry(detail_url)
    except VagasError as e:
        print(f"  [{PLATFORM}] vac {vid} err: {e}")
        # Mark seen so we don't keep retrying the same broken page
        state.mark_seen(our_id)
        return False

    detail = parse_vacancy_detail(html)
    salary_raw = detail.get("salary_raw") or meta.get("salary_raw") or ""
    if not _has_real_salary(salary_raw):
        state.mark_seen(our_id)
        return False

    title = detail.get("title") or meta.get("title", "")
    company = detail.get("company") or meta.get("company", "")
    location = detail.get("location") or meta.get("location", "")
    body = detail.get("body") or meta.get("snippet", "")

    item = {
        "id": our_id,
        "raw_id": vid,
        "platform": PLATFORM,
        "lang": "pt",
        "country_hint": "BR",
        "kind": "job_listing",
        "title": title[:300],
        "company": company[:200],
        "location": location[:200],
        "salary_range_brl": salary_raw[:200],
        "employment_type": detail.get("employment_type", ""),
        "body": body[:5000],
        "url": f"{BASE}/vagas/v{vid}",
        "matched_keyword": kw,
        "engagement": {"score": 0, "comments": 0, "views": None},
    }
    append_jsonl(item, PLATFORM, RAW_DIR)
    state.mark_seen(our_id)
    return True


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------
def run():
    state = State(PLATFORM)
    preload_seen(state, PLATFORM, key_field="id")
    budget = TimeBudget(PLATFORM_TIME_BUDGET_SEC)
    items_added = 0

    try:
        for kw in KEYWORDS:
            if budget.expired():
                print(f"[{PLATFORM}] time budget expired")
                break
            if state.is_kw_done(kw):
                continue
            if items_added >= PER_PLATFORM_LIMIT:
                break

            print(f"[{PLATFORM}] kw {kw}")
            start_page = state.get_cursor(kw, 1) or 1
            had_error = False

            for page in range(start_page, start_page + PAGES_PER_QUERY):
                if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                    break
                url = search_url(kw, page)
                try:
                    html = fetch_with_retry(url)
                except VagasError as e:
                    print(f"  [{PLATFORM}] search {kw} p{page} err: {e}")
                    had_error = True
                    break

                cards = parse_listing_cards(html)
                if not cards:
                    break

                for meta in cards:
                    if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                        break
                    try:
                        if process_vacancy(meta, kw, state):
                            items_added += 1
                            if items_added % 25 == 0:
                                print(f"  [{PLATFORM}] +{items_added} so far")
                    except VagasError as e:
                        print(f"  [{PLATFORM}] process err: {e}")
                    state.maybe_save(every=10)
                    polite_sleep()

                state.set_cursor(kw, page + 1)
                polite_sleep()

            if not had_error:
                state.mark_kw_done(kw)
            state.save()
            polite_sleep()
    finally:
        state.save(force=True)

    print(f"[{PLATFORM}] done, +{items_added} items this run")


if __name__ == "__main__":
    run()
