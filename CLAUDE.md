# shouru — 跨国收入与谋生方式研究

## 项目目标

回答「世界各国、各收入阶层的人，分别通过什么方式获得当前收入？」
（"美国年入百万美元的"、"中国月入 10 万的" …）

40+ 国 × 5 收入档（bottom / lower_middle / middle / upper_middle / top）×
12 类谋生机制（salary / equity / business / freelance / gig / passive /
rental / royalties / inheritance / pension / illicit / multiple）。

## 关键用户约束（必须遵守）

1. **必须本地母语原文**。已不再加新的英文 Reddit。
2. **货币符号必须明确记录**。绝对不能默认 USD。Schema 已分
   `income_amount_local + currency + period`，转 USD/年 由
   `extract/fx_normalize.py` 完成（带 `fx_rate_used` 审计字段）。
3. **不用 ANTHROPIC_API_KEY**。用户是 Claude 月度订阅。LLM 抽取走 subagent。
4. **subagent 写代码 → 主 agent Bash 跑**。subagent 在 sandbox 没网络，
   `python` 被 deny。
5. **subagent 抽取必须 terse prompt + chunk_size=20**。60 条/chunk 会
   stream watchdog 600s 超时死。验证过 20 条/chunk 平均 60-80s 跑通。

## 当前数据状态（2026-05-07 早 8:10 时间戳）

### 1. raw 已爬完 ✅

```
data/raw/*_native_*.jsonl  ← 14177 行 / 79 国 / 27 语 / 166 平台
```

详细分布见 `data/curated/native_raw_summary.md`。爬虫已经全部跑完，
**不需要再爬新数据**。死掉的站（CF 反爬）已放弃：
MoneySavingExpert, Mumsnet, Boards.ie, voz.vn, cari.com.my, PTT.cc,
Mobile01, Dcard, discuss.com.hk, 36kr 等。

### 2. LLM 抽取部分完成 ⏳

```
data/extracted/
  ├── chunks_small/         ← 703 chunks × 20 raw records (待抽取)
  ├── chunk_outputs_small/  ← 116 chunks 已抽 (555 IncomeRecord, 1761 skip)
  ├── _native_to_extract.jsonl   ← 14060 raw 合并 + dedupe
  ├── extracted_native_20260507.jsonl  ← 116 chunks merge 后入库源
  └── SYSTEM_PROMPT.txt     ← 抽取 prompt (subagent 必读)
```

**进度 116/703 (16.5%)**。剩余 587 chunks 没抽取。配额恢复后可继续。

### 3. income.db 已入库 ✅

```
data/curated/income.db
  - income_records: 3670 行，84 国
  - reddit_import 2328 + hackernews 787（早期英语）+ 555 新本地母语 = 3670
  - 含 USD/年: 2435 行（fx_normalize 之后）
  - fx_status 审计字段齐全
data/curated/income_records.csv  ← 同上的 CSV 导出
data/curated/figs/                ← 6 类 visualize 图（HTML+PNG）
data/curated/reports/             ← report.py 渲染 40 国 .md
```

### 4. 网站已上线（双部署）✅

**GitHub Pages（已推）**：https://atlan52.github.io/shouru/
**Local Flask（开发）**：`.venv/bin/python -m website.app` → http://localhost:5050

GitHub repo: https://github.com/atlan52/shouru （public, main 分支 /docs 目录）。
docs/ 是静态 HTML（3793 个文件）由 `website.build_static` 生成。



```
website/
  ├── app.py             ← Flask 主程序
  ├── templates/         ← 8 个 jinja 页面
  └── static/style.css

启动: cd /Users/jan/sen/code/spider/shouru && .venv/bin/python -m website.app
浏览: http://localhost:5050

路由:
  /                  ← 首页 (5 stats + 30 国卡片 + bracket/机制/职业/语言/平台分布)
  /records           ← 数据浏览 (9 维筛选 + 分页表)
  /country/<CC>      ← 单国详情 (stats + bracket + 机制 + sample 引用)
  /record/<id>       ← 单条记录详情 (FX 审计 + 原文 URL)
  /visualizations    ← 6 个 plotly 图嵌入
  /platforms         ← 166 平台分布
  /mechanisms        ← 12 机制全景 + 各国偏好
  /about             ← 方法论 + raw summary
```

数据库读 SQLite → 重跑 `load_sqlite + fx_normalize + aggregate + visualize +
report` 后网站自动更新（无需重启 Flask）。

## 目录关键文件

