# Morocco (MA) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 2
- **Records with USD/yr amount:** 3
- **Average reported income (USD/yr):** $8,139- **Low-confidence records (<0.5):** 0

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 0 |
| lower_middle | 1 |
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

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | office_administrator | 1 |

### middle

_No data for this bracket._

### upper_middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | maintenance_process_manager | 1 |

### top

_No data for this bracket._


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| salary_employment | 100.0% |
| business_owner | 0.0% |
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
| unknown | 0.0% |

## Narrative excerpts

### bottom bracket
_No excerpts for this bracket._

### lower_middle bracket
> "I work from 8 am to 7 pm, 6 days a week.  The salary is 3000 dirhams."

— [r_morocco](https://www.reddit.com/r/Morocco/comments/1q1v2em/need_your_advice/)
*Profession: office_administrator | Summary: 25-year-old Moroccan office administrator handling invoices, customer calls, web/social media, working 8am-7pm 6 days/week for 3000 dirhams/month.*


### middle bracket
_No excerpts for this bracket._

### upper_middle bracket
> "I am a maintenance/process manager with 14 years of experience. I have a BTS degree in electromechanics and a professional master's degree in industrial management. My current salary is 14,000 dirhams."

— [r_morocco](https://www.reddit.com/r/Morocco/comments/1ldkxx1/my_salary_as_manager/)
*Profession: maintenance_process_manager | Summary: Moroccan maintenance/process manager with 14 years of experience earning 14,000 MAD/month.*


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