# Pakistan (PK) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 3
- **Records with USD/yr amount:** 2
- **Average reported income (USD/yr):** $5,713- **Low-confidence records (<0.5):** 0

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 2 |
| lower_middle | 0 |
| middle | 1 |
| upper_middle | 0 |
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
| 1 | informal_day_laborer | 1 |
| 2 | petrol_subsidy_recipient | 1 |

### lower_middle

_No data for this bracket._

### middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | retired_elderly_remittance_recipient | 1 |

### upper_middle

_No data for this bracket._

### top

_No data for this bracket._


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| government_pension | 25.0% |
| illicit_grey | 25.0% |
| inheritance_trust | 25.0% |
| royalties_creator | 25.0% |
| business_owner | 0.0% |
| equity_compensation | 0.0% |
| freelance_contractor | 0.0% |
| multiple_streams | 0.0% |
| passive_investment | 0.0% |
| platform_gig | 0.0% |
| real_estate_rental | 0.0% |
| salary_employment | 0.0% |
| unknown | 0.0% |

## Narrative excerpts

### bottom bracket
> "Mera miyan din ke 500 kamata hai! Mere liye 10 rupay bhi keemti hain."

— [r_pakistan](https://www.reddit.com/r/pakistan/comments/1oypfxx/mera_miyan_din_ke_500_kamata_hai/)
*Profession: informal_day_laborer | Summary: Karachi low-income woman whose husband earns about 500 PKR/day (~182k PKR/year) in informal daily labor.*

> "I collected my amount today from HBL Konnect Agent and he charged me 100 rupees for it. So, it's 1900 after deduction."

— [r_pakistan](https://www.reddit.com/r/pakistan/comments/1st9g61/received_20_i_mean_1900_from_petrol_subsidy/)
*Profession: petrol_subsidy_recipient | Summary: Pakistani citizen received a one-time government petrol subsidy of 1,900 PKR (after 100 PKR agent fee).*


### lower_middle bracket
_No excerpts for this bracket._

### middle bracket
> "My elderly parents, both over 70, live in Pakistan in their own home. Every month, I send them 2.5 lakh rupees for their expenses. Since they own their house, there's no rent. Their monthly electricity bill is around 20–25 thousand, and the house help costs about 30 thousand per month."

— [r_pakistan](https://www.reddit.com/r/pakistan/comments/1nyjgk8/25_lakh_a_month_wheres_it_going/)
*Profession: retired_elderly_remittance_recipient | Summary: Elderly Pakistani couple over 70 living in their own home, supported by 2.5 lakh PKR/month (~30 lakh/year) in remittances from their adult child abroad.*


### upper_middle bracket
_No excerpts for this bracket._

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