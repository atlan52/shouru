"""Eyeball — print 30 random extracted records side-by-side with their source.

Used by humans to spot extraction errors. Reads from extracted/extracted_*.jsonl
and reconciles against the original source record (RAW_DIR or _to_extract.jsonl).
"""
import json
import random
from pathlib import Path

from config import EXTRACTED_DIR, RAW_DIR

N_SAMPLES = 30


def load_extracted() -> list[dict]:
    rows = []
    for f in EXTRACTED_DIR.glob("extracted_*.jsonl"):
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    return rows


def build_source_index() -> dict:
    idx = {}
    to_extract = EXTRACTED_DIR / "_to_extract.jsonl"
    if to_extract.exists():
        with to_extract.open(encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                rid = r.get("id") or r.get("record_id")
                if rid:
                    idx[str(rid)] = r
    # Also scan RAW_DIR (in case _to_extract was deleted)
    for jf in RAW_DIR.glob("*.jsonl"):
        with jf.open(encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                rid = r.get("id") or r.get("record_id")
                if rid and str(rid) not in idx:
                    idx[str(rid)] = r
    return idx


def fmt_mechanisms(mechs) -> str:
    if not mechs:
        return "(none)"
    if isinstance(mechs, list):
        return ", ".join(mechs)
    return str(mechs)


def render(i: int, total: int, extracted: dict, source: dict | None) -> str:
    lines = []
    lines.append(f"=== Record {i}/{total} ===")
    if source:
        platform = source.get("platform", "?")
        lang = source.get("lang", "?")
        country_hint = source.get("country_hint") or source.get("country", "?")
        title = (source.get("title") or "").strip()
        body = (source.get("body") or "").strip()
        body_preview = body[:500] + ("…" if len(body) > 500 else "")
        lines.append(f"Source ({platform}, {lang}, country_hint={country_hint}):")
        lines.append(f"  TITLE: {title}")
        lines.append(f"  BODY (first 500 chars): {body_preview}")
    else:
        lines.append("Source: (NOT FOUND in raw/ or _to_extract.jsonl)")

    country = extracted.get("country", "?")
    cconf = extracted.get("country_confidence", "?")
    bracket = extracted.get("income_bracket", "?")
    profession = extracted.get("profession", "?")
    profession_raw = extracted.get("profession_raw", "")
    industry = extracted.get("industry", "?")
    mechanisms = fmt_mechanisms(extracted.get("earning_mechanisms"))
    narrative = extracted.get("narrative_summary", "")
    raw_excerpt = extracted.get("raw_excerpt", "")
    amount = extracted.get("income_amount_local")
    currency = extracted.get("currency")
    period = extracted.get("period")
    conf = extracted.get("confidence", "?")
    model = extracted.get("extraction_model", "?")

    lines.append("")
    lines.append("Extracted:")
    lines.append(f"  country: {country} (confidence {cconf})")
    lines.append(f"  bracket: {bracket}")
    lines.append(f"  profession: {profession}  [raw: {profession_raw}]")
    lines.append(f"  industry: {industry}")
    lines.append(f"  mechanisms: {mechanisms}")
    lines.append(f"  amount: {amount} {currency} / {period}")
    lines.append(f"  confidence: {conf}  (model: {model})")
    lines.append(f"  narrative: {narrative}")
    lines.append(f"  raw_excerpt: {raw_excerpt}")
    lines.append("")
    return "\n".join(lines)


def run(n: int = N_SAMPLES, seed: int | None = None):
    if seed is not None:
        random.seed(seed)
    extracted = load_extracted()
    if not extracted:
        print("[eyeball] no extracted records found")
        return
    sample = random.sample(extracted, min(n, len(extracted)))
    src_idx = build_source_index()
    print(f"[eyeball] {len(sample)} samples (out of {len(extracted)} extracted, "
          f"{len(src_idx)} sources indexed)\n")
    for i, rec in enumerate(sample, 1):
        rid = str(rec.get("record_id"))
        src = src_idx.get(rid)
        print(render(i, len(sample), rec, src))


if __name__ == "__main__":
    run()
