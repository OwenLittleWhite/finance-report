# Finance Report — A股个股研报生成器

一个 Claude Code Skill，输入股票代码，自动生成 2 页 PDF 研究报告。

> **免责声明**：本项目仅供学习研究使用，不构成任何投资建议。报告内容由 AI 基于公开数据自动生成，可能存在数据滞后、分析偏差等问题。投资有风险，决策需谨慎。作者不对因使用本工具产生的任何投资损失承担责任。

## 示例报告

**安克创新 (300866) — 买入**

<p>
  <img src="examples/300866-page1.png" width="45%" />
  <img src="examples/300866-page2.png" width="45%" />
</p>

**达刚控股 (300103) — 中性**

<p>
  <img src="examples/300103-page1.png" width="45%" />
  <img src="examples/300103-page2.png" width="45%" />
</p>

## 设计思路

### 三段式流水线

```
用户输入股票代码 → fetch_data.py 抓取数据 → Claude 分析写 analysis.json → generate_report.py 渲染 PDF
```

把"确定性工作"和"需要判断的工作"分开：
- **数据抓取**（确定性）→ Python 脚本，可重复、可缓存
- **投资分析**（需要判断）→ Claude 读原始数据后写分析，发挥 LLM 的推理能力
- **PDF 渲染**（确定性）→ HTML + ECharts 图表 → Playwright 转 PDF

### 年季结合的数据使用原则

财务数据不是只用年报或只用季报，而是各取所长：

| 数据类型 | 用什么 | 为什么 |
|---------|-------|-------|
| 资产负债表 | **最新一期**（不管年/季） | 时点数据，越新越准 |
| 利润表 | **季度同比**讲边际 + **年度**讲趋势 | 投资者最关心"加速还是减速" |
| 现金流表 | **年度为主** + 季度参考 | 季报是累计值且季节性强 |
| 估值 | **TTM EPS**（滚动12个月） | 既反映最新盈利能力，又消除季节性 |

### TTM EPS 估值

估值使用 TTM（Trailing Twelve Months）EPS，而非静态年报 EPS：

```
TTM净利润 = 最近年报 + 最新季报累计 - 去年同期累计
例：2025Q3 → TTM = 2024年报 + 2025Q3 - 2024Q3
```

直接用季报累计数据（如 Q3 的 9 个月）做 PE 分母会让估值失真，TTM 是正确做法。

### 报告内容（2页 A4）

**第一页**：评级+目标价 → 核心指标（9格）→ 核心观点 → K线走势图 → 财务预测表 → 业务概述 → 主营构成

**第二页**：最新季报数据 → 资产负债+现金流（2年+最新季度）→ 营收利润图 → 分红历史+股吧词云 → 估值分析+评级+风险

## 安装

### 环境要求

- Python 3.10+
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI

### 安装步骤

```bash
# 1. 克隆仓库
git clone git@github.com:OwenLittleWhite/finance-report.git

# 2. 安装 Python 依赖
pip install requests playwright jieba

# 3. 安装 Playwright 浏览器
playwright install chromium

# 4. 将 skill 添加到 Claude Code
#    把 finance-report-skill/ 目录放到 Claude Code 能识别的 skill 路径下
#    或在项目的 .claude/settings.json 中配置 skill 路径
```

### 验证安装

```bash
# 测试数据抓取（以贵州茅台为例）
python finance-report-skill/scripts/fetch_data.py 600519 ./600519

# 测试报告生成（需要先有 analysis.json）
python finance-report-skill/scripts/generate_report.py ./600519
```

## 使用方式

### 配合 Claude Code（推荐）

直接告诉 Claude 一个股票代码即可：

```
> 帮我分析一下 300866
> 给 601318 出个研报
> 分析下贵州茅台
```

Claude 会自动完成全部流程：抓取数据 → 分析 → 生成 PDF → 审核调整。

### 手动使用

```bash
# 第一步：抓取数据
python finance-report-skill/scripts/fetch_data.py 300866 ./300866

# 第二步：手动编写 analysis.json（格式参见 SKILL.md）

# 第三步：生成报告
python finance-report-skill/scripts/generate_report.py ./300866
```

## 项目结构

```
finance-report/
├── finance-report-skill/
│   ├── SKILL.md                # Skill 定义（触发规则 + 分析指南 + 工作流）
│   ├── scripts/
│   │   ├── fetch_data.py       # 东方财富数据抓取
│   │   ├── generate_report.py  # HTML/PDF 报告渲染
│   │   └── requirements.txt
│   └── references/
│       ├── api_reference.md    # 东方财富 API 文档
│       └── valuation_guide.md  # 估值方法论
├── examples/                    # 示例报告截图
└── README.md
```

### 核心文件说明

| 文件 | 说明 |
|------|------|
| `SKILL.md` | Skill 定义文件。包含完整工作流、分析指南、数据使用原则、评级方法论。Claude 触发 skill 时读取此文件 |
| `fetch_data.py` | 从东方财富公开 API 抓取 10+ 类数据（行情、财报、分红、K线、股吧等），无需认证 |
| `generate_report.py` | 报告渲染引擎。读取 analysis.json + 原始数据 → 生成 HTML（含 ECharts 图表）→ Playwright 转 PDF |

## 数据来源

所有数据来自[东方财富](https://www.eastmoney.com/)公开 API，无需注册或认证：

| 数据 | 接口 |
|------|------|
| 实时行情 | Push2 API |
| 财务三表 | Datacenter API |
| 公司概况 | CompanySurveyAjax |
| 分红历史 | Datacenter API |
| 日K线 | Push2 Kline API |
| 股吧帖子 | GuBa API |

## 已知限制

- 仅支持 A 股（沪深主板、创业板、科创板）
- 数据依赖东方财富 API 可用性
- PDF 渲染需要 Playwright + Chromium
- 非交易时间股价显示昨收价（已内置 fallback 逻辑）
- 报告语言仅支持中文

## License

MIT
