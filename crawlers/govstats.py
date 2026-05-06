"""govstats — pull structured occupation × wage data from 11 national stat agencies.

Why: high-quality structured ground-truth backbone for our extraction. Per-occupation
mean wages from official sources. Target ~200-500 records total.

Strategy:
  - 11 sub-functions, each fetches the latest occupation × mean-wage table from
    one country's stat agency.
  - Fail-soft per source — if one helper raises, log and continue.
  - ANY data is valuable; we accept partial outputs and even single-record
    "summary fallbacks" when full table parsing fails.
  - Each helper gets ≤2 minutes of effort. Don't try too hard.

Per-row JSONL schema:
  {id, platform: "govstats", source: "<agency>", country_hint: "<ISO-2>",
   lang: "<ISO-2>", occupation: "...",
   body: "Full description string with mean salary etc.",
   mean_local: <num>, currency: "<ISO-4217>", period: "year",
   num_employed: <num>, percentile_X: <num>, source_url: "<url>",
   year: <int>, engagement: {score: 0, comments: 0}}
"""
import io
import re
import time
import zipfile
from typing import Optional

import requests
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    import pandas as pd
except ImportError:
    pd = None

from config import RAW_DIR, REQUEST_TIMEOUT_SEC
from crawlers.common import (
    append_jsonl, make_id, polite_sleep, preload_seen, default_headers,
)
from crawlers.state import State


# ============================================================================
# HTTP helper — uniform requests with timeout + UA + soft error handling.
# ============================================================================
def _fetch(url: str, *, binary: bool = False, accept_lang: str = "en-US,en;q=0.9",
           timeout: int = REQUEST_TIMEOUT_SEC):
    """Return (status_code, content). content is bytes if binary else str.
    Raises on non-2xx so callers can wrap in try/except."""
    headers = default_headers(accept_lang=accept_lang)
    r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    if binary:
        return r.status_code, r.content
    # Let requests guess encoding; fallback to utf-8.
    if not r.encoding:
        r.encoding = "utf-8"
    return r.status_code, r.text


def _summary_record(*, source: str, country: str, lang: str, url: str,
                    body: str, occupation: str = "(summary)",
                    year: Optional[int] = None) -> dict:
    """Last-resort fallback record — when we couldn't parse the table but at
    least retrieved the listing page. Single record per source."""
    return {
        "platform": "govstats",
        "source": source,
        "country_hint": country,
        "lang": lang,
        "occupation": occupation,
        "body": (body or "")[:8000],
        "mean_local": None,
        "currency": None,
        "period": "year",
        "num_employed": None,
        "source_url": url,
        "year": year,
        "engagement": {"score": 0, "comments": 0},
    }


def _to_int(v) -> Optional[int]:
    try:
        if v is None:
            return None
        s = str(v).replace(",", "").replace(" ", "").replace(" ", "").strip()
        if not s or s in {"-", "*", "nan", "NaN", "None"}:
            return None
        return int(float(s))
    except Exception:
        return None


def _to_float(v) -> Optional[float]:
    try:
        if v is None:
            return None
        s = str(v).replace(",", "").replace(" ", "").replace(" ", "").strip()
        if not s or s in {"-", "*", "nan", "NaN", "None"}:
            return None
        return float(s)
    except Exception:
        return None


