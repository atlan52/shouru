# South Africa (ZA) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 7
- **Records with USD/yr amount:** 7
- **Average reported income (USD/yr):** $66,211- **Low-confidence records (<0.5):** 0

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 0 |
| lower_middle | 1 |
| middle | 0 |
| upper_middle | 4 |
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
| 1 | early_career_employee | 1 |

### middle

_No data for this bracket._

### upper_middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | fire_household_dual_income | 1 |
| 2 | mobile_app_developer | 1 |
| 3 | recently_laid_off_employee | 1 |
| 4 | salaried_employee | 1 |

### top

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | financial_planning_analysis_manager | 1 |
| 2 | teacher_abroad | 1 |


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| salary_employment | 60.0% |
| passive_investment | 20.0% |
| freelance_contractor | 10.0% |
| real_estate_rental | 10.0% |
| business_owner | 0.0% |
| equity_compensation | 0.0% |
| government_pension | 0.0% |
| illicit_grey | 0.0% |
| inheritance_trust | 0.0% |
| multiple_streams | 0.0% |
| platform_gig | 0.0% |
| royalties_creator | 0.0% |
| unknown | 0.0% |

## Narrative excerpts

### bottom bracket
_No excerpts for this bracket._

### lower_middle bracket
> "I currently earn R16 000 a month and I am investing roughly R12 000 of that each and every month. ... R7 000 into my Alan Gray balanced fund R3 833ish into my TFSA (10x total world ETF) R1 000 into QQQM in my USD account"

— [r_personalfinanceza](https://www.reddit.com/r/PersonalFinanceZA/comments/1suen0p/all_of_my_investments_at_21_years_old/)
*Profession: early_career_employee | Summary: 21-year-old South African earning R16,000/month, investing R12,000 across Allan Gray balanced fund, TFSA, and a USD QQQM account.*


### middle bracket
_No excerpts for this bracket._

### upper_middle bracket
> "R90k post-tax income (about an 80/20 split between me/my wife) - R36k spent ... - R54k saved - 60% savings rate"

— [r_personalfinanceza](https://www.reddit.com/r/PersonalFinanceZA/comments/1q2soxu/fire_south_africa_2026_update/)
*Profession: fire_household_dual_income | Summary: South African dual-income FIRE household with R90k/month post-tax (80/20 split), R3.8M net worth, 60% savings rate.*

> "I got a decent salary bump today, about 30%. My gross is close to R60k. I don't need to pay for medical and I'm considering opening a retirement fund/investment."

— [r_personalfinanceza](https://www.reddit.com/r/PersonalFinanceZA/comments/1ry9zcl/i_need_your_guidance/)
*Profession: salaried_employee | Summary: South African salaried worker received a 30% raise; gross salary close to R60k/month.*

> "I'm about to receive a severance package from my employer due to no fault termination (approx 300k)... I'd need to make at least a once a month "withdrawal" to give myself a "salary" (approx 35k) until i find another job."

— [r_personalfinanceza](https://www.reddit.com/r/PersonalFinanceZA/comments/1r0q409/managing_severance_pay/)
*Profession: recently_laid_off_employee | Summary: South African employee receiving ~R300k severance after no-fault termination, planning to draw ~R35k/month while job-hunting.*


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