- `config.py` — 40 国 / `COUNTRY_DOMAINS` / `COUNTRY_BRACKETS` / 25 语言
  `INCOME_KEYWORDS` / `EARNING_MECHANISMS`
- `extract/schema.py` — Pydantic `IncomeRecord`
- `extract/prompts.py` — SYSTEM_PROMPT (10k chars, 含 5 档表 + 12 机制 + 4 例)
- `extract/fx_normalize.py` — 80+ 币种 → USD/年（已补全 PEN/LKR/KZT/UYU/JOD/
  QAR/OMR/BHD/KWD/BGN/HRK/RON/AMD/AZN/GEL/MNT/MMK/KHR/LAK/LBP/ETB 等等）
- `extract/native_chunker.py` — 把 14k raw 切 chunks (60→换 20 条版本)
- `analyze/load_sqlite.py` `aggregate.py` `visualize.py` `report.py` — 分析流水线
- `scripts/*.py` — 60+ 个抓本地母语网站的 requests+bs4 脚本（已跑完，无须再跑）
- `.venv/` — 虚拟环境（requests / bs4 / pandas / pydantic / flask / plotly /
  matplotlib / playwright（软链 token/.venv））

## 怎么继续 LLM 抽取（剩余 630 chunks）

### Subagent terse prompt 模板（验证可用，~60-80s/chunk, 4-8 extract/chunk）

每 chunk 单独 spawn 一个 subagent，prompt 模板：

```
**FAST. NO narration. ONLY tool calls.**

Read `/Users/jan/sen/code/spider/shouru/data/extracted/SYSTEM_PROMPT.txt`,
then read `/Users/jan/sen/code/spider/shouru/data/extracted/chunks_small/chunk_NNNN.jsonl`
(20 records). Write `/Users/jan/sen/code/spider/shouru/data/extracted/chunk_outputs_small/chunk_NNNN_out.jsonl`
— exactly 20 lines, each one JSON: full IncomeRecord OR
`{"skip":true,"reason":"...","record_id":"<echo>"}`. Echo
record_id/source_platform/source_url. ISO 4217 currency.
income_amount_usd_year=null. raw_excerpt original-language ≤300 chars.

ZERO commentary. Plan silently, write once.
Final report: "wrote N, K skip, M extract".
```

### 注意

- **chunk size 必须 20**，不能 60。60 触发 stream watchdog 600s 死（subagent
  还在 think 没 Write）。
- subagent 网络 deny / python deny 都没事 — 只用 Read + Write 工具。
- 一次响应里 spawn 25 个 subagent 没问题，配额够就并行。
- 一批结束后跑 merge → load_sqlite → fx_normalize → analyze。

### Merge + 入库流水（手动版）

```bash
# 1. merge chunk_outputs_small/* → 一份 extracted_native_<DAY>.jsonl
.venv/bin/python -c "
import json
from pathlib import Path
from datetime import datetime
import sys; sys.path.insert(0, '.')
from extract.schema import IncomeRecord

OUT = Path(f'data/extracted/extracted_native_{datetime.now().strftime(\"%Y%m%d\")}.jsonl')
n_ok = n_skip = n_bad = 0
with OUT.open('w', encoding='utf-8') as fout:
    for f in sorted(Path('data/extracted/chunk_outputs_small').glob('chunk_*_out.jsonl')):
        for line in f.open(encoding='utf-8'):
            try: obj = json.loads(line.strip())
            except: n_bad += 1; continue
            if obj.get('skip'): n_skip += 1; continue
            if not obj.get('extracted_at'): obj['extracted_at'] = datetime.utcnow().isoformat()+'Z'
            try: rec = IncomeRecord.model_validate(obj)
            except: n_bad += 1; continue
            fout.write(rec.model_dump_json()+'\n'); n_ok += 1
print(f'ok={n_ok} skip={n_skip} bad={n_bad} -> {OUT}')
"

# 2. 入库 + 归一 + 分析
.venv/bin/python -m analyze.load_sqlite
.venv/bin/python -m extract.fx_normalize
.venv/bin/python -m analyze.aggregate
.venv/bin/python -m analyze.visualize
.venv/bin/python -m analyze.report
```

## 失败 / 知识点（避免重踩）

- **subagent terse 强制**：60 条/chunk 会 watchdog 死。20 条 OK。Prompt 必须
  "FAST. NO narration." 否则 think 阶段就 timeout。
