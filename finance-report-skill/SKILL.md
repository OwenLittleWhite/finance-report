---
name: finance-report
description: Generate professional A-share stock research reports (个股研报). Use this skill whenever the user wants to analyze a stock, create a research report (研报), perform company valuation (估值), or mentions any A-share stock code (like 601318, 000001, 300750). Also triggers on keywords like 研报, 个股分析, 股票分析, 估值报告, investment report, stock analysis. Even if the user just says "帮我分析一下平安" or gives a stock code, use this skill.
---

# A股研报生成器 (Finance Report Generator)

Generate professional equity research reports for A-share listed companies. Three-stage pipeline: data fetching → AI analysis → PDF rendering.

## Workflow

```
Step 1: 用户输入股票代码
Step 2: fetch_data.py 抓取数据
Step 3: Claude 分析数据，生成 analysis.json
Step 4: generate_report.py 渲染 PDF
Step 5: Claude 审核 PDF，发现问题则修改 analysis.json 重新生成
```

## Step 1: Get User Input

Ask the user for a **6-digit A-share stock code** (e.g., `601318`). Default to 简单版 (2-page).

## Step 2: Fetch Data

```bash
python <skill-path>/scripts/fetch_data.py <stock_code> ./<stock_code>
```

Fetches from East Money APIs (no auth). Output files:

| File | Content | Key Fields |
|------|---------|------------|
| `quote.json` | 实时行情 | f43(现价), f60(昨收), f162(PE_TTM), f167(PB) |
| `company_survey.json` | 公司概况 | gsmc(公司名), gsjj(简介), jyfw(经营范围) |
| `income.json` | 利润表 ×12期 | TOTAL_OPERATE_INCOME, PARENT_NETPROFIT |
| `balance.json` | 资产负债表 ×12期 | TOTAL_ASSETS, TOTAL_LIABILITIES, TOTAL_PARENT_EQUITY |
| `cashflow.json` | 现金流表 ×12期 | NETCASH_OPERATE, NETCASH_INVEST, NETCASH_FINANCE |
| `dividend.json` | 分红历史 | PRETAX_BONUS_RMB, EX_DIVIDEND_DATE |
| `kline.json` | 日K线(250天) | 日期,开,收,高,低,量,额 |
| `mainop.json` | 主营构成 | 产品/地区分类收入占比 |
| `guba.json` | 股吧帖子 | 帖子标题, 阅读数, 评论数 |

### Financial Data Structure (重要)

财务三表每个文件包含 **12条记录 = 3年 × 4种报告期**：

| DATE_TYPE_CODE | 含义 | 日期格式 | 性质 |
|---|---|---|---|
| 001 | 年报 | YYYY-12-31 | 完整年度（期间数据的全年累计） |
| 002 | 中报 | YYYY-06-30 | 上半年累计 |
| 003 | 一季报 | YYYY-03-31 | Q1单季 |
| 004 | 三季报 | YYYY-09-30 | 前三季度累计 |

**关键概念**：
- 利润表和现金流表是**期间数据**（累计值）：Q3数据 = 前三季度合计，不是Q3单季
- 资产负债表是**时点数据**：反映报告日当天的资产负债快照
- 数据按日期倒序排列，`[0]` 是最新一期

## Step 3: AI Analysis (KEY STEP)

Read ALL the JSON files in the stock directory, then write `analysis.json`:

```json
{
  "business_summary": "150字以内的业务概述，总结提炼而非复制原文",
  "core_thesis": "3-5句核心投资观点。用最新季度同比讲边际趋势，用年度数据讲长期逻辑",
  "price_commentary": "股价走势分析，引用具体涨跌幅和52周区间数据",
  "financial_commentary": "营收利润分析。先讲最新季报边际变化，再用年度趋势对比",
  "balance_commentary": "资产负债分析。引用最新季度末时点数据（总资产、负债率）",
  "cashflow_commentary": "现金流分析。年度为主线，季度累计为参考，说明季节性",
  "dividend_commentary": "分红分析，评估股东回报",
  "valuation_analysis": "估值方法说明和关键假设",
  "guba_analysis": "股吧舆情分析，总结散户情绪和关注焦点",
  "risk_factors": ["风险1", "风险2", "风险3"],
  "rating": "买入/增持/中性/减持",
  "rating_reason": "评级理由，综合多因素"
}
```

### Analysis Guidelines

1. **基于数据说话** — 每个观点必须有具体数字支撑，不能空泛
2. **不要粉饰** — 亏损就说亏损，下滑就说下滑，不要回避负面数据
3. **业务概述要总结** — 不要直接复制原文，用150字概括核心业务和竞争地位
4. **核心观点要有逻辑** — 不是罗列数字，而是讲投资故事（为什么值得/不值得关注）
5. **风险要具体** — 结合该公司实际业务和财务状况，不要写泛泛的行业风险

### Data Freshness Principle (年季结合)

不同类型的财务数据，用法不同——年度是骨架（看趋势），季度是神经末梢（感知变化）：

| 数据类型 | 用什么 | 为什么 |
|---------|-------|-------|
| 资产负债表 | **最新一期**（不管年/季） | 时点数据，越新越准 |
| 利润表 | **季度同比**讲边际 + **年度**讲趋势 | 投资者最关心"加速还是减速" |
| 现金流表 | **年度为主** + 季度参考 | 季报是累计值且季节性强，单看易误判 |
| 成长性 | **最新季度同比**是核心 | 时效性最强的增长信号 |

