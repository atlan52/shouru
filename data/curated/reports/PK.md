# Pakistan (PK) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 6
- **Records with USD/yr amount:** 5
- **Average reported income (USD/yr):** $14,864- **Low-confidence records (<0.5):** 0

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 2 |
| lower_middle | 1 |
| middle | 1 |
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

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | informal_day_laborer | 1 |
| 2 | petrol_subsidy_recipient | 1 |

### lower_middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | office_worker | 1 |

### middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | retired_elderly_remittance_recipient | 1 |

### upper_middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | salaried_professional | 1 |

### top

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | it_developer | 1 |


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| salary_employment | 37.5% |
| freelance_contractor | 12.5% |
| government_pension | 12.5% |
| illicit_grey | 12.5% |
| inheritance_trust | 12.5% |
| royalties_creator | 12.5% |
| business_owner | 0.0% |
| equity_compensation | 0.0% |
| multiple_streams | 0.0% |
| passive_investment | 0.0% |
| platform_gig | 0.0% |
| real_estate_rental | 0.0% |
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
> "getting a 60k salary in this dead economy is already the hardest thing ever but even if someone miraculously earns that much how is a human supposed to stay alive"

— [r_pakistan](https://www.reddit.com/r/pakistan/comments/1sarih4/petrol_just_crossed_450_honestly_my_will_to_live/)
*Profession: office_worker | Summary: Pakistani office worker earning around PKR 60,000/month, struggling with fuel costs consuming most of their income.*


### middle bracket
> "My elderly parents, both over 70, live in Pakistan in their own home. Every month, I send them 2.5 lakh rupees for their expenses. Since they own their house, there's no rent. Their monthly electricity bill is around 20–25 thousand, and the house help costs about 30 thousand per month."

— [r_pakistan](https://www.reddit.com/r/pakistan/comments/1nyjgk8/25_lakh_a_month_wheres_it_going/)
*Profession: retired_elderly_remittance_recipient | Summary: Elderly Pakistani couple over 70 living in their own home, supported by 2.5 lakh PKR/month (~30 lakh/year) in remittances from their adult child abroad.*


### upper_middle bracket
> "even though Alhumdulillah I am making 800k plus (married with a newborn), savings are minimal after expenses but we do live 'large'."

— [r_pakistan](https://www.reddit.com/r/pakistan/comments/1ok3l0z/household_income_and_budget/)
*Profession: salaried_professional | Summary: Pakistani professional earning 800k+ PKR/month (married with newborn) managing household budget amid inflation.*


### top bracket
> "If You're currently earning around 6 lakh PKR/month in field of IT as dev/qa and have a stable life — house, car, savings, and all basic amenities"

— [r_pakistan](https://www.reddit.com/r/pakistan/comments/1sly3yv/what_would_you_do_in_this_situation/)
*Profession: it_developer | Summary: Pakistani IT developer/QA earning 6 lakh PKR/month (~7.2M PKR/year) with stable life considering relocation to Spain.*



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