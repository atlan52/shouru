"""Global config for shouru — 跨国收入与谋生方式研究爬虫.

Goals:
  (1) 各国各阶层各职业 — sample human self-reports of how they earn
  (2) 多语言、多平台 — locally-dominant sites in each language
  (3) Structured extraction — hand to Claude Sonnet 4.6 for {country, bracket,
      profession, earning_mechanism, narrative_summary, ...}
"""
from pathlib import Path
import os

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
EXTRACTED_DIR = DATA_DIR / "extracted"
CURATED_DIR = DATA_DIR / "curated"
STATE_DIR = DATA_DIR / "state"
LOGS_DIR = ROOT / "logs"
DOCS_DIR = ROOT / "docs"
for p in (RAW_DIR, EXTRACTED_DIR, CURATED_DIR, STATE_DIR, LOGS_DIR, DOCS_DIR,
          CURATED_DIR / "reports", CURATED_DIR / "figs"):
    p.mkdir(parents=True, exist_ok=True)


# ============================================================================
# 40 countries (ISO-3166 alpha-2)
# ============================================================================
COUNTRIES_40 = [
    "US", "CN", "JP", "KR", "IN", "DE", "GB", "FR", "BR", "RU",
    "MX", "ES", "IT", "CA", "AU", "NL", "CH", "SG", "MY", "TH",
    "ID", "PH", "VN", "TR", "SA", "AE", "EG", "ZA", "NG", "AR",
    "CO", "CL", "IL", "PL", "SE", "NO", "MA", "PK", "BD", "UA",
]

COUNTRY_NAMES_EN = {
    "US": "United States", "CN": "China", "JP": "Japan", "KR": "South Korea",
    "IN": "India", "DE": "Germany", "GB": "United Kingdom", "FR": "France",
    "BR": "Brazil", "RU": "Russia", "MX": "Mexico", "ES": "Spain",
    "IT": "Italy", "CA": "Canada", "AU": "Australia", "NL": "Netherlands",
    "CH": "Switzerland", "SG": "Singapore", "MY": "Malaysia", "TH": "Thailand",
    "ID": "Indonesia", "PH": "Philippines", "VN": "Vietnam", "TR": "Turkey",
    "SA": "Saudi Arabia", "AE": "UAE", "EG": "Egypt", "ZA": "South Africa",
    "NG": "Nigeria", "AR": "Argentina", "CO": "Colombia", "CL": "Chile",
    "IL": "Israel", "PL": "Poland", "SE": "Sweden", "NO": "Norway",
    "MA": "Morocco", "PK": "Pakistan", "BD": "Bangladesh", "UA": "Ukraine",
}

# Languages spoken / posted in for each country (ISO 639-1; for google_universal)
COUNTRY_LANGUAGES = {
    "US": ["en"], "CN": ["zh"], "JP": ["ja"], "KR": ["ko"],
    "IN": ["en", "hi"], "DE": ["de"], "GB": ["en"], "FR": ["fr"],
    "BR": ["pt"], "RU": ["ru"], "MX": ["es"], "ES": ["es"],
    "IT": ["it"], "CA": ["en", "fr"], "AU": ["en"], "NL": ["nl", "en"],
    "CH": ["de", "fr", "it"], "SG": ["en", "zh"], "MY": ["en", "ms"],
    "TH": ["th", "en"], "ID": ["id", "en"], "PH": ["en"], "VN": ["vi"],
    "TR": ["tr"], "SA": ["ar", "en"], "AE": ["ar", "en"], "EG": ["ar"],
    "ZA": ["en"], "NG": ["en"], "AR": ["es"], "CO": ["es"], "CL": ["es"],
    "IL": ["he", "en"], "PL": ["pl"], "SE": ["sv", "en"], "NO": ["no", "en"],
    "MA": ["ar", "fr"], "PK": ["en", "ur"], "BD": ["bn", "en"], "UA": ["uk", "ru"],
}


