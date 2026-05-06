# shouru — 跨国收入与谋生方式研究

A multi-language web scraping + LLM extraction + analysis project that
answers: **how do people in different income brackets across 40+ countries
earn their living?**

- 36 dedicated crawlers across forums / salary aggregators / gov stats /
  rich lists, anchored to each country's locally-dominant platforms
- Reuses existing 641MB / 3.18M-row Reddit corpus from `../reddit_spider/`
- LLM-extracts each post → `{country, bracket, profession, mechanism, narrative}`
  via Claude Sonnet 4.6 Batch API + Opus 4.7 re-check on top samples
- Outputs: 40 country markdown reports + cross-country charts + SQLite DB

## Quickstart

```bash
# 1. install deps
pip install -r requirements.txt
playwright install chromium

# 2. set up env
cp .env.example .env
# fill in ANTHROPIC_API_KEY (required) and any platform cookies you have

# 3. smoke-test (50 items per crawler, ~5 min total)
SMOKE_TEST=1 python run.py --tier P0

# 4. overnight crawl
python run.py --tier P0   # P0 platforms first, ~6h
python run.py --tier P1   # then P1
python run.py --phase extract   # LLM extraction
python run.py --phase analyze   # reports + charts
```

## Layout

- `config.py` — countries, languages, COUNTRY_DOMAINS, brackets, mechanisms
- `run.py` — multiprocessing dispatcher (10 workers default)
- `pipeline.py` — top-200 markdown summary per platform
- `crawlers/` — 36 platform modules + state, common, playwright_pool
- `extract/` — Anthropic Batch API LLM extraction + Pydantic schema
- `analyze/` — SQLite load, aggregation, viz, jinja2 country reports
- `data/` — gitignored: raw, extracted, curated (reports + figs), state
- `docs/` — BRACKETS.md, MECHANISMS.md, COUNTRY_PLATFORMS.md
- `logs/` — per-platform stdout

## Design

See `/Users/jan/.claude/plans/10-subagent-delegated-tulip.md` for the full
plan, including the per-country platform matrix, time budget, and risk list.

## Status / resume

```bash
python run.py --status     # progress per platform
python run.py --list       # platforms grouped by tier
python run.py --fresh xhs  # wipe one platform's state
```
