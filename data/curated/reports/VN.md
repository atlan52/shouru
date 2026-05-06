# Vietnam (VN) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 4
- **Records with USD/yr amount:** 4
- **Average reported income (USD/yr):** $16,425- **Low-confidence records (<0.5):** 0

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 1 |
| lower_middle | 0 |
| middle | 2 |
| upper_middle | 1 |
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
| 1 | online_freelancer_aspiring_coder | 1 |

### lower_middle

_No data for this bracket._

### middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | it_professional | 1 |
| 2 | service_engineer | 1 |

### upper_middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | pennywort_farmer | 1 |

### top

_No data for this bracket._


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| business_owner | 22.2% |
| freelance_contractor | 22.2% |
| salary_employment | 22.2% |
| equity_compensation | 11.1% |
| platform_gig | 11.1% |
| royalties_creator | 11.1% |
| government_pension | 0.0% |
| illicit_grey | 0.0% |
| inheritance_trust | 0.0% |
| multiple_streams | 0.0% |
| passive_investment | 0.0% |
| real_estate_rental | 0.0% |
| unknown | 0.0% |

## Narrative excerpts

### bottom bracket
> "I have around 9k saved but hope to do some online work to net an extra ~$300-$500 p/ month."

— [reddit_import](https://reddit.com/r/digitalnomad/comments/1guj1wy/thoughts_on_my_plan_for_69_months_in_da_nang/)
*Profession: online_freelancer_aspiring_coder | Summary: A US digital nomad plans to live in Da Nang, Vietnam, hoping to earn $300-$500/month from online work atop $9k savings.*


### lower_middle bracket
_No excerpts for this bracket._

### middle bracket
> "Kỹ Sư Dịch Vụ (Service Engineer) - Lương 400-800 USD"

— [vietnamworks](https://www.vietnamworks.com/ky-su-dich-vu-service-engineer-luong-400-800-usd-2045963-jv?utm_campaign_navi=2045963&utm_source_navi=specialOffers&utm_medium_navi=specialOffers)
*Profession: service_engineer | Summary: Vietnam service engineer job listing offering USD 400-800/month salary.*

> "$2500 a month let’s me live very well but I add another $500 or so for my travel out of country every 6-8 weeks for leisure... I’m in IT by trade"

— [reddit_import](https://reddit.com/r/financialindependence/comments/7trwzo/retiring_in_southeast_asia_might_be_a_lot_harder/dtf3v6h/)
*Profession: it_professional | Summary: An Australian-origin IT professional living in Vietnam describes spending around $2500/month plus travel, working in IT.*


### upper_middle bracket
> "Đổ 3 tỷ rồi trắng tay, 9X Quảng Ninh đổi hướng trồng rau má thu 50 triệu/tháng"

— [rss_vietnamnet_kinhdoanh](https://vietnamnet.vn/do-3-ty-roi-trang-tay-9x-quang-ninh-doi-huong-trong-rau-ma-thu-50-trieu-thang-2504190.html)
*Profession: pennywort_farmer | Summary: 9X Quang Ninh farmer who lost 3 billion VND pivoted to growing pennywort (rau ma) earning ~50 million VND/month.*


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