"""Anthropic Batch API runner. Submit chunks of 10k records → poll → parse.

Cost target: Sonnet 4.6 with prompt caching + 50% batch discount.
~55-100k records × ~600 input + ~280 output tokens ≈ $90-200 total.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from anthropic.types.messages.batch_create_params import (
    Request,
    MessageCreateParamsNonStreaming,
)

from config import EXTRACTED_DIR
from extract.prompts import SYSTEM_PROMPT, build_user_message
from extract.schema import IncomeRecord, SkipResult

CHUNK_SIZE = 10_000
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 900
POLL_INTERVAL_S = 60
MAX_INFLIGHT = 4  # Anthropic batch concurrency cap

client = anthropic.Anthropic()


def chunk_iter(records, n):
    buf = []
    for r in records:
        buf.append(r)
        if len(buf) >= n:
            yield buf
            buf = []
    if buf:
        yield buf


def _strip_fences(text: str) -> str:
    """Strip ```json ... ``` fences if the LLM added them despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        # Drop opening fence line
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def submit_batch(records):
    requests = []
    for r in records:
        rid = r.get("id") or r.get("record_id")
        if not rid:
            continue
        params = MessageCreateParamsNonStreaming(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": build_user_message(r)}],
        )
        requests.append(Request(custom_id=str(rid), params=params))
    batch = client.messages.batches.create(requests=requests)
    return batch.id


def poll_batch(batch_id):
    while True:
        b = client.messages.batches.retrieve(batch_id)
        if b.processing_status in ("ended", "canceled", "expired"):
            return b
        print(f"[batch] {batch_id}: {b.processing_status}, "
              f"req_counts={b.request_counts}")
        time.sleep(POLL_INTERVAL_S)


def parse_batch_results(batch):
    """Stream results JSONL from Anthropic, validate via Pydantic, write to extracted/."""
    out_path = EXTRACTED_DIR / (
        f"extracted_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{batch.id[:8]}.jsonl"
    )
    fail_path = EXTRACTED_DIR / "failures.jsonl"
    n_ok = 0
    n_skip = 0
    n_fail = 0
    results = client.messages.batches.results(batch.id)
    with out_path.open("a", encoding="utf-8") as fout, \
            fail_path.open("a", encoding="utf-8") as ffail:
        for entry in results:
            rid = entry.custom_id
            try:
                if entry.result.type == "succeeded":
                    msg = entry.result.message
                    text = "".join(
                        b.text for b in msg.content if hasattr(b, "text")
                    ).strip()
                    text = _strip_fences(text)
                    parsed = json.loads(text)
                    if parsed.get("skip"):
                        SkipResult.model_validate(parsed)
                        n_skip += 1
                        continue
                    parsed.setdefault("record_id", rid)
                    parsed.setdefault("extraction_model", MODEL)
                    parsed.setdefault(
                        "extracted_at",
                        datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    )
                    rec = IncomeRecord.model_validate(parsed)
                    fout.write(rec.model_dump_json() + "\n")
                    n_ok += 1
                else:
                    ffail.write(json.dumps({
                        "record_id": rid,
                        "reason": entry.result.type,
                        "detail": str(entry.result),
                    }) + "\n")
                    n_fail += 1
            except Exception as e:
                ffail.write(json.dumps({
                    "record_id": rid,
                    "reason": "parse_error",
                    "error": str(e),
                }) + "\n")
                n_fail += 1
    print(f"[batch] {batch.id}: ok={n_ok} skip={n_skip} fail={n_fail} "
          f"→ {out_path.name}")


def run():
    in_path = EXTRACTED_DIR / "_to_extract.jsonl"
    if not in_path.exists():
        from extract import sampler
        sampler.run()
    records = []
    with in_path.open(encoding="utf-8") as f:
        for line in f:
            try:
                records.append(json.loads(line))
            except Exception:
                continue
    n_chunks = (len(records) + CHUNK_SIZE - 1) // CHUNK_SIZE
    print(f"[batch] {len(records)} records to extract in {n_chunks} chunks")
    inflight = []
    for chunk in chunk_iter(records, CHUNK_SIZE):
        while len(inflight) >= MAX_INFLIGHT:
            done = inflight.pop(0)
            b = poll_batch(done)
            parse_batch_results(b)
        bid = submit_batch(chunk)
        print(f"[batch] submitted {bid} ({len(chunk)} records)")
        inflight.append(bid)
    for bid in inflight:
        b = poll_batch(bid)
        parse_batch_results(b)
    print("[batch] all done")


if __name__ == "__main__":
    run()
