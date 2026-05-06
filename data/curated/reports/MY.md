# Malaysia (MY) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 4
- **Records with USD/yr amount:** 3
- **Average reported income (USD/yr):** $256,557- **Low-confidence records (<0.5):** 1

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 0 |
| lower_middle | 0 |
| middle | 0 |
| upper_middle | 2 |
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
| 1 | csgo_skin_trader | 1 |
| 2 | tenured_academic_clinician | 1 |

### top

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | investment_banker | 1 |
| 2 | vape_ecommerce_founder | 1 |


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| salary_employment | 50.0% |
| business_owner | 25.0% |
| passive_investment | 12.5% |
| platform_gig | 12.5% |
| equity_compensation | 0.0% |
| freelance_contractor | 0.0% |
| government_pension | 0.0% |
| illicit_grey | 0.0% |
| inheritance_trust | 0.0% |
| multiple_streams | 0.0% |
| real_estate_rental | 0.0% |
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
> "I earn 104k annually, which might sound like a lot, but this is in Malaysian Ringgit (MYR), not USD. Chiefly disgruntled because when you compare salaries dollar by dollar, this equates to just under usd 25k."

— [reddit_import](https://reddit.com/r/financialindependence/comments/c0xg98/grass_is_greener_syndrome_discontented/)
*Profession: tenured_academic_clinician | Summary: An early-30s tenured academic in Malaysia earns MYR 104k/yr (~USD 25k) and saves 40-45% of take-home, lamenting weak currency vs Western peers.*

> "Im a 16 Year old living in Malaysia ... I trade online in a virtual economy known as CS:GO on a platform called Steam. I have been making about about 150 usd every 1-2 days and btw i am payed in bitcoin"

— [reddit_import](https://reddit.com/r/personalfinance/comments/3zeq86/16_year_old_making_2250month_need_suggestions/)
*Profession: csgo_skin_trader | Summary: 16-year-old in Malaysia earns about $2,250/month trading CS:GO skins on Steam, paid in bitcoin.*


### top bracket
> "32/m here earning a healthy number by US standards per annum in KL. Working in investment banking. Current networth excluding my condo is just over 100k USD ... Started my career on 3k salary"

— [reddit_import](https://reddit.com/r/financialindependence/comments/930ozg/any_fellow_third_world_citizens_trying_to_reach/e39xo8l/)
*Profession: investment_banker | Summary: 32-year-old Malaysian investment banker in KL earns a healthy US-standard salary, started at MYR 3k/month, now pulling MYR 4k/month net passive income.*

> "We do about USD60,000 in revenue per month right now - which is a hella lot of money for typical Malaysians."

— [reddit_import](https://reddit.com/r/Entrepreneur/comments/cqrshe/60kmonth_selling_vape_juice/)
*Profession: vape_ecommerce_founder | Summary: A Malaysian entrepreneur runs Vape Club, an e-liquid ecommerce business, generating about USD 60,000 in revenue per month.*



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