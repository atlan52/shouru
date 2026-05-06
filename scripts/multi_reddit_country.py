"""Reddit JSON API 多国本地母语收入帖批量抓取.

复用 r/mexico 模式（198 条本地西语原文证明可行），扫 ~12 个国家 subreddit + 各国本国语言关键词。

输出 data/raw/r_<subreddit>_native_<DAY>.jsonl，每个 subreddit 一份文件，schema 与
r_mexico_native 一致（id / raw_id / platform / lang / title / body / author / url /
country_hint / matched_keyword / engagement / subreddit / created_utc / crawled_at).

UA 用 shouru-research/1.0 — Reddit 公开 JSON API 不需要 cookie。
"""
import json, hashlib, time, random
from datetime import datetime, timezone
from pathlib import Path
import requests

UA = "shouru-research/1.0"
HDR = {"User-Agent": UA, "Accept": "application/json"}
DAY = datetime.now().strftime("%Y%m%d")

# (subreddit, country_iso, lang, [keywords in native language])
TARGETS = [
    # === 西语圈 ===
    ("spain",       "ES", "es", [
        "sueldo", "salario", "cuánto ganan", "sueldo neto", "freelance",
        "autónomo ingresos", "FIRE España", "nómina", "ingresos extra",
        "sueldo programador",
    ]),
    ("argentina",   "AR", "es", [
        "sueldo", "cuánto ganan", "ingresos en pesos", "freelance",
        "trabajo remoto sueldo", "monotributo ingresos", "blanco vs negro sueldo",
        "sueldo en dólares", "salario IT", "jubilación",
    ]),
    ("chile",       "CL", "es", [
        "sueldo", "cuánto ganan", "salario líquido", "sueldo programador",
        "freelance Chile", "AFP jubilación", "mi sueldo", "cuánto cobran",
    ]),
    ("colombia",    "CO", "es", [
        "sueldo", "cuánto ganan", "salario mínimo", "sueldo programador",
        "freelance ingresos", "trabajo remoto sueldo", "mi sueldo",
    ]),
    ("PERU",        "PE", "es", [
        "sueldo", "cuánto ganan", "sueldo programador", "freelance ingresos",
        "trabajo bien pagado", "mi sueldo",
    ]),
    # === 葡萄牙语圈 ===
    ("brasil",      "BR", "pt", [
        "salário", "quanto ganha", "renda mensal", "MEI faturamento",
        "freelancer renda", "salário desenvolvedor", "salário médico",
        "aposentadoria", "trabalho remoto salário",
    ]),
    ("portugal",    "PT", "pt", [
        "salário", "quanto ganham", "ordenado", "freelancer rendimentos",
        "salário programador", "trabalho remoto salário",
    ]),
    ("investimentos", "BR", "pt", [
        "salário", "renda", "FIRE Brasil", "renda passiva", "aposentadoria",
        "MEI faturamento", "dividendos mensais",
    ]),
    # === 东南亚 ===
    ("vietnam",     "VN", "vi", [
        "lương", "thu nhập", "lương kỹ sư", "lương lập trình viên",
        "freelance thu nhập", "kiếm tiền online", "FIRE Việt Nam",
    ]),
    ("indonesia",   "ID", "id", [
        "gaji", "pendapatan", "gaji programmer", "freelance pendapatan",
        "penghasilan bulanan", "kerja remote gaji", "pensiun",
    ]),
    ("malaysia",    "MY", "ms", [
        "gaji", "pendapatan", "gaji bersih", "freelance pendapatan",
        "kerja remote gaji", "FIRE Malaysia",
    ]),
    ("Thailand",    "TH", "th", [
        "เงินเดือน", "รายได้", "freelance รายได้", "เงินเดือนโปรแกรมเมอร์",
        "ทำงานออนไลน์", "อาชีพ รายได้ดี",
    ]),
    ("singapore",   "SG", "en", [
        "salary", "how much earn", "fresh grad salary", "freelance income",
        "tech salary", "FIRE Singapore",
    ]),
    ("Philippines", "PH", "tl", [
        "sahod", "sueldo", "kita buwanan", "freelance sahod",
        "bilang ng sahod", "trabaho online kita",
    ]),
    # === 其他长尾 ===
    ("Turkey",      "TR", "tr", [
        "maaş", "gelir", "ne kadar kazanıyor", "freelance gelir",
        "yazılımcı maaşı", "uzaktan çalışma maaş",
    ]),
    ("poland",      "PL", "pl", [
        "pensja", "zarobki", "ile zarabia", "freelance zarobki",
        "wynagrodzenie programisty", "praca zdalna pensja",
    ]),
    ("italy",       "IT", "it", [
        "stipendio", "salario", "quanto guadagna", "freelance redditi",
        "stipendio programmatore", "lavoro remoto stipendio",
    ]),
    ("france",      "FR", "fr", [
        "salaire", "combien gagne", "salaire net", "freelance revenus",
        "salaire développeur", "télétravail salaire", "FIRE France",
    ]),
    ("Nederlands",  "NL", "nl", [
        "salaris", "hoeveel verdien", "freelance inkomen", "salaris ontwikkelaar",
        "thuiswerk salaris",
    ]),
    ("AskARussian", "RU", "ru", [
        "зарплата", "доход", "сколько зарабатываете", "фриланс",
        "удаленная работа доход", "пассивный доход",
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
            try:
                seen.add(json.loads(line)["id"])
            except Exception:
                pass
    return seen


def crawl_subreddit(sr: str, country: str, lang: str, keywords: list[str]) -> int:
    out = Path(f"data/raw/r_{sr.lower()}_native_{DAY}.jsonl")
    seen = load_seen(out)
    platform = f"r_{sr.lower()}"
    total_new = 0
    for kw in keywords:
        url = f"https://www.reddit.com/r/{sr}/search.json"
        params = {"q": kw, "restrict_sr": "on", "limit": "100", "t": "year"}
        try:
            r = requests.get(url, params=params, headers=HDR, timeout=25)
            if r.status_code != 200:
                print(f"[r/{sr}] {kw!r} status={r.status_code}")
                polite()
                continue
            data = r.json()
            children = data.get("data", {}).get("children", [])
            if not children:
                print(f"[r/{sr}] {kw!r} 0 results")
                polite()
                continue
            added = 0
            for c in children:
                d = c.get("data", {})
                rid_raw = d.get("id") or d.get("name", "")
                if not rid_raw:
                    continue
                rid = md5_16(platform, rid_raw)
                if rid in seen:
                    continue
                title = d.get("title", "") or ""
                body = d.get("selftext", "") or ""
                author = d.get("author", "") or ""
                permalink = d.get("permalink", "") or ""
                full_url = f"https://www.reddit.com{permalink}" if permalink else (d.get("url", "") or "")
                obj = {
                    "id": rid,
                    "raw_id": rid_raw,
                    "platform": platform,
                    "lang": lang,
                    "title": title,
                    "body": body[:5000],
                    "author": author,
                    "url": full_url,
                    "country_hint": country,
                    "matched_keyword": kw,
                    "engagement": {
                        "score": int(d.get("score", 0) or 0),
                        "comments": int(d.get("num_comments", 0) or 0),
                        "upvote_ratio": d.get("upvote_ratio"),
                    },
                    "subreddit": d.get("subreddit", "") or sr,
                    "created_utc": d.get("created_utc"),
                    "crawled_at": now_iso(),
                }
                append(out, obj)
                seen.add(rid)
                total_new += 1
                added += 1
            print(f"[r/{sr}] {kw!r:<35} children={len(children):>3} new={added:>3} total={total_new}")
        except Exception as e:
            print(f"[r/{sr}] {kw!r} err: {e}")
        polite()
    print(f"[r/{sr}] DONE +{total_new}")
    return total_new


def main():
    grand_total = 0
    for sr, country, lang, kws in TARGETS:
        print(f"\n=== r/{sr} ({country}, {lang}, {len(kws)} kws) ===")
        n = crawl_subreddit(sr, country, lang, kws)
        grand_total += n
    print(f"\n=== GRAND TOTAL: +{grand_total} new records across {len(TARGETS)} subreddits ===")


if __name__ == "__main__":
    main()
