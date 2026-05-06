# Switzerland (CH) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 5
- **Records with USD/yr amount:** 5
- **Average reported income (USD/yr):** $78,057- **Low-confidence records (<0.5):** 1

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 0 |
| lower_middle | 1 |
| middle | 1 |
| upper_middle | 3 |
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
| 1 | unspecified_passive_income_recipient | 1 |

### middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | mobile_app_developer | 1 |

### upper_middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | frontend_software_developer | 1 |
| 2 | management_consultant | 1 |
| 3 | unspecified_professional | 1 |

### top

_No data for this bracket._


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| salary_employment | 50.0% |
| business_owner | 16.7% |
| passive_investment | 16.7% |
| royalties_creator | 16.7% |
| equity_compensation | 0.0% |
| freelance_contractor | 0.0% |
| government_pension | 0.0% |
| illicit_grey | 0.0% |
| inheritance_trust | 0.0% |
| multiple_streams | 0.0% |
| platform_gig | 0.0% |
| real_estate_rental | 0.0% |
| unknown | 0.0% |

## Narrative excerpts

### bottom bracket
_No excerpts for this bracket._

### lower_middle bracket
> "I do have an additional income source of around 1k USD per month, I'm honestly not sure if that's enough to live on in Pakistan."

— [r_pakistan](https://www.reddit.com/r/pakistan/comments/1qwfse8/hijrah_to_pakistan/)
*Profession: unspecified_passive_income_recipient | Summary: Pakistani-Swiss dual national living in Switzerland with ~$1k/month passive income source, planning relocation to Islamabad.*


### middle bracket
> "4 months after my initial app launch, with another 6 apps available on App Store, with only a small knowledge of iOS development, and making $4,000+ in in-app purchase and Google ads"

— [reddit_import](https://reddit.com/r/Entrepreneur/comments/199q53t/how_i_took_my_mobile_app_business_from_0_to_over/)
*Profession: mobile_app_developer | Summary: Swiss-based founder grew iOS app business to $4,000+ in 4 months via in-app purchases and ads; previously made ~$3k/mo on YouTube.*


### upper_middle bracket
> "I earn around 70k CHF in the Lausanne area as a frontend software developer. I could have negotiated a bit more but I'm at the start of my career. ... The median monthly salary is just about 6'000.-"

— [reddit_import](https://reddit.com/r/financialindependence/comments/82enog/fire_environment_in_switzerland/dv9r6x2/)
*Profession: frontend_software_developer | Summary: A frontend software developer in the Lausanne area of Switzerland earns about 70k CHF/year while supporting a family with significant rent and health-insurance costs.*

> "I took a job at a MBB consulting firm and started with a 121k salary (+up to 10% bonus). Of course this is on the high end, but most positions with large companies pay around 95k"

— [reddit_import](https://reddit.com/r/financialindependence/comments/82enog/fire_environment_in_switzerland/)
*Profession: management_consultant | Summary: An MBB management consultant in Switzerland starts at 121k salary plus up to 10% bonus, rising to ~160k after promotion.*

> "I think the 92k is correct for net income, breakdown would be something like:    Gross salary: 100k    Family allowance: ~300 x 3 x 12 = ~10.8k    Salary deductions (unemployment, retirement, social insurances): ~11k    Taxes: ~8k"

— [hackernews](https://news.ycombinator.com/item?id=24855887)
*Profession: unspecified_professional | Summary: Commenter breaks down a Swiss gross salary of 100k with family allowance and deductions yielding ~92k net.*


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