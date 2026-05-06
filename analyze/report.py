"""Render 40 country markdown reports + _index.md (jinja2).

Pulls all numbers via `analyze.aggregate.*` and renders
`templates/country_report.md.j2` for each ISO-2 in COUNTRIES_40.
Each country render is wrapped in try/except so one bad country never
kills the whole batch.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from config import (
    BRACKETS_5,
    COUNTRIES_40,
    COUNTRY_BRACKETS,
    COUNTRY_NAMES_EN,
    CURATED_DIR,
)
from analyze import aggregate as agg

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

TPL_DIR = Path(__file__).parent / "templates"
REPORTS_DIR = CURATED_DIR / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

LOW_CONFIDENCE_THRESHOLD = 0.5

_env = Environment(
    loader=FileSystemLoader(str(TPL_DIR)),
    autoescape=select_autoescape(disabled_extensions=("md", "j2")),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def _country_brackets(country: str) -> dict:
    return COUNTRY_BRACKETS.get(country) or COUNTRY_BRACKETS["DEFAULT"]


def _bracket_counts_for(country: str, all_counts: pd.DataFrame) -> pd.Series:
    if country not in all_counts.index:
        return pd.Series(dtype="int64")
    row = all_counts.loc[country]
    cols = [b for b in BRACKETS_5 if b in row.index]
    return row.reindex(cols).fillna(0).astype(int)


def _mechanism_share_for(country: str, all_share: pd.DataFrame) -> pd.Series:
    if all_share is None or all_share.empty or country not in all_share.index:
        return pd.Series(dtype="float64")
    return all_share.loc[country].sort_values(ascending=False)


def _avg_usd_for(country: str, avg_df: pd.DataFrame):
    if avg_df is None or avg_df.empty:
        return None, 0
    sub = avg_df[avg_df["country"] == country]
    if sub.empty:
        return None, 0
    val = sub["avg_usd_year"].iloc[0]
    n = int(sub["n_with_amount"].iloc[0]) if not pd.isna(sub["n_with_amount"].iloc[0]) else 0
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None, n
    return float(val), n


def _low_confidence_count(country: str) -> int:
    import sqlite3
    sql = """
        SELECT COUNT(*) FROM income_records
        WHERE country = ? AND confidence IS NOT NULL AND confidence < ?
    """
    with sqlite3.connect(CURATED_DIR / "income.db") as c:
        cur = c.execute(sql, (country, LOW_CONFIDENCE_THRESHOLD))
        (n,) = cur.fetchone()
    return int(n)


def render_country(
    country: str,
    *,
    all_counts: pd.DataFrame,
    all_share: pd.DataFrame,
    avg_df: pd.DataFrame,
) -> str:
    bracket_counts = _bracket_counts_for(country, all_counts)
    top_professions = agg.top_professions_per_bracket(country, top_k=10)
    mechanism_share = _mechanism_share_for(country, all_share)
    avg_usd_year, n_with_amount = _avg_usd_for(country, avg_df)
    n_low_confidence = _low_confidence_count(country)

    narratives: dict[str, pd.DataFrame] = {}
    for b in BRACKETS_5:
        try:
            narratives[b] = agg.narrative_examples(country, b, n=3)
        except Exception as exc:
            log.warning("narratives %s/%s failed: %s", country, b, exc)
            narratives[b] = pd.DataFrame()

    n_total = int(bracket_counts.sum()) if not bracket_counts.empty else 0

    template = _env.get_template("country_report.md.j2")
    return template.render(
        country=country,
        country_name=COUNTRY_NAMES_EN.get(country, country),
        brackets=_country_brackets(country),
        bracket_counts=bracket_counts,
        bracket_order=BRACKETS_5,
        top_professions=top_professions,
        mechanism_share=mechanism_share,
        narratives=narratives,
        avg_usd_year=avg_usd_year,
        n_with_amount=n_with_amount,
        n_low_confidence=n_low_confidence,
        n_total=n_total,
    )


def render_index(rendered: list[tuple[str, str, int]]) -> str:
    """rendered: list of (country, country_name, n_total)."""
    lines = [
        "# shouru — Income & Earning Mechanism Reports",
        "",
        "Cross-country charts:",
        "",
        "- [Profession × Country heatmap](../figs/heatmap_profession_country.html) "
        "([png](../figs/heatmap_profession_country.png))",
        "- [Bracket distribution per country](../figs/stacked_bar_bracket_country.html) "
        "([png](../figs/stacked_bar_bracket_country.png))",
        "- [Sankey: country -> bracket -> mechanism](../figs/sankey_country_bracket_mechanism.html)",
        "- [Treemap: top-bracket professions](../figs/treemap_top_bracket.html)",
        "- [Scatter: avg USD/yr vs sample count](../figs/scatter_avg_usd_count.html) "
        "([png](../figs/scatter_avg_usd_count.png))",
        "- [Stacked area: mechanism share by bracket](../figs/stacked_area_mechanism_bracket.png)",
        "",
        "## Country reports",
        "",
        "| Country | Code | Samples | Report |",
        "| --- | --- | ---: | --- |",
    ]
    for cc, name, n in rendered:
        lines.append(f"| {name} | {cc} | {n} | [{cc}.md]({cc}.md) |")
    lines.append("")
    return "\n".join(lines)


def run() -> None:
    log.info("loading aggregate frames")
    try:
        all_counts = agg.country_bracket_counts()
    except Exception as exc:
        log.exception("country_bracket_counts failed: %s", exc)
        all_counts = pd.DataFrame()
    try:
        all_share = agg.mechanism_share_per_country()
    except Exception as exc:
        log.exception("mechanism_share_per_country failed: %s", exc)
        all_share = pd.DataFrame()
    try:
        avg_df = agg.country_avg_usd_year()
    except Exception as exc:
        log.exception("country_avg_usd_year failed: %s", exc)
        avg_df = pd.DataFrame()

    rendered: list[tuple[str, str, int]] = []
    n_ok = 0
    n_fail = 0
    for cc in COUNTRIES_40:
        try:
            md = render_country(
                cc,
                all_counts=all_counts,
                all_share=all_share,
                avg_df=avg_df,
            )
            (REPORTS_DIR / f"{cc}.md").write_text(md, encoding="utf-8")
            n_total = 0
            if cc in all_counts.index:
                n_total = int(all_counts.loc[cc].sum())
            rendered.append((cc, COUNTRY_NAMES_EN.get(cc, cc), n_total))
            n_ok += 1
        except Exception as exc:
            log.exception("render_country(%s) FAILED: %s", cc, exc)
            n_fail += 1

    try:
        (REPORTS_DIR / "_index.md").write_text(render_index(rendered), encoding="utf-8")
    except Exception as exc:
        log.exception("render_index failed: %s", exc)

    print(f"[report] ok={n_ok} fail={n_fail} -> {REPORTS_DIR}")


if __name__ == "__main__":
    run()
