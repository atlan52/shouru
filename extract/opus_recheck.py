"""Opus 4.7 recheck — validate top-tier high-value samples.

After main extraction completes, pick top ~1k records by quality signal:
  - income_bracket == "top" (high-value)
  - confidence < 0.6 (uncertain — Opus might do better)
  - narrative_summary length > 200 chars (long, complex stories)

Re-run those through claude-opus-4-7 (NON-batch, parallel via concurrent.futures,
max 6 streams). Replace existing record with Opus result IFF confidence improves.
"""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from config import EXTRACTED_DIR, RAW_DIR
from extract.prompts import SYSTEM_PROMPT, build_user_message
from extract.schema import IncomeRecord, SkipResult

MODEL = "claude-opus-4-7"
MAX_TOKENS = 1100
MAX_WORKERS = 6
TOP_K = 1000

client = anthropic.Anthropic()


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def load_extracted() -> list[dict]:
    """Load every extracted_*.jsonl from EXTRACTED_DIR (excluding _retry, _opus)."""
    rows = []
    for f in EXTRACTED_DIR.glob("extracted_*.jsonl"):
        if "_opus" in f.name:
            continue
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    return rows


def quality_score(rec: dict) -> float:
    """Higher = more worth re-running through Opus."""
    score = 0.0
    if rec.get("income_bracket") == "top":
        score += 5.0
    conf = rec.get("confidence")
    if isinstance(conf, (int, float)) and conf < 0.6:
        score += 4.0 + (0.6 - conf) * 5  # extra weight when very uncertain
    narr = rec.get("narrative_summary") or ""
    if len(narr) > 200:
        score += 2.0 + min(len(narr), 1000) / 500.0
    # Tiebreaker: prefer underrep countries
    if rec.get("country") in {"VN", "TH", "ID", "PH", "TR", "MX", "BR", "RU",
                              "PL", "SE", "NO", "UA", "BD", "PK", "AR", "CO",
                              "CL", "ZA", "NG", "SA", "AE", "EG", "MA"}:
        score += 0.5
    return score


def pick_top(records: list[dict], k: int = TOP_K) -> list[dict]:
    scored = [(quality_score(r), r) for r in records]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for s, r in scored[:k] if s > 0]


def build_source_index() -> dict:
    """Map record_id → raw record from RAW_DIR + _to_extract.jsonl."""
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
    if not idx:
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


def opus_extract(record: dict) -> tuple[str, dict | None, str | None]:
    """Returns (record_id, validated_record_dict, error)."""
    rid = str(record.get("id") or record.get("record_id") or "")
    try:
        msg = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": build_user_message(record)}],
        )
        text = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
        text = _strip_fences(text)
        parsed = json.loads(text)
        if parsed.get("skip"):
            SkipResult.model_validate(parsed)
            return rid, {"skip": True, "reason": parsed.get("reason", "")}, None
        parsed.setdefault("record_id", rid)
        parsed["extraction_model"] = MODEL
        parsed.setdefault(
            "extracted_at",
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        validated = IncomeRecord.model_validate(parsed)
        return rid, validated.model_dump(), None
    except Exception as e:
        return rid, None, str(e)


def run():
    extracted = load_extracted()
    print(f"[opus] loaded {len(extracted)} previously extracted records")
    if not extracted:
        return
    candidates = pick_top(extracted, TOP_K)
    print(f"[opus] selected top {len(candidates)} candidates for Opus recheck")

    # Build map from record_id to original Sonnet extraction (for confidence comparison)
    sonnet_by_id = {str(r.get("record_id")): r for r in candidates}

    src_idx = build_source_index()
    print(f"[opus] indexed {len(src_idx)} source records")

    out_path = EXTRACTED_DIR / (
        f"extracted_opus_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    )
    fail_path = EXTRACTED_DIR / "opus_failures.jsonl"

    n_replaced = 0
    n_kept = 0
    n_skip = 0
    n_fail = 0
    n_no_source = 0

    jobs = []
    for rec in candidates:
        rid = str(rec.get("record_id"))
        src = src_idx.get(rid)
        if not src:
            n_no_source += 1
            continue
        jobs.append(src)

    print(f"[opus] dispatching {len(jobs)} requests with {MAX_WORKERS} workers")
    with out_path.open("a", encoding="utf-8") as fout, \
            fail_path.open("a", encoding="utf-8") as ffail, \
            ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(opus_extract, src): src for src in jobs}
        for fut in as_completed(futures):
            rid, payload, err = fut.result()
            if err:
                ffail.write(json.dumps({
                    "record_id": rid,
                    "error": err,
                }) + "\n")
                n_fail += 1
                continue
            if payload is None:
                n_fail += 1
                continue
            if payload.get("skip"):
                n_skip += 1
                continue
            sonnet_rec = sonnet_by_id.get(rid, {})
            sonnet_conf = sonnet_rec.get("confidence", 0.0) or 0.0
            opus_conf = payload.get("confidence", 0.0) or 0.0
            if opus_conf >= sonnet_conf:
                fout.write(json.dumps(payload, ensure_ascii=False) + "\n")
                n_replaced += 1
            else:
                n_kept += 1

    print(f"[opus] done: replaced={n_replaced} kept_sonnet={n_kept} "
          f"skip={n_skip} fail={n_fail} no_source={n_no_source} → {out_path.name}")


if __name__ == "__main__":
    run()
