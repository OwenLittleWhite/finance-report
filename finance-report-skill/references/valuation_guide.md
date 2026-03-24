# Valuation Methods Guide (估值方法指南)

## Method Selection by Industry

### 绝对估值法 (Absolute Valuation)
- **DCF (贴现现金流)**: V = Σ(CFt / (1+r)^t), suitable for stable cash flow companies
- **DDM (红利贴现模型)**: V = Σ(DPS_t / (1+r)^t), for high-dividend stocks
- **FCFE**: Net income + Depreciation - CapEx - ΔWorkingCapital - Debt repayment + New debt
- **FCFF**: EBIT×(1-Tax) + Depreciation - CapEx - ΔWorkingCapital

### 相对估值法 (Relative Valuation)
- **PE (市盈率)**: Price / EPS. Best for stable earnings, consumer/pharma/manufacturing
- **PB (市净率)**: Price / BVPS. Best for heavy-asset, cyclical, or financial companies
- **PS (市销率)**: Price / Revenue per share. For unprofitable tech/growth companies
- **PEV (内含价值)**: Price / Embedded Value. Insurance-specific

## Industry Mapping

| Industry | Primary | Why |
|----------|---------|-----|
| 银行 | PB-ROE | Book value is core; ROE drives fair PB |
| 保险 | PEV | Embedded value captures in-force business |
| 券商 | PB | Asset-heavy, cyclical earnings |
| 消费/医药 | PE | Stable earnings, growth-driven |
| 科技 | PS/PE | Often unprofitable early stage |
| 周期性 | PB | Earnings too volatile for PE |
| 公用事业 | PE+股息率 | Stable cash flow, dividend focus |

## Calculation Steps

1. Determine industry → select method
2. Get current metrics (PE, PB, EPS, BVPS, ROE)
3. Estimate reasonable multiple (based on growth, industry avg, historical range)
4. Target price = metric × reasonable multiple
5. Upside = (target - current) / current
6. Rating: ≥15% → 买入, ≥5% → 增持, ≥-5% → 中性, <-5% → 减持
