# Singapore (SG) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 7
- **Records with USD/yr amount:** 4
- **Average reported income (USD/yr):** $50,851- **Low-confidence records (<0.5):** 1

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 0 |
| lower_middle | 1 |
| middle | 3 |
| upper_middle | 1 |
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

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | food_service_worker | 1 |

### middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | career_switcher | 1 |
| 2 | entrepreneur | 1 |
| 3 | office_worker | 1 |

### upper_middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | banking_professional | 1 |

### top

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | early_retired_options_trader | 1 |
| 2 | international_consultant_chemicals | 1 |


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| salary_employment | 35.7% |
| business_owner | 21.4% |
| freelance_contractor | 14.3% |
| passive_investment | 14.3% |
| multiple_streams | 7.1% |
| real_estate_rental | 7.1% |
| equity_compensation | 0.0% |
| government_pension | 0.0% |
| illicit_grey | 0.0% |
| inheritance_trust | 0.0% |
| platform_gig | 0.0% |
| royalties_creator | 0.0% |
| unknown | 0.0% |

## Narrative excerpts

### bottom bracket
_No excerpts for this bracket._

### lower_middle bracket
> "Food service PWM base salary to rise to S$2,220 from Jul 1"

— [r_singapore](https://www.reddit.com/r/singapore/comments/1rvbd7s/food_service_pwm_base_salary_to_rise_to_s2220/)
*Profession: food_service_worker | Summary: Singapore food service workers under Progressive Wage Model to receive base salary of S$2,220/month from July 1.*


### middle bracket
> "For 1.5 years I was earning less than 20k SGD, and even now I'm earning just under 50k a year. I'm quite frugal, so I might be able to hit 100k early next year."

— [reddit_import](https://reddit.com/r/leanfire/comments/oirkvh/had_nowhere_else_to_share_my_nw_is_finally_close/)
*Profession: career_switcher | Summary: A 28-year-old in Singapore earning just under 50k SGD/year after a career switch, near 100k SGD net worth.*

> "Actual Income for 2016: $35000 (and ~$4000+ expected in December) Guaranteed income for 2016: ~$24,000 (4.5 months salary + bonuses from work last year)"

— [reddit_import](https://reddit.com/r/personalfinance/comments/5ebbcn/i_took_6_months_off_work_and_survived/)
*Profession: office_worker | Summary: Office worker took 6 months unpaid leave to be with overseas SO, earning $35k for the year including freelance illustration commissions.*

> "About me: I'm an average entrepreneur, dad and husband who is fascinated with  marketing, leadership, entrepreneurship and creating a life and  stuff  that matters."

— [reddit_import](https://reddit.com/r/Entrepreneur/comments/rcgpl6/in_2008_i_quit_a_job_i_hated_and_to_my_sad/)
*Profession: entrepreneur | Summary: Self-described average entrepreneur left a toxic job in 2008 and built a marketing-focused business career.*


### upper_middle bracket
> "30F; graduated in 2012; no kids; very HCOL... 2020|111k|402k... Hustled self into a decent paying banking job before graduation. Immediate cash flow after graduation."

— [reddit_import](https://reddit.com/r/financialindependence/comments/f7d21v/spendy_to_meticulous_just_crossed_400k_in_nw/)
*Profession: banking_professional | Summary: A 30-year-old female banker in a very high cost-of-living non-US city reports after-tax income rising from $70k in 2012 to $111k in 2020 with $402k net worth.*


### top bracket
> "I resigned in mid April 2024...Net worth increased by ~$250k despite having zero income from employment...I have been trading options for income for years"

— [reddit_import](https://reddit.com/r/financialindependence/comments/1k41nww/1_year_fire_update/)
*Profession: early_retired_options_trader | Summary: A Singaporean FIRE'd a year ago and now lives off investments and options-trading income, with net worth up about SGD $250k post-retirement.*

> "My savings is just shy of the 2 comma number, but not by a lot. ... I was a genuine independent international consultant for a big time Dow Component company, on the preferred vendor list."

— [reddit_import](https://reddit.com/r/financialindependence/comments/8t7reu/14_years_ago_i_was_27_years_old_i_paid_off_my/)
*Profession: international_consultant_chemicals | Summary: After consulting for a Dow Component company in Indonesia for four years on a 1-month-on/1-month-off contract, the author now works in-house in Singapore with savings just shy of $2 million.*



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