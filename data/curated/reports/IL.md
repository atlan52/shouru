# Israel (IL) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 1
- **Records with USD/yr amount:** 1
- **Average reported income (USD/yr):** $107,316- **Low-confidence records (<0.5):** 0

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 0 |
| lower_middle | 0 |
| middle | 0 |
| upper_middle | 1 |
| top | 0 |

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
| 1 | israeli_tech_employee | 1 |

### top

_No data for this bracket._


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| equity_compensation | 50.0% |
| salary_employment | 50.0% |
| business_owner | 0.0% |
| freelance_contractor | 0.0% |
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
> "I received an offer letter with with the option to convert part of the salary to stock options as per the below table. Base salary is ₪33K/month (Israeli Shekel). Be aware of '₪' vs '$' in some columns. As of this writing the exchange rate is 1$ = 3.7₪."

— [reddit_import](https://reddit.com/r/personalfinance/comments/9t8xj9/should_i_accept_stock_options_in_exchange_for/)
*Profession: israeli_tech_employee | Summary: An Israeli tech employee received an offer with a base salary of ₪33,000 per month, with optional conversion of part of the salary into stock options.*


### top bracket
_No excerpts for this bracket._


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