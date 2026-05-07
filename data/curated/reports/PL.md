# Poland (PL) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 8
- **Records with USD/yr amount:** 5
- **Average reported income (USD/yr):** $80,796- **Low-confidence records (<0.5):** 0

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 0 |
| lower_middle | 3 |
| middle | 1 |
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

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | average_worker | 1 |
| 2 | student_worker | 1 |
| 3 | unspecified_worker | 1 |

### middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | mobile_app_entrepreneur | 1 |

### upper_middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | air_traffic_controller | 1 |
| 2 | overemployed_software_engineer | 1 |

### top

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | plumber | 1 |
| 2 | saas_app_co_founder | 1 |


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| salary_employment | 50.0% |
| business_owner | 16.7% |
| multiple_streams | 16.7% |
| freelance_contractor | 8.3% |
| illicit_grey | 8.3% |
| equity_compensation | 0.0% |
| government_pension | 0.0% |
| inheritance_trust | 0.0% |
| passive_investment | 0.0% |
| platform_gig | 0.0% |
| real_estate_rental | 0.0% |
| royalties_creator | 0.0% |
| unknown | 0.0% |

## Narrative excerpts

### bottom bracket
_No excerpts for this bracket._

### lower_middle bracket
> "Studenci w Polsce zarabiają średnio 4,1 zł netto miesięcznie, jednak za satysfakcjonujący poziom wynagrodzenia uznaliby 9,9 zł na rękę"

— [forsal](https://forsal.pl/praca/wynagrodzenia/artykuly/11242365,ile-zarabia-student-w-polsce-roznica-z-oczekiwaniami-jest-ogromna.html)
*Profession: student_worker | Summary: Polish article reporting average student earnings of 4,100 PLN net/month in 2025-2026, with salary expectations of 9,900 PLN net.*

> "Żeby być uznawanym w Polsce za klasę średnią wystarczy zarabiać ok. 4 tys. zł na rękę. To niewiele więcej niż płaca minimalna."

— [wykop](https://wykop.pl/link/7917425/kryzys-normalsow-polskie-bogactwo-kredyt-leasing-i-scam)
*Profession: average_worker | Summary: Polish commentary noting that earning ~4000 PLN net/month is considered middle class in Poland, barely above minimum wage.*

> "myślę, że w tym przypadku mogę rozsądnie rzuć na start to 16kPLN brutto na UOP i nie będzie to przesadzone? Nie jestem zorientowany bo wynajmuję pokój, żyję jak szczur i zarabiam znacznie mniej"

— [wykop](https://wykop.pl/wpis/85507591/zaraz-powrot-do-wscibskiej-rodziny-na-swieta-wiec-)
*Profession: unspecified_worker | Summary: Polish worker earning less than an estimated 16,000 PLN gross/month, renting a room and unable to afford house construction.*


### middle bracket
> "My story: mobile app(s), quite a bit of traction (over 1M downloads), pretty solid plans for rapid and rather inexpensive growth. Enough revenue to support my family, but at least a few months away from that growth."

— [hackernews](https://news.ycombinator.com/item?id=8379370)
*Profession: mobile_app_entrepreneur | Summary: Mobile app developer entrepreneur with 1M+ downloads earns enough revenue to support his family while choosing between accelerator programs (Berlin/Helsinki).*


### upper_middle bracket
> "Do 20 tys. zł bez studiów. PAŻP ruszyło z nową rekrutacją i kusi konkretną kasą na start można wyciągnąć nawet 20 tys. zł brutto."

— [wykop](https://wykop.pl/link/7921317/do-20-tys-zl-bez-studiow-pazp-szuka-kandydatow-na-kontrolerow-ruchu-lotniczego)
*Profession: air_traffic_controller | Summary: Polish air traffic controller recruitment article, PAŻP offering up to 20,000 PLN gross/month, no university degree required.*

> "after my first double paycheck that I realize how awesome making over 12 times median earnings in my country feels."

— [reddit_import](https://reddit.com/r/overemployed/comments/virw7w/my_oe_journey/)
*Profession: overemployed_software_engineer | Summary: Software engineer running two jobs simultaneously now earns over 12x median earnings in his country, on track to pay off mortgage early.*


### top bracket
> "Now, after over five years, our average monthly revenue is around 20,000€ levels... The first month we made over 15,000€ in revenue because of ProductHunt"

— [reddit_import](https://reddit.com/r/Entrepreneur/comments/mhvryf/turning_a_small_app_into_a_20000mo_business/)
*Profession: saas_app_co_founder | Summary: A Polish full-stack developer co-founded FreeYourMusic which now averages around €20,000/month in revenue, allowing the founders to quit their day jobs.*

> "Hydraulik zarabia 20k miesięcznie? Ależ to zabolało Polaków Ile powinien zarabiać pracownik fizyczny? Połowa Polaków uważa, że uczciwa płaca za pełny etat pracy fizycznej nie powinna przekraczać 6,5 tys. zł."

— [wykop](https://wykop.pl/link/7834585/hydraulik-zarabia-20k-miesiecznie-alez-to-zabolalo-polakow)
*Profession: plumber | Summary: News-link discussion about a Polish plumber reportedly earning 20k PLN/month, contrasted with the public's view that fair pay shouldn't exceed 6.5k PLN.*



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