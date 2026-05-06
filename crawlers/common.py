"""Shared helpers — JSONL writer, ID hash, multi-language topic filter,
country/currency parsing, HTTP utils, polite sleep.

All crawlers depend on this module. Keep it simple and side-effect-free.
"""
import json
import hashlib
import random
import re
import time
from collections import defaultdict
from pathlib import Path
from datetime import datetime, timezone

from config import (
    TOPIC_TOKENS, INCOME_KEYWORDS, COUNTRY_KEYWORDS, INDUSTRY_KEYWORDS,
    COUNTRIES_40, RAW_DIR, UA_POOL, POLITENESS_DELAY_MS,
)


# ============================================================================
# IDs / timestamps / JSONL
# ============================================================================
def make_id(*parts) -> str:
    h = hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()
    return h[:16]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append_jsonl(item: dict, platform: str, raw_dir: Path = RAW_DIR) -> bool:
    """Append a single item to today's jsonl. Caller handles dedupe."""
    item.setdefault("crawled_at", now_iso())
    item.setdefault("platform", platform)
    stamp = datetime.now().strftime("%Y%m%d")
    out = raw_dir / f"{platform}_{stamp}.jsonl"
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
    return True


def preload_seen(state, platform: str, key_field: str = "id"):
    """Reconcile state.seen with what's already in raw jsonl files.

    Call at the top of each crawler's run() to make state crash-recoverable
    even when jsonl was written but state.json was lost. Idempotent.
    """
    n = 0
    for f in RAW_DIR.glob(f"{platform}_*.jsonl"):
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                k = item.get(key_field)
                if k and not state.is_seen(k):
                    state.mark_seen(k)
                    n += 1
        except Exception:
            pass
    if n:
        print(f"[{platform}] preload: +{n} ids from existing jsonl into state")
        state.save()
    return n


# ============================================================================
# Topic filter — multi-language. Item must contain a TOPIC_TOKEN in *any*
# of the candidate languages (fuzzy: we don't insist on language match).
# ============================================================================
def is_on_topic(*texts, lang: str | None = None) -> bool:
    """Return True if any candidate language's TOPIC_TOKENS hits the texts."""
    blob = " ".join((t or "").lower() for t in texts)
    if not blob.strip():
        return False
    candidates = [lang] if lang and lang in TOPIC_TOKENS else list(TOPIC_TOKENS.keys())
    for ln in candidates:
        for tok in TOPIC_TOKENS[ln]:
            if tok.lower() in blob:
                return True
    return False


# Backwards-compat shorthands
def is_on_topic_en(*texts) -> bool:
    return is_on_topic(*texts, lang="en")


def is_on_topic_zh(*texts) -> bool:
    return is_on_topic(*texts, lang="zh")


def is_on_topic_ja(*texts) -> bool:
    return is_on_topic(*texts, lang="ja")


def is_on_topic_ko(*texts) -> bool:
    return is_on_topic(*texts, lang="ko")


# ============================================================================
# Country detection
# ============================================================================
def detect_country(text: str, hint: str = "") -> str:
    """Return ISO-2 country code or '??'. `hint` is a fallback (e.g. subreddit
    region tag, platform's primary country, etc.).
    """
    if not text:
        return hint or "??"
    text_lower = text.lower()
    scores = defaultdict(int)
    for country, kws in COUNTRY_KEYWORDS.items():
        for kw in kws:
            if kw.lower() in text_lower:
                scores[country] += 1
    if scores:
        return max(scores, key=scores.get)
    return hint or "??"


def detect_industry(text: str) -> str:
    """Return canonical industry label. 'other' if nothing matches."""
    if not text:
        return "other"
    text_lower = text.lower()
    scores = defaultdict(int)
    for ind, kws in INDUSTRY_KEYWORDS.items():
        for kw in kws:
            if kw.lower() in text_lower:
                scores[ind] += 1
    return max(scores, key=scores.get) if scores else "other"


