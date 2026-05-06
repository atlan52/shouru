"""Load extracted JSONL records into SQLite + parquet snapshot.

Reads `data/extracted/extracted_*.jsonl`, upserts into `income.db`
(`income_records` + `earning_mechanisms`), and exports
`income_records.parquet` for fast pandas access.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import pandas as pd

from config import CURATED_DIR, EXTRACTED_DIR

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DB_PATH = CURATED_DIR / "income.db"
PARQUET_PATH = CURATED_DIR / "income_records.parquet"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS income_records (
    record_id TEXT PRIMARY KEY,
    source_platform TEXT,
    source_url TEXT,
    source_lang TEXT,
    country TEXT,
    country_confidence REAL,
    income_amount_local REAL,
    currency TEXT,
    period TEXT,
    income_amount_usd_year REAL,
    income_bracket TEXT,
    profession TEXT,
    profession_raw TEXT,
    industry TEXT,
    narrative_summary TEXT,
    raw_excerpt TEXT,
    confidence REAL,
    extraction_model TEXT,
    extracted_at TEXT
);

CREATE TABLE IF NOT EXISTS earning_mechanisms (
    record_id TEXT NOT NULL,
    mechanism TEXT NOT NULL,
    PRIMARY KEY (record_id, mechanism),
    FOREIGN KEY (record_id) REFERENCES income_records(record_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_income_country_bracket
    ON income_records(country, income_bracket);
CREATE INDEX IF NOT EXISTS idx_income_profession
    ON income_records(profession);
CREATE INDEX IF NOT EXISTS idx_mech_mechanism
    ON earning_mechanisms(mechanism);
"""


INSERT_RECORD_SQL = """
INSERT OR REPLACE INTO income_records (
    record_id, source_platform, source_url, source_lang,
    country, country_confidence,
    income_amount_local, currency, period, income_amount_usd_year,
    income_bracket, profession, profession_raw, industry,
    narrative_summary, raw_excerpt, confidence,
    extraction_model, extracted_at
) VALUES (
    :record_id, :source_platform, :source_url, :source_lang,
    :country, :country_confidence,
    :income_amount_local, :currency, :period, :income_amount_usd_year,
    :income_bracket, :profession, :profession_raw, :industry,
    :narrative_summary, :raw_excerpt, :confidence,
    :extraction_model, :extracted_at
);
"""

INSERT_MECH_SQL = """
INSERT OR REPLACE INTO earning_mechanisms (record_id, mechanism)
VALUES (?, ?);
"""


_RECORD_FIELDS = (
    "record_id", "source_platform", "source_url", "source_lang",
    "country", "country_confidence",
    "income_amount_local", "currency", "period", "income_amount_usd_year",
    "income_bracket", "profession", "profession_raw", "industry",
    "narrative_summary", "raw_excerpt", "confidence",
    "extraction_model", "extracted_at",
)


def _row_from_record(rec: dict) -> dict:
    return {k: rec.get(k) for k in _RECORD_FIELDS}


def _iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        for ln, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                log.warning("bad json %s:%d: %s", path.name, ln, exc)


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def load_jsonl_files(conn: sqlite3.Connection) -> tuple[int, int, int]:
    """Returns (files, records_inserted, mechanisms_inserted)."""
    n_files = 0
    n_records = 0
    n_mechs = 0
    for path in sorted(EXTRACTED_DIR.glob("extracted_*.jsonl")):
        n_files += 1
        log.info("loading %s", path.name)
        cur = conn.cursor()
        for rec in _iter_jsonl(path):
            if not isinstance(rec, dict):
                continue
            if rec.get("skip"):
                continue
            rid = rec.get("record_id")
            if not rid:
                continue
            try:
                cur.execute(INSERT_RECORD_SQL, _row_from_record(rec))
            except sqlite3.Error as exc:
                log.warning("insert failed for %s: %s", rid, exc)
                continue
            n_records += 1

            mechs = rec.get("earning_mechanisms") or []
            if isinstance(mechs, list):
                # Wipe old mechs for this record then re-insert
                cur.execute("DELETE FROM earning_mechanisms WHERE record_id = ?", (rid,))
                for m in mechs:
                    if not m:
                        continue
                    try:
                        cur.execute(INSERT_MECH_SQL, (rid, str(m)))
                        n_mechs += 1
                    except sqlite3.Error as exc:
                        log.warning("mech insert failed (%s, %s): %s", rid, m, exc)
        conn.commit()
    return n_files, n_records, n_mechs


def export_parquet(conn: sqlite3.Connection) -> int:
    df = pd.read_sql("SELECT * FROM income_records", conn)
    try:
        df.to_parquet(PARQUET_PATH, index=False)
    except (ImportError, ValueError) as e:
        # pyarrow / fastparquet missing — fall back to CSV
        csv_path = PARQUET_PATH.with_suffix(".csv")
        df.to_csv(csv_path, index=False)
        log.warning("parquet write failed (%s); wrote CSV instead: %s", e, csv_path)
    return len(df)


def run() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        init_db(conn)
        n_files, n_records, n_mechs = load_jsonl_files(conn)
        n_parquet = export_parquet(conn)
    finally:
        conn.close()
    print(
        f"[load_sqlite] files={n_files} records_upserted={n_records} "
        f"mechanisms_upserted={n_mechs} parquet_rows={n_parquet}"
    )
    print(f"[load_sqlite] db -> {DB_PATH}")
    print(f"[load_sqlite] parquet -> {PARQUET_PATH}")


if __name__ == "__main__":
    run()
