# Netherlands (NL) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 8
- **Records with USD/yr amount:** 5
- **Average reported income (USD/yr):** $61,639- **Low-confidence records (<0.5):** 0

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 1 |
| lower_middle | 0 |
| middle | 2 |
| upper_middle | 5 |
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

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | freelance_photographer | 1 |

### lower_middle

_No data for this bracket._

### middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | business_continuity_management_consultant_disabled | 1 |
| 2 | early_retiree | 1 |

### upper_middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | corporate_office_worker_expat | 1 |
| 2 | ecommerce_and_real_estate_entrepreneur | 1 |
| 3 | intern | 1 |
| 4 | programmer | 1 |
| 5 | software_engineer | 1 |

### top

_No data for this bracket._


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| salary_employment | 35.7% |
| business_owner | 14.3% |
| equity_compensation | 7.1% |
| freelance_contractor | 7.1% |
| government_pension | 7.1% |
| multiple_streams | 7.1% |
| passive_investment | 7.1% |
| real_estate_rental | 7.1% |
| royalties_creator | 7.1% |
| illicit_grey | 0.0% |
| inheritance_trust | 0.0% |
| platform_gig | 0.0% |
| unknown | 0.0% |

## Narrative excerpts

### bottom bracket
> "It's almost a year ago that I made the jump to give up my room ... to kickstart my dream as a freelance photographer ... Currently recovering from surgery, broker than ever before"

— [reddit_import](https://reddit.com/r/freelance/comments/e1qzt9/a_year_into_freelancing_but_still_struggling_hard/)
*Profession: freelance_photographer | Summary: Dutch freelance photographer struggling to find clients after a year, broke and recovering from surgery.*


### lower_middle bracket
_No excerpts for this bracket._

### middle bracket
> "I live in the Netherlands ... €550k => 5% SWR = €2300/month. That is 2,5x minimum wage."

— [reddit_import](https://reddit.com/r/financialindependence/comments/j0owcs/26_years_50_fire_small_income_country/g6u5pjr/)
*Profession: early_retiree | Summary: Netherlands-based commenter retired at 41 with €550k earning ~€2,300/month at a 5% SWR.*

> "I receive now disability benefits instead of salary for the rest of my life... My work CV: 1. Business Continuity Management (BCM) expert at Ernst & Young for Europe and Middle East. 2. BCM expert for Capgemini."

— [reddit_import](https://reddit.com/r/personalfinance/comments/6cue2g/ideas_to_earn_some_extra_money_next_to_100/)
*Profession: business_continuity_management_consultant_disabled | Summary: A 38-year-old former BCM/information security consultant in the Netherlands now receives 100% disability benefits due to cystic fibrosis and seeks supplemental income ideas.*


### upper_middle bracket
> "Right now, I have 5 weeks PTO, 8 weeks work from abroad, and a hybrid office situation (3 days office). Also get compensated with 104K TC, permanent contract(incredibly hard to get fired in my country), based in Amsterdam."

— [r_cscareerquestions](https://www.reddit.com/r/cscareerquestions/comments/1lqrw01/how_is_life_in_the_us_for_a_swe/)
*Profession: software_engineer | Summary: Amsterdam-based SWE with 5 YoE earning 104K TC, considering a move to the US.*

> "After taxes, I bring home €3270 per month (with some variation. +/- €30) ... On average, I have €700ish left over each month that I can invest/put to savings."

— [reddit_import](https://reddit.com/r/personalfinance/comments/8zl3my/i_did_not_understand_the_financial_consequences/)
*Profession: corporate_office_worker_expat | Summary: A 26-year-old US citizen who transferred to her company's Netherlands office takes home about €3270 per month after taxes and saves €700-1000 monthly.*

> "Income: EUR 48000 House: EUR 16800 Taxes: EUR 11800... A decent programmer makes somewhere in the ballpark of USD 80.000 a year, right?"

— [hackernews](https://news.ycombinator.com/item?id=5318676)
*Profession: programmer | Summary: Dutch programmer reports household income of EUR 48,000/yr considering move to SF/SV where programmers reportedly make ~$80,000/yr.*


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