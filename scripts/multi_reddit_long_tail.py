"""Reddit 长尾国家 — 拉美小国 / 中东 / 非洲 / 南亚 / 繁中 / 东欧 / 高加索 / 中亚.

同 multi_reddit_country 模式，覆盖 50+ 个之前没抓的国家本地 sub.
"""
import json, hashlib, time, random
from datetime import datetime, timezone
from pathlib import Path
import requests

UA = "shouru-research/1.0"
HDR = {"User-Agent": UA, "Accept": "application/json"}
DAY = datetime.now().strftime("%Y%m%d")

# (subreddit, country, lang, [keywords])
TARGETS = [
    # === 拉美 西语小国 ===
    ("uruguay",       "UY", "es", ["sueldo", "salario", "cuánto ganan", "freelance", "jubilación"]),
    ("paraguay",      "PY", "es", ["sueldo", "salario", "cuánto ganan", "freelance"]),
    ("ecuador",       "EC", "es", ["sueldo", "salario", "cuánto ganan", "freelance"]),
    ("bolivia",       "BO", "es", ["sueldo", "salario", "cuánto ganan", "freelance"]),
    ("Venezuela",     "VE", "es", ["sueldo", "salario", "cuánto ganan", "dolar", "bolívar"]),
    ("cuba",          "CU", "es", ["sueldo", "salario", "MLC", "cuánto ganan"]),
    ("dominicanrepublic","DO","es",["sueldo", "salario", "cuánto ganan"]),
    ("CostaRica",     "CR", "es", ["sueldo", "salario", "cuánto ganan", "colones"]),
    ("Guatemala",     "GT", "es", ["sueldo", "salario", "quetzales", "cuánto ganan"]),
    ("ElSalvador",    "SV", "es", ["sueldo", "salario", "cuánto ganan", "bitcoin sueldo"]),
    ("Honduras",      "HN", "es", ["sueldo", "salario", "cuánto ganan", "lempiras"]),
    ("Nicaragua",     "NI", "es", ["sueldo", "salario", "cuánto ganan"]),
    ("Panama",        "PA", "es", ["sueldo", "salario", "cuánto ganan", "balboas"]),
    # === 中东 + 海湾 (英语 sub) ===
    ("saudiarabia",   "SA", "en", ["salary", "income", "expat salary", "tax-free salary", "Aramco"]),
    ("dubai",         "AE", "en", ["salary", "income", "expat package", "tax-free", "DIFC", "tech salary Dubai"]),
    ("UAE",           "AE", "en", ["salary", "income", "expat salary", "DIFC", "ADGM"]),
    ("Lebanon",       "LB", "en", ["salary", "income", "lira", "USD salary", "fresh dollars"]),
    ("Egypt",         "EG", "en", ["salary", "income", "pound", "EGP", "expat salary Egypt"]),
    ("jordan",        "JO", "en", ["salary", "income", "dinar"]),
    ("qatar",         "QA", "en", ["salary", "income", "expat package", "tax-free"]),
    ("Kuwait",        "KW", "en", ["salary", "income", "expat package"]),
    ("bahrain",       "BH", "en", ["salary", "income"]),
    ("oman",          "OM", "en", ["salary", "income"]),
    ("iran",          "IR", "en", ["salary", "income", "rial", "toman"]),
    # === 非洲 (英语) ===
    ("Nigeria",       "NG", "en", ["salary", "income", "naira", "remote job pay"]),
    ("Kenya",         "KE", "en", ["salary", "income", "shilling", "tech salary Nairobi"]),
    ("ghana",         "GH", "en", ["salary", "income", "cedi"]),
    ("Ethiopia",      "ET", "en", ["salary", "income", "birr"]),
    ("Tanzania",      "TZ", "en", ["salary", "income", "shilling"]),
    ("uganda",        "UG", "en", ["salary", "income"]),
    ("morocco",       "MA", "en", ["salary", "income", "dirham"]),
    ("tunisia",       "TN", "en", ["salary", "income", "dinar"]),
    # === 南亚 ===
    ("bangladesh",    "BD", "en", ["salary", "income", "taka", "lakh"]),
    ("pakistan",      "PK", "en", ["salary", "income", "rupee", "lakh", "fresh grad salary PK"]),
    ("SriLanka",      "LK", "en", ["salary", "income", "rupee"]),
    ("nepal",         "NP", "en", ["salary", "income", "rupee"]),
    # === 东南亚补 ===
    ("cambodia",      "KH", "en", ["salary", "income", "riel"]),
    ("myanmar",       "MM", "en", ["salary", "income", "kyat"]),
    # === 大中华区繁中 ===
    ("HongKong",      "HK", "zh", ["人工", "月薪", "年薪", "搵錢", "凍薪", "炒車", "FIRE"]),
    ("taiwan",        "TW", "zh", ["薪水", "月薪", "年薪", "工資", "副業", "小資族", "FIRE"]),
    # === 东欧 / 巴尔干 ===
    ("Bulgaria",      "BG", "en", ["salary", "income", "lev"]),
    ("Croatia",       "HR", "en", ["salary", "income", "plaća", "freelance"]),
    ("serbia",        "RS", "en", ["salary", "income", "plata", "dinar"]),
    ("slovenia",      "SI", "en", ["salary", "income", "plača"]),
    ("Slovakia",      "SK", "en", ["salary", "income", "plat", "freelance"]),
    ("estonia",       "EE", "en", ["salary", "income", "palk", "freelance"]),
    ("latvia",        "LV", "en", ["salary", "income", "alga"]),
    ("lithuania",     "LT", "en", ["salary", "income", "atlyginimas"]),
    # === 高加索 ===
    ("georgia",       "GE", "en", ["salary", "income", "lari"]),
    ("armenia",       "AM", "en", ["salary", "income", "dram"]),
    ("azerbaijan",    "AZ", "en", ["salary", "income", "manat"]),
    # === 中亚 ===
    ("Kazakhstan",    "KZ", "en", ["salary", "income", "tenge"]),
    ("uzbekistan",    "UZ", "en", ["salary", "income", "som"]),
    # === 北欧小国 ===
    ("iceland",       "IS", "en", ["salary", "income", "krónur"]),
    ("denmark",       "DK", "en", ["salary", "income", "DKK"]),
    ("norge",         "NO", "no", ["lønn", "inntekt", "freelance"]),
    ("sweden",        "SE", "en", ["salary", "income", "SEK"]),
    ("Finland",       "FI", "en", ["salary", "income", "EUR"]),
    # === 其他 ===
    ("israel",        "IL", "en", ["salary", "income", "shekel", "high tech salary IL"]),
    ("hungary",       "HU", "en", ["salary", "income", "forint"]),
    ("czech",         "CZ", "en", ["salary", "income", "koruna"]),
    ("Romania",       "RO", "en", ["salary", "income", "lei"]),
    ("greece",        "GR", "en", ["salary", "income", "EUR"]),
    ("portugal",      "PT", "en", ["salary", "income"]),  # 英语版 portugal sub 也常见
    ("austria",       "AT", "en", ["salary", "income"]),
    ("Switzerland",   "CH", "en", ["salary", "income", "CHF"]),
    ("belgium",       "BE", "en", ["salary", "income"]),
    ("luxembourg",    "LU", "en", ["salary", "income"]),
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
                print(f"[r/{sr}] {kw!r:<40} 0")
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
                permalink = d.get("permalink", "") or ""
                full_url = f"https://www.reddit.com{permalink}" if permalink else (d.get("url", "") or "")
                obj = {
                    "id": rid, "raw_id": rid_raw, "platform": platform, "lang": lang,
                    "title": title, "body": body[:5000],
                    "author": d.get("author", "") or "", "url": full_url,
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
        try:
            n = crawl(sr, country, lang, kws)
        except Exception as e:
            print(f"[r/{sr}] CRAWL ERR: {e}"); n = 0
        grand += n
    print(f"\n=== GRAND TOTAL: +{grand} new across {len(TARGETS)} subreddits ===")


if __name__ == "__main__":
    main()
