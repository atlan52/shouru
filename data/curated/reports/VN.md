# Vietnam (VN) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 6
- **Records with USD/yr amount:** 6
- **Average reported income (USD/yr):** $15,572- **Low-confidence records (<0.5):** 0

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 1 |
| lower_middle | 0 |
| middle | 4 |
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
| 1 | business_development_executive | 1 |
| 2 | civil_engineer | 1 |
| 3 | it_professional | 1 |
| 4 | service_engineer | 1 |

### upper_middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | pennywort_farmer | 1 |

### top

_No data for this bracket._


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| salary_employment | 46.2% |
| business_owner | 15.4% |
| freelance_contractor | 15.4% |
| equity_compensation | 7.7% |
| platform_gig | 7.7% |
| royalties_creator | 7.7% |
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

> "đội ngũ kỹ sư có thu nhập từ 30 - 55 triệu đồng/tháng (tùy vị trí); công nhân có thu nhập 22 - 29 triệu đồng/tháng"

— [rss_vietnamnet_kinhdoanh](https://vietnamnet.vn/tong-thau-duong-sat-cao-toc-ha-tang-cua-vingroup-tuyen-dung-25-000-nhan-su-2497303.html)
*Profession: civil_engineer | Summary: Vietnamese construction engineers at SGC earning 30-55 million VND/month on major infrastructure projects.*

> "Business Development Executive (Bất Động Sản/ Tòa Nhà/ Quảng Cáo Từ 12–20Tr/tháng + Hoa Hồng + Thưởng)"

— [vietnamworks](https://www.vietnamworks.com/business-development-executive-bat-dong-san-toa-nha-quang-cao-tu-12-20tr-thang-hoa-hong-thuong-2036695-jv)
*Profession: business_development_executive | Summary: Business development executive role in Vietnam's real estate/advertising sector offering 12-20M VND/month plus commission and bonuses.*


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