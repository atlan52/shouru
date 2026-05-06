"""Pydantic schema for one extracted income record.

Sonnet 4.6 is asked to return a JSON object that conforms to `IncomeRecord`,
or `{"skip": true, "reason": "..."}` if the post does not describe income.
"""
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


# Closed-list literals used by the LLM
PERIOD = Literal["hour", "day", "week", "month", "year", "one-time", "unknown"]
BRACKET = Literal["bottom", "lower_middle", "middle", "upper_middle", "top", "unknown"]

# Earning mechanisms — must match config.EARNING_MECHANISMS
MECHANISM = Literal[
    "salary_employment",
    "equity_compensation",
    "business_owner",
    "freelance_contractor",
    "platform_gig",
    "passive_investment",
    "real_estate_rental",
    "royalties_creator",
    "inheritance_trust",
    "government_pension",
    "illicit_grey",
    "multiple_streams",
    "unknown",
]


class IncomeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str
    source_platform: str
    source_url: str | None = None
    source_lang: str = Field(description="ISO 639-1, e.g. 'en','zh','ja'")
    country: str = Field(description="ISO 3166-1 alpha-2, e.g. 'US'; '??' if unknown")
    country_confidence: float = Field(ge=0, le=1)

    income_amount_local: float | None = None
    currency: str | None = Field(default=None, description="ISO 4217, e.g. 'USD'")
    period: PERIOD = "unknown"
    income_amount_usd_year: float | None = Field(
        default=None,
        description="Set by Python downstream from (amount_local, currency, period). "
                    "LLM should leave None — Python converts using FX snapshot."
    )

    income_bracket: BRACKET = "unknown"
    profession: str = Field(description="canonical lowercase_with_underscores")
    profession_raw: str = Field(description="original-language phrase quoted from text")
    industry: str = Field(description="one of INDUSTRY_LABELS or 'other'")

    earning_mechanisms: list[MECHANISM] = Field(default_factory=list)
    narrative_summary: str = Field(description="one English sentence: who they are, how they earn")
    confidence: float = Field(ge=0, le=1)
    raw_excerpt: str = Field(description="≤300 chars, original lang, the quote that justified extraction")

    extraction_model: str = "claude-sonnet-4-6"
    extracted_at: str = ""


class SkipResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    skip: Literal[True] = True
    reason: str
    record_id: str | None = None
