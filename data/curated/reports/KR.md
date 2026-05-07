# South Korea (KR) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 2
- **Records with USD/yr amount:** 2
- **Average reported income (USD/yr):** $109,800- **Low-confidence records (<0.5):** 1

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 0 |
| lower_middle | 0 |
| middle | 1 |
| upper_middle | 0 |
| top | 1 |

## Bracket thresholds (USD/yr lower bound)

| Bracket | Lower bound (USD/yr) |
| --- | ---: |
| bottom | $0 |
| lower_middle | $18,000 |
| middle | $32,000 |
| upper_middle | $65,000 |
| top | $200,000 |

## Top professions per bracket

### bottom

_No data for this bracket._

### lower_middle

_No data for this bracket._

### middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | real_estate_auction_investor | 1 |

### upper_middle

_No data for this bracket._

### top

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | unknown_high_earner | 1 |


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| salary_employment | 66.7% |
| passive_investment | 33.3% |
| business_owner | 0.0% |
| equity_compensation | 0.0% |
| freelance_contractor | 0.0% |
| government_pension | 0.0% |
| illicit_grey | 0.0% |
| inheritance_trust | 0.0% |
| multiple_streams | 0.0% |
| platform_gig | 0.0% |
| real_estate_rental | 0.0% |
| royalties_creator | 0.0% |
| unknown | 0.0% |

## Narrative excerpts

### bottom bracket
_No excerpts for this bracket._

### lower_middle bracket
_No excerpts for this bracket._

### middle bracket
> "종잣돈이 없어서 마이너스 통장 열고 2000만원으로 시작했죠. (경매로 낙찰받은 세 채를 매도한 뒤) 모든 수익을 합치니 연봉 1억원을 넘어섰어요."

— [rss_chosun_economy](https://www.chosun.com/economy/realty/investment_trends/2026/05/06/MU4TMOLDHBSTKMJXGY3TOMRXMQ/)
*Profession: real_estate_auction_investor | Summary: Korean real estate auction beginner who started with 20M KRW credit and reportedly cleared 100M KRW (annual-equivalent) profit after selling three auctioned properties.*


### upper_middle bracket
_No excerpts for this bracket._

### top bracket
> "두쫀쿠 연봉 2억은댈듯 ㄹㅇ"

— [dcinside](https://gall.dcinside.com/board/view/?id=foreversingle&no=5391)
*Profession: unknown_high_earner | Summary: Korean dcinside post speculating someone (nicknamed 두쫀쿠) earns roughly 200 million KRW/year salary.*



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