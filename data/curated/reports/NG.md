# Nigeria (NG) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 2
- **Records with USD/yr amount:** 0
- **Average reported income (USD/yr):** n/a- **Low-confidence records (<0.5):** 0

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 0 |
| lower_middle | 0 |
| middle | 0 |
| upper_middle | 1 |
| top | 1 |

## Bracket thresholds (USD/yr lower bound)

| Bracket | Lower bound (USD/yr) |
| --- | ---: |
| bottom | $0 |
| lower_middle | $5,000 |
| middle | $15,000 |
| upper_middle | $40,000 |
| top | $150,000 |

## Top professions per bracket

### bottom

_No data for this bracket._

### lower_middle

_No data for this bracket._

### middle

_No data for this bracket._

### upper_middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | software_contractor | 1 |

### top

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | food_vendor | 1 |


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| business_owner | 33.3% |
| freelance_contractor | 33.3% |
| platform_gig | 33.3% |
| equity_compensation | 0.0% |
| government_pension | 0.0% |
| illicit_grey | 0.0% |
| inheritance_trust | 0.0% |
| multiple_streams | 0.0% |
| passive_investment | 0.0% |
| real_estate_rental | 0.0% |
| royalties_creator | 0.0% |
| salary_employment | 0.0% |
| unknown | 0.0% |

## Narrative excerpts

### bottom bracket
_No excerpts for this bracket._

### lower_middle bracket
_No excerpts for this bracket._

### middle bracket
_No excerpts for this bracket._

### upper_middle bracket
> "I started at my current role in April 2021 at which point the parallel market exchange rate was ₦480 to $1; earlier this month I exchanged currencies at ₦600 to $1."

— [hackernews](https://news.ycombinator.com/item?id=31687950)
*Profession: software_contractor | Summary: A Nigeria-based independent contractor for a foreign company is paid in USD to avoid naira devaluation and currency controls.*


### top bracket
> "UNILAG ChowDeck Vendor Mints Naira ₦1 Billion selling Spaghetti ₦1 Billion = $667,000"

— [r_nigeria](https://www.reddit.com/r/Nigeria/comments/1kqe5x1/thriving_in_the_midst_of_chaos_unilag_chowdeck/)
*Profession: food_vendor | Summary: UNILAG campus food vendor named Korode earned ₦1 billion selling spaghetti via ChowDeck platform.*



---

## Methodology

Records extracted from public posts on locally-dominant platforms by an
LLM (Claude Sonnet 4.6) constrained to the
[`IncomeRecord`](../../extract/schema.py) schema. Local-currency amounts
are converted to USD/year via a dated FX snapshot
(see `extract.fx`); period normalization (hour/day/week/month/year) is
performed downstream of the LLM. Income brackets are country-specific
USD/yr thresholds defined in `config.COUNTRY_BRACKETS`. Earning
mechanisms are picked from a closed list documented in
[docs/MECHANISMS.md](../../docs/MECHANISMS.md). Counts here reflect
sampled posts, not population statistics — interpret accordingly.