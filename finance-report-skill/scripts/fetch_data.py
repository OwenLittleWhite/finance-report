#!/usr/bin/env python3
"""Fetch stock data from East Money (东方财富) APIs.

Usage: python fetch_data.py <stock_code> <output_dir>
Example: python fetch_data.py 601318 ./data/601318

Data sources:
  - Push2 API: real-time quote, K-line
  - Datacenter API: income, balance, cashflow, dividends
  - F10 AJAX API: company survey (profile, business scope, etc.)

Removed endpoints (broken/deprecated):
  - RPT_F10_FN_MAINFINADATA (financial indicators) — no longer returns data
  - RPT_F10_NPROFIT_PREDICT (analyst forecasts) — returns failure
"""
import sys
import os
import json
import time
import requests

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.eastmoney.com'
}
TIMEOUT = 15
DELAY = 0.3


def get_secid(code):
    """Map stock code to East Money secid format (market.code)."""
    if code.startswith(('6', '9')):
        return f"1.{code}"
    return f"0.{code}"


def get_market_prefix(code):
    """Map stock code to SH/SZ prefix for F10 APIs."""
    if code.startswith(('6', '9')):
        return f"SH{code}"
    return f"SZ{code}"


def api_get(url, params=None, retries=2):
    """HTTP GET with retry."""
    for i in range(retries):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(1)


def datacenter_get(report_name, code, page_size=20, sort_col='REPORT_DATE', extra_filter=''):
    """Fetch from the datacenter-web API."""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    filt = f'(SECURITY_CODE="{code}")'
    if extra_filter:
        filt = f'(SECURITY_CODE="{code}")({extra_filter})'
    params = {
        'reportName': report_name,
        'columns': 'ALL',
        'filter': filt,
        'sortColumns': sort_col,
        'sortTypes': '-1',
        'pageNumber': '1',
        'pageSize': str(page_size),
        'token': '894050c76af8597a853f5b408b759f5d',
    }
    return api_get(url, params)


# ── Individual fetchers ──────────────────────────────────────

def fetch_quote(secid):
    """Real-time quote with key metrics."""
    fields = ','.join([
        'f43', 'f44', 'f45', 'f46', 'f47', 'f48', 'f50',
        'f51', 'f52', 'f55', 'f57', 'f58', 'f60',
        'f116', 'f117', 'f127', 'f128',
        'f161', 'f162', 'f163', 'f167', 'f169', 'f170', 'f171',
    ])
    return api_get("https://push2.eastmoney.com/api/qt/stock/get", {
        'secid': secid, 'fields': fields,
        'ut': 'fa5fd1943c7b386f172d6893dbbd1d0c', 'fltt': '2',
    })


def fetch_company_survey(code):
    """Company survey via F10 AJAX API — returns rich profile data.

    Response contains:
      - jbzl (基本资料): gsmc (公司名), gsjj (公司简介), jyfw (经营范围),
        clrq (成立日期), ssrq (上市日期), etc.
      - gdhs (股东户数), zygc (主营构成), etc.
    """
    prefix = get_market_prefix(code)
    url = f"https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax?code={prefix}"
    return api_get(url)


def fetch_income(code):
    """Income statement (last 12 periods)."""
    return datacenter_get('RPT_DMSK_FN_INCOME', code, page_size=12)


def fetch_balance(code):
    """Balance sheet (last 12 periods)."""
    return datacenter_get('RPT_DMSK_FN_BALANCE', code, page_size=12)


def fetch_cashflow(code):
    """Cash flow statement (last 12 periods)."""
    return datacenter_get('RPT_DMSK_FN_CASHFLOW', code, page_size=12)


def fetch_dividend(code):
    """Dividend history.

    Key fields in response:
      - IMPL_PLAN_PROFILE: 分红方案描述
      - PRETAX_BONUS_RMB: 每10股税前派现(元)
      - BASIC_EPS: 每股收益
      - BVPS: 每股净资产
      - EX_DIVIDEND_DATE: 除息日
      - REPORT_DATE / EQUITY_RECORD_DATE
    """
    return datacenter_get('RPT_SHAREBONUS_DET', code, page_size=30,
                          sort_col='EX_DIVIDEND_DATE')


