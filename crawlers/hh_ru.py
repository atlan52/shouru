"""HeadHunter (hh.ru) crawler — Russia's #1 job board, public JSON API.

API: https://api.hh.ru/vacancies?text=<kw>&per_page=50&page=<n>

Per vacancy we capture:
  vacancyId, name (role), employer name, area (city), salary {from, to,
  currency, gross}, experience, employment, schedule, snippet.requirement,
  snippet.responsibility, URL https://hh.ru/vacancy/<vacancyId>.

Country: detected from area.country.name (RU/UA/BY/KZ); default "RU".
We skip vacancies without any salary range (most posted RU jobs do have
ranges).

No auth, polite (1.5s sleep). HH's docs allow ~6 req/sec; we stay well below.
"""
import time
import requests

from config import (
    INCOME_KEYWORDS, PER_PLATFORM_LIMIT, RAW_DIR, PLATFORM_TIME_BUDGET_SEC,
)
from crawlers.common import (
    append_jsonl, make_id, polite_sleep, preload_seen, default_headers,
    TimeBudget,
)
from crawlers.state import State


PLATFORM = "hh_ru"
API_BASE = "https://api.hh.ru/vacancies"
PUBLIC_BASE = "https://hh.ru/vacancy"
PER_PAGE = 50
PAGES = 3  # paginate 3 pages per keyword

EXTRA_KEYWORDS = [
    "программист", "врач", "учитель", "продавец",
    "водитель", "юрист", "бухгалтер", "дизайнер",
]

# country.name (Russian) → ISO-2
COUNTRY_NAME_TO_ISO = {
    "Россия": "RU",
    "Украина": "UA",
    "Беларусь": "BY",
    "Білорусь": "BY",
    "Казахстан": "KZ",
    "Узбекистан": "UZ",
    "Кыргызстан": "KG",
    "Грузия": "GE",
    "Армения": "AM",
    "Азербайджан": "AZ",
    "Молдова": "MD",
    "Таджикистан": "TJ",
}


class HHError(Exception):
    pass


def _headers() -> dict:
    h = default_headers(accept_lang="ru-RU,ru;q=0.9,en;q=0.6")
    # HH explicitly recommends a meaningful UA per their api docs.
    h["User-Agent"] = "shouru-crawler/1.0 (research)"
    h["Accept"] = "application/json"
    return h


def fetch_json(url: str, params=None, timeout: int = 25):
    try:
        r = requests.get(url, headers=_headers(), params=params, timeout=timeout)
    except Exception as e:
        raise HHError(f"net err {url}: {e}")
    if r.status_code in (403, 429):
        raise HHError(f"{r.status_code} on {url}")
    if r.status_code != 200:
        raise HHError(f"status {r.status_code} on {url}")
    try:
        return r.json()
    except Exception:
        raise HHError(f"non-JSON response on {url}")


def fetch_with_retry(url: str, params=None):
    try:
        return fetch_json(url, params=params)
    except HHError as e:
        msg = str(e)
        if "403" in msg or "429" in msg:
            print(f"  [{PLATFORM}] backoff 30s on {url}")
            time.sleep(30)
            return fetch_json(url, params=params)
        raise


def detect_country_from_area(area: dict) -> str:
    if not isinstance(area, dict):
        return "RU"
    country = area.get("country") or {}
    if isinstance(country, dict):
        name = country.get("name") or ""
        iso = COUNTRY_NAME_TO_ISO.get(name)
        if iso:
            return iso
    # Fallback: name field for areas without explicit country (typical of RU regions)
    return "RU"