# ============================================================================
# COUNTRY_DOMAINS — Tier-A: known income-discussion domains per country.
# google_universal builds `site:<domain> <kw>` queries from this dict.
# Excludes domains we directly crawl (set via COVERED_BY_DEDICATED).
# ============================================================================
COUNTRY_DOMAINS = {
    "US": [
        "bogleheads.org", "biggerpockets.com", "mrmoneymustache.com",
        "earlyretirementextreme.com", "fatfire.com", "leanfire.com",
        "thefinancebuff.com", "physicianonfire.com", "mymoneywizard.com",
        "fatfire.com", "indeed.com",
    ],
    "CN": [
        "xueqiu.com", "36kr.com", "kanzhun.com", "zhipin.com",
        "lagou.com", "hupu.com", "tieba.baidu.com", "douban.com",
        "toutiao.com", "wallstreetcn.com", "huxiu.com", "ifanr.com",
    ],
    "JP": [
        "hatena.ne.jp", "mynavi.jp", "doda.jp", "rikunabi.com",
        "type.jp", "en-japan.com", "girlschannel.net", "bizjournal.jp",
        "nikkei.com", "mynavi-agent.jp",
    ],
    "KR": [
        "clien.net", "ppomppu.co.kr", "saramin.co.kr", "jobplanet.co.kr",
        "jobkorea.co.kr", "wanted.co.kr", "remember.co.kr", "ilbe.com",
        "fmkorea.com", "ruliweb.com",
    ],
    "IN": [
        "quora.com", "telegram.org", "jobbuzz.timesjobs.com", "shine.com",
        "indeed.co.in", "indianexpress.com", "moneycontrol.com",
        "inshorts.com", "instamojo.com",
    ],
    "DE": [
        "xing.com", "stepstone.de", "finanzen.net", "wallstreet-online.de",
        "gulli.com", "computerbase.de", "mydealz.de", "gutefrage.net",
        "studis-online.de", "fragwürdig.de",
    ],
    "GB": [
        "reed.co.uk", "totaljobs.com", "citywire.co.uk", "moneymarketing.co.uk",
        "thisismoney.co.uk", "moneyweek.com", "ftadviser.com",
        "indeed.co.uk", "money.co.uk", "ukbusinessforums.co.uk",
    ],
    "FR": [
        "jeuxvideo.com", "forum.hardware.fr", "doctissimo.fr", "glassdoor.fr",
        "indeed.fr", "lesalaire.fr", "cadremploi.fr", "hellowork.com",
        "lemonde.fr", "lesechos.fr", "bfmtv.com",
    ],
    "BR": [
        "catho.com.br", "glassdoor.com.br", "twitter.com",
        "infomoney.com.br", "exame.com", "valor.globo.com",
        "b3.com.br", "investidor10.com.br",
    ],
    "RU": [
        "yandex.ru", "banki.ru", "zen.yandex.ru", "drom.ru",
        "irecommend.ru", "otzovik.com", "fontanka.ru", "lenta.ru",
    ],
    "MX": [
        "occ.com.mx", "computrabajo.com.mx", "glassdoor.com.mx",
        "indeed.com.mx", "expansion.mx", "elfinanciero.com.mx",
    ],
    "ES": [
        "infojobs.net", "tecnoempleo.com", "burbuja.info",
        "glassdoor.es", "indeed.es", "expansion.com",
        "elconfidencial.com", "rankia.com",
    ],
    "IT": [
        "glassdoor.it", "indeed.it", "subito.it",
        "finanzaonline.com", "ilsole24ore.com", "milanofinanza.it",
        "studenti.it",
    ],
    "CA": [
        "indeed.ca", "glassdoor.ca", "workopolis.com",
        "financialpost.com", "theglobeandmail.com", "redflagdeals.com",
    ],
    "AU": [
        "seek.com.au", "glassdoor.com.au", "ozbargain.com.au",
        "afr.com", "smh.com.au", "whirlpool.net.au",
    ],
    "NL": [
        "tweakers.net", "glassdoor.nl", "indeed.nl",
        "nationalevacaturebank.nl", "monsterboard.nl", "iens.nl",
    ],
    "CH": [
        "comparis.ch", "glassdoor.ch", "indeed.ch",
        "jobs.ch", "20min.ch", "blick.ch",
    ],
    "SG": [
        "jobstreet.com.sg", "glassdoor.sg", "mycareersfuture.gov.sg",
        "edmw.sg", "stomp.straitstimes.com",
    ],
    "MY": [
        "jobstreet.com.my", "lowyat.net", "glassdoor.com.my",
        "thestar.com.my", "lowyat.net/forum", "carigold.com",
    ],
    "TH": [
        "jobsdb.com", "glassdoor.co.th", "longdo.com",
        "topgun.in.th", "thairath.co.th",
    ],
    "ID": [
        "jobstreet.co.id", "glassdoor.co.id", "kompas.com",
        "detik.com", "kaskus.co.id", "tokopedia.com",
    ],
    "PH": [
        "jobstreet.com.ph", "glassdoor.com.ph", "philnews.ph",
        "rappler.com", "abs-cbn.com",
    ],
    "VN": [
        "vietnamworks.com", "itviec.com", "topcv.vn",
        "vnexpress.net", "tuoitre.vn", "voz.vn",
    ],
    "TR": [
        "kariyer.net", "donanimhaber.com", "eksisozluk.com",
        "milliyet.com.tr", "hurriyet.com.tr", "secretcv.com",
    ],
    "SA": [
        "bayt.com", "gulftalent.com", "tanqeeb.com",
        "okaz.com.sa", "argaam.com",
    ],
    "AE": [
        "bayt.com", "gulftalent.com", "thenationalnews.com",
        "khaleejtimes.com", "gulfnews.com", "emirates247.com",
    ],
    "EG": [
        "wuzzuf.net", "bayt.com", "youm7.com",
        "ahram.org.eg", "almasryalyoum.com",
    ],
    "ZA": [
        "careerjunction.co.za", "indeed.co.za", "moneyweb.co.za",
        "fin24.com", "businesstech.co.za",
    ],
    "NG": [
        "nairaland.com", "myjobmag.com", "jobberman.com",
        "punchng.com", "vanguardngr.com", "nairametrics.com",
    ],
    "AR": [
        "bumeran.com.ar", "glassdoor.com.ar", "computrabajo.com.ar",
        "iprofesional.com", "infobae.com",
    ],
    "CO": [
        "computrabajo.com.co", "glassdoor.com.co", "elempleo.com",
        "semana.com", "elcolombiano.com",
    ],
    "CL": [
        "trabajando.com", "glassdoor.cl", "computrabajo.cl",
        "emol.com", "biobiochile.cl",
    ],
    "IL": [
        "alljobs.co.il", "glassdoor.com", "ynet.co.il",
        "globes.co.il", "calcalist.co.il",
    ],
    "PL": [
        "wykop.pl", "pracuj.pl", "olx.pl",
        "bankier.pl", "money.pl",
    ],
    "SE": [
        "flashback.org", "blocket.se", "glassdoor.se",
        "di.se", "svd.se", "aftonbladet.se",
    ],
    "NO": [
        "finansavisen.no", "finn.no", "glassdoor.com",
        "dn.no", "e24.no",
    ],
    "MA": [
        "hespress.com", "rekrute.com", "anapec.org",
        "marocannonces.com", "challenge.ma",
    ],
    "PK": [
        "rozee.pk", "mustakbil.com", "jobz.pk",
        "dawn.com", "tribune.com.pk",
    ],
    "BD": [
        "bdjobs.com", "skill.jobs", "prothomalo.com",
        "thedailystar.net",
    ],
    "UA": [
        "work.ua", "rabota.ua", "robota.ua",
        "pravda.com.ua", "lb.ua",
    ],
}