def fetch_kline(secid, limit=500):
    """Daily K-line data (forward adjusted)."""
    return api_get("https://push2his.eastmoney.com/api/qt/stock/kline/get", {
        'secid': secid,
        'fields1': 'f1,f2,f3,f4,f5,f6',
        'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
        'klt': '101', 'fqt': '1',
        'end': '20500101', 'lmt': str(limit),
        'ut': 'fa5fd1943c7b386f172d6893dbbd1d0c',
    })


def fetch_mainop(code):
    """Main business composition (主营构成) by segment and region."""
    return datacenter_get('RPT_F10_FN_MAINOP', code, page_size=30)


def fetch_guba(code, pages=3):
    """Fetch stock forum (股吧) post titles for sentiment word cloud."""
    import re as _re
    all_posts = []
    for page in range(1, pages + 1):
        url = f'https://guba.eastmoney.com/list,{code},f_{page}.html'
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            match = _re.search(r'var article_list\s*=\s*(\{.*?\});', resp.text, _re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                for p in data.get('re', []):
                    all_posts.append({
                        'title': p.get('post_title', ''),
                        'clicks': p.get('post_click_count', 0),
                        'comments': p.get('post_comment_count', 0),
                        'time': p.get('post_publish_time', ''),
                    })
        except Exception:
            pass
        time.sleep(DELAY)
    return {'posts': all_posts, 'count': len(all_posts)}


def fetch_peers(secid):
    """Fetch peer companies in the same industry for comparison.

    Uses the quote's f127 (industry) to find peers via sector list API.
    Returns batch quotes for top peers.
    """
    # First get this stock's industry sector code from quote
    quote = fetch_quote(secid)
    bk_code = ''
    if quote and quote.get('data'):
        bk_code = quote['data'].get('f128', '')  # 板块

    # Fetch sector stock list sorted by market cap, get top 8
    # Use industry sector: f127 field maps to BK code
    # Fallback: use the sector list API
    sector_url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        'pn': '1', 'pz': '8', 'po': '1', 'np': '1',
        'fltt': '2', 'invt': '2',
        'fid': 'f20',  # sort by market cap
        'fs': f'b:{bk_code}' if bk_code else f'm:1+t:2',
        'fields': 'f2,f3,f9,f12,f14,f20,f21,f23,f26,f115,f128,f140,f141,f136,f152',
    }
    return api_get(sector_url, params)


# ── Main ─────────────────────────────────────────────────────

FETCHERS = [
    ('quote',          lambda code, secid: fetch_quote(secid)),
    ('company_survey', lambda code, secid: fetch_company_survey(code)),
    ('income',         lambda code, secid: fetch_income(code)),
    ('balance',        lambda code, secid: fetch_balance(code)),
    ('cashflow',       lambda code, secid: fetch_cashflow(code)),
    ('dividend',       lambda code, secid: fetch_dividend(code)),
    ('kline',          lambda code, secid: fetch_kline(secid)),
    ('mainop',         lambda code, secid: fetch_mainop(code)),
    ('guba',           lambda code, secid: fetch_guba(code)),
    ('peers',          lambda code, secid: fetch_peers(secid)),
]


def main():
    if len(sys.argv) < 2:
        print("Usage: python fetch_data.py <stock_code> [output_dir]")
        print("  If output_dir is omitted, defaults to ./<stock_code>/")
        sys.exit(1)

    code = sys.argv[1].strip()
    out_dir = sys.argv[2].strip() if len(sys.argv) >= 3 else f'./{code}'

    if len(code) != 6 or not code.isdigit():
        print(f"Error: Invalid stock code '{code}'. Must be 6 digits.")
        sys.exit(1)

    os.makedirs(out_dir, exist_ok=True)
    secid = get_secid(code)
    print(f"Fetching data for {code} (secid={secid})...\n")

    results = {}
    for name, fetcher in FETCHERS:
        try:
            print(f"  [{name}] fetching...", end=' ', flush=True)
            data = fetcher(code, secid)
            path = os.path.join(out_dir, f'{name}.json')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            results[name] = True
            print("OK")
        except Exception as e:
            results[name] = False
            print(f"FAILED: {e}")
        time.sleep(DELAY)

    # Summary
    ok = sum(1 for v in results.values() if v)
    print(f"\nDone: {ok}/{len(results)} datasets fetched -> {out_dir}/")
    if ok < len(results):
        failed = [k for k, v in results.items() if not v]
        print(f"Failed: {', '.join(failed)}")
        sys.exit(1)


if __name__ == '__main__':
    main()
