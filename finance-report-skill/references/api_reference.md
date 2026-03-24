# East Money (东方财富) API Reference

## API Families

### 1. Push2 API — Real-time quotes, K-line, market lists
Base: `https://push2.eastmoney.com/api/qt/`

### 2. Datacenter API — Financial statements, indicators, dividends, forecasts
Base: `https://datacenter-web.eastmoney.com/api/data/v1/get`
Parameterized by `reportName`.

### 3. F10 AJAX API — Company profile, forecasts
Base: `https://emweb.securities.eastmoney.com/PC_HSF10/`

## secid Convention
- `1.XXXXXX` — Shanghai (codes starting with 6, 9)
- `0.XXXXXX` — Shenzhen (codes starting with 0, 2, 3)

## Key Field Codes (Push2 API)

| Code | Meaning | Note |
|------|---------|------|
| f43 | Latest price | |
| f44 | Day high | |
| f45 | Day low | |
| f46 | Open | |
| f47 | Volume | shares |
| f48 | Turnover | yuan |
| f55 | EPS | |
| f57 | Stock code | |
| f58 | Stock name | |
| f60 | Prev close | |
| f116 | Total market cap | yuan |
| f117 | Circulating cap | yuan |
| f127 | Industry | |
| f162 | PE (TTM) | |
| f163 | PE (static) | |
| f167 | PB | |
| f170 | Change % | |

With `fltt=2`, values are already human-readable (no need to divide).

## reportName Quick Reference

| reportName | Data |
|------------|------|
| RPT_F10_ORG_ORGPROFILE | Company profile |
| RPT_F10_FN_MAINFINADATA | Key financial indicators |
| RPT_DMSK_FN_INCOME | Income statement |
| RPT_DMSK_FN_BALANCE | Balance sheet |
| RPT_DMSK_FN_CASHFLOW | Cash flow |
| RPT_SHAREBONUS_DET | Dividend history |

## No Authentication Required
All APIs are public. Use `Referer: https://www.eastmoney.com` header and 0.3s delay between calls.
