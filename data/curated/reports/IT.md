# Italy (IT) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 7
- **Records with USD/yr amount:** 5
- **Average reported income (USD/yr):** $42,021- **Low-confidence records (<0.5):** 0

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 1 |
| lower_middle | 0 |
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

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | chef_apprentice | 1 |

### lower_middle

_No data for this bracket._

### middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | eu_funds_project_manager | 1 |
| 2 | seasonal_hotel_owner_manager | 1 |
| 3 | serial_entrepreneur_saas_founder | 1 |

### upper_middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | professional_relocating_to_italy | 1 |

### top

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | freelance_data_scientist | 1 |
| 2 | software_developer_overemployed | 1 |


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| salary_employment | 46.2% |
| business_owner | 15.4% |
| multiple_streams | 15.4% |
| freelance_contractor | 7.7% |
| illicit_grey | 7.7% |
| real_estate_rental | 7.7% |
| equity_compensation | 0.0% |
| government_pension | 0.0% |
| inheritance_trust | 0.0% |
| passive_investment | 0.0% |
| platform_gig | 0.0% |
| royalties_creator | 0.0% |
| unknown | 0.0% |

## Narrative excerpts

### bottom bracket
> "I've been screwed out of payment by kitchen/hotel owners after providing my service, yes... which is why I retired for the 2nd time after losing 3 months of payment in my last gig in Italy"

— [hackernews](https://news.ycombinator.com/item?id=25987011)
*Profession: chef_apprentice | Summary: Cook recounts being unpaid for 3 months at a final Italy gig and previously screwed out of pay; alongside a barman in his 50s working 6 months unpaid.*


### lower_middle bracket
_No excerpts for this bracket._

### middle bracket
> "my partner own an apartment in Milan that she rents for 1000€/month (net around 600). We both have project management jobs (EU funds)"

— [reddit_import](https://reddit.com/r/leanfire/comments/1q07p0k/barista_lean_in_italy_help/)
*Profession: eu_funds_project_manager | Summary: An Italian couple working EU-funded project management jobs plan barista FIRE supplemented by a Milan apartment renting for ~1000 EUR/month.*

> "Small Seasonal Hotel owner here. So here's my issue, we have a seasonal hotel that currently employes 18 people over the summer (March to October). I took over as a manager 3 years ago"

— [reddit_import](https://reddit.com/r/smallbusiness/comments/1n5jfcu/how_do_i_address_my_team_about_excessive_overtime/)
*Profession: seasonal_hotel_owner_manager | Summary: A small seasonal hotel owner-manager in Europe describes managing a 18-employee staff including paid housekeepers earning overtime pay above minimum wage.*

> "In 2015, I had a SaaS pulling in $2K MRR, could've blown it up... In 2017, we dropped a delivery app, 80K users, $60K MRR."

— [reddit_import](https://reddit.com/r/Entrepreneur/comments/1ng0an0/10_fckups_in_15_years_my_startup_survival_guide/)
*Profession: serial_entrepreneur_saas_founder | Summary: A serial entrepreneur reflects on 15 years building products, mentioning a SaaS at $2K MRR and a delivery app that hit $60K MRR before failing.*


### upper_middle bracket
> "I will likely be moving to Italy soon for a new role (ca. €60k starting salary)"

— [r_ukpersonalfinance](https://www.reddit.com/r/UKPersonalFinance/comments/1s3hg1q/uk_vs_italy_state_pension_worth_reaching_10_years/)
*Profession: professional_relocating_to_italy | Summary: 31-year-old Italian citizen moving from UK to Italy for a new role with ca. €60k starting salary.*


### top bracket
> "It was a good job, as a Senior Data Scientist, in a US company, working from Italy. I was paid well above the Italian average. I had stocks and bonuses, private medical insurance and various benefits I never used. Overall, I made more than €100k in 2022"

— [hackernews](https://news.ycombinator.com/item?id=38813381)
*Profession: freelance_data_scientist | Summary: A Senior Data Scientist working from Italy for a US company earned over EUR 100k in 2022 before going freelance.*

> "I have a job which required 7+ years experience for both j1 and j2, yet I only have 2. J2 is as a consultant as a FAANG company ... My new j1 however ... It pays alot though - twice as much as my FAANG company."

— [reddit_import](https://reddit.com/r/overemployed/comments/10egeuf/not_only_am_i_grossly_overemployed_but_im_also/)
*Profession: software_developer_overemployed | Summary: An underqualified developer holds two jobs (FAANG consultant and a startup) where the startup pays twice as much as the FAANG role.*



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