# ============================================================================
# 1. BLS (US) — Occupational Employment Statistics National
# ============================================================================
def _bls_us() -> list[dict]:
    """Fetch BLS OES National. Try the most recent annual zip; fall back to
    landing page summary."""
    base = "https://www.bls.gov/oes/special.requests/oesm{yy}nat.zip"
    landing_url = "https://www.bls.gov/oes/tables.htm"
    out: list[dict] = []
    # Try recent years, newest first.
    for yy in ("24", "23", "22"):
        url = base.format(yy=yy)
        try:
            polite_sleep()
            sc, content = _fetch(url, binary=True)
            year = 2000 + int(yy)
            # Open zip in memory and locate the national xlsx.
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                xlsx_name = None
                for n in zf.namelist():
                    nl = n.lower()
                    if nl.endswith(".xlsx") and "nat" in nl:
                        xlsx_name = n
                        break
                if not xlsx_name:
                    # Take any xlsx.
                    for n in zf.namelist():
                        if n.lower().endswith(".xlsx"):
                            xlsx_name = n
                            break
                if not xlsx_name or pd is None:
                    raise RuntimeError("no xlsx or pandas missing")
                with zf.open(xlsx_name) as fh:
                    df = pd.read_excel(fh, sheet_name=0, dtype=str, engine="openpyxl")
            cols = {c.lower().strip(): c for c in df.columns}

            def col(*opts):
                for o in opts:
                    if o in cols:
                        return cols[o]
                return None

            occ_code_col = col("occ_code", "occ code")
            occ_name_col = col("occ_title", "occ title", "occupation_title")
            mean_col = col("a_mean", "annual mean wage", "annual_mean")
            emp_col = col("tot_emp", "total_emp", "total employment")
            p10 = col("a_pct10", "annual_pct10")
            p25 = col("a_pct25", "annual_pct25")
            p50 = col("a_median", "annual_median")
            p75 = col("a_pct75", "annual_pct75")
            p90 = col("a_pct90", "annual_pct90")
            if not (occ_name_col and mean_col):
                raise RuntimeError("expected columns missing")

            # Filter to detailed occupations only when possible (group col).
            group_col = col("o_group", "group")
            if group_col:
                df = df[df[group_col].astype(str).str.lower().eq("detailed")]
            # Cap: take ~50 rows.
            df = df.head(50)
            for _, row in df.iterrows():
                name = str(row.get(occ_name_col, "")).strip()
                if not name or name.lower() == "nan":
                    continue
                mean_v = _to_float(row.get(mean_col))
                rec = {
                    "lang": "en",
                    "occupation": name,
                    "occupation_code": str(row.get(occ_code_col, "") or "").strip() if occ_code_col else None,
                    "mean_local": mean_v,
                    "currency": "USD",
                    "period": "year",
                    "num_employed": _to_int(row.get(emp_col)) if emp_col else None,
                    "source_url": url,
                    "year": year,
                    "engagement": {"score": 0, "comments": 0},
                }
                if p10: rec["percentile_10"] = _to_float(row.get(p10))
                if p25: rec["percentile_25"] = _to_float(row.get(p25))
                if p50: rec["percentile_50"] = _to_float(row.get(p50))
                if p75: rec["percentile_75"] = _to_float(row.get(p75))
                if p90: rec["percentile_90"] = _to_float(row.get(p90))
                rec["body"] = (
                    f"BLS OES National {year}. Occupation: {name}. "
                    f"Mean annual wage: ${mean_v:,.0f}. "
                    f"Employed: {rec['num_employed']:,}." if (mean_v and rec.get("num_employed"))
                    else f"BLS OES National {year}. Occupation: {name}. Mean annual wage: ${mean_v}."
                )
                out.append(rec)
            if out:
                return out
        except Exception:
            continue
    # Fallback to landing-page summary.
    try:
        polite_sleep()
        _, html = _fetch(landing_url)
        text = ""
        if BeautifulSoup is not None:
            text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
        else:
            text = re.sub(r"<[^>]+>", " ", html)
        out.append(_summary_record(
            source="BLS", country="US", lang="en", url=landing_url,
            body="BLS OES tables landing page (full Excel parse failed). " + text[:4000],
        ))
    except Exception:
        pass
    return out


