# Turkey (TR) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 1
- **Records with USD/yr amount:** 0
- **Average reported income (USD/yr):** n/a- **Low-confidence records (<0.5):** 0

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 0 |
| lower_middle | 0 |
| middle | 0 |
| upper_middle | 0 |
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

_No data for this bracket._

### top

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | gravel_middleman_iraq_war | 1 |


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| business_owner | 100.0% |
| equity_compensation | 0.0% |
| freelance_contractor | 0.0% |
| government_pension | 0.0% |
| illicit_grey | 0.0% |
| inheritance_trust | 0.0% |
| multiple_streams | 0.0% |
| passive_investment | 0.0% |
| platform_gig | 0.0% |
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
_No excerpts for this bracket._

### top bracket
> "the US Military would ask Mehmet for X amount of gravel, Mehmet would make phone calls, arrange for the delivery, the US Military would pay him $2,000 a truck, he would turn around and pay the whoever delivered it to him $200 a truck  pocketing the $1,800."

— [reddit_import](https://reddit.com/r/Entrepreneur/comments/ec8ror/the_story_of_my_friends_uncle_and_how_he_made/)
*Profession: gravel_middleman_iraq_war | Summary: A Turkish entrepreneur acted as a middleman selling gravel to the US military in Iraq, pocketing $1,800 per truckload across thousands of trucks.*



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