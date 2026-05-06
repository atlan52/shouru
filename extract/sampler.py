"""Sample Reddit records for LLM extraction.

For Reddit (3.18M rows), score = log(1+upvotes)*2 + log(1+len(body))*3 + 5*has_amount + 3*has_bracket_hint + 2*is_underrep_country
Pick top 25k by score, capped 4k per country (so US doesn't drown small countries).

For all other platforms: full set.
"""
import json
import math
import random
from collections import Counter
from pathlib import Path
from config import RAW_DIR, EXTRACTED_DIR

UNDERREP_COUNTRIES = {"VN", "TH", "ID", "PH", "TR", "MX", "BR", "RU", "PL", "SE",
                      "NO", "UA", "BD", "PK", "AR", "CO", "CL", "ZA", "NG", "SA",
                      "AE", "EG", "MA"}
PER_COUNTRY_CAP_REDDIT = 1000
TOTAL_REDDIT_TARGET = 5000


def _score(item):
    body_len = len(item.get("body", "") or "")
    upvotes = (item.get("engagement") or {}).get("score") or 0
    has_amount = 1 if (item.get("amount_hint") or "").strip() else 0
    has_bracket = 1 if (item.get("bracket_hint") or "").strip() in (
        "bottom", "lower_middle", "middle", "upper_middle", "top") else 0
    country = item.get("country_hint", "??")
    underrep = 1 if country in UNDERREP_COUNTRIES else 0
    return (math.log1p(max(0, int(upvotes))) * 2
            + math.log1p(body_len) * 3
            + 5 * has_amount + 3 * has_bracket + 2 * underrep)


def sample_reddit():
    """Read all reddit_import_*.jsonl files, score, sample."""
    rows = []
    for f in RAW_DIR.glob("reddit_import_*.jsonl"):
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                rows.append(item)
    print(f"[sampler] read {len(rows)} reddit rows")
    if not rows:
        return []
    # Score and sort
    for r in rows:
        r["_score"] = _score(r)
    rows.sort(key=lambda r: r["_score"], reverse=True)
    # Cap per country
    selected = []
    counts = Counter()
    for r in rows:
        c = r.get("country_hint", "??")
        if counts[c] >= PER_COUNTRY_CAP_REDDIT:
            continue
        selected.append(r)
        counts[c] += 1
        if len(selected) >= TOTAL_REDDIT_TARGET:
            break
    print(f"[sampler] selected {len(selected)} reddit rows; "
          f"per-country counts: {counts.most_common(20)}")
    return selected


def collect_other_platforms():
    """Collect ALL records from all non-reddit_import platforms — full volume."""
    rows = []
    for f in RAW_DIR.glob("*.jsonl"):
        if f.name.startswith("reddit_import_"):
            continue
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    print(f"[sampler] collected {len(rows)} non-reddit rows")
    return rows


def run():
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    sampled = []
    sampled.extend(sample_reddit())
    sampled.extend(collect_other_platforms())
    # Light shuffle so chunks are heterogeneous (better cache utilization across
    # languages/countries within a batch).
    random.shuffle(sampled)
    print(f"[sampler] total to extract: {len(sampled)}")
    out = EXTRACTED_DIR / "_to_extract.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in sampled:
            # Drop transient score field before writing
            r.pop("_score", None)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[sampler] wrote {out}")
    return sampled


if __name__ == "__main__":
    run()