# Domains already crawled by dedicated crawlers — google_universal must skip
# `site:<domain>` queries for these to avoid double-counting.
COVERED_BY_DEDICATED = {
    "reddit.com", "news.ycombinator.com", "zhihu.com", "weibo.com",
    "xiaohongshu.com", "maimai.cn", "bilibili.com",
    "5ch.net", "note.com", "chiebukuro.yahoo.co.jp", "openwork.jp",
    "cafe.naver.com", "gallery.dcinside.com",
    "ambitionbox.com", "naukri.com", "kununu.com", "gehalt.de",
    "moneysavingexpert.com", "mumsnet.com",
    "pikabu.ru", "habr.com", "hh.ru", "vk.com", "sravni.ru",
    "vagas.com.br", "reclameaqui.com.br",
    "forocoches.com", "pantip.com", "kaskus.co.id", "tinhte.vn",
    "forums.hardwarezone.com.sg", "hardwarezone.com.sg",
    "x.com", "twitter.com", "blind", "teamblind.com",
    "levels.fyi", "glassdoor.com",
    "forbes.com", "hurun.net", "bloomberg.com",
}


# ============================================================================
# Income brackets — per-country USD/year thresholds (5 tiers).
# Hardcoded for top 11 economies; rest may be derived from World Bank API at
# runtime (see crawlers/govstats.py if implemented).
# ============================================================================
BRACKETS_5 = ["bottom", "lower_middle", "middle", "upper_middle", "top"]

