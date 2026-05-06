"""Subagent-based LLM extraction (no Anthropic API needed).

Architecture (replaces extract.batch_runner for users without API key):
  1. sampler.py picks N records → data/extracted/_to_extract.jsonl
  2. THIS module splits _to_extract.jsonl into chunks of CHUNK_SIZE records
     → data/extracted/chunks/chunk_{NNNN}.jsonl
  3. The main conversation (or external orchestrator) spawns one Claude Code
     subagent per chunk. Each subagent reads its input chunk, follows the
     extraction protocol in extract/prompts.py SYSTEM_PROMPT, and writes
     → data/extracted/chunk_outputs/chunk_{NNNN}_out.jsonl
  4. After all subagents finish, run merge() to concatenate chunk_outputs/*
     into a single extracted_{date}.jsonl that load_sqlite.py expects.

Why chunks of 60: a Claude Code subagent's working window comfortably
handles ~60 records (~40k input tokens + ~20k output tokens) per run, with
margin for the system prompt and reasoning.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from config import EXTRACTED_DIR
from extract.schema import IncomeRecord

CHUNK_SIZE = 60
CHUNKS_DIR = EXTRACTED_DIR / "chunks"
OUTPUTS_DIR = EXTRACTED_DIR / "chunk_outputs"


def split() -> int:
    """Read _to_extract.jsonl → chunks/chunk_NNNN.jsonl. Returns chunk count."""
    in_path = EXTRACTED_DIR / "_to_extract.jsonl"
    if not in_path.exists():
        print(f"[chunker] no input at {in_path}; run extract.sampler first")
        return 0
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    records = []
    with in_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    print(f"[chunker] read {len(records)} records from {in_path.name}")

    n_chunks = 0
    for i in range(0, len(records), CHUNK_SIZE):
        chunk = records[i : i + CHUNK_SIZE]
        out = CHUNKS_DIR / f"chunk_{n_chunks:04d}.jsonl"
        with out.open("w", encoding="utf-8") as f:
            for r in chunk:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        n_chunks += 1
    print(f"[chunker] wrote {n_chunks} chunks of <={CHUNK_SIZE} → {CHUNKS_DIR}")
    return n_chunks


def list_pending() -> list[Path]:
    """Return chunks that have no corresponding output yet."""
    if not CHUNKS_DIR.exists():
        return []
    pending = []
    for chunk in sorted(CHUNKS_DIR.glob("chunk_*.jsonl")):
        out = OUTPUTS_DIR / f"{chunk.stem}_out.jsonl"
        if not out.exists():
            pending.append(chunk)
    return pending


def merge() -> int:
    """Concatenate all chunk_outputs/*.jsonl into one extracted_{date}.jsonl.
    Validates each line via Pydantic and skips bad records.
    Returns count of records written.
    """
    if not OUTPUTS_DIR.exists():
        print(f"[chunker] no outputs dir at {OUTPUTS_DIR}")
        return 0
    out_path = EXTRACTED_DIR / f"extracted_{datetime.now().strftime('%Y%m%d')}.jsonl"
    n_ok = 0
    n_skip = 0
    n_bad = 0
    with out_path.open("w", encoding="utf-8") as fout:
        for chunk_out in sorted(OUTPUTS_DIR.glob("chunk_*_out.jsonl")):
            with chunk_out.open(encoding="utf-8") as fin:
                for line in fin:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        n_bad += 1
                        continue
                    if obj.get("skip"):
                        n_skip += 1
                        continue
                    try:
                        rec = IncomeRecord.model_validate(obj)
                    except Exception:
                        n_bad += 1
                        continue
                    fout.write(rec.model_dump_json() + "\n")
                    n_ok += 1
    print(f"[chunker] merged {n_ok} valid records ({n_skip} skipped, {n_bad} bad) → {out_path}")
    return n_ok


def status() -> None:
    n_chunks = len(list(CHUNKS_DIR.glob("chunk_*.jsonl"))) if CHUNKS_DIR.exists() else 0
    n_done = len(list(OUTPUTS_DIR.glob("chunk_*_out.jsonl"))) if OUTPUTS_DIR.exists() else 0
    print(f"chunks={n_chunks} done={n_done} pending={n_chunks - n_done}")


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "split":
        split()
    elif cmd == "merge":
        merge()
    elif cmd == "status":
        status()
    else:
        print("usage: subagent_chunker.py {split|merge|status}")
