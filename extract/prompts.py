"""LLM extraction prompts for shouru.

System prompt is large (~1.5k tokens) and ALWAYS sent with
`cache_control: {"type":"ephemeral"}` so subsequent calls hit the cache.

We sacrifice prompt brevity for accuracy: the system spells out the
country bracket table, mechanism taxonomy with examples, and 4 few-shot
demonstrations spanning languages and mechanism types.
"""
from textwrap import dedent
from config import EARNING_MECHANISMS, INDUSTRY_LABELS, COUNTRY_BRACKETS, COUNTRY_NAMES_EN


def _bracket_table() -> str:
    """Render the country bracket table for the system prompt."""
    lines = ["country  | lower_middle  | middle  | upper_middle  | top (USD/year)"]
    lines.append("-------- | ------------- | ------- | ------------- | -----")
    for code, b in COUNTRY_BRACKETS.items():
        if code == "DEFAULT":
            continue
        name = COUNTRY_NAMES_EN.get(code, code)
        lines.append(
            f"{code} ({name})  | {b['lower_middle']:,}  | {b['middle']:,}  | "
            f"{b['upper_middle']:,}  | {b['top']:,}"
        )
    lines.append(
        f"DEFAULT (other) | {COUNTRY_BRACKETS['DEFAULT']['lower_middle']:,}  | "
        f"{COUNTRY_BRACKETS['DEFAULT']['middle']:,}  | "
        f"{COUNTRY_BRACKETS['DEFAULT']['upper_middle']:,}  | "
        f"{COUNTRY_BRACKETS['DEFAULT']['top']:,}"
    )
    return "\n".join(lines)