**写法示范**：
- ❌ "2024年营收247亿元"（只有年报，缺乏时效性）
- ✅ "2025Q3累计营收210亿（同比+27.8%），增速较2024全年41.4%有所放缓但仍在高位"
- ❌ "总资产166亿元"（用了年报旧数据）
- ✅ "截至2025Q3总资产200亿元，较2024年末166亿元增长20%"
- ❌ "2025Q3经营现金流为负，造血能力差"（忽略季节性）
- ✅ "2024全年经营现金流27.5亿元，盈利含金量高。2025Q3累计-8.6亿元，主要受季节性备货影响"

### Rating Methodology

综合以下因子判断评级，不能只看估值空间：
- **估值水平**：PE/PB 相对历史和行业是否合理
- **盈利能力**：ROE 水平、是否盈利、利润趋势
- **成长性**：营收/利润增速、**最新季报的边际变化方向**
- **财务健康**：最新季度末的资产负债率、年度现金流质量
- **分红回报**：股息率（注意：超过2年未分红的不计股息率）
- **市场情绪**：股吧舆情的情绪倾向

### Price Handling

股价数据优先取实时价（f43），非交易时间可能为 0，自动 fallback：实时价 → 昨收价（f60）→ K线最后收盘价。`generate_report.py` 已内置此逻辑。Claude 在分析中应使用"当前价位"而非"实时价格"措辞。

### Valuation

估值由 `generate_report.py` 自动计算（PE/PB/PEV等），使用 **TTM EPS**（滚动12个月每股收益）而非年报 EPS 作为估值基础：

```
TTM净利润 = 最近年报净利润 + 最新季报累计净利润 - 去年同期累计净利润
例：2025Q3时 TTM = 2024年报 + 2025Q3累计 - 2024Q3累计
```

TTM 的优势：既反映最新盈利能力，又是完整12个月消除了季节性。直接用季报累计（如Q3的9个月数据）做分母会导致PE失真。

Claude 在 `valuation_analysis` 中补充文字说明：为什么选这个方法、关键假设、与市场估值的比较。

### Dividend Yield Rule

如果公司最近一次分红距今超过2年，则股息率显示为"—"，不计入评级考量。在分析中应说明"公司已较长时间未实施分红"。

## Step 4: Generate Report

```bash
python <skill-path>/scripts/generate_report.py ./<stock_code>
```

The script reads `analysis.json` + raw data files → generates HTML with ECharts → converts to PDF via Playwright.

## Step 5: Review & Adjust

生成 PDF 后审核报告质量：

1. **转成图片查看**：
   ```bash
   pdftoppm -png -r 200 ./<stock_code>/report.pdf ./<stock_code>/pdf_page
   ```

2. **检查项**：
   - ✅ 严格2页，没有溢出到第三页
   - ✅ 表格数据正确、没有截断
   - ✅ 图表正常渲染（K线图、营收利润图、词云、主营构成图）
   - ✅ 分析文字合理、没有事实错误
   - ✅ 股价不为0（非交易时间应显示昨收价）
   - ✅ footer 在页面底部可见

3. **常见问题及修复**：

| 问题 | 原因 | 修复方法 |
|------|------|---------|
| 溢出到第三页 | commentary 文字过长 | 缩短 analysis.json 中对应字段的文字，每段控制在80字以内 |
| 股价显示0 | 非交易时间f43为0 | 代码已自动 fallback，若仍为0检查 quote.json 的 f60 字段 |
| JSON解析失败 | analysis.json 中有中文引号 `""` | 中文引号只能出现在字符串值内部，不能用作 JSON 的键值界定符。用 `「」` 代替或用 Python 的 `json.dump()` 重写 |
| 数据用的旧年报 | 分析时忽略了季报 | 检查 income/balance/cashflow.json 的第一条记录（最新期），确保分析引用了它 |

4. **最多审核调整2轮**，然后交付给用户

### Commentary Length Guidelines

Page 2 空间有限，每段 commentary 需控制长度：

| 字段 | 建议长度 | 说明 |
|------|---------|------|
| financial_commentary | 60-100字 | 在 Page 1，空间较充裕 |
| balance_commentary | 60-80字 | Page 2 两表共用一段评论 |
| cashflow_commentary | 60-80字 | 同上 |
| dividend_commentary | 40-60字 | Page 2 分红表下方 |
| guba_analysis | 60-80字 | Page 2 词云下方 |
| valuation_analysis | 由脚本自动处理 | — |

如果审核发现 Page 2 溢出，优先缩短 balance_commentary 和 cashflow_commentary。

## Industry → Valuation Method Mapping

| Industry | Primary | Secondary |
|----------|---------|-----------|
| 银行 | PB-ROE | PE |
| 保险 | PEV (内含价值) | PB |
| 证券 | PB | PE |
| 消费/医药 | PE | PEG |
| 科技/半导体 | PS / PE | PEG |
| 周期性(钢铁/煤炭/化工) | PB | 正常化PE |
| 公用事业 | PE | 股息率 |
| 其他 | PE + PB | — |

## Report Structure (简单版 2 Pages)

**Page 1**: 标题+评级 → 9格指标 → 核心观点 → 股价走势图+评论 → 财务预测表(年度+预测)+评论 → 业务概述 → 公司信息 → 主营构成图

**Page 2**: 最新季度数据+评论 → 资产负债表(2年+最新季度)+现金流表(2年+最新季度)+评论 → 营收利润柱状图 → 分红历史+词云+评论 → 估值分析+评级+风险

## Dependencies

```bash
pip install requests playwright jieba
playwright install chromium
```

## Notes

- All East Money APIs are public, no authentication needed
- Intermediate data saved as JSON for reproducibility
- PDF: A4 format, KaiTi font, Playwright Chromium rendering
- Stock data directory: `./<stock_code>/` contains all data + analysis + report
- Each page fixed at 297mm (A4 height), overflow hidden, footer absolute-positioned at bottom
