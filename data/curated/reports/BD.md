# Bangladesh (BD) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 4
- **Records with USD/yr amount:** 4
- **Average reported income (USD/yr):** $8,796- **Low-confidence records (<0.5):** 0

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 0 |
| lower_middle | 2 |
| middle | 0 |
| upper_middle | 2 |
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
| 1 | data_analyst_jobseeker | 1 |
| 2 | digital_marketer | 1 |

### middle

_No data for this bracket._

### upper_middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | it_graduate | 1 |
| 2 | remote_engineer | 1 |

### top

_No data for this bracket._


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| salary_employment | 80.0% |
| illicit_grey | 20.0% |
| business_owner | 0.0% |
| equity_compensation | 0.0% |
| freelance_contractor | 0.0% |
| government_pension | 0.0% |
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
> "I'm looking to bring on an experienced Digital Marketer (Remote | 30,000 BDT/month, but salary is negotiable based on experience)."

— [r_bangladesh](https://www.reddit.com/r/bangladesh/comments/1oyfsrt/looking_for_digital_marketer/)
*Profession: digital_marketer | Summary: Remote digital marketer role in Bangladesh advertised at 30,000 BDT/month with B2B lead-generation responsibilities.*

> "The offers I received were very low, around 20k, which makes it nearly impossible to live in those job locations, let alone help my family."

— [r_bangladesh](https://www.reddit.com/r/bangladesh/comments/1nfopbu/urgent_help/)
*Profession: data_analyst_jobseeker | Summary: Unemployed Bangladeshi entry-level data/research worker reporting available offers around 20k BDT/month, currently doing part-time writing.*


### middle bracket
_No excerpts for this bracket._

### upper_middle bracket
> "Been working remotely for ~6 months for a foreign company, making around 1.5 lakh/month. Living with family so my expenses are low — about 30k on myself + another 30k to family."

— [r_bangladesh](https://www.reddit.com/r/bangladesh/comments/1nimhdd/earning_15_lakhmonth_where_should_i_invest_my/)
*Profession: remote_engineer | Summary: Bangladeshi engineering student working remotely for a foreign company earning ~1.5 lakh BDT/month.*

> "is 147,000 BDT a good salary for someone who just graduated with an IT degree?"

— [r_bangladesh](https://www.reddit.com/r/bangladesh/comments/1l9seh0/good_salary/)
*Profession: it_graduate | Summary: Bangladesh IT graduate asking if 147,000 BDT/month is a good salary for a fresh grad.*


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