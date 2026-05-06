"""Cross-country charts & per-country bar charts.

Outputs:
    data/curated/figs/<name>.png
    data/curated/figs/<name>.html
    data/curated/figs/per_country/<COUNTRY>.png

Every function is fail-soft: it logs and continues so one broken chart
does not nuke the whole pipeline.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import seaborn as sns

from config import BRACKETS_5, COUNTRIES_40, CURATED_DIR
from analyze import aggregate as agg

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

FIGS_DIR = CURATED_DIR / "figs"
PER_COUNTRY_DIR = FIGS_DIR / "per_country"
FIGS_DIR.mkdir(parents=True, exist_ok=True)
PER_COUNTRY_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = CURATED_DIR / "income.db"


# ----------------------------------------------------------------------
# 1. Heatmap: top-30 professions × top-25 countries
# ----------------------------------------------------------------------
def heatmap_profession_country() -> None:
    sql = """
        SELECT country, profession, COUNT(*) AS n
        FROM income_records
        WHERE country IS NOT NULL AND country != '??'
              AND profession IS NOT NULL AND profession != ''
        GROUP BY country, profession
    """
    with sqlite3.connect(DB_PATH) as c:
        df = pd.read_sql(sql, c)
    if df.empty:
        log.warning("heatmap: empty data")
        return
    top_countries = df.groupby("country")["n"].sum().nlargest(25).index
    top_profs = df.groupby("profession")["n"].sum().nlargest(30).index
    sub = df[df["country"].isin(top_countries) & df["profession"].isin(top_profs)]
    pv = sub.pivot_table(index="profession", columns="country",
                         values="n", aggfunc="sum", fill_value=0)
    pv = pv.reindex(index=top_profs, columns=top_countries, fill_value=0)
    log_pv = np.log1p(pv)

    fig, ax = plt.subplots(figsize=(14, 12))
    sns.heatmap(log_pv, cmap="viridis", ax=ax, cbar_kws={"label": "log(1+count)"})
    ax.set_title("Profession × Country (log count, top 30 × top 25)")
    fig.tight_layout()
    fig.savefig(FIGS_DIR / "heatmap_profession_country.png", dpi=120)
    plt.close(fig)

    pfig = px.imshow(
        log_pv, aspect="auto", color_continuous_scale="viridis",
        labels=dict(color="log(1+count)"),
        title="Profession × Country (log count)",
    )
    pfig.write_html(FIGS_DIR / "heatmap_profession_country.html")


# ----------------------------------------------------------------------
# 2. Stacked bar: 5 brackets per country (top 20 by sample count)
# ----------------------------------------------------------------------
def stacked_bar_bracket_country() -> None:
    cb = agg.country_bracket_counts()
    if cb.empty:
        log.warning("stacked_bar: empty data")
        return
    cb = cb.assign(_total=cb.sum(axis=1)).sort_values("_total", ascending=False)
    cb = cb.head(20).drop(columns=["_total"])
    bracket_cols = [b for b in BRACKETS_5 if b in cb.columns]
    cb = cb[bracket_cols]

    fig, ax = plt.subplots(figsize=(14, 7))
    bottom = np.zeros(len(cb))
    palette = sns.color_palette("rocket", n_colors=len(bracket_cols))
    for col, color in zip(bracket_cols, palette):
        ax.bar(cb.index, cb[col].values, bottom=bottom, label=col, color=color)
        bottom += cb[col].values
    ax.set_title("Bracket distribution per country (top 20 by samples)")
    ax.set_ylabel("records")
    ax.legend(loc="upper right")
    plt.xticks(rotation=45, ha="right")
    fig.tight_layout()
    fig.savefig(FIGS_DIR / "stacked_bar_bracket_country.png", dpi=120)
    plt.close(fig)

    long = cb.reset_index().melt(id_vars="country", var_name="bracket", value_name="n")
    pfig = px.bar(
        long, x="country", y="n", color="bracket",
        category_orders={"bracket": bracket_cols},
        title="Bracket distribution per country (top 20 by samples)",
    )
    pfig.write_html(FIGS_DIR / "stacked_bar_bracket_country.html")


# ----------------------------------------------------------------------
# 3. Sankey: country -> bracket -> mechanism (top 10 countries)
# ----------------------------------------------------------------------
def sankey_country_bracket_mechanism() -> None:
    sql = """
        SELECT r.country AS country, r.income_bracket AS bracket,
               m.mechanism AS mechanism, COUNT(*) AS n
        FROM income_records r
        JOIN earning_mechanisms m ON r.record_id = m.record_id
        WHERE r.country IS NOT NULL AND r.country != '??'
        GROUP BY r.country, r.income_bracket, m.mechanism
    """
    with sqlite3.connect(DB_PATH) as c:
        df = pd.read_sql(sql, c)
    if df.empty:
        log.warning("sankey: empty data")
        return
    top10 = df.groupby("country")["n"].sum().nlargest(10).index
    df = df[df["country"].isin(top10)]
    if df.empty:
        return

    countries = list(df["country"].unique())
    brackets = list(df["bracket"].unique())
    mechs = list(df["mechanism"].unique())
    nodes = countries + brackets + mechs
    idx = {label: i for i, label in enumerate(nodes)}

    src, tgt, val = [], [], []
    cb = df.groupby(["country", "bracket"])["n"].sum().reset_index()
    for _, row in cb.iterrows():
        src.append(idx[row["country"]])
        tgt.append(idx[row["bracket"]])
        val.append(int(row["n"]))
    bm = df.groupby(["bracket", "mechanism"])["n"].sum().reset_index()
    for _, row in bm.iterrows():
        src.append(idx[row["bracket"]])
        tgt.append(idx[row["mechanism"]])
        val.append(int(row["n"]))

    fig = go.Figure(go.Sankey(
        node=dict(label=nodes, pad=12, thickness=14),
        link=dict(source=src, target=tgt, value=val),
    ))
    fig.update_layout(title="Country -> Bracket -> Mechanism (top 10 countries)")
    fig.write_html(FIGS_DIR / "sankey_country_bracket_mechanism.html")


# ----------------------------------------------------------------------
# 4. Per-country top-10 professions bar chart
# ----------------------------------------------------------------------
def per_country_top_professions(country: str) -> None:
    sql = """
        SELECT profession, COUNT(*) AS n
        FROM income_records
        WHERE country = ? AND profession IS NOT NULL AND profession != ''
        GROUP BY profession
        ORDER BY n DESC
        LIMIT 10
    """
    with sqlite3.connect(DB_PATH) as c:
        df = pd.read_sql(sql, c, params=(country,))
    if df.empty:
        log.info("per_country %s: empty", country)
        return
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh(df["profession"][::-1], df["n"][::-1], color="#3a7bd5")
    ax.set_title(f"{country} — top 10 professions by samples")
    ax.set_xlabel("records")
    fig.tight_layout()
    fig.savefig(PER_COUNTRY_DIR / f"{country}.png", dpi=120)
    plt.close(fig)


# ----------------------------------------------------------------------
# 5. Treemap: profession share within "top" bracket
# ----------------------------------------------------------------------
def treemap_top_bracket() -> None:
    sql = """
        SELECT country, profession, COUNT(*) AS n
        FROM income_records
        WHERE income_bracket = 'top'
              AND country IS NOT NULL AND country != '??'
              AND profession IS NOT NULL AND profession != ''
        GROUP BY country, profession
    """
    with sqlite3.connect(DB_PATH) as c:
        df = pd.read_sql(sql, c)
    if df.empty:
        log.warning("treemap: empty data")
        return
    fig = px.treemap(
        df, path=["country", "profession"], values="n",
        title="Top-bracket professions by country (treemap)",
    )
    fig.write_html(FIGS_DIR / "treemap_top_bracket.html")


# ----------------------------------------------------------------------
# 6. Scatter: avg USD/yr vs sample count per country
# ----------------------------------------------------------------------
def scatter_avg_usd_count() -> None:
    avg = agg.country_avg_usd_year()
    if avg.empty:
        log.warning("scatter: empty data")
        return
    sql = "SELECT country, COUNT(*) AS n_total FROM income_records GROUP BY country"
    with sqlite3.connect(DB_PATH) as c:
        totals = pd.read_sql(sql, c)
    df = avg.merge(totals, on="country", how="left").dropna(subset=["avg_usd_year"])
    if df.empty:
        return

    fig, ax = plt.subplots(figsize=(10, 7))
    ax.scatter(df["n_total"], df["avg_usd_year"], s=40, alpha=0.7, color="#cc3a5d")
    for _, row in df.iterrows():
        ax.annotate(row["country"], (row["n_total"], row["avg_usd_year"]),
                    fontsize=7, alpha=0.8)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("samples (log)")
    ax.set_ylabel("avg USD/yr (log)")
    ax.set_title("Mean reported income vs sample count, per country")
    fig.tight_layout()
    fig.savefig(FIGS_DIR / "scatter_avg_usd_count.png", dpi=120)
    plt.close(fig)

    pfig = px.scatter(
        df, x="n_total", y="avg_usd_year", text="country",
        log_x=True, log_y=True, hover_name="country",
        title="Mean reported income vs sample count, per country",
    )
    pfig.update_traces(textposition="top center")
    pfig.write_html(FIGS_DIR / "scatter_avg_usd_count.html")


# ----------------------------------------------------------------------
# 7. Stacked area: bracket × mechanism share
# ----------------------------------------------------------------------
def stacked_area_mechanism_bracket() -> None:
    df = agg.mechanism_by_bracket()
    if df.empty:
        log.warning("stacked_area: empty data")
        return
    pv = df.pivot_table(index="bracket", columns="mechanism",
                        values="n", aggfunc="sum", fill_value=0)
    order = [b for b in BRACKETS_5 if b in pv.index]
    if order:
        pv = pv.reindex(order)
    row_sums = pv.sum(axis=1).replace(0, np.nan)
    share = pv.div(row_sums, axis=0).fillna(0.0)

    fig, ax = plt.subplots(figsize=(11, 6))
    palette = sns.color_palette("tab20", n_colors=share.shape[1])
    ax.stackplot(range(len(share.index)), share.T.values,
                 labels=list(share.columns), colors=palette, alpha=0.9)
    ax.set_xticks(range(len(share.index)))
    ax.set_xticklabels(list(share.index), rotation=20)
    ax.set_ylabel("share")
    ax.set_ylim(0, 1)
    ax.set_title("Earning mechanism share, by income bracket")
    ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0), fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGS_DIR / "stacked_area_mechanism_bracket.png", dpi=120)
    plt.close(fig)


# ----------------------------------------------------------------------
def run() -> None:
    jobs = [
        ("heatmap_profession_country", heatmap_profession_country),
        ("stacked_bar_bracket_country", stacked_bar_bracket_country),
        ("sankey_country_bracket_mechanism", sankey_country_bracket_mechanism),
        ("treemap_top_bracket", treemap_top_bracket),
        ("scatter_avg_usd_count", scatter_avg_usd_count),
        ("stacked_area_mechanism_bracket", stacked_area_mechanism_bracket),
    ]
    for name, fn in jobs:
        try:
            log.info("running %s", name)
            fn()
        except Exception as exc:
            log.exception("%s FAILED: %s", name, exc)

    for cc in COUNTRIES_40:
        try:
            per_country_top_professions(cc)
        except Exception as exc:
            log.warning("per_country %s FAILED: %s", cc, exc)


if __name__ == "__main__":
    run()
