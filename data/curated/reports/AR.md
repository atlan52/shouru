# Argentina (AR) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 9
- **Records with USD/yr amount:** 8
- **Average reported income (USD/yr):** $12,264- **Low-confidence records (<0.5):** 1

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 4 |
| lower_middle | 2 |
| middle | 2 |
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
| 1 | qa_engineer | 1 |
| 2 | restaurant_worker | 1 |
| 3 | tattoo_artist | 1 |
| 4 | unspecified_worker_minimum_wage | 1 |

### lower_middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | family_business_operator_developer | 1 |
| 2 | retail_salesperson | 1 |

### middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | remote_interpreter | 1 |
| 2 | veterinarian_farm_manager | 1 |

### upper_middle

_No data for this bracket._

### top

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | tech_worker_fired | 1 |


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| salary_employment | 58.8% |
| freelance_contractor | 11.8% |
| illicit_grey | 11.8% |
| business_owner | 5.9% |
| passive_investment | 5.9% |
| real_estate_rental | 5.9% |
| equity_compensation | 0.0% |
| government_pension | 0.0% |
| inheritance_trust | 0.0% |
| multiple_streams | 0.0% |
| platform_gig | 0.0% |
| royalties_creator | 0.0% |
| unknown | 0.0% |

## Narrative excerpts

### bottom bracket
> "Estoy en negro. Cobro menos de $100mil pesos a la semana."

— [r_argentina](https://www.reddit.com/r/argentina/comments/1rmgpnz/trabajo_en_un_restaurante_hagan_sus_preguntas/)
*Profession: restaurant_worker | Summary: Argentine restaurant worker earning less than ARS 100,000/week off the books (en negro), underpaid informal employment.*

> "soy novato y estoy queriendo aprender aceptó críticas cobre 15 dólares está bien?"

— [r_argentina](https://www.reddit.com/r/argentina/comments/1r9d5in/mi_primer_tatuaje_en_realismo_soy_novato_y_estoy/)
*Profession: tattoo_artist | Summary: Novice Argentine tattoo artist charged 15 USD for their first realism tattoo, asking if it was a fair price.*

> "$ 2.000,00 (Mensual) contrato de grupo o por equipo Trabajo nocturno Para nuestro equipo de desarrollo, estamos buscando un especialista QA."

— [computrabajo_ar](https://ar.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-qa-kq-engineer-82695880-en-3-de-febrero-F4B2178F69D7F96661373E686DCF3405#lc=ListOffers-Score4-8)
*Profession: qa_engineer | Summary: Argentina QA engineer job listing offering ARS 2,000/month for testing web portals and mobile apps.*


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

> "$ 2.500.000,00 (Mensual) otro tipo de contrato Jornada completa Nos encontramos en la búsqueda de un/a Jefe de Zona para liderar la operación ganadera"

— [computrabajo_ar](https://ar.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-veterinario-o-ingeniero-zootecnista-para-trabajar-en-granja-en-la-cocha-C7AF0577E7EDAF9361373E686DCF3405#lc=ListOffers-Score4-6)
*Profession: veterinarian_farm_manager | Summary: Argentine veterinarian or zootechnics engineer job posting for farm zone manager role in Tucumán at ARS 2,500,000/month.*


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