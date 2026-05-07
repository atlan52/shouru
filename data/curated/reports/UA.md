# Ukraine (UA) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 5
- **Records with USD/yr amount:** 5
- **Average reported income (USD/yr):** $12,927- **Low-confidence records (<0.5):** 0

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 0 |
| lower_middle | 0 |
| middle | 3 |
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

_No data for this bracket._

### middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | cnc_plasma_cutting_operator | 1 |
| 2 | warehouse_loader | 1 |
| 3 | warehouse_picker_loader | 1 |

### upper_middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | concrete_mixer_truck_driver | 1 |
| 2 | software_engineer | 1 |

### top

_No data for this bracket._


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| salary_employment | 100.0% |
| business_owner | 0.0% |
| equity_compensation | 0.0% |
| freelance_contractor | 0.0% |
| government_pension | 0.0% |
| illicit_grey | 0.0% |
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
_No excerpts for this bracket._

### middle bracket
> "Вантажник 30 000 грн Вища за середню Агропродукт Харчова промисловість ; 10–50 співробітників Суми, Лебединська вулиця, 19."

— [workua](https://www.work.ua/jobs/6587995/)
*Profession: warehouse_loader | Summary: Warehouse loader job posting in Sumy, Ukraine at Agroprodukt offering 30,000 UAH/month at a flour mill.*

> "Вантажник-комплектувальник 25 000 – 26 500 грн Тексіка Оптова торгівля, дистрибуція, імпорт, експорт ; 50–250 співробітників Хмельницький"

— [workua](https://www.work.ua/jobs/6041661/)
*Profession: warehouse_picker_loader | Summary: Warehouse loader/picker job listing in Khmelnytskyi, Ukraine offering 25,000-26,500 UAH/month at a fabric wholesaler.*

> "Оператор плазмової різки з ЧПУ 30 000 – 40 000 грн BlueBird Tech ... Заробітна плата на ВТ: 30 000 грн Постійна заробітна плата: 40 000 грн + премії за виконання плану"

— [workua](https://www.work.ua/jobs/7911225/)
*Profession: cnc_plasma_cutting_operator | Summary: Job ad in Zhytomyr for a CNC plasma-cutting operator at defense-industry firm BlueBird Tech offering 30,000-40,000 UAH/month.*


### upper_middle bracket
> "Інженер-програміст 30 000 – 40 000 грн , Переглядатиметься за результатами співбесіди. Аркус Україна, ТОВ Оборонно-промисловий комплекс"

— [workua](https://www.work.ua/jobs/7469227/)
*Profession: software_engineer | Summary: Ukrainian software engineer (C/C++/Python, embedded systems) job in Kamianets-Podilskyi paying 30,000-40,000 UAH/month at defense-industry firm Arkus.*

> "Водій автобетонозмішувача (міксер) у Святопетрівське 45 000 – 90 000 грн ... Конкурентну заробітну плату — 90 000 грн на місяць."

— [workua](https://www.work.ua/jobs/5681858/)
*Profession: concrete_mixer_truck_driver | Summary: Job listing for a concrete-mixer truck driver in Sviatopetrivske, Ukraine, paying 45,000-90,000 UAH/month.*


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