# ============================================================================
# 2. ONS (UK) — ASHE occupation by 4-digit SOC
# ============================================================================
def _ons_uk() -> list[dict]:
    landing = ("https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork/"
               "earningsandworkinghours/datasets/occupation4digitsoc2010ashetable14")
    out: list[dict] = []
    try:
        polite_sleep()
        _, html = _fetch(landing, accept_lang="en-GB,en;q=0.9")
    except Exception:
        return out

    # Find the most recent xls/xlsx download link in the HTML.
    xlsx_url = None
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.lower().endswith((".xls", ".xlsx")):
                if href.startswith("/"):
                    xlsx_url = "https://www.ons.gov.uk" + href
                elif href.startswith("http"):
                    xlsx_url = href
                else:
                    xlsx_url = "https://www.ons.gov.uk/" + href
                break
    if xlsx_url and pd is not None:
        try:
            polite_sleep()
            _, content = _fetch(xlsx_url, binary=True)
            engine = "openpyxl" if xlsx_url.lower().endswith(".xlsx") else None
            xls = pd.ExcelFile(io.BytesIO(content), engine=engine)
            # Pick a sheet with "All" or "mean" in its name.
            sheet = xls.sheet_names[0]
            for cand in xls.sheet_names:
                if "all" in cand.lower() and "mean" in cand.lower():
                    sheet = cand
                    break
            df = xls.parse(sheet, header=None, dtype=str)
            # Heuristic parse: scan rows for patterns "<4-digit code> <name> ... <number>".
            count = 0
            for _, row in df.iterrows():
                vals = [str(v).strip() for v in row.tolist() if v is not None and str(v).strip() not in {"nan", ""}]
                if len(vals) < 3:
                    continue
                # Look for a 4-digit SOC code in the first cell.
                if not re.match(r"^\d{4}$", vals[0]):
                    continue
                code = vals[0]
                name = vals[1]
                # Find first numeric value (≥5 digits is likely annual £).
                mean_local = None
                for v in vals[2:]:
                    fv = _to_float(v)
                    if fv and fv > 5000:
                        mean_local = fv
                        break
                rec = {
                    "lang": "en",
                    "occupation": name,
                    "occupation_code": code,
                    "mean_local": mean_local,
                    "currency": "GBP",
                    "period": "year",
                    "source_url": xlsx_url,
                    "year": None,
                    "body": f"ONS ASHE table 14: {code} {name}. Mean annual gross pay: £{mean_local}.",
                    "engagement": {"score": 0, "comments": 0},
                }
                out.append(rec)
                count += 1
                if count >= 50:
                    break
        except Exception:
            pass
    if out:
        return out
    # Fallback summary.
    text = ""
    if BeautifulSoup is not None:
        text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
    else:
        text = re.sub(r"<[^>]+>", " ", html)
    out.append(_summary_record(
        source="ONS", country="GB", lang="en", url=landing,
        body=("ONS ASHE Table 14 landing (full xlsx parse failed). " + text[:4000]),
    ))
    return out