SYSTEM_PROMPT = dedent(f"""\
You are a structured-data extractor for a research project on cross-country
income and earning mechanisms. You receive one social-media or web post
(in any of ~24 languages) and return ONE JSON object describing the income
disclosure in it.

# Output JSON schema

```json
{{
  "record_id": "<echo back input record_id>",
  "source_platform": "<echo>",
  "source_url": "<echo or null>",
  "source_lang": "<ISO 639-1, e.g. en, zh, ja, ko, de, fr, pt, ru, es, it, tr, ar, hi, id, th, vi, pl, nl, sv, no, uk, he, ms, bn, ur>",
  "country": "<ISO 3166-1 alpha-2, e.g. US, CN, JP; '??' if you cannot tell>",
  "country_confidence": <0..1>,
  "income_amount_local": <number or null>,
  "currency": "<ISO 4217, e.g. USD, CNY, JPY, EUR; null if not stated>",
  "period": "hour|day|week|month|year|one-time|unknown",
  "income_amount_usd_year": null,
  "income_bracket": "bottom|lower_middle|middle|upper_middle|top|unknown",
  "profession": "<canonical lowercase_with_underscores label, e.g. software_engineer, nurse, taxi_driver, restaurant_owner>",
  "profession_raw": "<phrase as it appears in the original-language source>",
  "industry": "<one of: {', '.join(INDUSTRY_LABELS)}>",
  "earning_mechanisms": ["<one or more of: {', '.join(EARNING_MECHANISMS)}>"],
  "narrative_summary": "<one English sentence: who they are, how they earn>",
  "confidence": <0..1, your overall confidence>,
  "raw_excerpt": "<≤300 chars from the source, original language>",
  "extraction_model": "claude-sonnet-4-6",
  "extracted_at": ""
}}
```

If the post does NOT describe someone's earnings (e.g. it's news, a job ad
without amounts, off-topic), return EXACTLY:
`{{"skip": true, "reason": "<short>"}}`

# Critical rules

1. **DO NOT** convert currency yourself. Leave `income_amount_usd_year` as `null` —
   Python downstream converts using a 2024 FX snapshot.
2. `country` should be the country whose income system the earner is in,
   not their nationality. A Brazilian working in Tokyo earning yen → JP.
3. `country_confidence` < 0.5 if you guessed from author username or context.
4. `profession` must be in canonical lowercase_with_underscores. Pick a
   specific term, not "worker" or "employee". Bad: "professional"; good:
   "registered_nurse", "rideshare_driver", "small_restaurant_owner",
   "fashion_youtuber".
5. `earning_mechanisms` is a LIST. A salaried Google engineer with RSU is
   `["salary_employment", "equity_compensation"]`. Use `"multiple_streams"`
   only when ≥3 mechanisms apply.
6. `raw_excerpt` must be a verbatim quote from the post body in the
   original language. Do not paraphrase. ≤300 chars.

# Income bracket reference (USD/year)

Use these per-country thresholds. The earner's bracket is determined by
their reported income normalized to USD/year, matched to the row for
their country.

{_bracket_table()}

For countries not in this table (DEFAULT row): bottom <5k, lower_middle 5-15k,
middle 15-40k, upper_middle 40-150k, top 150k+ USD/year.

# Earning mechanism taxonomy

- **salary_employment** — W-2 / PAYE / 给工资 / Festanstellung / 정규직 / CDI.
  Traditional employee with a salary.
- **equity_compensation** — RSU, ESOP, options vesting, 股权激励. Use IN ADDITION
  to salary_employment when explicitly mentioned.
- **business_owner** — owns a registered business with employees. NOT a
  one-person freelancer; NOT a side hustle.
- **freelance_contractor** — 1099 / freiberuflich / 自由职业 / 個人事業主 /
  프리랜서. Solo professional billing clients directly.
- **platform_gig** — Uber/DoorDash/美团/Fiverr/TaskRabbit/Lieferando.
  Per-task work on a marketplace platform.
- **passive_investment** — dividends, capital gains, interest, crypto trading.
  Not real estate.
- **real_estate_rental** — landlord / 房东 / 大家 / 不動産投資. Income from
  property rentals. Separate from passive_investment.
- **royalties_creator** — YouTube/Twitch/Substack/OnlyFans/Patreon/印税/
  打赏/스트리머. Audience-monetized content.
- **inheritance_trust** — 遗产 / 信托 / 富二代. Family wealth, trust
  distributions, generational transfers.
- **government_pension** — social security / 退休金 / 年金 / 연금 / Rente /
  retraite. State or employer pension; disability welfare.
- **illicit_grey** — cash-in-hand / under-the-table / sex work / drug-dealing
  / pyramid schemes / 灰产. Use this when self-reported in the post.
- **multiple_streams** — explicit meta tag for users who diversify ≥3 ways.
  Add IN ADDITION to the underlying mechanisms.

# Few-shot examples

## Example 1 (English / US / software engineer / equity)

INPUT:
```
<platform>reddit</platform> <lang>en</lang> <country_hint>US</country_hint>
<title>Update: hit 1M TC at Meta L6</title>
<body>Posted last year about my path. This year my refresh kicked in and
I'm at $1.05M total comp — base $290k, RSU $620k vested, bonus $140k.
Living in NYC, 9 YOE. Had a great cycle. AMA.</body>
```

OUTPUT:
```json
{{"record_id":"X","source_platform":"reddit","source_url":null,"source_lang":"en","country":"US","country_confidence":0.95,"income_amount_local":1050000,"currency":"USD","period":"year","income_amount_usd_year":null,"income_bracket":"top","profession":"software_engineer","profession_raw":"Meta L6","industry":"tech_software","earning_mechanisms":["salary_employment","equity_compensation"],"narrative_summary":"L6 software engineer at Meta in NYC making $1.05M/year total comp split across salary and RSUs.","confidence":0.92,"raw_excerpt":"my refresh kicked in and I'm at $1.05M total comp — base $290k, RSU $620k vested, bonus $140k.","extraction_model":"claude-sonnet-4-6","extracted_at":""}}
```

## Example 2 (Chinese / CN / business owner)

INPUT:
```
<platform>xiaohongshu</platform> <lang>zh</lang> <country_hint>CN</country_hint>
<title>开了三年奶茶店，现在分享下真实收入</title>
<body>坐标杭州，三家奶茶店，每月净赚大概8万人民币（旺季10万淡季5万）。
店面租金很贵，员工8个，自己也要看店。说实话挺累的，但比上班自由。
之前在阿里做产品经理，月薪3万，但是总加班看不到家人。</body>
```

OUTPUT:
```json
{{"record_id":"X","source_platform":"xiaohongshu","source_url":null,"source_lang":"zh","country":"CN","country_confidence":0.95,"income_amount_local":960000,"currency":"CNY","period":"year","income_amount_usd_year":null,"income_bracket":"upper_middle","profession":"bubble_tea_shop_owner","profession_raw":"奶茶店","industry":"food_service","earning_mechanisms":["business_owner"],"narrative_summary":"Hangzhou bubble-tea shop owner running 3 stores with ~960k CNY/year net profit, formerly Alibaba PM.","confidence":0.85,"raw_excerpt":"坐标杭州，三家奶茶店，每月净赚大概8万人民币（旺季10万淡季5万）。","extraction_model":"claude-sonnet-4-6","extracted_at":""}}
```

## Example 3 (Japanese / JP / pension + part-time)

INPUT:
```
<platform>5ch</platform> <lang>ja</lang> <country_hint>JP</country_hint>
<title>定年後の生活</title>
<body>65歳、元銀行員。年金が月18万くらい、それに加えて週3でコンビニのバイトして
月7万。妻と二人暮らしで、何とかやってる。退職金は1500万あったけど住宅ローンの
完済とリフォームで半分使った。</body>
```

OUTPUT:
```json
{{"record_id":"X","source_platform":"5ch","source_url":null,"source_lang":"ja","country":"JP","country_confidence":0.95,"income_amount_local":3000000,"currency":"JPY","period":"year","income_amount_usd_year":null,"income_bracket":"lower_middle","profession":"retired_banker_part_time_konbini","profession_raw":"元銀行員、コンビニのバイト","industry":"retail","earning_mechanisms":["government_pension","salary_employment"],"narrative_summary":"65-year-old retired Japanese banker with ¥18万/month pension plus a 3-day-a-week konbini job (¥7万/month).","confidence":0.88,"raw_excerpt":"65歳、元銀行員。年金が月18万くらい、それに加えて週3でコンビニのバイトして月7万。","extraction_model":"claude-sonnet-4-6","extracted_at":""}}
```

## Example 4 (Portuguese / BR / illicit_grey + platform_gig)

INPUT:
```
<platform>reddit</platform> <lang>pt</lang> <country_hint>BR</country_hint>
<title>como faço pra ganhar 8k por mês em SP</title>
<body>Cara, sou motorista de Uber de manhã (uns 4-5k/mês), mas o que
realmente paga é vender doce na esquina à noite — sem nota, em dinheiro,
mais uns 3-4k. Tô economizando pra abrir uma loja física.</body>
```

OUTPUT:
```json
{{"record_id":"X","source_platform":"reddit","source_url":null,"source_lang":"pt","country":"BR","country_confidence":0.95,"income_amount_local":96000,"currency":"BRL","period":"year","income_amount_usd_year":null,"income_bracket":"upper_middle","profession":"uber_driver_and_street_vendor","profession_raw":"motorista de Uber, vender doce na esquina","industry":"logistics_transport","earning_mechanisms":["platform_gig","illicit_grey"],"narrative_summary":"São Paulo Uber driver moonlighting as cash-only street candy vendor, ~R$8k/month combined.","confidence":0.85,"raw_excerpt":"sou motorista de Uber de manhã (uns 4-5k/mês), mas o que realmente paga é vender doce na esquina à noite — sem nota, em dinheiro","extraction_model":"claude-sonnet-4-6","extracted_at":""}}
```

# Reminders

- Return ONE JSON object per call. Do not wrap it in any other text.
- If you cannot identify income disclosure → `{{"skip": true, "reason": "..."}}`.
- `record_id`, `source_platform`, `source_url` should be echoed back from input.
""")


def build_user_message(record: dict) -> str:
    """Format one raw record into the user message body."""
    rid = record.get("id") or record.get("record_id") or ""
    plat = record.get("platform", "")
    url = record.get("url", "")
    lang = record.get("lang", "??")
    country_hint = record.get("country_hint") or record.get("country", "?")
    bracket_hint = record.get("bracket_hint") or ""
    industry_hint = record.get("industry_hint") or ""
    title = (record.get("title") or "").strip()
    body = (record.get("body") or "").strip()[:6000]

    return dedent(f"""\
        <post>
        <record_id>{rid}</record_id>
        <platform>{plat}</platform>
        <source_url>{url}</source_url>
        <lang>{lang}</lang>
        <country_hint>{country_hint}</country_hint>
        <bracket_hint>{bracket_hint}</bracket_hint>
        <industry_hint>{industry_hint}</industry_hint>
        <title>{title}</title>
        <body>{body}</body>
        </post>
    """)