# Inclusive lower bound USD/year. "top" = top 1% of the country.
COUNTRY_BRACKETS = {
    "US": {"bottom": 0,    "lower_middle": 18_000, "middle": 40_000,  "upper_middle": 90_000,  "top": 300_000},
    "CN": {"bottom": 0,    "lower_middle": 4_000,  "middle": 12_000,  "upper_middle": 30_000,  "top": 150_000},
    "JP": {"bottom": 0,    "lower_middle": 18_000, "middle": 32_000,  "upper_middle": 65_000,  "top": 200_000},
    "IN": {"bottom": 0,    "lower_middle": 2_000,  "middle": 6_000,   "upper_middle": 20_000,  "top": 100_000},
    "DE": {"bottom": 0,    "lower_middle": 22_000, "middle": 40_000,  "upper_middle": 75_000,  "top": 200_000},
    "GB": {"bottom": 0,    "lower_middle": 20_000, "middle": 38_000,  "upper_middle": 75_000,  "top": 200_000},
    "FR": {"bottom": 0,    "lower_middle": 20_000, "middle": 35_000,  "upper_middle": 65_000,  "top": 180_000},
    "BR": {"bottom": 0,    "lower_middle": 3_000,  "middle": 8_000,   "upper_middle": 25_000,  "top": 100_000},
    "RU": {"bottom": 0,    "lower_middle": 5_000,  "middle": 12_000,  "upper_middle": 30_000,  "top": 120_000},
    "MX": {"bottom": 0,    "lower_middle": 4_000,  "middle": 10_000,  "upper_middle": 25_000,  "top": 90_000},
    "KR": {"bottom": 0,    "lower_middle": 18_000, "middle": 32_000,  "upper_middle": 65_000,  "top": 200_000},
    # Defaults for unspecified countries — derived as 0.3x / 1x / 2x / 8x of country median income (USD/yr)
    # Will be filled in at runtime by analyze.bracket_resolver.
    "DEFAULT": {"bottom": 0, "lower_middle": 5_000, "middle": 15_000, "upper_middle": 40_000, "top": 150_000},
}


# ============================================================================
# Earning mechanisms — closed list. LLM picks ≥1 per record (multiple_streams
# is reserved for the meta case where ≥3 mechanisms are present).
# ============================================================================
EARNING_MECHANISMS = [
    "salary_employment",      # W-2 / PAYE / 给工资
    "equity_compensation",    # RSU, ESOP, options vesting
    "business_owner",         # owns registered business with employees
    "freelance_contractor",   # 1099 / freiberuflich / 自由职业 — solo professional
    "platform_gig",           # Uber/DoorDash/美团/Fiverr — per-task marketplace
    "passive_investment",     # dividends, capital gains, interest, crypto
    "real_estate_rental",     # landlord
    "royalties_creator",      # YouTube/Twitch/Substack/OF/印税/打赏
    "inheritance_trust",      # family wealth, trust distributions
    "government_pension",     # social security, 年金, retirement, disability
    "illicit_grey",           # cash-in-hand, crime, sex work, grey-market
    "multiple_streams",       # explicitly diversified (≥3 of above)
]


# ============================================================================
# Industries — port from reddit_spider for compatibility
# ============================================================================
INDUSTRY_LABELS = [
    "tech_software", "finance_banking", "healthcare", "law", "education",
    "engineering_nonsoftware", "sales", "marketing", "blue_collar_trades",
    "food_service", "freelance_consulting", "entrepreneur_ecom",
    "government_military", "design_creative", "content_creator",
    "logistics_transport", "manufacturing", "agriculture", "real_estate",
    "retail", "energy_mining", "pharma_biotech", "other",
]


