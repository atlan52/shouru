"""govstats_salary — 各国官方统计局工资 / 收入分布的权威基线抓取。

策略：
  - 每个机构选 1-2 个 SSR landing page（不下载 dataset zip）。
  - 抓页面 HTML，从中提取：
      a) 表格 row（行业 / 职业 + 工资数 + 货币 + 时间戳），或
      b) 出现「中位数 X 元 / 月」「mean wage X」「平均工资 X」等
         数额句的段落。
  - 把页面描述性段落 + 抽到的工资句拼成 body。
  - 严格本国语言，UA Chrome/124，polite ~2-3s。

输出：data/raw/govstats_salary_native_<DAY>.jsonl
record schema 与 r_mexico_native / otzovik_native 对齐：
  id / raw_id / platform=govstats_<CC>_<src> / lang / title / body /
  author=机构名 / url / country_hint / matched_keyword / engagement.

只挑了「最容易拿到 SSR HTML」的若干国家（避免登录墙 / SPA）：
  US / UK / DE / FR / JP / KR / BR / MX / AU / CA / IN / RU
失败的国家（4xx/5xx / 页面无工资数）会自动跳过。
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sys
import time
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUT_DIR = "/Users/jan/sen/code/spider/shouru/data/raw"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
TIMEOUT = 30
SLEEP = 2.5  # polite — statgov 慢

# ------------------------------------------------------------------ TARGETS

# 每个 entry: 国家代码、机构名简写、本国语言、Accept-Language、若干 landing pages、
# 货币（用于过滤数额单位），以及该国会出现「数额 + currency token」的常用形式
# 用一个 regex 匹配出工资句（每国一个，更稳）。
TARGETS: list[dict] = [
    # ---------------------------------------------------------------- US
    {
        "cc": "US",
        "src": "BLS",
        "lang": "en",
        "accept_lang": "en-US,en;q=0.9",
        "currency": "USD",
        "urls": [
            "https://www.bls.gov/oes/current/oes_nat.htm",
            "https://www.bls.gov/news.release/ocwage.htm",
            "https://www.bls.gov/news.release/empsit.htm",
        ],
        # $XX.XX / $XX,XXX
        "amount_re": re.compile(r"\$\s?[\d,]{2,}(?:\.\d+)?", re.U),
        "context_keywords": [
            "wage", "median", "mean", "annual", "hourly", "occupation",
            "salary", "earn",
        ],
    },
    # ---------------------------------------------------------------- UK
    {
        "cc": "GB",
        "src": "ONS",
        "lang": "en",
        "accept_lang": "en-GB,en;q=0.9",
        "currency": "GBP",
        "urls": [
            "https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork/earningsandworkinghours/bulletins/annualsurveyofhoursandearnings/2024",
            "https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork/earningsandworkinghours",
        ],
        # £XX,XXX or £XX.XX
        "amount_re": re.compile(r"£\s?[\d,]{2,}(?:\.\d+)?", re.U),
        "context_keywords": [
            "median", "mean", "earnings", "weekly", "annual", "wage", "salary",
            "hourly", "pay",
        ],
    },
    # ---------------------------------------------------------------- DE
    {
        "cc": "DE",
        "src": "Destatis",
        "lang": "de",
        "accept_lang": "de-DE,de;q=0.9,en;q=0.5",
        "currency": "EUR",
        "urls": [
            "https://www.destatis.de/DE/Themen/Arbeit/Verdienste/_inhalt.html",
            "https://www.destatis.de/DE/Themen/Arbeit/Verdienste/Branchen-Berufe/_inhalt.html",
            "https://www.destatis.de/DE/Themen/Arbeit/Verdienste/Verdienste-Verdienstunterschiede/_inhalt.html",
        ],
        # 40.000 € or 40 000 € or 4.500,50 €
        "amount_re": re.compile(r"\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?\s*€|\d+(?:,\d+)?\s*€", re.U),
        "context_keywords": [
            "verdienst", "lohn", "gehalt", "median", "durchschnitt", "monat",
            "jahr", "stunde", "brutto", "netto",
        ],
    },
    # ---------------------------------------------------------------- FR
    {
        "cc": "FR",
        "src": "INSEE",
        "lang": "fr",
        "accept_lang": "fr-FR,fr;q=0.9,en;q=0.5",
        "currency": "EUR",
        "urls": [
            "https://www.insee.fr/fr/statistiques/8275432",  # Salaires dans le privé en 2023
            "https://www.insee.fr/fr/statistiques/4277630",  # Salaires dans la fonction publique
            "https://www.insee.fr/fr/statistiques/2381498",  # Salaires moyens
        ],
        # 2 500 € or 30 000 €  (FR uses NBSP / regular space as 千分位)
        "amount_re": re.compile(r"\d{1,3}(?:[\s ]\d{3})+(?:,\d+)?\s*(?:€|euros?)|\d+(?:,\d+)?\s*(?:€|euros?)", re.U | re.I),
        "context_keywords": [
            "salaire", "médian", "moyen", "mensuel", "annuel", "horaire",
            "smic", "brut", "net", "rémunération",
        ],
    },
    # ---------------------------------------------------------------- JP
    {
        "cc": "JP",
        "src": "MHLW",
        "lang": "ja",
        "accept_lang": "ja-JP,ja;q=0.9,en;q=0.5",
        "currency": "JPY",
        "urls": [
            "https://www.mhlw.go.jp/toukei/itiran/roudou/chingin/kouzou/z2023/index.html",
            "https://www.mhlw.go.jp/toukei/list/chinginkouzou.html",
        ],
        # 300,000 円 / 30万円 / 3,000千円
        "amount_re": re.compile(r"\d{1,3}(?:,\d{3})+\s*(?:円|千円|万円)|\d+\s*万円|\d+\s*千円", re.U),
        "context_keywords": [
            "賃金", "給与", "年収", "月収", "平均", "中央値", "所定内", "所得",
            "報酬",
        ],
    },
    # ---------------------------------------------------------------- KR
    {
        "cc": "KR",
        "src": "KOSTAT",
        "lang": "ko",
        "accept_lang": "ko-KR,ko;q=0.9,en;q=0.5",
        "currency": "KRW",
        "urls": [
            "https://kostat.go.kr/board.es?mid=a10301060300&bid=210",
            "https://kostat.go.kr/anse/index.action",
        ],
        # 3,500,000원 / 350만원
        "amount_re": re.compile(r"\d{1,3}(?:,\d{3})+\s*원|\d+\s*만\s*원|\d+\s*억\s*원", re.U),
        "context_keywords": [
            "임금", "급여", "월급", "연봉", "평균", "중위", "소득",
        ],
    },
    # ---------------------------------------------------------------- CN
    {
        "cc": "CN",
        "src": "NBS",
        "lang": "zh",
        "accept_lang": "zh-CN,zh;q=0.9,en;q=0.5",
        "currency": "CNY",
        "urls": [
            "https://www.stats.gov.cn/sj/zxfb/202405/t20240520_1955622.html",  # 2023年城镇单位平均工资
            "https://www.stats.gov.cn/sj/sjjd/202405/t20240520_1955628.html",
            "https://www.stats.gov.cn/sj/",
        ],
        # 100,000元 / 10万元 / 5000元
        "amount_re": re.compile(r"\d{1,3}(?:,\d{3})+\s*元|\d+(?:\.\d+)?\s*万元|\d{3,}\s*元", re.U),
        "context_keywords": [
            "工资", "薪酬", "年薪", "月薪", "平均", "中位", "收入", "城镇", "私营",
            "非私营",
        ],
    },
    # ---------------------------------------------------------------- BR
    {
        "cc": "BR",
        "src": "IBGE",
        "lang": "pt",
        "accept_lang": "pt-BR,pt;q=0.9,en;q=0.5",
        "currency": "BRL",
        "urls": [
            "https://www.ibge.gov.br/estatisticas/sociais/trabalho/9171-pesquisa-nacional-por-amostra-de-domicilios-continua-mensal.html",
            "https://www.ibge.gov.br/explica/desemprego.php",
            "https://agenciadenoticias.ibge.gov.br/agencia-sala-de-imprensa/2013-agencia-de-noticias/releases.html?categoria=mercado-de-trabalho",
        ],
        # R$ 3.500,00
        "amount_re": re.compile(r"R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d+)?|R\$\s?\d+(?:,\d+)?", re.U),
        "context_keywords": [
            "rendimento", "salário", "médio", "mediano", "habitual", "mensal",
            "renda", "trabalho",
        ],
    },
    # ---------------------------------------------------------------- MX
    {
        "cc": "MX",
        "src": "INEGI",
        "lang": "es",
        "accept_lang": "es-MX,es;q=0.9,en;q=0.5",
        "currency": "MXN",
        "urls": [
            "https://www.inegi.org.mx/temas/empleo/",
            "https://www.inegi.org.mx/programas/enoe/15ymas/",
            "https://www.inegi.org.mx/programas/enoen/15ymas/",
        ],
        # $5,000.00 / $5 000 (MXN — pesos)
        "amount_re": re.compile(r"\$\s?\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?", re.U),
        "context_keywords": [
            "salario", "ingreso", "promedio", "mediano", "mensual", "diario",
            "remuneración", "sueldo",
        ],
    },
    # ---------------------------------------------------------------- AU
    {
        "cc": "AU",
        "src": "ABS",
        "lang": "en",
        "accept_lang": "en-AU,en;q=0.9",
        "currency": "AUD",
        "urls": [
            "https://www.abs.gov.au/statistics/labour/earnings-and-working-conditions/average-weekly-earnings-australia/latest-release",
            "https://www.abs.gov.au/statistics/labour/earnings-and-working-conditions/employee-earnings-and-hours-australia/latest-release",
            "https://www.abs.gov.au/statistics/labour/earnings-and-working-conditions/employee-earnings/latest-release",
        ],
        "amount_re": re.compile(r"\$\s?[\d,]{2,}(?:\.\d+)?", re.U),
        "context_keywords": [
            "weekly", "earnings", "median", "mean", "average", "wage", "salary",
            "full-time",
        ],
    },
    # ---------------------------------------------------------------- CA
    {
        "cc": "CA",
        "src": "StatCan",
        "lang": "en",
        "accept_lang": "en-CA,en;q=0.9,fr-CA;q=0.5",
        "currency": "CAD",
        "urls": [
            "https://www150.statcan.gc.ca/n1/daily-quotidien/240426/dq240426a-eng.htm",
            "https://www150.statcan.gc.ca/n1/pub/71-222-x/71-222-x2024001-eng.htm",
            "https://www.statcan.gc.ca/en/subjects-start/labour_/wages_and_salaries",
        ],
        "amount_re": re.compile(r"\$\s?[\d,]{2,}(?:\.\d+)?", re.U),
        "context_keywords": [
            "wage", "median", "mean", "average", "weekly", "hourly", "annual",
            "earnings", "salary",
        ],
    },
    # ---------------------------------------------------------------- RU
    {
        "cc": "RU",
        "src": "Rosstat",
        "lang": "ru",
        "accept_lang": "ru-RU,ru;q=0.9,en;q=0.5",
        "currency": "RUB",
        "urls": [
            "https://rosstat.gov.ru/labour_force",
            "https://rosstat.gov.ru/labour_costs",
            "https://rosstat.gov.ru/storage/mediabank/itog-monitor11-23.html",
        ],
        # 50 000 рублей / 50000 руб
        "amount_re": re.compile(r"\d{1,3}(?:[\s ]\d{3})+(?:,\d+)?\s*(?:руб|рублей|₽)|\d{4,}\s*(?:руб|рублей|₽)", re.U | re.I),
        "context_keywords": [
            "зарплат", "заработн", "средн", "медиан", "доход", "оклад",
        ],
    },
    # ---------------------------------------------------------------- IN
    {
        "cc": "IN",
        "src": "MOSPI",
        "lang": "en",
        "accept_lang": "en-IN,en;q=0.9,hi;q=0.5",
        "currency": "INR",
        "urls": [
            "https://mospi.gov.in/216-press-release",
            "https://www.mospi.gov.in/sites/default/files/publication_reports/Periodic_Labour_Force_Survey_Quarterly_Bulletin_Quarter_Ending_December_2023.pdf",
            "https://mospi.gov.in/16-employment-unemployment",
        ],
        # ₹50,000 / Rs. 50,000
        "amount_re": re.compile(r"(?:₹|Rs\.?)\s?[\d,]{2,}(?:\.\d+)?", re.U | re.I),
        "context_keywords": [
            "wage", "earning", "median", "mean", "monthly", "average",
            "salary", "income",
        ],
    },
]

OFFICIAL_NAMES = {
    "US": "U.S. Bureau of Labor Statistics",
    "GB": "UK Office for National Statistics",
    "DE": "Statistisches Bundesamt (Destatis)",
    "FR": "Institut national de la statistique (INSEE)",
    "JP": "厚生労働省 賃金構造基本統計調査",
    "KR": "통계청 (Statistics Korea)",
    "CN": "国家统计局",
    "BR": "Instituto Brasileiro de Geografia e Estatística (IBGE)",
    "MX": "Instituto Nacional de Estadística y Geografía (INEGI)",
    "AU": "Australian Bureau of Statistics (ABS)",
    "CA": "Statistics Canada",
    "RU": "Федеральная служба государственной статистики (Rosstat)",
    "IN": "Ministry of Statistics and Programme Implementation (MoSPI)",
}


# ------------------------------------------------------------------ HTTP

def headers(accept_lang: str) -> dict:
    return {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": accept_lang,
        "Cache-Control": "no-cache",
    }


def fetch(url: str, accept_lang: str) -> str | None:
    try:
        r = requests.get(url, headers=headers(accept_lang), timeout=TIMEOUT, allow_redirects=True)
    except Exception as e:
        print(f"  fetch err {url}: {e}", file=sys.stderr)
        return None
    if r.status_code >= 400:
        print(f"  status {r.status_code} {url}", file=sys.stderr)
        return None
    # encoding sniff: requests' default may misdetect on Asian sites
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding or "utf-8"
    return r.text


# ------------------------------------------------------------------ PARSE

NAV_HINTS = (
    # title 中带这些关键词的极可能是搜索/列表/导航页 — 跳过
    "search results",
    "site map",
    "サイトマップ",
    "搜索结果",
    "результаты поиска",
    "résultats de recherche",
)


def page_title(soup: BeautifulSoup) -> str:
    t = soup.select_one("h1") or soup.select_one("title")
    return (t.get_text(" ", strip=True) if t else "").strip()[:300]


def is_nav_page(title: str) -> bool:
    tl = title.lower()
    return any(h in tl for h in NAV_HINTS)


def descriptive_paragraph(soup: BeautifulSoup, max_len: int = 800) -> str:
    """Pick a paragraph that's description-y (longest p in <article>/<main>)."""
    container = (
        soup.find("article")
        or soup.find("main")
        or soup.find("div", attrs={"role": "main"})
        or soup.body
    )
    if container is None:
        return ""
    paras = [p.get_text(" ", strip=True) for p in container.find_all(["p", "li"])]
    paras = [p for p in paras if len(p) >= 60]
    if not paras:
        return ""
    paras.sort(key=len, reverse=True)
    return paras[0][:max_len]