- subagent 网络被 deny / python deny — 只用 Read + Write 工具就行。
- `pip install` PEP 668 阻挡 → 必须 `.venv/bin/pip`。
- 大 wheel 网络超时（pyarrow / playwright）：pyarrow 跳过 CSV fallback；
  playwright 软链 `../token/.venv`。
- 德语 `40.000 €/Jahr` 千分位不是小数点 → 让 LLM parse，别让 Python parse。
- CF 反爬死的站接受死了：MSE/Mumsnet/Boards.ie/voz/cari/PTT/Dcard/Mobile01/
  discuss/36kr 等。
- TW 整国（PTT/Mobile01/Dcard）海外 IP 拦截 / SSL EOF。HK 只 LIHKG API 通但
  收入帖密度极低（财经板多政经新闻）。
- "hit your limit" 的 subagent 任务实际多数已 Write 完文件，只是汇报阶段
  超额。文件存在就 OK。
- 千万别提 ANTHROPIC_API_KEY — 用户月度订阅，没 API key。

## 当前在做什么 / 后续工作

**已完成**：
1. ✅ 14177 行本地母语 raw 爬虫（79 国 / 27 语 / 166 平台）
2. ✅ 116/703 chunks LLM 抽取 → 555 新 IncomeRecord 入库
3. ✅ income.db 3670 行 / 84 国 / 2435 含 USD/年
4. ✅ 6 类可视化图重生
5. ✅ 40 国 markdown 报告重生
6. ✅ Flask 网站全 11 路由 200 OK
7. ✅ 静态站 3793 HTML 上 GitHub Pages（atlan52/shouru, public）

**待办（按优先级）**：
1. ⏭ 配额恢复后继续抽剩余 **587 chunks**（chunk_0116 起）。每批 20-30 并发。
   按 ~5 extract/chunk 算，预期再加 ~2900 IncomeRecord，最终 ~6500 行 / 90+ 国。
2. ⏭（可选）补抓更多 raw（如用户要求新地区/语种）。
3. ⏭（可选）增强网站 — 加 leaflet 地图、profession 自动补全、跨国比较页。

## 一键继续抽取（新窗口直接复用）

```bash
cd /Users/jan/sen/code/spider/shouru

# 1. 看进度
done=$(ls data/extracted/chunk_outputs_small/ | wc -l)
echo "进度: $done / 703"
next=$(printf "%04d" $done)
echo "下一批从 chunk_$next 开始"

# 2. 用 Agent 工具 spawn N 个 subagent 并发，每个 prompt 模板：
#    "FAST. NO narration. ONLY tool calls. Read SYSTEM_PROMPT.txt + chunks_small/chunk_NNNN.jsonl,
#     write 20 lines IncomeRecord-or-skip JSON to chunk_outputs_small/chunk_NNNN_out.jsonl"

# 3. 跑完后一键合并 + 入库 + 静态化 + 推送：
.venv/bin/python -c "
import json, sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0, '.')
from extract.schema import IncomeRecord
OUT = Path(f'data/extracted/extracted_native_{datetime.now().strftime(\"%Y%m%d\")}.jsonl')
n_ok = n_skip = n_bad = 0
with OUT.open('w', encoding='utf-8') as fout:
    for f in sorted(Path('data/extracted/chunk_outputs_small').glob('chunk_*_out.jsonl')):
        for line in f.open(encoding='utf-8'):
            try: obj = json.loads(line.strip())
            except: n_bad += 1; continue
            if obj.get('skip'): n_skip += 1; continue
            if not obj.get('extracted_at'): obj['extracted_at'] = datetime.utcnow().isoformat()+'Z'
            try: rec = IncomeRecord.model_validate(obj)
            except: n_bad += 1; continue
            fout.write(rec.model_dump_json()+'\n'); n_ok += 1
print(f'merged {n_ok}/{n_ok+n_skip+n_bad}')
"
.venv/bin/python -m analyze.load_sqlite
.venv/bin/python -m extract.fx_normalize
.venv/bin/python -m analyze.aggregate
.venv/bin/python -m analyze.visualize
.venv/bin/python -m analyze.report
.venv/bin/python -m website.build_static
git add docs/ data/curated/income.db data/curated/income_records.csv data/curated/reports/ data/curated/figs/
git commit -m "更新数据"
git push
```

## 用户工作风格

- 中文回复，简洁
- 接受技术决策，不需要每步确认
- 喜欢并行 subagent / 多开（但配额满了会喊"不要多开"）
- 重视真实数据 > 漂亮报告
- 货币准确性是底线，宁可不归一 USD 也不能默认 USD
- "进度" 询问时给一句话总览即可
