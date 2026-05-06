# Philippines (PH) — Income & Earning Mechanism Report

## Overview

- **Total samples:** 9
- **Records with USD/yr amount:** 5
- **Average reported income (USD/yr):** $3,486- **Low-confidence records (<0.5):** 1

## Bracket distribution

| Bracket | Records |
| --- | ---: |
| bottom | 2 |
| lower_middle | 3 |
| middle | 2 |
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

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | family_household_helpers | 1 |
| 2 | philippines_virtual_assistant | 1 |

### lower_middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | aerospace_it_specialist | 1 |
| 2 | government_employee_salary_grade_1 | 1 |
| 3 | teacher_or_engineer | 1 |

### middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | retired_factory_worker_pensioner | 1 |
| 2 | virtual_assistant | 1 |

### upper_middle

| # | Profession | Records |
| ---: | --- | ---: |
| 1 | digital_nomad_worker | 1 |
| 2 | early_retired_tech_worker | 1 |

### top

_No data for this bracket._


## Earning mechanism share

| Mechanism | Share |
| --- | ---: |
| salary_employment | 60.0% |
| freelance_contractor | 20.0% |
| business_owner | 6.7% |
| government_pension | 6.7% |
| passive_investment | 6.7% |
| equity_compensation | 0.0% |
| illicit_grey | 0.0% |
| inheritance_trust | 0.0% |
| multiple_streams | 0.0% |
| platform_gig | 0.0% |
| real_estate_rental | 0.0% |
| royalties_creator | 0.0% |
| unknown | 0.0% |

## Narrative excerpts

### bottom bracket
> "For less than $2/hr and 40hr a week I get an employee who will work diligently and intelligently to accomplish a myriad of tasks for my business."

— [reddit_import](https://reddit.com/r/Entrepreneur/comments/edt40x/how_i_learned_to_scale_my_business_fast/)
*Profession: philippines_virtual_assistant | Summary: Filipino remote workers hired by the author earn under $2/hr for 40-hour weeks doing tasks like web design, accounting, and video editing.*

> "I only have one sibling who is working and is earning $160/month. Once my working sibling gets off of her 'trial' period in work, she earns ~$560."

— [reddit_import](https://reddit.com/r/personalfinance/comments/678s0i/ph_my_dads_house_is_being_taken_away_this_july/)
*Profession: family_household_helpers | Summary: A Filipino college student does freelance writing while a working sibling earns roughly $160/month (rising to ~$560 after probation) to support the family.*


### lower_middle bracket
> "makakatanggap ang isang Salary Grade 1 na empleyado ng dagdag na P573 kada buwan, mula P14,061 hanggang P14,634."

— [r_philippines](https://www.reddit.com/r/Philippines/comments/1q1ufg8/taassahod_sa_mga_govt_employees_ayon_sa_executive/)
*Profession: government_employee_salary_grade_1 | Summary: Philippines Salary Grade 1 government employee receiving PHP 14,634/month after the EO 64 raise.*

> "mostly sweldo ng mga guro at engineers eh nasa 15-18k lang."

— [r_philippines](https://www.reddit.com/r/Philippines/comments/1slb54h/high_quality_education_buildings_gusto_pero_sahod/)
*Profession: teacher_or_engineer | Summary: Philippine commentary citing teachers and engineers earning only PHP 15-18k/month for skilled licensed work.*

> "It’s in the field of Space, I get to practice my IT skills... it pays above the normal starting rate for a fresh grad employee... I also accept part time works from friends"

— [reddit_import](https://reddit.com/r/digitalnomad/comments/gqixqa/my_almost_digital_nomad_life/)
*Profession: aerospace_it_specialist | Summary: 21-year-old fresh aerospace/IT graduate works a project-based 9-5 in space-related IT paid above the normal fresh-grad starting rate, with side part-time gigs.*


### middle bracket
> "My factory closed when I was 49. I had 30 years in but not nearly enough money saved for long term... Instead, I retired and moved to the Philippines. The value of my pension doubled or maybe even tripled overnight from the exchange rate."

— [reddit_import](https://reddit.com/r/personalfinance/comments/2zwy4f/lost_my_job_2_years_ago_today_probably_one_of_the/cpndcps/)
*Profession: retired_factory_worker_pensioner | Summary: A 49-year-old retired factory worker moved to the Philippines where their pension's purchasing power doubled or tripled due to exchange rates.*

> "What's the cost of a full time VA?** Approx $400/month, $2.5/hour (plus bonuses -- it helps to incentivize!)."

— [reddit_import](https://reddit.com/r/smallbusiness/comments/6iwc8u/crucial_answers_you_should_know_before_hiring_a/)
*Profession: virtual_assistant | Summary: A virtual assistant typically earns about $400/month or $2.50/hour working full-time for an outsourcing client.*


### upper_middle bracket
> "NW increased from $1.1M → $1.3M ... $3,500-$4,000 monthly budget for the past 3 months ... I was really nervous about quitting my well-paying job and moving back to SE Asia"

— [reddit_import](https://reddit.com/r/leanfire/comments/1mp5jd5/update_34m_11_nw_ready_to_pull_the_trigger_would/)
*Profession: early_retired_tech_worker | Summary: A 34-year-old American expat living in Manila reports a $1.3M net worth funding a $3.5-4k/month lifestyle on roughly 3-3.5% safe withdrawal rate after leaving a well-paying US job.*

> "I'm a full time (Mon-Fri, 9-5) digital worker for a company based outside the Philippines. I get paid in the currency of the country that my company is based in, which is very strong against the Filipino peso."

— [reddit_import](https://reddit.com/r/digitalnomad/comments/1af5k1e/my_definitive_review_of_the_philippines_as_a/)
*Profession: digital_nomad_worker | Summary: Digital nomad based in Cebu working remote for foreign company; spends ~$220-280/week on living expenses.*


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