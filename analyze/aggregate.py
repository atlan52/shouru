"""SQL-backed pandas aggregations over `income.db`.

All queries read from the SQLite snapshot produced by `load_sqlite.run()`.
Functions return DataFrames / Series so callers (visualize, report) can
shape them as needed.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager

import pandas as pd

from config import BRACKETS_5, CURATED_DIR

log = logging.getLogger(__name__)

DB_PATH = CURATED_DIR / "income.db"


@contextmanager
def _conn():
    c = sqlite3.connect(DB_PATH)
    try:
        yield c
    finally:
        c.close()


# ----------------------------------------------------------------------
# Country × bracket
# ----------------------------------------------------------------------
def country_bracket_counts() -> pd.DataFrame:
    """Pivot: rows = country, cols = bracket, values = count.
    Bracket columns ordered per BRACKETS_5; missing filled with 0.
    """
    sql = """
        SELECT country, income_bracket, COUNT(*) AS n
        FROM income_records
        WHERE country IS NOT NULL AND country != '??'
        GROUP BY country, income_bracket
    """
    with _conn() as c:
        df = pd.read_sql(sql, c)
    if df.empty:
        return pd.DataFrame(columns=BRACKETS_5)
    pv = df.pivot_table(
        index="country", columns="income_bracket", values="n",
        aggfunc="sum", fill_value=0,
    )
    cols = [b for b in BRACKETS_5 if b in pv.columns]
    extra = [c for c in pv.columns if c not in BRACKETS_5]
    return pv[cols + extra]


def top_professions_per_bracket(country: str, top_k: int = 15) -> pd.DataFrame:
    """For one country, top-K professions per bracket.
    Returns long-form: bracket | profession | n. Sorted bracket-then-n.
    """
    sql = """
        SELECT income_bracket AS bracket, profession, COUNT(*) AS n
        FROM income_records
        WHERE country = ? AND profession IS NOT NULL AND profession != ''
        GROUP BY income_bracket, profession
    """
    with _conn() as c:
        df = pd.read_sql(sql, c, params=(country,))
    if df.empty:
        return df
    df = (
        df.sort_values(["bracket", "n"], ascending=[True, False])
          .groupby("bracket", group_keys=False)
          .head(top_k)
          .reset_index(drop=True)
    )
    return df


# ----------------------------------------------------------------------
# Mechanism shares
# ----------------------------------------------------------------------
def mechanism_share_per_country() -> pd.DataFrame:
    """Pivot: rows = country, cols = mechanism, values = row-normalized share.
    """
    sql = """
        SELECT r.country AS country, m.mechanism AS mechanism, COUNT(*) AS n
        FROM income_records r
        JOIN earning_mechanisms m ON r.record_id = m.record_id
        WHERE r.country IS NOT NULL AND r.country != '??'
        GROUP BY r.country, m.mechanism
    """
    with _conn() as c:
        df = pd.read_sql(sql, c)
    if df.empty:
        return df
    pv = df.pivot_table(
        index="country", columns="mechanism", values="n",
        aggfunc="sum", fill_value=0,
    )
    row_sums = pv.sum(axis=1).replace(0, pd.NA)
    pv = pv.div(row_sums, axis=0).fillna(0.0)
    return pv


def mechanism_by_bracket() -> pd.DataFrame:
    """Long form: bracket | mechanism | count."""
    sql = """
        SELECT r.income_bracket AS bracket, m.mechanism AS mechanism, COUNT(*) AS n
        FROM income_records r
        JOIN earning_mechanisms m ON r.record_id = m.record_id
        GROUP BY r.income_bracket, m.mechanism
    """
    with _conn() as c:
        return pd.read_sql(sql, c)


# ----------------------------------------------------------------------
# Narrative excerpts
# ----------------------------------------------------------------------
def narrative_examples(country: str, bracket: str, n: int = 3) -> pd.DataFrame:
    """Top-`n` records (by confidence DESC) for one country × bracket.

    Columns: profession, raw_excerpt, source_url, source_platform,
    narrative_summary, confidence.
    """
    sql = """
        SELECT profession, raw_excerpt, source_url, source_platform,
               narrative_summary, confidence
        FROM income_records
        WHERE country = ? AND income_bracket = ?
        ORDER BY confidence DESC NULLS LAST, extracted_at DESC
        LIMIT ?
    """
    with _conn() as c:
        try:
            return pd.read_sql(sql, c, params=(country, bracket, int(n)))
        except sqlite3.OperationalError:
            # SQLite < 3.30 doesn't support NULLS LAST
            sql2 = sql.replace("NULLS LAST", "")
            return pd.read_sql(sql2, c, params=(country, bracket, int(n)))


# ----------------------------------------------------------------------
# USD/year averages
# ----------------------------------------------------------------------
def country_avg_usd_year() -> pd.DataFrame:
    """country | avg_usd_year | n_with_amount."""
    sql = """
        SELECT country,
               AVG(income_amount_usd_year) AS avg_usd_year,
               SUM(CASE WHEN income_amount_usd_year IS NOT NULL THEN 1 ELSE 0 END)
                   AS n_with_amount
        FROM income_records
        WHERE country IS NOT NULL AND country != '??'
        GROUP BY country
    """
    with _conn() as c:
        return pd.read_sql(sql, c)


def unique_profession_count_per_country() -> pd.DataFrame:
    """country | n_unique_professions."""
    sql = """
        SELECT country, COUNT(DISTINCT profession) AS n_unique_professions
        FROM income_records
        WHERE country IS NOT NULL AND country != '??'
              AND profession IS NOT NULL AND profession != ''
        GROUP BY country
    """
    with _conn() as c:
        return pd.read_sql(sql, c)


# ----------------------------------------------------------------------
def run() -> None:
    print("[aggregate] sanity check")
    try:
        cb = country_bracket_counts()
        print(f"  country_bracket_counts: {cb.shape}")
    except Exception as exc:
        print(f"  country_bracket_counts FAILED: {exc}")
    try:
        mc = mechanism_share_per_country()
        print(f"  mechanism_share_per_country: {mc.shape}")
    except Exception as exc:
        print(f"  mechanism_share_per_country FAILED: {exc}")
    try:
        au = country_avg_usd_year()
        print(f"  country_avg_usd_year: {len(au)} countries with data")
    except Exception as exc:
        print(f"  country_avg_usd_year FAILED: {exc}")
    try:
        up = unique_profession_count_per_country()
        print(f"  unique_profession_count_per_country: {len(up)} countries")
    except Exception as exc:
        print(f"  unique_profession_count_per_country FAILED: {exc}")


if __name__ == "__main__":
    run()
