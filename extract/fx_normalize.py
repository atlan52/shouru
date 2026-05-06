"""货币 + period → USD/year 标准化器。

每条 income_records:
1. 读 (income_amount_local, currency, period)
2. 按 period 转年化 (hour×2080, day×260, week×52, month×12)
3. 按 FX 转 USD
4. 写 income_amount_usd_year + fx_rate_used + period_factor 透明字段

不改 currency / income_amount_local / period — 原值保留。
新增 audit 字段：fx_rate_used (float), period_factor (float), fx_normalized_at (str)
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from config import CURATED_DIR

DB_PATH = CURATED_DIR / "income.db"

# FX rates: 2024 年均值 → USD（1 单位本地 = X USD）
# 数据源参考各币种 2024 年平均汇率
FX_TO_USD = {
    "USD": 1.000,
    "EUR": 1.082,
    "GBP": 1.279,
    "JPY": 0.00659,
    "CNY": 0.1404,
    "RMB": 0.1404,
    "HKD": 0.1281,
    "TWD": 0.0312,
    "KRW": 0.000732,
    "INR": 0.01198,
    "AUD": 0.660,
    "CAD": 0.730,
    "NZD": 0.610,
    "CHF": 1.135,
    "SGD": 0.749,
    "MYR": 0.218,
    "THB": 0.0285,
    "VND": 0.0000395,
    "IDR": 0.0000632,
    "PHP": 0.01753,
    "BRL": 0.1860,
    "MXN": 0.0548,
    "ARS": 0.001057,
    "COP": 0.000254,
    "CLP": 0.001067,
    "RUB": 0.01085,
    "UAH": 0.0244,
    "PLN": 0.250,
    "CZK": 0.0432,
    "HUF": 0.00276,
    "TRY": 0.0299,
    "ZAR": 0.0548,
    "EGP": 0.0207,
    "SAR": 0.2666,
    "AED": 0.2722,
    "ILS": 0.2710,
    "SEK": 0.0945,
    "NOK": 0.0930,
    "DKK": 0.1450,
    "ISK": 0.00718,
    "ZMW": 0.0419,
    "NGN": 0.000638,
    "PKR": 0.00359,
    "BDT": 0.00845,
    "MAD": 0.0995,
    "PEN": 0.265,
    "LKR": 0.00337,
    "KZT": 0.00211,
    "UYU": 0.0234,
    "TND": 0.317,
    "KES": 0.00772,
    "GHS": 0.0670,
    "UZS": 0.0000801,
    "NPR": 0.00750,
    "BYN": 0.302,
    "BOB": 0.1444,
    "VES": 0.02500,
    "ETB": 0.00770,
    "TZS": 0.000395,
    "UGX": 0.000270,
    "DOP": 0.0166,
    "GTQ": 0.129,
    "HNL": 0.0399,
    "SVN": 0.116,
    "JMD": 0.00626,
    "PYG": 0.0001339,
    "CRC": 0.00200,
    "PAB": 1.000,
    "AMD": 0.00257,
    "AZN": 0.5882,
    "GEL": 0.367,
    "MNT": 0.000295,
    "MMK": 0.000476,
    "KHR": 0.000244,
    "LAK": 0.0000466,
    "LBP": 0.0000112,
    "JOD": 1.4109,
    "QAR": 0.2747,
    "OMR": 2.5974,
    "BHD": 2.6525,
    "KWD": 3.2484,
    "RSD": 0.00921,
    "BGN": 0.5530,
    "HRK": 0.1425,
    "RON": 0.2161,
    "ALL": 0.0103,
    "MKD": 0.01757,
    "BIF": 0.000343,
    "RWF": 0.000732,
    "ZMW": 0.0419,
    "AOA": 0.001094,
    "MZN": 0.01568,
    "XOF": 0.00164,
    "XAF": 0.00164,
    # CN 习惯用 RMB 字符 — 别名
}

# Period multiplier → year
PERIOD_FACTOR = {
    "hour": 2080,    # 40h × 52 weeks
    "day":  260,     # 5d × 52 weeks
    "week": 52,
    "month": 12,
    "year": 1,
    "one-time": None,    # 一次性事件 — 不年化
    "unknown": None,
}


def normalize():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Add columns if missing
    existing = {row[1] for row in cur.execute("PRAGMA table_info(income_records)")}
    for col, ddl in [
        ("fx_rate_used", "ALTER TABLE income_records ADD COLUMN fx_rate_used REAL"),
        ("period_factor", "ALTER TABLE income_records ADD COLUMN period_factor REAL"),
        ("fx_normalized_at", "ALTER TABLE income_records ADD COLUMN fx_normalized_at TEXT"),
        ("fx_status", "ALTER TABLE income_records ADD COLUMN fx_status TEXT"),
    ]:
        if col not in existing:
            cur.execute(ddl)
            print(f"[fx] added column {col}")
    conn.commit()

    # Audit & update
    rows = cur.execute("""
        SELECT record_id, income_amount_local, currency, period
        FROM income_records
    """).fetchall()
    print(f"[fx] processing {len(rows)} records")

    n_done = n_skip_no_amt = n_skip_no_curr = n_skip_unknown_curr = n_skip_one_time = 0
    n_skip_unknown_period = 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for rec_id, amt, curr, period in rows:
        # No amount → can't compute
        if amt is None:
            cur.execute("UPDATE income_records SET fx_status=?, fx_normalized_at=? WHERE record_id=?",
                        ("no_amount", now, rec_id))
            n_skip_no_amt += 1
            continue

        # No currency → assume reporter context (US default for now, mark explicitly)
        if curr is None or curr == "":
            cur.execute("UPDATE income_records SET fx_status=?, fx_normalized_at=? WHERE record_id=?",
                        ("no_currency_recorded", now, rec_id))
            n_skip_no_curr += 1
            continue

        curr_upper = curr.upper().strip()
        fx = FX_TO_USD.get(curr_upper)
        if fx is None:
            cur.execute("UPDATE income_records SET fx_status=?, currency=?, fx_normalized_at=? WHERE record_id=?",
                        (f"unknown_currency_{curr_upper}", curr_upper, now, rec_id))
            n_skip_unknown_curr += 1
            continue

        # Period
        pfactor = PERIOD_FACTOR.get(period or "unknown")
        if pfactor is None:
            # one-time / unknown — keep currency + amount, mark
            cur.execute("UPDATE income_records SET fx_rate_used=?, fx_status=?, fx_normalized_at=? WHERE record_id=?",
                        (fx, f"period_{period or 'unknown'}_no_annualization", now, rec_id))
            if period == "one-time":
                n_skip_one_time += 1
            else:
                n_skip_unknown_period += 1
            continue

        # Compute USD/year
        usd_year = float(amt) * pfactor * fx
        cur.execute("""
            UPDATE income_records
            SET income_amount_usd_year=?, fx_rate_used=?, period_factor=?,
                fx_status='ok', fx_normalized_at=?
            WHERE record_id=?
        """, (usd_year, fx, pfactor, now, rec_id))
        n_done += 1

    conn.commit()
    conn.close()

    print(f"\n=== FX normalize summary ===")
    print(f"  ok (USD/year computed):       {n_done}")
    print(f"  skip - no amount:             {n_skip_no_amt}")
    print(f"  skip - no currency:           {n_skip_no_curr}")
    print(f"  skip - unknown currency:      {n_skip_unknown_curr}")
    print(f"  skip - one-time (no annual):  {n_skip_one_time}")
    print(f"  skip - unknown period:        {n_skip_unknown_period}")


def report():
    """打印 FX 之后的状态报告"""
    conn = sqlite3.connect(DB_PATH)
    print("\n=== FX 之后货币分布 ===")
    for c, n in conn.execute("""
        SELECT currency, COUNT(*) FROM income_records
        WHERE income_amount_usd_year IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC LIMIT 20
    """):
        print(f"  {c}: {n}")
    print()
    print("=== fx_status 分布 ===")
    for s, n in conn.execute("SELECT fx_status, COUNT(*) FROM income_records GROUP BY 1 ORDER BY 2 DESC"):
        print(f"  {s}: {n}")
    print()
    print("=== 各国 USD/yr 中位数（5 档前的真实金额，前 15 国按样本数）===")
    for c, n, med in conn.execute("""
        SELECT country, COUNT(*),
               (SELECT income_amount_usd_year FROM income_records ir2
                WHERE ir2.country=ir.country AND income_amount_usd_year IS NOT NULL
                ORDER BY income_amount_usd_year LIMIT 1
                OFFSET (SELECT COUNT(*)/2 FROM income_records ir3
                        WHERE ir3.country=ir.country AND income_amount_usd_year IS NOT NULL))
        FROM income_records ir
        WHERE income_amount_usd_year IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC LIMIT 15
    """):
        print(f"  {c}: n={n}, median ${med:,.0f}/yr")


if __name__ == "__main__":
    normalize()
    report()
