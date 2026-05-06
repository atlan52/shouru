"""把 14k 行本地母语 raw → chunks（仅 *_native_*.jsonl，跳过已抽 reddit_import / hackernews）。

输出 data/extracted/chunks_native/chunk_NNNN.jsonl。一份 chunk 60 条。
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from config import RAW_DIR, EXTRACTED_DIR

CHUNK_SIZE = 60
CHUNKS_DIR = EXTRACTED_DIR / "chunks_native"
OUTPUTS_DIR = EXTRACTED_DIR / "chunk_outputs_native"


def collect():
    """Read all *_native_*.jsonl files and merge into a single in-memory list, deduped by id."""
    rows = []
    seen = set()
    files_loaded = 0
    for f in RAW_DIR.glob("*_native_*.jsonl"):
        with f.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                rid = obj.get("id")
                if not rid or rid in seen:
                    continue
                # truncate body to 2500 chars to keep prompt tokens manageable
                if "body" in obj and obj["body"]:
                    obj["body"] = obj["body"][:2500]
                rows.append(obj)
                seen.add(rid)
        files_loaded += 1
    print(f"[native_chunker] loaded {len(rows)} unique rows from {files_loaded} files")
    return rows


def split():
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    rows = collect()
    random.shuffle(rows)

    # Save full list for audit
    with (EXTRACTED_DIR / "_native_to_extract.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n_chunks = 0
    for i in range(0, len(rows), CHUNK_SIZE):
        chunk = rows[i : i + CHUNK_SIZE]
        out = CHUNKS_DIR / f"chunk_{n_chunks:04d}.jsonl"
        with out.open("w", encoding="utf-8") as f:
            for r in chunk:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        n_chunks += 1
    print(f"[native_chunker] wrote {n_chunks} chunks → {CHUNKS_DIR}")
    return n_chunks


def list_pending():
    if not CHUNKS_DIR.exists():
        return []
    pending = []
    for chunk in sorted(CHUNKS_DIR.glob("chunk_*.jsonl")):
        out = OUTPUTS_DIR / f"{chunk.stem}_out.jsonl"
        if not out.exists():
            pending.append(chunk)
    return pending


def status():
    n_chunks = len(list(CHUNKS_DIR.glob("chunk_*.jsonl"))) if CHUNKS_DIR.exists() else 0
    n_done = len(list(OUTPUTS_DIR.glob("chunk_*_out.jsonl"))) if OUTPUTS_DIR.exists() else 0
    print(f"chunks={n_chunks} done={n_done} pending={n_chunks - n_done}")


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "split":
        split()
    elif cmd == "status":
        status()
    else:
        print("usage: native_chunker.py {split|status}")