# ============================================================================
# Income-related keywords per language. Used by:
#   - dedicated crawlers (search query seeds)
#   - google_universal (free-search + site:-anchored search)
#   - common.is_on_topic_<lang>
# Aim ~12-18 per language. Mix:
#   - "how much do you earn / 年收入 / 年収 / 연봉 / Gehalt / cuánto ganas"
#   - "side hustle / 副业 / 副業"
#   - "salary breakdown / 工资单 / total compensation"
#   - "passive income / 被动收入 / 不労所得"
# ============================================================================
INCOME_KEYWORDS = {
    "en": [
        "salary breakdown", "how much do you earn", "annual income",
        "total compensation", "side hustle income", "passive income",
        "money diary", "income breakdown", "net worth journey",
        "how I make money", "career change salary", "freelance income",
        "FIRE journey", "millionaire AMA", "six figures",
        "minimum wage to", "from poverty to", "share your salary",
    ],
    "zh": [
        "年收入", "月收入", "工资单", "晒工资", "我是怎么赚到",
        "月入十万", "月入5万", "副业收入", "被动收入", "财务自由",
        "创业收入", "我的赚钱方式", "下海经商", "互联网大厂工资",
        "我的收入构成", "如何月入过万",
    ],
    "ja": [
        "年収", "月収", "給料", "副業 収入", "稼ぎ方", "手取り",
        "賞与", "ボーナス", "不労所得", "FIRE達成", "個人事業主",
        "フリーランス収入", "サラリーマン年収", "高年収",
    ],
    "ko": [
        "연봉", "월급", "수입", "부업", "투잡", "재테크",
        "월수입", "노후 자금", "파이어족", "프리랜서 수입",
        "자영업 수입", "어떻게 돈을 버는가", "고소득",
    ],
    "de": [
        "Gehalt", "Einkommen", "wie viel verdient ihr",
        "Gehaltsthread", "Nebeneinkommen", "Selbstständigkeit",
        "passives Einkommen", "Nettoeinkommen", "Brutto",
        "freiberuflich Einkommen", "wie viel verdient man als",
    ],
    "fr": [
        "salaire", "combien gagnez-vous", "revenus complémentaires",
        "salaire métier", "freelance revenus", "revenus passifs",
        "combien gagne un", "salaire brut", "indépendant revenus",
    ],
    "es": [
        "cuánto ganas", "sueldo profesión", "ingresos extra",
        "cómo gano dinero", "ingresos pasivos", "salario bruto",
        "trabajo autónomo ingresos", "FIRE jubilación anticipada",
    ],
    "pt": [
        "quanto você ganha", "salário profissão", "renda extra",
        "como ganho dinheiro", "renda passiva", "MEI faturamento",
        "freelancer renda", "FIRE independência financeira",
    ],
    "ru": [
        "зарплата", "доход", "сколько зарабатываете",
        "пассивный доход", "фриланс доход", "подработка",
        "как заработать", "финансовая независимость",
    ],
    "it": [
        "stipendio", "quanto guadagni", "entrate extra",
        "reddito passivo", "freelance reddito", "guadagno",
    ],
    "tr": [
        "maaş", "ne kadar kazanıyorsunuz", "ek gelir",
        "pasif gelir", "freelance kazanç", "yan iş",
    ],
    "ar": [
        "راتب", "دخل", "كم تكسب", "دخل سلبي",
        "عمل حر دخل", "كيف تكسب المال",
    ],
    "hi": [
        "वेतन", "आय", "कितना कमाते हैं", "साइड बिजनेस",
        "पैसिव इनकम", "फ्रीलांस आय",
    ],
    "id": [
        "gaji", "pendapatan", "berapa pendapatan",
        "penghasilan tambahan", "freelance pendapatan",
    ],
    "th": [
        "เงินเดือน", "รายได้", "หาเงิน", "รายได้เสริม",
        "ฟรีแลนซ์", "อาชีพ เงินเดือน",
    ],
    "vi": [
        "lương", "thu nhập", "kiếm tiền", "thu nhập thụ động",
        "freelance thu nhập",
    ],
    "pl": [
        "pensja", "zarobki", "ile zarabiacie", "dochód pasywny",
        "freelancer zarobki",
    ],
    "nl": [
        "salaris", "inkomen", "hoeveel verdien jij",
        "freelance inkomen", "passief inkomen",
    ],
    "sv": [
        "lön", "inkomst", "hur mycket tjänar du",
        "passiv inkomst", "frilans inkomst",
    ],
    "no": [
        "lønn", "inntekt", "hvor mye tjener du",
        "passiv inntekt", "frilans inntekt",
    ],
    "uk": [
        "зарплата", "дохід", "скільки заробляєте",
        "пасивний дохід", "фріланс дохід",
    ],
    "he": [
        "משכורת", "הכנסה", "כמה אתה מרוויח",
        "הכנסה פסיבית", "פרילנס הכנסה",
    ],
    "ms": [
        "gaji", "pendapatan", "berapa gaji anda",
        "pendapatan sampingan", "kerja bebas",
    ],
    "bn": [
        "বেতন", "আয়", "কত আয়", "ফ্রিল্যান্স আয়",
    ],
    "ur": [
        "تنخواہ", "آمدنی", "کتنا کماتے ہیں",
    ],
}