# ============================================================================
# 3. INSEE (France) — Salaires des salariés (PCS)
# ============================================================================
def _insee_fr() -> list[dict]:
    landing = "https://www.insee.fr/fr/statistiques/2418189"
    out: list[dict] = []
    try:
        polite_sleep()
        _, html = _fetch(landing, accept_lang="fr-FR,fr;q=0.9,en;q=0.5")
    except Exception:
        return out
    if BeautifulSoup is None:
        out.append(_summary_record(
            source="INSEE", country="FR", lang="fr", url=landing,
            body="INSEE PCS salary page (bs4 unavailable for parse).",
        ))
        return out
    soup = BeautifulSoup(html, "html.parser")
    # Try first <table> on the page.
    table = soup.find("table")
    if table:
        rows = table.find_all("tr")
        count = 0
        for tr in rows[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            occ = cells[0]
            mean_local = None
            for v in cells[1:]:
                fv = _to_float(v.replace("€", "").replace(" ", ""))
                if fv and fv > 1000:
                    mean_local = fv
                    break
            if not occ or len(occ) < 3:
                continue
            out.append({
                "lang": "fr",
                "occupation": occ,
                "mean_local": mean_local,
                "currency": "EUR",
                "period": "year",
                "source_url": landing,
                "year": None,
                "body": f"INSEE salaire moyen — {occ}: {mean_local} €/an.",
                "engagement": {"score": 0, "comments": 0},
            })
            count += 1
            if count >= 50:
                break
    if out:
        return out
    text = soup.get_text("\n", strip=True)
    out.append(_summary_record(
        source="INSEE", country="FR", lang="fr", url=landing,
        body="INSEE 2418189 salaires PCS (table parse failed). " + text[:4000],
    ))
    return out


# ============================================================================
# 4. Destatis (Germany) — Verdiensterhebung
# ============================================================================
def _destatis_de() -> list[dict]:
    landing = ("https://www.destatis.de/EN/Themes/Labour/Earnings/"
               "Sectors-Occupations/_node.html")
    out: list[dict] = []
    try:
        polite_sleep()
        _, html = _fetch(landing, accept_lang="en-US,en;q=0.9,de;q=0.5")
    except Exception:
        return out
    if BeautifulSoup is None:
        out.append(_summary_record(
            source="Destatis", country="DE", lang="en", url=landing,
            body="Destatis page (bs4 unavailable).",
        ))
        return out
    soup = BeautifulSoup(html, "html.parser")
    # Look for tables with occupation/wage data.
    table = soup.find("table")
    if table:
        rows = table.find_all("tr")
        count = 0
        for tr in rows[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            occ = cells[0]
            mean_local = None
            for v in cells[1:]:
                fv = _to_float(v.replace("€", "").replace(".", "").replace(",", "."))
                if fv and fv > 100:
                    mean_local = fv
                    break
            if not occ or len(occ) < 3:
                continue
            out.append({
                "lang": "en",
                "occupation": occ,
                "mean_local": mean_local,
                "currency": "EUR",
                "period": "year",
                "source_url": landing,
                "year": None,
                "body": f"Destatis Verdiensterhebung — {occ}: {mean_local} EUR.",
                "engagement": {"score": 0, "comments": 0},
            })
            count += 1
            if count >= 30:
                break
    if out:
        return out
    text = soup.get_text("\n", strip=True)
    out.append(_summary_record(
        source="Destatis", country="DE", lang="en", url=landing,
        body="Destatis Earnings by sector / occupation landing. " + text[:4000],
    ))
    return out


# ============================================================================
# 5. NBS China — 国家统计局 average wage by industry
# ============================================================================
def _nbs_cn() -> list[dict]:
    # The dynamic easyquery endpoint is JS-rendered; instead grab the
    # latest annual report bulletin landing page summary.
    landing = "http://www.stats.gov.cn/sj/zxfb/202405/t20240520_1955486.html"
    fallback = ("https://data.stats.gov.cn/easyquery.htm?cn=C01&zb=A0405")
    out: list[dict] = []
    pages_to_try = [
        "http://www.stats.gov.cn/sj/zxfb/202405/t20240520_1955486.html",
        "http://www.stats.gov.cn/sj/",
        fallback,
    ]
    for url in pages_to_try:
        try:
            polite_sleep()
            _, html = _fetch(url, accept_lang="zh-CN,zh;q=0.9,en;q=0.5")
            text = ""
            if BeautifulSoup is not None:
                text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
            else:
                text = re.sub(r"<[^>]+>", " ", html)
            if text and len(text) > 200:
                # Try to extract numeric figures in 万元 / 元 around "平均工资".
                rec = _summary_record(
                    source="NBS_CN", country="CN", lang="zh", url=url,
                    body="国家统计局 — 城镇单位就业人员平均工资。" + text[:6000],
                    occupation="城镇单位就业人员",
                )
                rec["currency"] = "CNY"
                # Attempt to pick a headline number (e.g. 120698 元).
                m = re.search(r"平均工资[^\d]{0,30}(\d{4,7})\s*元", text)
                if m:
                    rec["mean_local"] = float(m.group(1))
                out.append(rec)
                return out
        except Exception:
            continue
    return out


# ============================================================================
# 6. NTA Japan — 国税庁 民間給与実態統計調査
# ============================================================================
def _nta_jp() -> list[dict]:
    candidates = [
        "https://www.nta.go.jp/publication/statistics/kokuzeicho/minkan2022/menu.htm",
        "https://www.nta.go.jp/publication/statistics/kokuzeicho/minkan2021/menu.htm",
        "https://www.nta.go.jp/publication/statistics/kokuzeicho/top.htm",
    ]
    out: list[dict] = []
    for url in candidates:
        try:
            polite_sleep()
            _, html = _fetch(url, accept_lang="ja-JP,ja;q=0.9,en;q=0.5")
            text = ""
            if BeautifulSoup is not None:
                text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
            else:
                text = re.sub(r"<[^>]+>", " ", html)
            if not text or len(text) < 100:
                continue
            rec = _summary_record(
                source="NTA_JP", country="JP", lang="ja", url=url,
                body="国税庁 民間給与実態統計調査 — 業種別・年齢別・規模別 平均年収。" + text[:6000],
                occupation="給与所得者全体",
            )
            rec["currency"] = "JPY"
            # Look for a yen figure like "458万円" or "4,580,000円".
            m = re.search(r"(\d{3,4})\s*万円", text)
            if m:
                rec["mean_local"] = float(m.group(1)) * 10_000
            out.append(rec)
            return out
        except Exception:
            continue
    return out


# ============================================================================
# 7. KOSIS (Korea) — 통계청 wage by occupation code
# ============================================================================
def _kosis_kr() -> list[dict]:
    landing = ("https://kosis.kr/statHtml/statHtml.do?orgId=118&tblId=DT_118N_PAY29")
    fallback = "https://kosis.kr/index/index.do"
    out: list[dict] = []
    for url in (landing, fallback):
        try:
            polite_sleep()
            _, html = _fetch(url, accept_lang="ko-KR,ko;q=0.9,en;q=0.5")
            text = ""
            if BeautifulSoup is not None:
                text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
            else:
                text = re.sub(r"<[^>]+>", " ", html)
            if not text or len(text) < 100:
                continue
            rec = _summary_record(
                source="KOSIS_KR", country="KR", lang="ko", url=url,
                body="통계청 KOSIS — 직종별 임금 (DT_118N_PAY29). " + text[:6000],
                occupation="임금근로자 전체",
            )
            rec["currency"] = "KRW"
            out.append(rec)
            return out
        except Exception:
            continue
    return out


# ============================================================================
# 8. IBGE (Brazil) — PNAD Contínua income by occupation
# ============================================================================
def _ibge_br() -> list[dict]:
    candidates = [
        "https://sidra.ibge.gov.br/pesquisa/pnadct/tabelas",
        "https://www.ibge.gov.br/estatisticas/sociais/trabalho/9171-pesquisa-nacional-por-amostra-de-domicilios-continua-mensal.html",
    ]
    out: list[dict] = []
    for url in candidates:
        try:
            polite_sleep()
            _, html = _fetch(url, accept_lang="pt-BR,pt;q=0.9,en;q=0.5")
            text = ""
            if BeautifulSoup is not None:
                text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
            else:
                text = re.sub(r"<[^>]+>", " ", html)
            if not text or len(text) < 100:
                continue
            rec = _summary_record(
                source="IBGE_BR", country="BR", lang="pt", url=url,
                body="IBGE PNAD Contínua — Rendimento por ocupação. " + text[:6000],
                occupation="trabalhadores ocupados",
            )
            rec["currency"] = "BRL"
            m = re.search(r"R\$\s*([\d\.\,]+)", text)
            if m:
                rec["mean_local"] = _to_float(m.group(1).replace(".", "").replace(",", "."))
            out.append(rec)
            return out
        except Exception:
            continue
    return out


# ============================================================================
# 9. Rosstat (Russia) — labour costs / wages by occupation
# ============================================================================
def _rosstat_ru() -> list[dict]:
    candidates = [
        "https://rosstat.gov.ru/labour_costs",
        "https://rosstat.gov.ru/labour_force",
        "https://rosstat.gov.ru/folder/210/document/13238",
    ]
    out: list[dict] = []
    for url in candidates:
        try:
            polite_sleep()
            _, html = _fetch(url, accept_lang="ru-RU,ru;q=0.9,en;q=0.5")
            text = ""
            if BeautifulSoup is not None:
                text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
            else:
                text = re.sub(r"<[^>]+>", " ", html)
            if not text or len(text) < 100:
                continue
            rec = _summary_record(
                source="Rosstat_RU", country="RU", lang="ru", url=url,
                body="Росстат — Сведения о зарплатах по профессиям. " + text[:6000],
                occupation="средняя зарплата по РФ",
            )
            rec["currency"] = "RUB"
            m = re.search(r"(\d{2,3}\s?\d{3})\s*(?:руб|₽)", text)
            if m:
                rec["mean_local"] = _to_float(m.group(1))
            out.append(rec)
            return out
        except Exception:
            continue
    return out


# ============================================================================
# 10. INEGI (Mexico) — ENOE (Encuesta Nacional de Ocupación y Empleo)
# ============================================================================
def _inegi_mx() -> list[dict]:
    candidates = [
        "https://www.inegi.org.mx/temas/empleo/",
        "https://www.inegi.org.mx/programas/enoe/15ymas/",
    ]
    out: list[dict] = []
    for url in candidates:
        try:
            polite_sleep()
            _, html = _fetch(url, accept_lang="es-MX,es;q=0.9,en;q=0.5")
            text = ""
            if BeautifulSoup is not None:
                text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
            else:
                text = re.sub(r"<[^>]+>", " ", html)
            if not text or len(text) < 100:
                continue
            rec = _summary_record(
                source="INEGI_MX", country="MX", lang="es", url=url,
                body="INEGI ENOE — Ingreso por ocupación y rama. " + text[:6000],
                occupation="población ocupada",
            )
            rec["currency"] = "MXN"
            out.append(rec)
            return out
        except Exception:
            continue
    return out


# ============================================================================
# 11. MOSPI (India) — Periodic Labour Force Survey
# ============================================================================
def _mospi_in() -> list[dict]:
    # The PDF is hard to scrape; use the listing page that hosts the report.
    candidates = [
        "https://www.mospi.gov.in/publication/annual-report-plfs-2022-23",
        "https://www.mospi.gov.in/sites/default/files/publication_reports/AnnualReport_PLFS2022-23.pdf",
        "https://mospi.gov.in/",
    ]
    out: list[dict] = []
    for url in candidates:
        try:
            polite_sleep()
            sc, html = _fetch(url, accept_lang="en-IN,en;q=0.9")
        except Exception:
            continue
        # Skip raw PDF binary — only parse HTML.
        if isinstance(html, bytes) or url.lower().endswith(".pdf"):
            # We did fetch successfully; record that the URL exists.
            out.append(_summary_record(
                source="MOSPI_IN", country="IN", lang="en", url=url,
                body=f"MOSPI PLFS 2022-23 annual report (PDF fetched, not parsed). URL: {url}",
                occupation="labour force (PLFS)",
            ))
            return out
        text = ""
        if BeautifulSoup is not None:
            text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
        else:
            text = re.sub(r"<[^>]+>", " ", html)
        if not text or len(text) < 100:
            continue
        rec = _summary_record(
            source="MOSPI_IN", country="IN", lang="en", url=url,
            body="MOSPI PLFS 2022-23 — Earnings by occupation (CWS / Self-employed / Regular wage). "
                 + text[:6000],
            occupation="labour force (PLFS)",
        )
        rec["currency"] = "INR"
        # Look for a Rs / ₹ figure.
        m = re.search(r"(?:₹|Rs\.?)\s*([\d,]+)", text)
        if m:
            rec["mean_local"] = _to_float(m.group(1))
        out.append(rec)
        return out
    return out


# ============================================================================
# Entry point
# ============================================================================
def run():
    state = State("govstats")
    preload_seen(state, "govstats", key_field="id")
    items_added = 0
    sources = [
        ("BLS",         _bls_us,     "US"),
        ("ONS",         _ons_uk,     "GB"),
        ("INSEE",       _insee_fr,   "FR"),
        ("Destatis",    _destatis_de, "DE"),
        ("NBS_CN",      _nbs_cn,     "CN"),
        ("NTA_JP",      _nta_jp,     "JP"),
        ("KOSIS_KR",    _kosis_kr,   "KR"),
        ("IBGE_BR",     _ibge_br,    "BR"),
        ("Rosstat_RU",  _rosstat_ru, "RU"),
        ("INEGI_MX",    _inegi_mx,   "MX"),
        ("MOSPI_IN",    _mospi_in,   "IN"),
    ]
    for name, fn, country in sources:
        try:
            t0 = time.time()
            records = fn() or []
            for rec in records:
                rec.setdefault("country_hint", country)
                rec.setdefault("platform", "govstats")
                rec.setdefault("source", name)
                rec.setdefault("engagement", {"score": 0, "comments": 0})
                rec.setdefault("period", "year")
                rid = rec.get("id") or make_id(
                    "govstats", name, rec.get("occupation", ""), rec.get("year", "") or "",
                    rec.get("occupation_code", "") or "",
                )
                rec["id"] = rid
                if state.is_seen(rid):
                    continue
                append_jsonl(rec, "govstats", RAW_DIR)
                state.mark_seen(rid)
                items_added += 1
            print(f"[govstats] {name}: +{len(records)} records ({time.time()-t0:.1f}s)")
        except Exception as e:
            print(f"[govstats] {name} FAILED: {e}")
        state.save()
    state.save(force=True)
    print(f"[govstats] done, +{items_added} items")


if __name__ == "__main__":
    run()
