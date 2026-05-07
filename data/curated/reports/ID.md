# Indonesia (ID) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 6
- **Records with USD/yr amount:** 4
- **Average reported income (USD/yr):** $120,846- **Low-confidence records (<0.5):** 0

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 0 |
| lower_middle | 2 |
| middle | 1 |
| upper_middle | 2 |
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

_No data for this bracket._

### lower_middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | bank_back_office_staff | 1 |
| 2 | dive_instructor | 1 |

### middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | online_motorcycle_taxi_driver | 1 |

### upper_middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | crypto_day_trader | 1 |
| 2 | saas_sales_copywriter | 1 |

### top

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | productized_design_service_founder | 1 |


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| business_owner | 25.0% |
| salary_employment | 25.0% |
| freelance_contractor | 12.5% |
| multiple_streams | 12.5% |
| passive_investment | 12.5% |
| platform_gig | 12.5% |
| equity_compensation | 0.0% |
| government_pension | 0.0% |
| illicit_grey | 0.0% |
| inheritance_trust | 0.0% |
| real_estate_rental | 0.0% |
| royalties_creator | 0.0% |
| unknown | 0.0% |

## Narrative excerpts

### bottom bracket
_No excerpts for this bracket._

### lower_middle bracket
> "I knew the owners of the resort and told them to just give my salary (not much about $900 a month) to the local staff."

— [reddit_import](https://reddit.com/r/financialindependence/comments/y76g2f/two_year_fire_update_breakdown_of_my_budget/)
*Profession: dive_instructor | Summary: A FIRE retiree from US working as a dive instructor at an Indonesian resort earns about $900/month, which he donates to local staff.*

> "Saya sekarang kerja di bank besar, bagian back office urus data dan mainan Microsoft Office... Gaji juga ga nyampe 2 digit jadi belum bisa coping kalau gue bisa pensiun dini atau semacamnya."

— [r_indonesia](https://www.reddit.com/r/indonesia/comments/1ofl3y3/pekerjaan_yang_work_life_balance_nya_lebih_baik/)
*Profession: bank_back_office_staff | Summary: Jakarta-area bank back-office worker on single-digit-million IDR/month salary working long hours and weekend overtime.*


### middle bracket
> "mitra Grab Indonesia bisa mendapat penghasilan hingga Rp 10 juta/bulan. Asalkan, untuk roda dua, harus mengambil setidaknya 28 orderan sehari. Sedangkan roda empat mengambil 11 orderan sehari."

— [detik](https://oto.detik.com/motor/d-8377781/biar-dapet-rp-10-juta-bulan-ojol-harus-ambil-berapa-orderan)
*Profession: online_motorcycle_taxi_driver | Summary: Indonesian Grab ojol two-wheel drivers can earn over Rp 10 million/month (~Rp 120M/year) by taking ~28 orders/day full time.*


### upper_middle bracket
> "I'm a SaaS sales copywriter and, sure, I've ticked the cliché boxes (five-figure months, live in Bali etc.)"

— [reddit_import](https://reddit.com/r/digitalnomad/comments/l9fa67/what_are_the_holy_grail_jobs_for_digital_nomads/glibokw/)
*Profession: saas_sales_copywriter | Summary: A SaaS sales copywriter living in Bali earns five-figure months as a digital nomad.*

> "I closed my e-com store (too many negative emotions attached to it) and started leverage trading bitcoin (on Bitmex)... I was averaging $200-$300 days which is incredible for a noob."

— [reddit_import](https://reddit.com/r/financialindependence/comments/blzmtb/the_dark_side_of_fire_that_almost_broke_me/)
*Profession: crypto_day_trader | Summary: After FIRE-ing from a high-paid corporate job, the author moved to Bali and earned about $200–$300/day leverage trading bitcoin alongside other side hustles.*


### top bracket
> "We went from 0 to $400,000 in revenue in 12 months, with a 25% profit margin (after paying ourselves salaries). More than 80+ designers got full-time, stable income this year!"

— [reddit_import](https://reddit.com/r/Entrepreneur/comments/a55q3r/we_are_one_year_in_business_today_our_highs_and/)
*Profession: productized_design_service_founder | Summary: Founder built a productized design subscription service from Indonesia that did $400k revenue in year one with 25% margin and employs 80+ designers.*



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