# ============================================================================
# On-topic filter tokens — broader (substring match in title+body).
# An item must contain at least one in its language to be saved.
# ============================================================================
TOPIC_TOKENS = {
    "en": [
        "salary", "income", "earn", "wage", "bonus", "equity",
        "side hustle", "freelance", "net worth", "rental", "dividend",
        "compensation", "paycheck", "comp", "401k", "passive",
        "$", "k/yr", "/hr", "/year", "annual",
        "figures", "millionaire", "make money", "make a living",
        "afford", "rich", "wealth", "get rich",
    ],
    "zh": [
        "工资", "收入", "薪资", "薪水", "赚", "挣", "奖金",
        "副业", "被动", "年薪", "月薪", "时薪", "总包",
        "¥", "元", "万", "财务自由", "财富",
    ],
    "ja": [
        "年収", "月収", "給料", "賃金", "副業", "ボーナス",
        "不労所得", "稼", "手取り", "¥", "円", "万",
    ],
    "ko": [
        "연봉", "월급", "수입", "급여", "부업", "보너스",
        "원", "만원", "재테크", "수익",
    ],
    "de": [
        "Gehalt", "Einkommen", "Lohn", "Bonus", "Nebeneinkommen",
        "Brutto", "Netto", "€", "Euro", "passiv",
    ],
    "fr": [
        "salaire", "revenu", "gagner", "bonus", "freelance",
        "€", "euro", "passif", "indépendant",
    ],
    "es": [
        "sueldo", "salario", "ingreso", "ganar", "bono",
        "freelance", "€", "$", "pasivo", "autónomo",
    ],
    "pt": [
        "salário", "renda", "ganhar", "bonus", "freelancer",
        "R$", "passivo", "MEI",
    ],
    "ru": [
        "зарплата", "доход", "заработок", "бонус", "фриланс",
        "руб", "₽", "пассивный",
    ],
    "it": [
        "stipendio", "reddito", "guadagno", "bonus", "freelance",
        "€", "euro", "passivo",
    ],
    "tr": [
        "maaş", "gelir", "kazanç", "bonus", "freelance",
        "₺", "TL", "pasif",
    ],
    "ar": [
        "راتب", "دخل", "ربح", "حر", "ريال", "درهم",
    ],
    "hi": [
        "वेतन", "आय", "कमाना", "फ्रीलांस", "रुपये", "₹",
    ],
    "id": ["gaji", "pendapatan", "penghasilan", "Rp", "freelance"],
    "th": ["เงินเดือน", "รายได้", "บาท", "฿"],
    "vi": ["lương", "thu nhập", "VND", "đồng"],
    "pl": ["pensja", "zarobki", "PLN", "zł"],
    "nl": ["salaris", "inkomen", "€"],
    "sv": ["lön", "inkomst", "kr", "SEK"],
    "no": ["lønn", "inntekt", "kr", "NOK"],
    "uk": ["зарплата", "дохід", "₴", "грн"],
    "he": ["משכורת", "הכנסה", "₪"],
    "ms": ["gaji", "pendapatan", "RM"],
    "bn": ["বেতন", "আয়", "টাকা"],
    "ur": ["تنخواہ", "آمدنی", "روپے"],
}


