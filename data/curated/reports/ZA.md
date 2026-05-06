# South Africa (ZA) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 5
- **Records with USD/yr amount:** 5
- **Average reported income (USD/yr):** $78,754- **Low-confidence records (<0.5):** 0

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 0 |
| lower_middle | 0 |
| middle | 0 |
| upper_middle | 3 |
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

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | mobile_app_developer | 1 |
| 2 | recently_laid_off_employee | 1 |
| 3 | salaried_employee | 1 |

### top

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | financial_planning_analysis_manager | 1 |
| 2 | teacher_abroad | 1 |


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| salary_employment | 66.7% |
| freelance_contractor | 16.7% |
| real_estate_rental | 16.7% |
| business_owner | 0.0% |
| equity_compensation | 0.0% |
| government_pension | 0.0% |
| illicit_grey | 0.0% |
| inheritance_trust | 0.0% |
| multiple_streams | 0.0% |
| passive_investment | 0.0% |
| platform_gig | 0.0% |
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
> "I got a decent salary bump today, about 30%. My gross is close to R60k. I don't need to pay for medical and I'm considering opening a retirement fund/investment."

— [r_personalfinanceza](https://www.reddit.com/r/PersonalFinanceZA/comments/1ry9zcl/i_need_your_guidance/)
*Profession: salaried_employee | Summary: South African salaried worker received a 30% raise; gross salary close to R60k/month.*

> "I'm about to receive a severance package from my employer due to no fault termination (approx 300k)... I'd need to make at least a once a month "withdrawal" to give myself a "salary" (approx 35k) until i find another job."

— [r_personalfinanceza](https://www.reddit.com/r/PersonalFinanceZA/comments/1r0q409/managing_severance_pay/)
*Profession: recently_laid_off_employee | Summary: South African employee receiving ~R300k severance after no-fault termination, planning to draw ~R35k/month while job-hunting.*

> "in my country, being able to earn $100 an hour is way attractive... favourable exchange rate would make me a local millionaire in half a year"

— [reddit_import](https://reddit.com/r/freelance/comments/4k28sq/my_impression_of_toptal/)
*Profession: mobile_app_developer | Summary: A senior mobile developer in a country with favorable exchange rate sought to earn $100/hour through Toptal but was rejected.*


### top bracket
> "Profession: FP&A/Management Accountant/Finance Business Partner Gross Salary: Soon to be a little over R1m annual. Gross Rental Income: R13k per month."

— [reddit_import](https://reddit.com/r/financialindependence/comments/1efu27a/fire_progress_35m_nonfirst_world_south_africa/)
*Profession: financial_planning_analysis_manager | Summary: A 35-year-old FP&A and management accountant in South Africa earns just over R1 million annually plus about R13k/month in gross rental income, with a net worth of R4 million.*

> "I don't earn more than R1.25 million per year. I have not interacted with SARS in that time. Over the last two years my salary has been paid into my South African bank account."

— [r_personalfinanceza](https://www.reddit.com/r/PersonalFinanceZA/comments/1oqk5w2/south_african_teaching_abroad/)
*Profession: teacher_abroad | Summary: South African expat teacher abroad for 8 years earning under R1.25M/year paid into SA bank account, worried about SARS compliance.*



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