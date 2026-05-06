"""Reddit data importer — reuse existing 641MB / 3.18M-row reddit_money_detailed.csv
into shouru's JSONL pipeline. NO NETWORK.

The CSV (built by /Users/jan/sen/code/spider/reddit_spider/) has Chinese column
headers. We translate to our schema:

  ID         → raw_id
  类型       → kind          (帖子 / 评论 / 子评论(层N))
  子版块     → subreddit
  帖子标题   → title
  详细内容   → body
  作者       → author        (KEPT — user opted to keep usernames+links)
  发布时间   → created_date  (YYYY-MM-DD)
  点赞数     → score
  国家       → country_hint  (e.g. 美国, 英国, 德国 → mapped to ISO-2)
  行业       → industry_hint (Chinese category — kept as hint, not canonical)
  收入阶层   → bracket_hint  (低/中低/中/中高/高)
  提及金额   → amount_hint
  内容长度   → body_length
  链接       → url
"""
import os
import time
import pandas as pd
from pathlib import Path

from config import REDDIT_CSV_PATH, RAW_DIR
from crawlers.common import append_jsonl, make_id
from crawlers.state import State

# 中文国家名 → ISO-2
COUNTRY_ZH_TO_ISO = {
    "美国": "US", "英国": "GB", "加拿大": "CA", "澳大利亚": "AU",
    "德国": "DE", "法国": "FR", "日本": "JP", "中国": "CN",
    "印度": "IN", "韩国": "KR", "巴西": "BR", "荷兰": "NL",
    "瑞士": "CH", "瑞典": "SE", "挪威": "NO", "新加坡": "SG",
    "新西兰": "NZ", "爱尔兰": "IE", "西班牙": "ES", "意大利": "IT",
    "墨西哥": "MX", "俄罗斯": "RU", "阿联酋": "AE", "沙特": "SA",
    "菲律宾": "PH", "马来西亚": "MY", "泰国": "TH", "越南": "VN",
    "印尼": "ID", "波兰": "PL", "以色列": "IL", "土耳其": "TR",
    "南非": "ZA", "尼日利亚": "NG", "埃及": "EG", "阿根廷": "AR",
    "哥伦比亚": "CO", "智利": "CL", "未知": "??", "": "??",
}

# 中文行业 → INDUSTRY_LABELS 中的英文
INDUSTRY_ZH_TO_EN = {
    "科技/IT/软件": "tech_software", "金融/银行": "finance_banking",
    "医疗/健康": "healthcare", "法律": "law", "教育": "education",
    "工程(非软件)": "engineering_nonsoftware", "销售": "sales",
    "营销/广告": "marketing", "蓝领/技工": "blue_collar_trades",
    "餐饮/服务业": "food_service", "自由职业/咨询": "freelance_consulting",
    "创业/电商": "entrepreneur_ecom", "政府/军队": "government_military",
    "设计/创意": "design_creative", "内容创作": "content_creator",
    "物流/运输": "logistics_transport", "制造业": "manufacturing",
    "农业/畜牧": "agriculture", "房地产": "real_estate", "零售": "retail",
    "能源/矿业": "energy_mining", "医药/生物": "pharma_biotech",
    "其他": "other", "未知": "other", "": "other",
}

# 中文阶层 → 5档 brackets
BRACKET_ZH_TO_EN = {
    "低收入(贫困线附近)": "bottom",
    "中低收入(入门级)": "lower_middle",
    "中等收入": "middle",
    "中高收入(6位数)": "upper_middle",
    "高收入(顶层)": "top",
    "未知": "unknown", "": "unknown",
}

CHUNK_SIZE = 20_000


def run():
    if not REDDIT_CSV_PATH.exists():
        print(f"[reddit_import] ERR: {REDDIT_CSV_PATH} does not exist")
        return

    print(f"[reddit_import] reading {REDDIT_CSV_PATH} ({REDDIT_CSV_PATH.stat().st_size / 1024 / 1024:.1f} MB)")

    state = State("reddit_import")
    smoke = bool(os.environ.get("SMOKE_TEST"))
    smoke_cap = 50

    items_added = 0
    rows_seen = 0
    start = time.time()
    try:
        for chunk in pd.read_csv(
            REDDIT_CSV_PATH,
            chunksize=CHUNK_SIZE,
            encoding="utf-8-sig",
            on_bad_lines="skip",
            dtype=str,
        ):
            for row in chunk.itertuples():
                rows_seen += 1
                raw_id = str(getattr(row, "ID", "") or "")
                if not raw_id:
                    continue
                rid = make_id("reddit", raw_id)
                if state.is_seen(rid):
                    continue

                country_zh = str(getattr(row, "国家", "") or "未知")
                industry_zh = str(getattr(row, "行业", "") or "未知")
                bracket_zh = str(getattr(row, "收入阶层", "") or "未知")

                body = str(getattr(row, "详细内容", "") or "")[:8000]
                title = str(getattr(row, "帖子标题", "") or "")[:500]
                if not body and not title:
                    continue

                try:
                    score = int(float(str(getattr(row, "点赞数", 0) or 0)))
                except (ValueError, TypeError):
                    score = 0
                try:
                    body_len = int(float(str(getattr(row, "内容长度", 0) or 0)))
                except (ValueError, TypeError):
                    body_len = len(body)

                item = {
                    "id": rid,
                    "raw_id": raw_id,
                    "platform": "reddit_import",
                    "lang": "en",  # default; LLM will refine for non-English subs
                    "kind": str(getattr(row, "类型", "") or ""),
                    "subreddit": str(getattr(row, "子版块", "") or ""),
                    "title": title,
                    "body": body,
                    "author": str(getattr(row, "作者", "") or ""),
                    "url": str(getattr(row, "链接", "") or ""),
                    "created_date": str(getattr(row, "发布时间", "") or ""),
                    "country_hint": COUNTRY_ZH_TO_ISO.get(country_zh, "??"),
                    "country_hint_zh": country_zh,
                    "industry_hint": INDUSTRY_ZH_TO_EN.get(industry_zh, "other"),
                    "bracket_hint": BRACKET_ZH_TO_EN.get(bracket_zh, "unknown"),
                    "amount_hint": str(getattr(row, "提及金额", "") or ""),
                    "body_length": body_len,
                    "engagement": {
                        "score": score, "comments": None, "views": None,
                    },
                }
                append_jsonl(item, "reddit_import", RAW_DIR)
                state.mark_seen(rid)
                items_added += 1
                if items_added % 5000 == 0:
                    state.maybe_save(every=1)
                    elapsed = time.time() - start
                    print(f"  [reddit_import] {items_added} items / {rows_seen} rows seen "
                          f"({elapsed:.0f}s, {items_added / elapsed:.0f}/s)")
                if smoke and items_added >= smoke_cap:
                    print(f"[reddit_import] SMOKE_TEST cap reached ({smoke_cap})")
                    return
    finally:
        state.save(force=True)

    elapsed = time.time() - start
    print(f"[reddit_import] done: {items_added} items / {rows_seen} rows in {elapsed:.0f}s")


if __name__ == "__main__":
    run()
