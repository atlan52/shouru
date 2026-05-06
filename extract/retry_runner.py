"""Retry runner — re-issue records that failed in batch_runner.

Reads `data/extracted/failures.jsonl`, looks up the source record in
`_to_extract.jsonl` (or RAW_DIR as fallback), and re-issues it against Sonnet
non-batch (full price) with a stricter system reminder. Up to 2 retries; after
2 failures, drop and log.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from config import EXTRACTED_DIR, RAW_DIR
from extract.prompts import SYSTEM_PROMPT, build_user_message
from extract.schema import IncomeRecord, SkipResult

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 900
MAX_RETRIES = 2

STRICT_REMINDER = (
    "\n\n# CRITICAL OUTPUT FORMAT\n"
    "Return ONLY valid JSON. No markdown, no fence, no commentary, no prose. "
    "Your entire response must be parseable by `json.loads`. "
    "If you cannot extract income data, return exactly "
    '`{"skip": true, "reason": "<short>"}`.'
)

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


def load_failed_ids() -> list[str]:
    fail_path = EXTRACTED_DIR / "failures.jsonl"
    if not fail_path.exists():
        return []
    ids = []
    seen = set()
    with fail_path.open(encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            rid = obj.get("record_id")
            if rid and rid not in seen:
                seen.add(rid)
                ids.append(rid)
    return ids


def build_record_index() -> dict:
    """Map record_id → raw record. Searches _to_extract.jsonl first, then RAW_DIR."""
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
    # Fallback: scan RAW_DIR
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


def extract_one(record: dict) -> tuple[bool, str | dict]:
    """Single non-batch call. Returns (ok, parsed_or_error_str)."""
    try:
        msg = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT + STRICT_REMINDER,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": build_user_message(record)}],
        )
        text = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
        text = _strip_fences(text)
        parsed = json.loads(text)
        return True, parsed
    except Exception as e:
        return False, str(e)


def run():
    failed_ids = load_failed_ids()
    if not failed_ids:
        print("[retry] no failures.jsonl entries — nothing to do")
        return
    print(f"[retry] {len(failed_ids)} failed records to retry")

    idx = build_record_index()
    print(f"[retry] indexed {len(idx)} candidate records")

    out_path = EXTRACTED_DIR / (
        f"extracted_retry_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    )
    drop_path = EXTRACTED_DIR / "retry_dropped.jsonl"

    n_ok = 0
    n_skip = 0
    n_drop = 0
    with out_path.open("a", encoding="utf-8") as fout, \
            drop_path.open("a", encoding="utf-8") as fdrop:
        for rid in failed_ids:
            rec = idx.get(str(rid))
            if not rec:
                fdrop.write(json.dumps({
                    "record_id": rid,
                    "reason": "source_not_found",
                }) + "\n")
                n_drop += 1
                continue

            success = False
            last_err = ""
            for attempt in range(1, MAX_RETRIES + 1):
                ok, payload = extract_one(rec)
                if not ok:
                    last_err = f"api_error: {payload}"
                    continue
                try:
                    if isinstance(payload, dict) and payload.get("skip"):
                        SkipResult.model_validate(payload)
                        n_skip += 1
                        success = True
                        break
                    payload.setdefault("record_id", rid)
                    payload.setdefault("extraction_model", MODEL)
                    payload.setdefault(
                        "extracted_at",
                        datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    )
                    validated = IncomeRecord.model_validate(payload)
                    fout.write(validated.model_dump_json() + "\n")
                    n_ok += 1
                    success = True
                    break
                except Exception as e:
                    last_err = f"validation_error_attempt{attempt}: {e}"
                    continue

            if not success:
                fdrop.write(json.dumps({
                    "record_id": rid,
                    "reason": "max_retries_exceeded",
                    "last_error": last_err,
                }) + "\n")
                n_drop += 1
                print(f"[retry] dropped {rid}: {last_err}")

    print(f"[retry] done: ok={n_ok} skip={n_skip} dropped={n_drop} → {out_path.name}")


if __name__ == "__main__":
    run()
