"""shouru — Cross-country income & earning mechanism explorer.

Run:
  cd /Users/jan/sen/code/spider/shouru
  .venv/bin/python -m website.app
Then open http://localhost:5050
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from flask import Flask, abort, g, jsonify, render_template, request, url_for, send_from_directory

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "curated" / "income.db"
REPORTS_DIR = ROOT / "data" / "curated" / "reports"
FIGS_DIR = ROOT / "data" / "curated" / "figs"
RAW_DIR = ROOT / "data" / "raw"

PER_PAGE = 50

app = Flask(
    __name__,
    static_folder=str(Path(__file__).parent / "static"),
    template_folder=str(Path(__file__).parent / "templates"),
)


# ============================================================================
# DB connection
# ============================================================================

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn:
        conn.close()


# ============================================================================
# Constants & helpers
# ============================================================================

COUNTRY_NAMES = {
    "US": "美国", "GB": "英国", "CA": "加拿大", "AU": "澳大利亚", "NZ": "新西兰",
    "IE": "爱尔兰", "JP": "日本", "CN": "中国", "TW": "台湾", "HK": "香港",
    "KR": "韩国", "DE": "德国", "AT": "奥地利", "CH": "瑞士", "FR": "法国",
    "IT": "意大利", "ES": "西班牙", "PT": "葡萄牙", "NL": "荷兰", "BE": "比利时",
    "SE": "瑞典", "NO": "挪威", "DK": "丹麦", "FI": "芬兰", "IS": "冰岛",
    "PL": "波兰", "CZ": "捷克", "HU": "匈牙利", "RO": "罗马尼亚", "BG": "保加利亚",
    "HR": "克罗地亚", "RS": "塞尔维亚", "SI": "斯洛文尼亚", "SK": "斯洛伐克",
    "EE": "爱沙尼亚", "LV": "拉脱维亚", "LT": "立陶宛", "RU": "俄罗斯", "UA": "乌克兰",
    "BY": "白俄罗斯", "TR": "土耳其", "GE": "格鲁吉亚", "AM": "亚美尼亚", "AZ": "阿塞拜疆",
    "KZ": "哈萨克斯坦", "UZ": "乌兹别克斯坦", "IL": "以色列", "SA": "沙特", "AE": "阿联酋",
    "QA": "卡塔尔", "KW": "科威特", "BH": "巴林", "OM": "阿曼", "JO": "约旦",
    "LB": "黎巴嫩", "EG": "埃及", "MA": "摩洛哥", "TN": "突尼斯", "DZ": "阿尔及利亚",
    "NG": "尼日利亚", "KE": "肯尼亚", "GH": "加纳", "ET": "埃塞俄比亚", "TZ": "坦桑尼亚",
    "UG": "乌干达", "ZA": "南非", "IN": "印度", "PK": "巴基斯坦", "BD": "孟加拉",
    "LK": "斯里兰卡", "NP": "尼泊尔", "ID": "印尼", "MY": "马来西亚", "SG": "新加坡",
    "PH": "菲律宾", "TH": "泰国", "VN": "越南", "MM": "缅甸", "KH": "柬埔寨",
    "MX": "墨西哥", "AR": "阿根廷", "BR": "巴西", "CL": "智利", "CO": "哥伦比亚",
    "PE": "秘鲁", "VE": "委内瑞拉", "UY": "乌拉圭", "PY": "巴拉圭", "EC": "厄瓜多尔",
    "BO": "玻利维亚", "CR": "哥斯达黎加", "PA": "巴拿马", "CU": "古巴", "DO": "多米尼加",
    "GT": "危地马拉", "SV": "萨尔瓦多", "HN": "洪都拉斯", "NI": "尼加拉瓜", "JM": "牙买加",
    "IR": "伊朗", "GR": "希腊",
}

LANG_NAMES = {
    "en": "英语", "zh": "中文", "ja": "日语", "ko": "韩语", "de": "德语",
    "fr": "法语", "it": "意大利语", "es": "西班牙语", "pt": "葡萄牙语", "ru": "俄语",
    "tr": "土耳其语", "ar": "阿拉伯语", "hi": "印地语", "id": "印尼语", "th": "泰语",
    "vi": "越南语", "pl": "波兰语", "nl": "荷兰语", "sv": "瑞典语", "no": "挪威语",
    "da": "丹麦语", "fi": "芬兰语", "uk": "乌克兰语", "he": "希伯来语", "ms": "马来语",
    "tl": "他加禄语", "cs": "捷克语", "hu": "匈牙利语", "ro": "罗马尼亚语",
    "bg": "保加利亚语", "el": "希腊语", "fa": "波斯语", "ua": "乌克兰语",
}

BRACKET_LABEL = {
    "bottom": "Bottom 底层",
    "lower_middle": "Lower-middle 下中产",
    "middle": "Middle 中产",
    "upper_middle": "Upper-middle 上中产",
    "top": "Top 顶层",
    "unknown": "未知",
}

BRACKET_ORDER = ["bottom", "lower_middle", "middle", "upper_middle", "top", "unknown"]

MECHANISM_LABEL = {
    "salary_employment": "工资雇佣",
    "equity_compensation": "股权期权",
    "business_owner": "企业主",
    "freelance_contractor": "自由职业",
    "platform_gig": "平台零工",
    "passive_investment": "被动投资",
    "real_estate_rental": "房产租金",
    "royalties_creator": "创作者收入",
    "inheritance_trust": "遗产信托",
    "government_pension": "退休金",
    "illicit_grey": "灰色非法",
    "multiple_streams": "多重收入",
    "unknown": "未知",
}


def country_name(code: str) -> str:
    return COUNTRY_NAMES.get(code, code)


def lang_name(code: str) -> str:
    return LANG_NAMES.get(code, code)


def bracket_label(b: str) -> str:
    return BRACKET_LABEL.get(b, b)


def mechanism_label(m: str) -> str:
    return MECHANISM_LABEL.get(m, m)


# Register Jinja filters
app.jinja_env.filters["country_name"] = country_name
app.jinja_env.filters["lang_name"] = lang_name
app.jinja_env.filters["bracket_label"] = bracket_label
app.jinja_env.filters["mechanism_label"] = mechanism_label


@app.context_processor
def inject_globals():
    return {
        "BRACKET_ORDER": BRACKET_ORDER,
        "BRACKET_LABEL": BRACKET_LABEL,
        "MECHANISM_LABEL": MECHANISM_LABEL,
        "COUNTRY_NAMES": COUNTRY_NAMES,
    }


# ============================================================================
# Routes — pages
# ============================================================================

@app.route("/")
def index():
    """Home — global stats, top countries/professions, recent records."""
    cur = db().cursor()

    stats = {
        "total": cur.execute("SELECT COUNT(*) FROM income_records").fetchone()[0],
        "countries": cur.execute("SELECT COUNT(DISTINCT country) FROM income_records").fetchone()[0],
        "with_usd": cur.execute(
            "SELECT COUNT(*) FROM income_records WHERE income_amount_usd_year IS NOT NULL"
        ).fetchone()[0],
        "platforms": cur.execute(
            "SELECT COUNT(DISTINCT source_platform) FROM income_records"
        ).fetchone()[0],
        "languages": cur.execute(
            "SELECT COUNT(DISTINCT source_lang) FROM income_records"
        ).fetchone()[0],
    }

    # Top 30 countries — compute median in Python (SQLite subquery scoping is finicky)
    base = cur.execute("""
        SELECT country,
               COUNT(*) AS n,
               COUNT(income_amount_usd_year) AS n_usd,
               CAST(AVG(income_amount_usd_year) AS REAL) AS avg_usd
        FROM income_records
        WHERE country != '??' AND country IS NOT NULL
        GROUP BY 1 ORDER BY n DESC LIMIT 30
    """).fetchall()
    countries = []
    for b in base:
        usd_vals = [r[0] for r in cur.execute(
            "SELECT income_amount_usd_year FROM income_records "
            "WHERE country = ? AND income_amount_usd_year IS NOT NULL "
            "ORDER BY income_amount_usd_year",
            (b["country"],)
        ).fetchall()]
        median = usd_vals[len(usd_vals) // 2] if usd_vals else None
        countries.append({
            "country": b["country"], "n": b["n"], "n_usd": b["n_usd"],
            "avg_usd": b["avg_usd"], "median_usd": median,
        })

    # Top professions
    professions = cur.execute("""
        SELECT profession, COUNT(*) AS n
        FROM income_records
        WHERE profession != '' AND profession IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC LIMIT 20
    """).fetchall()

    # Bracket distribution
    brackets = cur.execute("""
        SELECT income_bracket, COUNT(*) AS n
        FROM income_records GROUP BY 1
    """).fetchall()
    bracket_dist = {row["income_bracket"]: row["n"] for row in brackets}

    # Mechanism distribution
    mechanisms = cur.execute("""
        SELECT mechanism, COUNT(*) AS n
        FROM earning_mechanisms GROUP BY 1 ORDER BY 2 DESC
    """).fetchall()

    # Language distribution
    langs = cur.execute("""
        SELECT source_lang, COUNT(*) AS n
        FROM income_records GROUP BY 1 ORDER BY 2 DESC LIMIT 20
    """).fetchall()

    # Platform distribution
    platforms = cur.execute("""
        SELECT source_platform, COUNT(*) AS n
        FROM income_records GROUP BY 1 ORDER BY 2 DESC LIMIT 20
    """).fetchall()

    return render_template(
        "index.html",
        stats=stats,
        countries=countries,
        professions=professions,
        bracket_dist=bracket_dist,
        mechanisms=mechanisms,
        langs=langs,
        platforms=platforms,
    )


@app.route("/country/<code>")
def country(code):
    """Single country detail page."""
    code = code.upper()
    cur = db().cursor()

    rows = cur.execute("""
        SELECT * FROM income_records
        WHERE country = ?
        ORDER BY confidence DESC, income_amount_usd_year DESC NULLS LAST
    """, (code,)).fetchall()

    if not rows:
        abort(404)

    n_total = len(rows)
    n_with_usd = sum(1 for r in rows if r["income_amount_usd_year"])
    usd_values = sorted([r["income_amount_usd_year"] for r in rows if r["income_amount_usd_year"]])

    median_usd = usd_values[len(usd_values) // 2] if usd_values else None
    avg_usd = sum(usd_values) / len(usd_values) if usd_values else None

    bracket_counts = Counter(r["income_bracket"] for r in rows)
    profession_counts = Counter(r["profession"] for r in rows if r["profession"]).most_common(15)
    platform_counts = Counter(r["source_platform"] for r in rows).most_common()

    # Mechanisms for this country
    mech_rows = cur.execute("""
        SELECT em.mechanism, COUNT(*) AS n
        FROM earning_mechanisms em
        JOIN income_records ir ON em.record_id = ir.record_id
        WHERE ir.country = ?
        GROUP BY 1 ORDER BY 2 DESC
    """, (code,)).fetchall()

    # Sample records: 1 per bracket, max 3 per
    samples_by_bracket = defaultdict(list)
    for r in rows:
        b = r["income_bracket"] or "unknown"
        if len(samples_by_bracket[b]) < 3:
            samples_by_bracket[b].append(r)

    # Existing markdown report
    md_path = REPORTS_DIR / f"{code}.md"
    md_report = md_path.read_text(encoding="utf-8") if md_path.exists() else None

    return render_template(
        "country.html",
        code=code,
        country_name=country_name(code),
        rows=rows[:200],  # cap displayed rows
        n_total=n_total,
        n_with_usd=n_with_usd,
        median_usd=median_usd,
        avg_usd=avg_usd,
        bracket_counts=bracket_counts,
        profession_counts=profession_counts,
        platform_counts=platform_counts,
        mech_rows=mech_rows,
        samples_by_bracket=samples_by_bracket,
        md_report=md_report,
    )


@app.route("/records")
def records():
    """Data explorer — paginated, filterable table."""
    page = max(1, int(request.args.get("page", 1)))
    q_country = request.args.get("country", "").strip().upper()
    q_lang = request.args.get("lang", "").strip().lower()
    q_bracket = request.args.get("bracket", "").strip()
    q_profession = request.args.get("profession", "").strip()
    q_mechanism = request.args.get("mechanism", "").strip()
    q_currency = request.args.get("currency", "").strip().upper()
    q_text = request.args.get("q", "").strip()
    q_min_usd = request.args.get("min_usd", "").strip()
    q_max_usd = request.args.get("max_usd", "").strip()

    where = []
    params: list = []
    if q_country:
        where.append("country = ?")
        params.append(q_country)
    if q_lang:
        where.append("source_lang = ?")
        params.append(q_lang)
    if q_bracket:
        where.append("income_bracket = ?")
        params.append(q_bracket)
    if q_profession:
        where.append("profession LIKE ?")
        params.append(f"%{q_profession}%")
    if q_currency:
        where.append("currency = ?")
        params.append(q_currency)
    if q_text:
        where.append("(narrative_summary LIKE ? OR raw_excerpt LIKE ? OR profession_raw LIKE ?)")
        params.extend([f"%{q_text}%"] * 3)
    if q_min_usd:
        try:
            where.append("income_amount_usd_year >= ?")
            params.append(float(q_min_usd))
        except ValueError:
            pass
    if q_max_usd:
        try:
            where.append("income_amount_usd_year <= ?")
            params.append(float(q_max_usd))
        except ValueError:
            pass

    if q_mechanism:
        where.append("record_id IN (SELECT record_id FROM earning_mechanisms WHERE mechanism = ?)")
        params.append(q_mechanism)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    cur = db().cursor()
    total = cur.execute(f"SELECT COUNT(*) FROM income_records {where_sql}", params).fetchone()[0]
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = min(page, pages)

    rows = cur.execute(f"""
        SELECT * FROM income_records
        {where_sql}
        ORDER BY confidence DESC, income_amount_usd_year DESC NULLS LAST
        LIMIT ? OFFSET ?
    """, params + [PER_PAGE, (page - 1) * PER_PAGE]).fetchall()

    # Filter dropdown options
    all_countries = [r["country"] for r in cur.execute(
        "SELECT country, COUNT(*) AS n FROM income_records GROUP BY 1 ORDER BY n DESC"
    ).fetchall()]
    all_langs = [r["source_lang"] for r in cur.execute(
        "SELECT source_lang, COUNT(*) AS n FROM income_records WHERE source_lang IS NOT NULL GROUP BY 1 ORDER BY n DESC"
    ).fetchall()]
    all_currencies = [r[0] for r in cur.execute(
        "SELECT currency FROM income_records WHERE currency IS NOT NULL AND currency != '' GROUP BY 1 ORDER BY COUNT(*) DESC"
    ).fetchall()]

    return render_template(
        "records.html",
        rows=rows,
        total=total,
        page=page,
        pages=pages,
        per_page=PER_PAGE,
        filters={
            "country": q_country,
            "lang": q_lang,
            "bracket": q_bracket,
            "profession": q_profession,
            "mechanism": q_mechanism,
            "currency": q_currency,
            "q": q_text,
            "min_usd": q_min_usd,
            "max_usd": q_max_usd,
        },
        all_countries=all_countries,
        all_langs=all_langs,
        all_currencies=all_currencies,
    )


@app.route("/record/<rid>")
def record_detail(rid):
    cur = db().cursor()
    row = cur.execute("SELECT * FROM income_records WHERE record_id = ?", (rid,)).fetchone()
    if not row:
        abort(404)
    mechs = cur.execute(
        "SELECT mechanism FROM earning_mechanisms WHERE record_id = ?", (rid,)
    ).fetchall()
    return render_template("record.html", row=row, mechs=[m["mechanism"] for m in mechs])


@app.route("/visualizations")
def visualizations():
    figs = []
    for f in sorted(FIGS_DIR.glob("*.html")):
        figs.append({
            "name": f.stem,
            "html_url": f"/figs/{f.name}",
        })
    return render_template("visualizations.html", figs=figs)


@app.route("/figs/<path:fname>")
def serve_fig(fname):
    return send_from_directory(FIGS_DIR, fname)


@app.route("/platforms")
def platforms():
    cur = db().cursor()
    rows = cur.execute("""
        SELECT source_platform, COUNT(*) AS n,
               COUNT(DISTINCT country) AS n_countries,
               COUNT(income_amount_usd_year) AS n_usd
        FROM income_records GROUP BY 1 ORDER BY n DESC
    """).fetchall()
    return render_template("platforms.html", rows=rows)


@app.route("/mechanisms")
def mechanisms():
    cur = db().cursor()
    rows = cur.execute("""
        SELECT em.mechanism,
               COUNT(*) AS n,
               COUNT(DISTINCT ir.country) AS n_countries,
               AVG(ir.income_amount_usd_year) AS avg_usd
        FROM earning_mechanisms em
        JOIN income_records ir ON em.record_id = ir.record_id
        GROUP BY 1 ORDER BY n DESC
    """).fetchall()
    # Per-country mechanism share
    per_country = cur.execute("""
        SELECT ir.country, em.mechanism, COUNT(*) AS n
        FROM earning_mechanisms em
        JOIN income_records ir ON em.record_id = ir.record_id
        WHERE ir.country != '??'
        GROUP BY 1, 2
    """).fetchall()
    return render_template("mechanisms.html", rows=rows, per_country=per_country)


@app.route("/about")
def about():
    summary_path = ROOT / "data" / "curated" / "native_raw_summary.md"
    summary_md = summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""
    return render_template("about.html", summary_md=summary_md)


@app.route("/api/records")
def api_records():
    """JSON API for AJAX use."""
    cur = db().cursor()
    rows = cur.execute("""
        SELECT record_id, country, income_amount_usd_year, profession, source_platform
        FROM income_records LIMIT 500
    """).fetchall()
    return jsonify([dict(r) for r in rows])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)