def normalize(v: dict, kw: str):
    """Convert one HH vacancy dict into our schema. Returns None if filtered."""
    rid = str(v.get("id") or "")
    if not rid:
        return None

    salary = v.get("salary")
    if not isinstance(salary, dict):
        # Skip vacancies without a salary block
        return None
    s_from = salary.get("from")
    s_to = salary.get("to")
    if s_from is None and s_to is None:
        # Skip purely "по договоренности" listings
        return None

    name = v.get("name") or ""
    employer_obj = v.get("employer") or {}
    employer_name = employer_obj.get("name") if isinstance(employer_obj, dict) else ""
    area_obj = v.get("area") or {}
    area_name = area_obj.get("name") if isinstance(area_obj, dict) else ""
    country = detect_country_from_area(area_obj)

    snippet = v.get("snippet") or {}
    requirement = snippet.get("requirement") or "" if isinstance(snippet, dict) else ""
    responsibility = snippet.get("responsibility") or "" if isinstance(snippet, dict) else ""

    experience_obj = v.get("experience") or {}
    employment_obj = v.get("employment") or {}
    schedule_obj = v.get("schedule") or {}
    experience = experience_obj.get("name") if isinstance(experience_obj, dict) else ""
    employment = employment_obj.get("name") if isinstance(employment_obj, dict) else ""
    schedule = schedule_obj.get("name") if isinstance(schedule_obj, dict) else ""

    salary_currency = salary.get("currency") or "RUR"
    salary_gross = salary.get("gross")

    title = f"{name} — {employer_name or '?'} ({area_name or '?'})"

    body_parts = [
        f"Должность: {name}",
        f"Работодатель: {employer_name}" if employer_name else "",
        f"Регион: {area_name}" if area_name else "",
        f"Опыт: {experience}" if experience else "",
        f"Занятость: {employment}" if employment else "",
        f"График: {schedule}" if schedule else "",
        f"Зарплата: от {s_from if s_from is not None else '?'} до "
        f"{s_to if s_to is not None else '?'} {salary_currency} "
        f"({'gross' if salary_gross else 'net'})",
    ]
    if requirement:
        body_parts.append(f"Требования: {requirement}")
    if responsibility:
        body_parts.append(f"Обязанности: {responsibility}")
    body = "\n".join([p for p in body_parts if p])

    url = v.get("alternate_url") or f"{PUBLIC_BASE}/{rid}"

    return {
        "id": make_id(PLATFORM, rid),
        "raw_id": rid,
        "platform": PLATFORM,
        "subtype": "vacancy",
        "lang": "ru",
        "country_hint": country,
        "title": title,
        "body": body[:5000],
        "author": employer_name or "",
        "url": url,
        "engagement": {"score": 0, "comments": 0},
        "salary": {
            "from": s_from,
            "to": s_to,
            "currency": salary_currency,
            "gross": salary_gross,
        },
        "vacancy": {
            "name": name,
            "employer": employer_name,
            "area": area_name,
            "experience": experience,
            "employment": employment,
            "schedule": schedule,
            "requirement": requirement,
            "responsibility": responsibility,
        },
        "matched_keyword": kw,
        "created_utc": v.get("published_at") or v.get("created_at"),
    }


def run():
    state = State(PLATFORM)
    preload_seen(state, PLATFORM, key_field="id")
    budget = TimeBudget(PLATFORM_TIME_BUDGET_SEC)
    items_added = 0

    keywords = list(INCOME_KEYWORDS["ru"]) + EXTRA_KEYWORDS
    # de-dup while preserving order
    seen_kw = set()
    keywords = [k for k in keywords if not (k in seen_kw or seen_kw.add(k))]

    try:
        for kw in keywords:
            if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                break
            if state.is_kw_done(kw):
                continue

            print(f"[{PLATFORM}] kw {kw}")
            start_page = state.get_cursor(kw, 0) or 0
            had_error = False

            for page in range(start_page, start_page + PAGES):
                if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                    break
                params = {
                    "text": kw,
                    "per_page": PER_PAGE,
                    "page": page,
                    "only_with_salary": "true",
                }
                try:
                    j = fetch_with_retry(API_BASE, params=params)
                except HHError as e:
                    print(f"  [{PLATFORM}] {kw} p{page} err: {e}")
                    had_error = True
                    break

                items = j.get("items") if isinstance(j, dict) else None
                if not items:
                    break

                for v in items:
                    if budget.expired() or items_added >= PER_PLATFORM_LIMIT:
                        break
                    try:
                        it = normalize(v, kw)
                    except Exception as e:
                        print(f"  [{PLATFORM}] normalize err: {e}")
                        continue
                    if not it:
                        continue
                    if state.is_seen(it["id"]):
                        continue
                    append_jsonl(it, PLATFORM, RAW_DIR)
                    state.mark_seen(it["id"])
                    items_added += 1
                    if items_added % 50 == 0:
                        print(f"  [{PLATFORM}] +{items_added} so far")
                    state.maybe_save(every=10)

                # HH returns total pages; bail early if we've passed it
                pages_total = j.get("pages") if isinstance(j, dict) else None
                state.set_cursor(kw, page + 1)
                polite_sleep(1500, 2500)
                if isinstance(pages_total, int) and page + 1 >= pages_total:
                    break

            if not had_error:
                state.mark_kw_done(kw)
            state.save()
            polite_sleep(1500, 2500)
    finally:
        state.save(force=True)

    print(f"[{PLATFORM}] done, +{items_added} items this run")


if __name__ == "__main__":
    run()