# ============================================================================
# Country detection keywords (multi-language hints in text body)
# ============================================================================
COUNTRY_KEYWORDS = {
    "US": ["usa", "united states", "america", "american", "nyc", "california", "texas",
           "florida", "new york", "chicago", "los angeles", "san francisco", "seattle",
           "boston", "austin", "401k", "roth ira", "$", "mcol", "hcol", "lcol"],
    "GB": ["uk", "united kingdom", "britain", "england", "london", "scotland", "wales",
           "manchester", "£", "nhs", "paye", "isa"],
    "CA": ["canada", "canadian", "toronto", "vancouver", "montreal", "cad",
           "ontario", "tfsa", "rrsp", "loonie"],
    "AU": ["australia", "australian", "sydney", "melbourne", "aud",
           "aussie", "super fund", "superannuation"],
    "DE": ["germany", "german", "berlin", "munich", "münchen", "deutschland", "€"],
    "FR": ["france", "french", "paris", "lyon", "marseille"],
    "JP": ["japan", "japanese", "tokyo", "osaka", "¥", "yen", "東京", "日本"],
    "CN": ["china", "chinese", "beijing", "shanghai", "shenzhen", "rmb", "yuan",
           "wechat pay", "alipay", "中国", "北京", "上海", "深圳", "广州", "杭州"],
    "IN": ["india", "indian", "mumbai", "bangalore", "bengaluru", "delhi",
           "inr", "rupee", "lakh", "crore", "₹"],
    "KR": ["korea", "korean", "seoul", "won", "한국", "서울", "원"],
    "BR": ["brazil", "brazilian", "brasil", "são paulo", "rio", "brl", "R$"],
    "RU": ["russia", "russian", "moscow", "санкт-петербург", "москва", "рубль", "₽"],
    "MX": ["mexico", "mexican", "méxico", "guadalajara", "monterrey"],
    "ES": ["spain", "spanish", "madrid", "barcelona", "españa", "valencia"],
    "IT": ["italy", "italian", "rome", "milan", "italia", "roma"],
    "NL": ["netherlands", "dutch", "amsterdam", "nederland"],
    "CH": ["switzerland", "swiss", "zurich", "chf", "geneva", "schweiz"],
    "SG": ["singapore", "singaporean", "sgd", "cpf"],
    "MY": ["malaysia", "malaysian", "kuala lumpur", "ringgit", "rm "],
    "TH": ["thailand", "thai", "bangkok", "baht", "ประเทศไทย"],
    "ID": ["indonesia", "indonesian", "jakarta", "rupiah", "Rp"],
    "PH": ["philippines", "filipino", "manila", "peso"],
    "VN": ["vietnam", "vietnamese", "hanoi", "VND", "việt nam"],
    "TR": ["turkey", "turkish", "istanbul", "lira", "türkiye"],
    "SA": ["saudi", "riyadh", "jeddah", "السعودية"],
    "AE": ["uae", "dubai", "abu dhabi", "emirates", "الإمارات"],
    "EG": ["egypt", "egyptian", "cairo", "مصر"],
    "ZA": ["south africa", "johannesburg", "cape town", "rand"],
    "NG": ["nigeria", "nigerian", "lagos", "naira"],
    "AR": ["argentina", "buenos aires", "argentine", "argentino"],
    "CO": ["colombia", "colombian", "bogota", "bogotá"],
    "CL": ["chile", "chilean", "santiago"],
    "IL": ["israel", "israeli", "tel aviv", "shekel", "ישראל"],
    "PL": ["poland", "polish", "warsaw", "zloty", "warszawa"],
    "SE": ["sweden", "swedish", "stockholm", "sek"],
    "NO": ["norway", "norwegian", "oslo", "nok"],
    "MA": ["morocco", "moroccan", "casablanca", "rabat", "المغرب"],
    "PK": ["pakistan", "pakistani", "karachi", "lahore", "rupee"],
    "BD": ["bangladesh", "bangladeshi", "dhaka", "taka"],
    "UA": ["ukraine", "ukrainian", "kyiv", "kiev", "hryvnia", "україна"],
}


