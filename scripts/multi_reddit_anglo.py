"""英语国家**本地** subreddit — UKPersonalFinance / AusFinance / PersonalFinanceCanada /
NZPersonalFinance / IrelandPersonalFinance 等。

之前 reddit_import 只覆盖了全球泛英语大 sub (personalfinance / entrepreneur / antiwork ...)
没有按英语国家本地 sub 抓。补这一轮。
"""
import json, hashlib, time, random
from datetime import datetime, timezone
from pathlib import Path
import requests

UA = "shouru-research/1.0"
HDR = {"User-Agent": UA, "Accept": "application/json"}
DAY = datetime.now().strftime("%Y%m%d")

TARGETS = [
    # === UK ===
    ("UKPersonalFinance",  "GB", "en", [
        "salary", "how much do you earn", "FIRE UK", "graduate salary",
        "pension UK", "ISA limit", "umbrella company income", "teacher salary",
        "nurse pay", "consultant salary",
    ]),
    ("UKJobs",             "GB", "en", [
        "salary", "pay rise", "graduate scheme salary", "starting salary",
        "freelance contract rate", "umbrella vs ltd",
    ]),
    ("FIREUK",             "GB", "en", [
        "salary", "how much earn", "income", "milestone",
        "FIRE number UK", "pension salary",
    ]),
    ("ukpolitics",         "GB", "en", [
        "wages stagnation", "minimum wage UK", "median income UK",
        "cost of living salary",
    ]),
    # === Australia ===
    ("AusFinance",         "AU", "en", [
        "salary", "how much earn", "FIRE Australia", "income",
        "starting salary", "tradie salary", "doctor salary AU",
        "engineer salary AU", "FY net income",
    ]),
    ("ausjdocs",           "AU", "en", [
        "doctor salary", "registrar pay", "consultant pay", "GP income",
    ]),
    ("AusProperty",        "AU", "en", [
        "income to qualify mortgage", "salary needed buy",
    ]),
    # === Canada ===
    ("PersonalFinanceCanada", "CA", "en", [
        "salary", "how much earn", "FIRE Canada", "income",
        "RRSP contribution salary", "T4 income", "starting salary Canada",
        "engineer salary Canada", "nurse salary Canada", "doctor salary Canada",
    ]),
    ("CanadianInvestor",   "CA", "en", [
        "income", "salary", "dividend income",
    ]),
    ("CanadaJobs",         "CA", "en", [
        "salary", "pay raise", "starting salary",
    ]),
    # === New Zealand ===
    ("PersonalFinanceNZ",  "NZ", "en", [
        "salary", "how much earn", "income NZ", "KiwiSaver salary",
        "starting salary NZ", "engineer salary NZ",
    ]),
    ("newzealand",         "NZ", "en", [
        "salary NZ", "how much do you earn", "minimum wage NZ", "FIRE NZ",
    ]),
    # === Ireland ===
    ("irishpersonalfinance", "IE", "en", [
        "salary", "how much earn", "FIRE Ireland", "income",
        "starting salary Ireland",
    ]),
    ("ireland",            "IE", "en", [
        "salary Ireland", "how much do you earn", "tech salary Dublin",
    ]),
    # === US 本地金融/职业 sub（补全）===
    ("financialindependence", "US", "en", [
        "salary", "income", "FIRE number", "milestone",
    ]),
    ("fatFIRE",            "US", "en", [
        "salary", "income", "net worth", "exit",
    ]),
    ("FIRE",               "US", "en", [
        "salary", "income", "FIRE number",
    ]),
    ("Salary",             "US", "en", [
        "salary", "how much do you earn", "raise",
    ]),
    ("cscareerquestions",  "US", "en", [
        "salary", "TC", "total comp", "offer", "negotiation salary",
        "FAANG comp", "L5 salary", "L6 salary",
    ]),
    ("ExperiencedDevs",    "US", "en", [
        "salary", "TC", "total comp", "raise",
    ]),
    ("nursing",            "US", "en", [
        "RN salary", "ICU pay", "travel nurse pay", "shift differential",
    ]),
    ("teaching",           "US", "en", [
        "teacher salary", "stipend", "summer pay",
    ]),
    # === 南非 ===
    ("PersonalFinanceZA",  "ZA", "en", [
        "salary", "how much earn", "income SA", "FIRE South Africa",
    ]),
    # === 印度 ===
    ("IndiaInvestments",   "IN", "en", [
        "salary", "income", "lakh per month", "starting salary",
        "tech salary India",
    ]),
    ("IndianStreetBets",   "IN", "en", [
        "salary", "ctc", "lakh", "package",
    ]),
]


def md5_16(*p): return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]
def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def polite(): time.sleep(random.uniform(1.3, 2.0))


def append(path: Path, obj: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def load_seen(path: Path) -> set:
    seen = set()
    if path.exists():
        for line in path.open(encoding="utf-8"):
            try: seen.add(json.loads(line)["id"])
            except Exception: pass
    return seen


def crawl(sr: str, country: str, lang: str, kws: list[str]) -> int:
    out = Path(f"data/raw/r_{sr.lower()}_native_{DAY}.jsonl")
    seen = load_seen(out)
    platform = f"r_{sr.lower()}"
    total = 0
    for kw in kws:
        url = f"https://www.reddit.com/r/{sr}/search.json"
        params = {"q": kw, "restrict_sr": "on", "limit": "100", "t": "year"}
        try:
            r = requests.get(url, params=params, headers=HDR, timeout=25)
            if r.status_code != 200:
                print(f"[r/{sr}] {kw!r:<40} status={r.status_code}")
                polite(); continue
            data = r.json()
            children = data.get("data", {}).get("children", [])
            if not children:
                print(f"[r/{sr}] {kw!r:<40} 0 results")
                polite(); continue
            added = 0
            for c in children:
                d = c.get("data", {})
                rid_raw = d.get("id") or d.get("name", "")
                if not rid_raw: continue
                rid = md5_16(platform, rid_raw)
                if rid in seen: continue
                title = d.get("title", "") or ""
                body = d.get("selftext", "") or ""
                author = d.get("author", "") or ""
                permalink = d.get("permalink", "") or ""
                full_url = f"https://www.reddit.com{permalink}" if permalink else (d.get("url", "") or "")
                obj = {
                    "id": rid, "raw_id": rid_raw, "platform": platform, "lang": lang,
                    "title": title, "body": body[:5000], "author": author, "url": full_url,
                    "country_hint": country, "matched_keyword": kw,
                    "engagement": {
                        "score": int(d.get("score", 0) or 0),
                        "comments": int(d.get("num_comments", 0) or 0),
                        "upvote_ratio": d.get("upvote_ratio"),
                    },
                    "subreddit": d.get("subreddit", "") or sr,
                    "created_utc": d.get("created_utc"),
                    "crawled_at": now_iso(),
                }
                append(out, obj); seen.add(rid); total += 1; added += 1
            print(f"[r/{sr}] {kw!r:<40} children={len(children):>3} new={added:>3} total={total}")
        except Exception as e:
            print(f"[r/{sr}] {kw!r} err: {e}")
        polite()
    print(f"[r/{sr}] DONE +{total}")
    return total


def main():
    grand = 0
    for sr, country, lang, kws in TARGETS:
        print(f"\n=== r/{sr} ({country}, {lang}, {len(kws)} kws) ===")
        n = crawl(sr, country, lang, kws)
        grand += n
    print(f"\n=== GRAND TOTAL: +{grand} new across {len(TARGETS)} subreddits ===")


if __name__ == "__main__":
    main()
