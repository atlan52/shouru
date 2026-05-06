#!/usr/bin/env bash
# 12h overnight orchestration for shouru/.
#
# Phase A (t=0..3min): bootstrap — reddit_import (CSV → JSONL)
# Phase B (t=0..6h):   crawl — P0+P1 platforms in parallel
# Phase C (t=4..10h):  rolling LLM extraction (Sonnet 4.6 batch)
# Phase D (t=10..12h): analysis — load_sqlite, viz, 40 country reports
#
# Usage:
#   bash run-overnight.sh                # full pipeline
#   bash run-overnight.sh --skip-crawl   # extract+analyze only (data already crawled)
#   bash run-overnight.sh --smoke        # SMOKE_TEST=1 sanity pass

set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

VENV="$ROOT/.venv"
if [ -d "$VENV" ]; then PY="$VENV/bin/python"; else PY="python3"; fi

[ -f .env ] && set -a && . ./.env && set +a

SMOKE=""
SKIP_CRAWL=""
for arg in "$@"; do
  case "$arg" in
    --smoke) SMOKE=1; export SMOKE_TEST=1 ;;
    --skip-crawl) SKIP_CRAWL=1 ;;
  esac
done

PLATFORM_TIME_BUDGET_SEC="${PLATFORM_TIME_BUDGET_SEC:-21600}"
export PLATFORM_TIME_BUDGET_SEC

log() { echo "[overnight $(date +%H:%M:%S)] $*"; }

# ---------- Phase A: reddit_import (no network, ~3 min) ----------
if [ -z "$SKIP_CRAWL" ]; then
  log "PHASE A: reddit_import (3.18M-row CSV → JSONL)"
  $PY -m crawlers.reddit_import 2>&1 | tee -a logs/reddit_import.log
fi

# ---------- Phase B: crawl P0 then P1 (parallel) ----------
if [ -z "$SKIP_CRAWL" ]; then
  log "PHASE B: crawl P0 (10 workers, 6h budget)"
  $PY run.py --tier P0 --workers 10 2>&1 | tee -a logs/dispatcher.log

  log "PHASE B: crawl P1 (10 workers, 4h budget)"
  PLATFORM_TIME_BUDGET_SEC=14400 $PY run.py --tier P1 --workers 10 2>&1 | tee -a logs/dispatcher.log

  log "PHASE B: crawl P2 fill (10 workers, 2h budget)"
  PLATFORM_TIME_BUDGET_SEC=7200 $PY run.py --tier P2 --workers 10 2>&1 | tee -a logs/dispatcher.log

  log "PHASE B done — pipeline.py to render top-200 per platform"
  $PY pipeline.py 2>&1 | tee -a logs/pipeline.log
fi

# ---------- Phase C: LLM extraction ----------
log "PHASE C: extract.sampler — pick 25-30k Reddit + full others"
$PY -m extract.sampler 2>&1 | tee -a logs/extract.log

log "PHASE C: extract.batch_runner (Sonnet 4.6 Batch API)"
$PY -m extract.batch_runner 2>&1 | tee -a logs/extract.log

log "PHASE C: extract.retry_runner (failed records)"
$PY -m extract.retry_runner 2>&1 | tee -a logs/extract.log || true

log "PHASE C: extract.opus_recheck (top-1k high-value)"
$PY -m extract.opus_recheck 2>&1 | tee -a logs/extract.log || true

log "PHASE C: extract.eyeball — sample 30 for human review"
$PY -m extract.eyeball 2>&1 | tee -a logs/extract.log || true

# ---------- Phase D: analyze ----------
log "PHASE D: analyze.load_sqlite"
$PY -m analyze.load_sqlite 2>&1 | tee -a logs/analyze.log

log "PHASE D: analyze.aggregate (sanity print)"
$PY -m analyze.aggregate 2>&1 | tee -a logs/analyze.log

log "PHASE D: analyze.visualize — 7 chart families"
$PY -m analyze.visualize 2>&1 | tee -a logs/analyze.log

log "PHASE D: analyze.report — 40 country markdown"
$PY -m analyze.report 2>&1 | tee -a logs/analyze.log

log "DONE. Outputs: data/curated/{reports,figs,income.db,income_records.parquet}"