# ============================================================================
# Currency / amount parsing
# ============================================================================
_AMOUNT_PATTERNS = [
    # Symbol-prefixed amounts
    (r'\$\s*([\d,]+(?:\.\d{1,2})?)\s*([kKmM]?)', "USD"),
    (r'£\s*([\d,]+(?:\.\d{1,2})?)\s*([kK]?)', "GBP"),
    (r'€\s*([\d,]+(?:\.\d{1,2})?)\s*([kK]?)', "EUR"),
    (r'¥\s*([\d,]+(?:\.\d{1,2})?)\s*([万kK]?)', "JPY"),
    (r'₹\s*([\d,]+(?:\.\d{1,2})?)\s*(lakh|crore|[kK]?)', "INR"),
    (r'₽\s*([\d,]+(?:\.\d{1,2})?)\s*([kKмMт]?)', "RUB"),
    (r'₩\s*([\d,]+(?:\.\d{1,2})?)\s*(만|[kK]?)', "KRW"),
    (r'R\$\s*([\d,]+(?:\.\d{1,2})?)\s*([kKmilM]*)', "BRL"),
    (r'₺\s*([\d,]+(?:\.\d{1,2})?)\s*([kK]?)', "TRY"),
    (r'₪\s*([\d,]+(?:\.\d{1,2})?)\s*([kK]?)', "ILS"),
    # Suffix-style amounts
    (r'([\d,]+(?:\.\d{1,2})?)\s*(USD|dollars?)', "USD"),
    (r'([\d,]+(?:\.\d{1,2})?)\s*(EUR|euros?)', "EUR"),
    (r'([\d,]+(?:\.\d{1,2})?)\s*(CNY|RMB|yuan|元)', "CNY"),
    (r'([\d,]+(?:\.\d{1,2})?)\s*(JPY|yen|円)', "JPY"),
    (r'([\d,]+(?:\.\d{1,2})?)\s*(만원|KRW|won|원)', "KRW"),
    (r'([\d,]+(?:\.\d{1,2})?)\s*(INR|rupees?|₹)', "INR"),
    (r'([\d,]+(?:\.\d{1,2})?)\s*(GBP|pounds?)', "GBP"),
    # Chinese 万 suffix on naked numbers
    (r'([\d,]+(?:\.\d{1,2})?)\s*(万|萬|wan)', "CNY_WAN"),
]


def parse_amounts(text: str) -> list[dict]:
    """Find money amounts in text. Returns list of {raw, currency, value, unit_hint}.

    `value` is normalized to the base unit of `currency` (USD, EUR, CNY, etc.).
    `unit_hint` is "" for plain, "k" for thousands, "m" for millions, "wan" for 万,
    "lakh" for 100,000 INR, "crore" for 10M INR.
    """
    if not text:
        return []
    out = []
    for pat, ccy in _AMOUNT_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            raw = m.group(0).strip()
            try:
                val_str = m.group(1).replace(",", "")
                val = float(val_str)
            except (ValueError, IndexError):
                continue
            unit_hint = ""
            if m.lastindex and m.lastindex >= 2:
                suf = (m.group(2) or "").lower()
                if "万" in suf or "萬" in suf or "wan" == suf:
                    unit_hint = "wan"
                    val *= 10_000
                elif "k" == suf:
                    unit_hint = "k"
                    val *= 1_000
                elif "m" == suf:
                    unit_hint = "m"
                    val *= 1_000_000
                elif "lakh" == suf:
                    unit_hint = "lakh"
                    val *= 100_000
                elif "crore" == suf:
                    unit_hint = "crore"
                    val *= 10_000_000
                elif "만" == suf or "만원" == suf:
                    unit_hint = "wan"
                    val *= 10_000
            normalized_ccy = "CNY" if ccy == "CNY_WAN" else ccy
            out.append({
                "raw": raw,
                "currency": normalized_ccy,
                "value": val,
                "unit_hint": unit_hint,
            })
    return out


def has_amount(text: str) -> bool:
    """Quick check: does the text mention any monetary amount?"""
    if not text:
        return False
    for pat, _ in _AMOUNT_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


# ============================================================================
# HTTP / sleep / UA
# ============================================================================
def polite_sleep(lo_ms: float | None = None, hi_ms: float | None = None):
    if lo_ms is None or hi_ms is None:
        lo_ms, hi_ms = POLITENESS_DELAY_MS
    time.sleep(random.uniform(lo_ms / 1000.0, hi_ms / 1000.0))


def random_ua() -> str:
    return random.choice(UA_POOL)


def default_headers(accept_lang: str = "en-US,en;q=0.9") -> dict:
    return {
        "User-Agent": random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": accept_lang,
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }


# ============================================================================
# Time-budget helper — crawlers should check this in their main loop.
# ============================================================================
class TimeBudget:
    def __init__(self, seconds: int):
        self.budget = seconds
        self.start = time.time()

    def expired(self) -> bool:
        return (time.time() - self.start) > self.budget

    def remaining(self) -> float:
        return max(0.0, self.budget - (time.time() - self.start))


# ============================================================================
# Cookie env parser — reused by zhihu/weibo/xhs/maimai/blind/naver.
# ============================================================================
def parse_cookie_env(var_name: str, domain: str) -> list[dict]:
    """Parse a raw 'Cookie: foo=bar; baz=qux' string from env var.
    Returns Playwright-ready cookie dicts. Returns [] if unset.
    """
    import os
    raw = (os.environ.get(var_name) or "").strip()
    if not raw:
        return []
    if raw.lower().startswith("cookie:"):
        raw = raw[len("cookie:"):].strip()
    cookies = []
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        cookies.append({"name": name.strip(), "value": value.strip(),
                        "domain": domain, "path": "/"})
    return cookies