def extract_table_rows(soup: BeautifulSoup, amount_re: re.Pattern, max_rows: int = 25) -> list[str]:
    """For every <table>, return rows where the row text contains an amount.

    Each returned string is formatted as: "<row text> [first amount: X]".
    """
    out: list[str] = []
    for table in soup.find_all("table"):
        # skip layout tables (no <tr> with td & th)
        rows = table.find_all("tr")
        for tr in rows:
            cells = tr.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            row_text = " | ".join(c.get_text(" ", strip=True) for c in cells)
            row_text = re.sub(r"\s+", " ", row_text).strip()
            if not row_text or len(row_text) > 400:
                continue
            m = amount_re.search(row_text)
            if not m:
                continue
            out.append(row_text)
            if len(out) >= max_rows:
                return out
    return out


def extract_amount_sentences(
    soup: BeautifulSoup,
    amount_re: re.Pattern,
    context_keywords: list[str],
    max_sents: int = 15,
) -> list[str]:
    """Find sentences in body that contain BOTH an amount and at least one
    income-related keyword (in that target's language)."""
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    # crude sentence split — works well enough for EN/DE/FR/RU; for JP/CN/KR
    # we also split on 。 / . / ！ / ？
    sents = re.split(r"(?<=[\.\!\?。！？])\s+", text)
    out: list[str] = []
    seen: set[str] = set()
    kws_lower = [k.lower() for k in context_keywords]
    for s in sents:
        s = s.strip()
        if not s or len(s) < 30 or len(s) > 500:
            continue
        if not amount_re.search(s):
            continue
        sl = s.lower()
        if not any(k in sl for k in kws_lower):
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= max_sents:
            break
    return out


