# Spain (ES) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 2
- **Records with USD/yr amount:** 2
- **Average reported income (USD/yr):** $1,958,400- **Low-confidence records (<0.5):** 2

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 0 |
| lower_middle | 0 |
| middle | 0 |
| upper_middle | 0 |
| top | 2 |

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
| 1 | ecommerce_founder_bicycle_brand | 1 |
| 2 | green_tech_ecommerce_founder | 1 |


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| salary_employment | 50.0% |
| business_owner | 33.3% |
| freelance_contractor | 16.7% |
| equity_compensation | 0.0% |
| government_pension | 0.0% |
| illicit_grey | 0.0% |
| inheritance_trust | 0.0% |
| multiple_streams | 0.0% |
| passive_investment | 0.0% |
| platform_gig | 0.0% |
| real_estate_rental | 0.0% |
| royalties_creator | 0.0% |
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
> "Our monthly turnover is 200.000€. Our main markets are France, Spain, Netherlands, Italy and UK. And our brand represents around 20% of the turnover."

— [reddit_import](https://reddit.com/r/Entrepreneur/comments/d2d0nw/250kmonth_selling_fixies/)
*Profession: ecommerce_founder_bicycle_brand | Summary: Founder of Spanish bicycle e-commerce brand Santafixie reports monthly revenue of 200,000 euros (about $250k).*

> "Product: green tech products * Revenue/mo: $110,000 * Started: November 2009 * Location: Pamplona ... I am a 36-year-old father-of-three from Spain that runs a retail business"

— [reddit_import](https://reddit.com/r/Entrepreneur/comments/di9y96/110000month_selling_green_tech_products_with_my/)
*Profession: green_tech_ecommerce_founder | Summary: Spanish entrepreneur runs a green-tech retail/e-commerce business in Pamplona generating $110,000 per month in revenue.*



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