# ============================================================================
# Industry keywords — broader, multi-language stub. Default heuristics.
# (Reused by reddit_import; LLM extracts canonical labels later.)
# ============================================================================
INDUSTRY_KEYWORDS = {
    "tech_software": ["software", "developer", "programmer", "engineer", "tech",
                      "data scientist", "machine learning", "ai", "cloud",
                      "devops", "frontend", "backend", "fullstack", "saas",
                      "faang", "coding", "computer science", "sysadmin",
                      "cybersecurity", "infosec", "qa", "product manager",
                      "程序员", "开发", "码农", "工程师", "プログラマ", "エンジニア",
                      "개발자", "프로그래머"],
    "finance_banking": ["finance", "banking", "investment", "trader", "accountant",
                        "cpa", "financial analyst", "hedge fund", "private equity",
                        "wall street", "fintech", "actuary", "auditor", "cfp",
                        "金融", "银行", "基金", "投行", "金融機関"],
    "healthcare": ["doctor", "nurse", "physician", "surgeon", "dentist",
                   "pharmacist", "therapist", "healthcare", "medical",
                   "医生", "护士", "医師", "看護師", "의사", "간호사"],
    "law": ["lawyer", "attorney", "law firm", "paralegal", "legal", "biglaw",
            "律师", "弁護士", "변호사"],
    "education": ["teacher", "professor", "tutor", "education", "school",
                  "university", "academia", "lecturer", "adjunct",
                  "教师", "教授", "教師", "先生", "교사", "교수"],
    "engineering_nonsoftware": ["mechanical engineer", "civil engineer", "electrical",
                                "chemical engineer", "aerospace", "structural",
                                "petroleum engineer", "biomedical"],
    "sales": ["sales", "sdr", "account executive", "business development",
              "commission", "quota", "b2b", "b2c", "saas sales", "销售",
              "営業", "영업"],
    "marketing": ["marketing", "advertising", "copywriter", "seo",
                  "social media", "digital marketing", "brand manager"],
    "blue_collar_trades": ["electrician", "plumber", "welder", "carpenter", "hvac",
                           "mechanic", "construction", "truck driver", "cdl",
                           "blue collar", "trade", "union", "apprentice"],
    "food_service": ["restaurant", "bartender", "server", "waiter", "chef",
                     "cook", "barista", "food service", "hospitality"],
    "freelance_consulting": ["freelance", "self-employed", "consultant", "contractor",
                             "1099", "solopreneur", "consulting", "自由职业",
                             "フリーランス", "프리랜서"],
    "entrepreneur_ecom": ["entrepreneur", "founder", "startup", "business owner",
                          "e-commerce", "dropshipping", "amazon fba", "shopify",
                          "创业", "电商", "起業", "창업"],
    "government_military": ["government", "federal", "military", "army", "navy",
                            "air force", "civil service", "公务员", "軍人", "公務員"],
    "design_creative": ["designer", "graphic design", "ux", "ui", "photographer",
                        "videographer", "animator", "illustrator", "art director"],
    "content_creator": ["youtuber", "streamer", "influencer", "content creator",
                        "blogger", "podcaster", "twitch", "tiktok", "instagram",
                        "网红", "博主", "ユーチューバー"],
    "logistics_transport": ["logistics", "supply chain", "warehouse", "delivery",
                            "trucking", "pilot", "airline", "uber", "lyft",
                            "外卖", "快递", "配達"],
    "manufacturing": ["manufacturing", "factory", "production", "machinist",
                      "cnc", "quality control", "plant manager", "工厂"],
    "agriculture": ["farming", "agriculture", "ranch", "crop", "livestock", "农民"],
    "real_estate": ["real estate", "property", "landlord", "rental income",
                    "flipping", "property manager", "realtor", "broker", "中介",
                    "房产", "不動産"],
    "retail": ["retail", "store", "shop", "customer service", "cashier"],
    "energy_mining": ["oil", "gas", "mining", "energy", "petroleum", "solar",
                      "wind power", "offshore"],
    "pharma_biotech": ["pharma", "pharmaceutical", "biotech", "clinical trial",
                       "research scientist", "lab", "fda"],
}


# ============================================================================
# Per-platform scale + parallelism caps
# ============================================================================
_smoke = bool(os.environ.get("SMOKE_TEST"))

PER_PLATFORM_LIMIT = 50 if _smoke else 4000
PER_KEYWORD_LIMIT = 10 if _smoke else 80
PAGES_PER_QUERY = 1 if _smoke else 4
GOOGLE_PAGES_PER_QUERY = 1 if _smoke else 3
HN_HITS_PER_QUERY = 30 if _smoke else 200

MAX_PLATFORM_WORKERS = 10
MAX_CONCURRENT_REQUESTS_PER_PLATFORM = 8
PLAYWRIGHT_MAX_CONTEXTS = 4
REQUEST_TIMEOUT_SEC = 30
POLITENESS_DELAY_MS = (500, 2000)

# Per-platform wall-clock budget — each crawler's run() should check
# (time.time() - start) > PLATFORM_TIME_BUDGET_SEC and exit cleanly.
PLATFORM_TIME_BUDGET_SEC = int(os.environ.get("PLATFORM_TIME_BUDGET_SEC", 21600))


# ============================================================================
# UA pool
# ============================================================================
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

UA_POOL = [
    UA,
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]


# Reddit data path — points to the existing 641MB reddit_money_detailed.csv
REDDIT_CSV_PATH = Path("/Users/jan/sen/code/spider/reddit_spider/data/reddit_money_detailed.csv")