def make_id(*parts: str) -> str:
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ MAIN

def process_target(t: dict, out_fp, seen: set[str]) -> tuple[int, int]:
    """Returns (items_seen_pages, items_written)."""
    cc = t["cc"]
    pages_ok = 0
    written = 0
    official = OFFICIAL_NAMES.get(cc, t["src"])
    for url in t["urls"]:
        print(f"[{cc}/{t['src']}] GET {url}", flush=True)
        html = fetch(url, t["accept_lang"])
        time.sleep(SLEEP)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        title = page_title(soup) or f"{official} — {urlparse(url).path}"
        if is_nav_page(title):
            print(f"  -> nav page, skip ({title!r})", file=sys.stderr)
            continue
        pages_ok += 1

        desc = descriptive_paragraph(soup)
        rows = extract_table_rows(soup, t["amount_re"])
        sents = extract_amount_sentences(soup, t["amount_re"], t["context_keywords"])

        # Prefer table rows (one record per row, max ~10), fallback to sentences,
        # plus a single "summary" record for the page itself.
        if rows:
            # one record per useful row
            for i, row in enumerate(rows):
                rid = make_id(cc, t["src"], url, "row", str(i), row[:80])
                if rid in seen:
                    continue
                amount_match = t["amount_re"].search(row)
                amt_str = amount_match.group(0) if amount_match else ""
                body_chunks = [
                    f"{official} — {title}",
                    desc[:400] if desc else "",
                    f"[Table row]: {row}",
                ]
                body = "\n\n".join(c for c in body_chunks if c)[:3000]
                rec = {
                    "id": rid,
                    "raw_id": f"{cc}_{t['src']}_row_{i}_{hashlib.md5(row.encode()).hexdigest()[:8]}",
                    "platform": f"govstats_{cc}_{t['src']}",
                    "lang": t["lang"],
                    "title": f"{official}: {title[:200]}",
                    "body": body,
                    "author": official,
                    "url": url,
                    "country_hint": cc,
                    "matched_keyword": amt_str[:40],
                    "engagement": {"score": 0, "comments": 0, "views": 0},
                    "currency": t["currency"],
                    "src_kind": "table_row",
                }
                out_fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out_fp.flush()
                seen.add(rid)
                written += 1

        if sents:
            for i, sent in enumerate(sents):
                rid = make_id(cc, t["src"], url, "sent", str(i), sent[:80])
                if rid in seen:
                    continue
                amount_match = t["amount_re"].search(sent)
                amt_str = amount_match.group(0) if amount_match else ""
                body_chunks = [
                    f"{official} — {title}",
                    desc[:400] if desc else "",
                    f"[Excerpt]: {sent}",
                ]
                body = "\n\n".join(c for c in body_chunks if c)[:3000]
                rec = {
                    "id": rid,
                    "raw_id": f"{cc}_{t['src']}_sent_{i}_{hashlib.md5(sent.encode()).hexdigest()[:8]}",
                    "platform": f"govstats_{cc}_{t['src']}",
                    "lang": t["lang"],
                    "title": f"{official}: {title[:200]}",
                    "body": body,
                    "author": official,
                    "url": url,
                    "country_hint": cc,
                    "matched_keyword": amt_str[:40],
                    "engagement": {"score": 0, "comments": 0, "views": 0},
                    "currency": t["currency"],
                    "src_kind": "amount_sentence",
                }
                out_fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out_fp.flush()
                seen.add(rid)
                written += 1

        if not rows and not sents:
            # last-resort: keep a single page-level record only if the desc
            # paragraph itself contains an amount — otherwise skip (likely a
            # nav/landing without numbers).
            blob = (desc or "") + " " + title
            if t["amount_re"].search(blob):
                rid = make_id(cc, t["src"], url, "page")
                if rid not in seen:
                    body = f"{official} — {title}\n\n{desc}"[:3000]
                    rec = {
                        "id": rid,
                        "raw_id": f"{cc}_{t['src']}_page_{hashlib.md5(url.encode()).hexdigest()[:8]}",
                        "platform": f"govstats_{cc}_{t['src']}",
                        "lang": t["lang"],
                        "title": f"{official}: {title[:200]}",
                        "body": body,
                        "author": official,
                        "url": url,
                        "country_hint": cc,
                        "matched_keyword": "",
                        "engagement": {"score": 0, "comments": 0, "views": 0},
                        "currency": t["currency"],
                        "src_kind": "page_summary",
                    }
                    out_fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    out_fp.flush()
                    seen.add(rid)
                    written += 1
            else:
                print(
                    f"  -> no rows / no sents / no amount in desc, skipping page",
                    file=sys.stderr,
                )

        print(f"  -> rows={len(rows)} sents={len(sents)} written_total={written}", flush=True)

    return pages_ok, written


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    today = datetime.datetime.now().strftime("%Y%m%d")
    out_path = os.path.join(OUT_DIR, f"govstats_salary_native_{today}.jsonl")

    seen: set[str] = set()
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    seen.add(json.loads(line)["id"])
                except Exception:
                    pass
        print(f"[init] resumed seen={len(seen)} from {out_path}")

    per_country: dict[str, tuple[int, int]] = {}
    total_written = 0

    with open(out_path, "a", encoding="utf-8") as out_fp:
        for t in TARGETS:
            cc = t["cc"]
            try:
                pages, written = process_target(t, out_fp, seen)
            except Exception as e:
                print(f"[{cc}] EXC {e}", file=sys.stderr)
                pages, written = 0, 0
            per_country[cc] = (pages, written)
            total_written += written

    # Summary count from file (incl. resumed lines)
    file_lines = 0
    with open(out_path, "r", encoding="utf-8") as f:
        for _ in f:
            file_lines += 1

    print("\n========== SUMMARY ==========")
    for cc, (pages, written) in per_country.items():
        print(f"  {cc:>3} pages_ok={pages} written_new={written}")
    print(f"  total_new_written={total_written}")
    print(f"  file_total_lines={file_lines}")
    print(f"  out={out_path}")


if __name__ == "__main__":
    main()
