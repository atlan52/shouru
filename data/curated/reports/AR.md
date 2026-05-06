# Argentina (AR) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 5
- **Records with USD/yr amount:** 5
- **Average reported income (USD/yr):** $12,175- **Low-confidence records (<0.5):** 1

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 1 |
| lower_middle | 2 |
| middle | 1 |
| upper_middle | 0 |
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
| 1 | unspecified_worker_minimum_wage | 1 |

### lower_middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | family_business_operator_developer | 1 |
| 2 | retail_salesperson | 1 |

### middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | remote_interpreter | 1 |

### upper_middle

_No data for this bracket._

### top

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | tech_worker_fired | 1 |


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| salary_employment | 58.3% |
| business_owner | 8.3% |
| freelance_contractor | 8.3% |
| illicit_grey | 8.3% |
| passive_investment | 8.3% |
| real_estate_rental | 8.3% |
| equity_compensation | 0.0% |
| government_pension | 0.0% |
| inheritance_trust | 0.0% |
| multiple_streams | 0.0% |
| platform_gig | 0.0% |
| royalties_creator | 0.0% |
| unknown | 0.0% |

## Narrative excerpts

### bottom bracket
> "En el trabajo empezaron a tratarme mal, solo porque el jefe quería meter a su hijo en mi puesto, así que intentó de todo para hacerme renunciar, pero no lo logró, aunque si me terminó bajando el sueldo al mínimo legal."

— [r_argentina](https://www.reddit.com/r/argentina/comments/1mlc49c/un_simple_desahogo/)
*Profession: unspecified_worker_minimum_wage | Summary: Argentine worker in La Matanza whose boss reduced his salary to the legal minimum wage, struggling to pay rent.*


### lower_middle bracket
> "Soy vendedor en una casa de comercio pero quiero cambiar de trabajo, gano 1M neto no tenemos extras por comisiones"

— [r_argentina](https://www.reddit.com/r/argentina/comments/1q5zr7s/cual_es_su_sueldo_como_vendedor_del_comercio/)
*Profession: retail_salesperson | Summary: Argentine retail salesperson earning ARS 1M/month net with no commissions, considering moving to bigger chain stores.*

> "Hoy entre las dos se factura +200k usd/mes ... Yo quedé como “comodín” en ambas ... aun así yo vivo con ~1000 usd/mes"

— [r_argentina](https://www.reddit.com/r/argentina/comments/1qx3fts/update_gracias_post_del_local_decisión_sueldo/)
*Profession: family_business_operator_developer | Summary: 22-year-old Argentine programmer/operations lead across two family companies (combined revenue >USD 200k/month) personally drawing only ~USD 1000/month.*


### middle bracket
> "Mis ingresos son bastante pocos, fluctúan entre 800/1000 usd por mes, realizados en dos pagos quincenales."

— [r_argentina](https://www.reddit.com/r/argentina/comments/1pttkgv/necesito_ayuda_con_wallets_en_usd/)
*Profession: remote_interpreter | Summary: Argentine remote interpreter paid via Deel, earning roughly USD 800-1000/month in two biweekly payments.*


### upper_middle bracket
_No excerpts for this bracket._

### top bracket
> "Cost of living is much lower in Argentina, so my savings rate has been high; some well paid tech jobs, early compounding and the bull market made me pretty much FIRE accidentally."

— [reddit_import](https://reddit.com/r/financialindependence/comments/vfr3zo/daily_fi_discussion_thread_sunday_june_19_2022/icyqz4t/)
*Profession: tech_worker_fired | Summary: A northern European living in Argentina accidentally became FIRE through well-paid tech jobs and a tech-heavy stock portfolio.*



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