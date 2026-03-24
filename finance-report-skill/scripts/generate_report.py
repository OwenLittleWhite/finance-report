#!/usr/bin/env python3
"""Generate A-share stock research report as PDF.

Produces a dense, professional 2-page report modeled after real analyst reports
from firms like 国金证券. Contains financial tables, ECharts charts, valuation
analysis, and investment thesis — all in Chinese.

Usage: python generate_report.py <data_dir> <simple|full> <output.pdf>
Example: python generate_report.py ./data/601318 simple ./reports/601318_report.pdf
"""
import sys
import os
import json
import math
from datetime import datetime


# ══════════════════════════════════════════════════════════════
#  Data Loading
# ══════════════════════════════════════════════════════════════

class StockData:
    """Load and expose all fetched data with computed financial metrics."""

    def __init__(self, data_dir):
        self.dir = data_dir
        self._cache = {}

    def _load(self, name):
        if name not in self._cache:
            path = os.path.join(self.dir, f'{name}.json')
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    self._cache[name] = json.load(f)
            else:
                self._cache[name] = None
        return self._cache[name]

    # ── Quote shortcuts ──
    @property
    def quote(self):
        raw = self._load('quote')
        return raw.get('data', {}) if raw else {}

    @property
    def name(self):
        return self.quote.get('f58', '未知')

    @property
    def code(self):
        return self.quote.get('f57', '')

    @property
    def full_code(self):
        c = self.code
        if c.startswith(('6', '9')):
            return f'SH{c}'
        return f'SZ{c}'

    @property
    def industry(self):
        return self.quote.get('f127', '')

    @property
    def price(self):
        p = self.quote.get('f43', 0)
        if p and p > 0:
            return p
        # Non-trading hours: fall back to prev_close, then last kline close
        p = self.quote.get('f60', 0)
        if p and p > 0:
            return p
        klines = self.kline_parsed(last_n=1)
        if klines:
            return klines[-1]['close']
        return 0

    @property
    def high(self):
        return self.quote.get('f44', 0)

    @property
    def low(self):
        return self.quote.get('f45', 0)

    @property
    def open_price(self):
        return self.quote.get('f46', 0)

    @property
    def volume(self):
        return self.quote.get('f47', 0)

    @property
    def turnover(self):
        return self.quote.get('f48', 0)

    @property
    def market_cap(self):
        """Total market cap in 亿元."""
        v = self.quote.get('f116', 0)
        return round(v / 1e8, 2) if v else 0

    @property
    def circ_cap(self):
        v = self.quote.get('f117', 0)
        return round(v / 1e8, 2) if v else 0

    @property
    def pe_ttm(self):
        return self.quote.get('f162', 0)

    @property
    def pb(self):
        return self.quote.get('f167', 0)

    @property
    def change_pct(self):
        return self.quote.get('f170', 0)

    @property
    def prev_close(self):
        return self.quote.get('f60', 0)

    @property
    def turnover_rate(self):
        return self.quote.get('f161', 0)

    @property
    def eps_quote(self):
        return self.quote.get('f55', 0)

    # ── Company Survey (from CompanySurveyAjax) ──
    @property
    def company_survey(self):
        return self._load('company_survey') or {}

    @property
    def jbzl(self):
        """基本资料 section from company survey."""
        return self.company_survey.get('jbzl', {})

    @property
    def company_name(self):
        return self.jbzl.get('gsmc', '') or self.name

    @property
    def company_intro(self):
        """公司简介 — rich text description of the company."""
        return self.jbzl.get('gsjj', '') or ''

    @property
    def business_scope(self):
        """经营范围."""
        return self.jbzl.get('jyfw', '') or ''

    @property
    def chairman(self):
        return self.jbzl.get('frdb', '') or ''

    @property
    def listing_date(self):
        return self.jbzl.get('ssrq', '') or ''

    @property
    def registered_capital(self):
        return self.jbzl.get('zczb', '') or ''

    @property
    def main_business_composition(self):
        """主营构成 from company survey."""
        return self.company_survey.get('zygc', []) or []

    def mainop_by_segment(self):
        """主营业务按业务分类 (MAINOP_TYPE=2), latest period."""
        raw = self._load('mainop')
        if not raw or not raw.get('result') or not raw['result'].get('data'):
            return []
        data = raw['result']['data']
        # Filter type=2 (by business segment), latest date
        segments = [r for r in data if r.get('MAINOP_TYPE') == '2' or r.get('MAINOP_TYPE') == 2]
        if not segments:
            return []
        latest_date = segments[0].get('REPORT_DATE', '')
        return [
            {'name': r.get('ITEM_NAME', ''), 'revenue': r.get('MAIN_BUSINESS_INCOME', 0) or 0, 'ratio': r.get('MBI_RATIO', 0) or 0}
            for r in segments if r.get('REPORT_DATE') == latest_date
        ]

    @property
    def fxxg(self):
        """发行信息 from company survey."""
        return self.company_survey.get('fxxg', {}) or {}

    @property
    def founding_date(self):
        return self.fxxg.get('clrq', '') or ''

    @property
    def ipo_date(self):
        return self.fxxg.get('ssrq', '') or ''

    @property
    def employee_count(self):
        return self.jbzl.get('gyrs', '') or ''

    # ── Legacy profile fallback (RPT_F10_ORG_ORGPROFILE) ──
    @property
    def profile(self):
        raw = self._load('profile')
        if raw and raw.get('result') and raw['result'].get('data'):
            return raw['result']['data'][0]
        return {}

    @property
    def org_profile(self):
        # Prefer company_survey intro; fall back to legacy profile
        if self.company_intro:
            return self.company_intro
        return self.profile.get('ORG_PROFILE', '')

    # ── Income statement ──
    @property
    def income_list(self):
        raw = self._load('income')
        if raw and raw.get('result') and raw['result'].get('data'):
            return raw['result']['data']
        return []

    def annual_income(self, n=5):
        return [r for r in self.income_list if '12-31' in r.get('REPORT_DATE', '')][:n]

    # ── Balance sheet ──
    @property
    def balance_list(self):
        raw = self._load('balance')
        if raw and raw.get('result') and raw['result'].get('data'):
            return raw['result']['data']
        return []

    def annual_balance(self, n=5):
        return [r for r in self.balance_list if '12-31' in r.get('REPORT_DATE', '')][:n]

    def latest_balance(self):
        """Most recent balance sheet (quarterly or annual)."""
        return self.balance_list[0] if self.balance_list else {}

    def _period_label(self, date_str):
        """Convert date string to readable period label like '2025Q3'."""
        if not date_str:
            return ''
        y = date_str[:4]
        if '03-31' in date_str: return f'{y}Q1'
        if '06-30' in date_str: return f'{y}H1'
        if '09-30' in date_str: return f'{y}Q3'
        if '12-31' in date_str: return y
        return date_str[:10]

    # ── Cash flow ──
    @property
    def cashflow_list(self):
        raw = self._load('cashflow')
        if raw and raw.get('result') and raw['result'].get('data'):
            return raw['result']['data']
        return []

    def annual_cashflow(self, n=5):
        return [r for r in self.cashflow_list if '12-31' in r.get('REPORT_DATE', '')][:n]

    def latest_cashflow(self):
        """Most recent cash flow statement (quarterly or annual)."""
        return self.cashflow_list[0] if self.cashflow_list else {}

    def latest_income(self):
        """Most recent income statement (quarterly or annual)."""
        return self.income_list[0] if self.income_list else {}

    # ── Dividends ──
    @property
    def dividends(self):
        raw = self._load('dividend')
        if raw and raw.get('result') and raw['result'].get('data'):
            return raw['result']['data']
        return []

    # ── AI Analysis ──
    @property
    def analysis(self):
        """AI-generated analysis content from analysis.json."""
        raw = self._load('analysis')
        return raw if raw and isinstance(raw, dict) else {}

    # ── K-line ──
    @property
    def klines(self):
        raw = self._load('kline')
        if raw and raw.get('data') and raw['data'].get('klines'):
            return raw['data']['klines']
        return []

    def kline_parsed(self, last_n=250):
        """Parse kline strings into dicts. last_n=250 ~ 1 year trading days."""
        rows = self.klines[-last_n:] if len(self.klines) > last_n else self.klines
        result = []
        for line in rows:
            parts = line.split(',')
            if len(parts) >= 11:
                result.append({
                    'date': parts[0], 'open': float(parts[1]),
                    'close': float(parts[2]), 'high': float(parts[3]),
                    'low': float(parts[4]), 'volume': float(parts[5]),
                    'turnover': float(parts[6]),
                })
        return result

    # ── Announcements ──
    @property
    def announcements(self):
        raw = self._load('announcements')
        if raw and raw.get('data') and raw['data'].get('list'):
            return raw['data']['list']
        return []

    def recent_announcements(self, n=10):
        """Get n most recent important announcements (filter out routine H-share notices)."""
        result = []
        for a in self.announcements:
            title = a.get('title', '')
            # Skip routine H-share monthly reports
            if 'H股公告' in title and ('月报表' in title or '證券變動' in title):
                continue
            result.append({
                'date': (a.get('notice_date') or '')[:10],
                'title': title.split(':')[-1] if ':' in title else title,  # Remove company prefix
            })
            if len(result) >= n:
                break
        return result

    # ── All periods (including interim) ──
    def all_period_income(self, n=12):
        """All income records sorted by date (annual + quarterly + semi-annual)."""
        return self.income_list[:n]

    def interim_financials(self):
        """Build financials for the latest interim period (Q1/H1/Q3) if newer than last annual."""
        annuals = self.annual_income(1)
        last_annual_date = annuals[0].get('REPORT_DATE', '')[:10] if annuals else '2000-01-01'

        results = []
        for inc in self.income_list:
            rd = inc.get('REPORT_DATE', '')[:10]
            if rd > last_annual_date and '12-31' not in rd:
                rev = inc.get('TOTAL_OPERATE_INCOME') or inc.get('OPERATE_INCOME') or 0
                net_profit = inc.get('PARENT_NETPROFIT') or inc.get('NETPROFIT') or 0
                # Label: Q1/H1/Q3
                if '03-31' in rd:
                    label = f'{rd[:4]}Q1'
                elif '06-30' in rd:
                    label = f'{rd[:4]}H1'
                elif '09-30' in rd:
                    label = f'{rd[:4]}Q3'
                else:
                    label = rd[:7]
                # YoY growth from same period prior year
                same_period_prev = None
                prev_date = f'{int(rd[:4])-1}{rd[4:]}'
                for prev_inc in self.income_list:
                    if prev_inc.get('REPORT_DATE', '').startswith(prev_date[:10]):
                        same_period_prev = prev_inc
                        break
                rev_yoy = None
                profit_yoy = None
                if same_period_prev:
                    prev_rev = same_period_prev.get('TOTAL_OPERATE_INCOME') or same_period_prev.get('OPERATE_INCOME') or 0
                    prev_profit = same_period_prev.get('PARENT_NETPROFIT') or same_period_prev.get('NETPROFIT') or 0
                    if prev_rev and prev_rev != 0:
                        rev_yoy = round((rev / prev_rev - 1) * 100, 2)
                    if prev_profit and prev_profit != 0:
                        profit_yoy = round((net_profit / prev_profit - 1) * 100, 2)

                results.append({
                    'label': label,
                    'date': rd,
                    'revenue': rev,
                    'revenue_yoy': rev_yoy,
                    'net_profit': net_profit,
                    'profit_yoy': profit_yoy,
                })
        return results

    # ── Computed financial metrics (from raw income/balance data) ──

    def _safe_div(self, a, b):
        if a is None or b is None or b == 0:
            return None
        return a / b

    def compute_annual_financials(self, n=5):
        """Build a list of annual financial metric dicts from raw statements.

        Computes: revenue, revenue_growth, net_profit, profit_growth, eps,
                  roe, net_margin, gross_margin, debt_ratio, total_assets,
                  total_liabilities, parent_equity.
        """
        incomes = self.annual_income(n)
        balances = self.annual_balance(n)
        dividends = self.dividends

        # Build a lookup: year -> balance data
        bal_by_year = {}
        for b in balances:
            y = b.get('REPORT_DATE', '')[:4]
            if y:
                bal_by_year[y] = b

        # Build a lookup: year -> dividend EPS/BVPS
        div_by_year = {}
        for d in dividends:
            rd = d.get('REPORT_DATE', '')
            if rd:
                y = rd[:4]
                if y not in div_by_year:
                    div_by_year[y] = d

        results = []
        for i, inc in enumerate(incomes):
            year = inc.get('REPORT_DATE', '')[:4]
            rev = inc.get('TOTAL_OPERATE_INCOME') or inc.get('OPERATE_INCOME') or 0
            net_profit = inc.get('PARENT_NETPROFIT') or inc.get('NETPROFIT') or 0

            # Revenue growth
            rev_growth = None
            if i + 1 < len(incomes):
                prev_rev = incomes[i + 1].get('TOTAL_OPERATE_INCOME') or incomes[i + 1].get('OPERATE_INCOME') or 0
                if prev_rev and prev_rev != 0:
                    rev_growth = round((rev / prev_rev - 1) * 100, 2)

            # Profit growth
            profit_growth = None
            if i + 1 < len(incomes):
                prev_profit = incomes[i + 1].get('PARENT_NETPROFIT') or incomes[i + 1].get('NETPROFIT') or 0
                if prev_profit and prev_profit != 0:
                    profit_growth = round((net_profit / prev_profit - 1) * 100, 2)

            # Net margin
            net_margin = round(net_profit / rev * 100, 2) if rev and rev != 0 else None

            # Gross margin: (revenue - cost) / revenue
            cost = inc.get('OPERATE_COST') or 0
            gross_margin = round((rev - cost) / rev * 100, 2) if rev and rev != 0 else None

            # Balance sheet metrics
            bal = bal_by_year.get(year, {})
            total_assets = bal.get('TOTAL_ASSETS') or 0
            total_liab = bal.get('TOTAL_LIABILITIES') or 0
            parent_equity = bal.get('TOTAL_PARENT_EQUITY') or 0
            if parent_equity == 0 and total_assets and total_liab:
                parent_equity = total_assets - total_liab

            debt_ratio = round(total_liab / total_assets * 100, 2) if total_assets else None

            # ROE = Parent Net Profit / Average Parent Equity
            # Use current year equity as approximation (average would need prior year)
            prev_year = str(int(year) - 1) if year.isdigit() else ''
            prev_bal = bal_by_year.get(prev_year, {})
            prev_equity = prev_bal.get('TOTAL_PARENT_EQUITY') or 0
            if prev_equity and parent_equity:
                avg_equity = (parent_equity + prev_equity) / 2
            else:
                avg_equity = parent_equity
            roe = round(net_profit / avg_equity * 100, 2) if avg_equity and avg_equity != 0 else None

            # ROA
            prev_assets = prev_bal.get('TOTAL_ASSETS') or 0
            if prev_assets and total_assets:
                avg_assets = (total_assets + prev_assets) / 2
            else:
                avg_assets = total_assets
            roa = round(net_profit / avg_assets * 100, 2) if avg_assets and avg_assets != 0 else None

            # EPS — prefer dividend data's BASIC_EPS, then calculate
            div_data = div_by_year.get(year, {})
            eps = div_data.get('BASIC_EPS')
            if eps is None and self.market_cap and self.price and self.price > 0:
                # shares = market_cap_yuan / price
                total_shares = (self.market_cap * 1e8) / self.price
                eps = round(net_profit / total_shares, 4) if total_shares else None

            # BVPS from dividend data
            bvps = div_data.get('BVPS')

            # PE for this year (using current price)
            pe = round(self.price / eps, 2) if eps and eps > 0 and self.price else None

            # PB for this year
            pb_val = None
            if bvps and bvps > 0 and self.price:
                pb_val = round(self.price / bvps, 2)

            results.append({
                'year': year,
                'revenue': rev,
                'revenue_growth': rev_growth,
                'net_profit': net_profit,
                'profit_growth': profit_growth,
                'eps': eps,
                'bvps': bvps,
                'roe': roe,
                'roa': roa,
                'net_margin': net_margin,
                'gross_margin': gross_margin,
                'debt_ratio': debt_ratio,
                'total_assets': total_assets,
                'total_liabilities': total_liab,
                'parent_equity': parent_equity,
                'pe': pe,
                'pb': pb_val,
            })

        return results

    @property
    def latest_annual(self):
        """Most recent annual financials dict."""
        annuals = self.compute_annual_financials(1)
        return annuals[0] if annuals else {}

    @property
    def roe(self):
        la = self.latest_annual
        return la.get('roe') or 0

    @property
    def latest_eps(self):
        la = self.latest_annual
        return la.get('eps') or self.eps_quote or 0

    @property
    def eps_ttm(self):
        """Trailing 12-month EPS = annual + latest_cumulative - same_period_last_year.

        Example at 2025Q3: TTM = 2024_annual + 2025Q3_cum - 2024Q3_cum
        Falls back to latest_eps (annual) if quarterly data unavailable.
        """
        annual_income = self.annual_income(1)
        if not annual_income:
            return self.latest_eps

        annual_date = annual_income[0].get('REPORT_DATE', '')[:10]
        annual_np = annual_income[0].get('PARENT_NETPROFIT') or annual_income[0].get('NETPROFIT') or 0

        # Find latest interim (newer than annual)
        latest_interim = None
        for inc in self.income_list:
            rd = inc.get('REPORT_DATE', '')[:10]
            if rd > annual_date and '12-31' not in rd:
                latest_interim = inc
                break

        if not latest_interim:
            return self.latest_eps

        interim_date = latest_interim.get('REPORT_DATE', '')[:10]
        interim_np = latest_interim.get('PARENT_NETPROFIT') or latest_interim.get('NETPROFIT') or 0

        # Find same period last year
        prev_year_date = f'{int(interim_date[:4]) - 1}{interim_date[4:]}'
        same_period_prev = None
        for inc in self.income_list:
            if inc.get('REPORT_DATE', '').startswith(prev_year_date):
                same_period_prev = inc
                break

        if not same_period_prev:
            return self.latest_eps

        prev_np = same_period_prev.get('PARENT_NETPROFIT') or same_period_prev.get('NETPROFIT') or 0

        # TTM net profit = annual + latest_interim - same_period_prev
        ttm_np = annual_np + interim_np - prev_np

        # Convert to EPS using share count
        if self.market_cap and self.price and self.price > 0:
            total_shares = (self.market_cap * 1e8) / self.price
            if total_shares > 0:
                return round(ttm_np / total_shares, 4)

        return self.latest_eps

    @property
    def latest_bvps(self):
        la = self.latest_annual
        v = la.get('bvps')
        if v:
            return v
        # Fallback: price / PB
        if self.pb and self.pb > 0 and self.price:
            return round(self.price / self.pb, 2)
        return 0

    @property
    def dividend_yield(self):
        """Estimated dividend yield. Returns 0 if no dividend in last 2 years."""
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%d')
        for d in self.dividends:
            ex_date = (d.get('EX_DIVIDEND_DATE') or '')[:10]
            if ex_date < cutoff:
                return 0  # Too old, stop looking
            bonus = d.get('PRETAX_BONUS_RMB')
            if bonus and self.price and self.price > 0:
                return round(bonus / 10 / self.price * 100, 2)
        return 0

    def week52_range(self):
        """52-week high and low from kline data."""
        klines = self.kline_parsed(250)
        if not klines:
            return (0, 0)
        highs = [k['high'] for k in klines]
        lows = [k['low'] for k in klines]
        return (min(lows), max(highs))


# ══════════════════════════════════════════════════════════════
#  Valuation Engine
# ══════════════════════════════════════════════════════════════

INDUSTRY_METHOD = {
    '银行': 'pb_roe',
    '保险': 'pev',
    '多元金融': 'pb',
    '证券': 'pb',
    '房地产开发': 'nav',
    '房地产服务': 'pe',
    '食品饮料': 'pe',
    '医药': 'pe',
    '生物制品': 'pe',
    '家用电器': 'pe',
    '白色家电': 'pe',
    '消费': 'pe',
    '零售': 'pe',
    '电子': 'ps_pe',
    '计算机': 'ps_pe',
    '通信': 'ps_pe',
    '半导体': 'ps_pe',
    '传媒': 'ps_pe',
    '互联网': 'ps_pe',
    '钢铁': 'pb_cycle',
    '煤炭': 'pb_cycle',
    '有色金属': 'pb_cycle',
    '基础化工': 'pb_cycle',
    '电力': 'pe_div',
    '水务': 'pe_div',
    '燃气': 'pe_div',
    '公用事业': 'pe_div',
    '汽车': 'pe',
    '机械': 'pe',
    '军工': 'pe',
    '建筑': 'pe',
    '交通运输': 'pe_div',
    '纺织服装': 'pe',
    '农林牧渔': 'pe',
}

# Comparable company context by industry for the report text
INDUSTRY_COMPS = {
    '银行': '工商银行、建设银行、招商银行等可比银行',
    '保险': '中国人寿、中国太保、新华保险等可比保险公司',
    '证券': '中信证券、华泰证券、海通证券等可比券商',
    '食品饮料': '贵州茅台、五粮液、伊利股份等行业龙头',
    '医药': '恒瑞医药、药明康德、迈瑞医疗等可比标的',
    '电子': '立讯精密、歌尔股份、韦尔股份等可比公司',
    '计算机': '海康威视、用友网络、金山办公等可比标的',
    '半导体': '中芯国际、北方华创、韦尔股份等可比公司',
    '家用电器': '美的集团、海尔智家、格力电器等可比公司',
    '汽车': '比亚迪、长城汽车、长安汽车等可比标的',
    '房地产': '万科A、保利发展、招商蛇口等可比公司',
    '钢铁': '宝钢股份、鞍钢股份等可比标的',
    '煤炭': '中国神华、陕西煤业等可比公司',
    '电力': '长江电力、华能国际等可比标的',
}


def detect_method(industry):
    for key, method in INDUSTRY_METHOD.items():
        if key in industry:
            return method
    return 'pe_pb'


def get_comps_text(industry):
    for key, text in INDUSTRY_COMPS.items():
        if key in industry:
            return text
    return '同行业可比上市公司'


def calc_valuation(data: StockData):
    """Calculate valuation with bear/base/bull scenarios."""
    method = detect_method(data.industry)
    comps = get_comps_text(data.industry)
    result = {
        'method': method,
        'method_name': '',
        'current_pe': data.pe_ttm,
        'current_pb': data.pb,
        'current_price': data.price,
        'roe': data.roe,
        'eps': data.eps_ttm,
        'bvps': data.latest_bvps,
        'target_price': 0,
        'upside': 0,
        'rating': '',
        'explanation': '',
        'details': [],
        'comps': comps,
        'scenarios': {},  # bear/base/bull
    }

    pe = data.pe_ttm if data.pe_ttm and data.pe_ttm > 0 else None
    pb = data.pb if data.pb and data.pb > 0 else None
    roe = data.roe
    price = data.price
    latest_eps = data.eps_ttm
    bvps = data.latest_bvps

    # Get EPS growth from computed financials
    annuals = data.compute_annual_financials(3)
    eps_growth = None
    if len(annuals) >= 2:
        eps1 = annuals[0].get('eps') or 0
        eps2 = annuals[1].get('eps') or 0
        if eps2 and eps2 > 0 and eps1:
            eps_growth = round((eps1 / eps2 - 1) * 100, 1)

    # Revenue growth for projection
    rev_growth = annuals[0].get('revenue_growth') if annuals else None

    if method == 'pb_roe':
        result['method_name'] = 'PB-ROE 估值法'
        bvps_calc = price / pb if pb and pb > 0 else 0
        if bvps and bvps > 0:
            bvps_calc = bvps
        theoretical_pb = roe / 10 if roe and roe > 0 else 1.0
        reasonable_pb = min(theoretical_pb, pb * 1.3) if pb else theoretical_pb
        reasonable_pb = max(reasonable_pb, pb * 1.1) if pb else reasonable_pb
        reasonable_pb = round(max(0.4, min(reasonable_pb, 2.5)), 2)

        bear_pb = round(reasonable_pb * 0.85, 2)
        bull_pb = round(reasonable_pb * 1.15, 2)

        target = round(bvps_calc * reasonable_pb, 2) if bvps_calc else price
        result['target_price'] = target
        result['scenarios'] = {
            'bear': round(bvps_calc * bear_pb, 2),
            'base': target,
            'bull': round(bvps_calc * bull_pb, 2),
        }
        result['explanation'] = f'基于 ROE {roe:.1f}% 给予合理 PB {reasonable_pb:.2f}x，参考{comps}'
        result['details'] = [
            f'每股净资产 (BVPS): {bvps_calc:.2f} 元',
            f'当前 PB: {pb:.2f}x | ROE: {roe:.1f}%',
            f'理论 PB (ROE÷COE): {theoretical_pb:.2f}x',
            f'合理 PB (综合市场折价): {reasonable_pb:.2f}x',
            f'悲观/基准/乐观 PB: {bear_pb:.2f}x / {reasonable_pb:.2f}x / {bull_pb:.2f}x',
            f'目标价: BVPS {bvps_calc:.2f} x PB {reasonable_pb:.2f} = {target:.2f} 元',
        ]

    elif method == 'pev':
        result['method_name'] = 'PEV (内含价值) 估值法'
        bvps_calc = price / pb if pb and pb > 0 else price
        if bvps and bvps > 0:
            bvps_calc = bvps
        ev_per_share = bvps_calc * 1.5
        if roe and roe > 12:
            reasonable_pev = 1.1
        elif roe and roe > 8:
            reasonable_pev = 1.0
        else:
            reasonable_pev = 0.85
        target = round(ev_per_share * reasonable_pev, 2)
        result['target_price'] = target
        result['scenarios'] = {
            'bear': round(ev_per_share * (reasonable_pev - 0.15), 2),
            'base': target,
            'bull': round(ev_per_share * (reasonable_pev + 0.15), 2),
        }
        result['explanation'] = f'保险公司适用内含价值估值，EVPS≈{ev_per_share:.2f}元，给予{reasonable_pev:.1f}x PEV，参考{comps}'
        result['details'] = [
            f'每股净资产 (BVPS): {bvps_calc:.2f} 元',
            f'估算每股内含价值 (EVPS≈1.5xBVPS): {ev_per_share:.2f} 元',
            f'当前 PB: {pb:.2f}x | ROE: {roe:.1f}%',
            f'合理 PEV: {reasonable_pev:.1f}x',
            f'悲观/基准/乐观: {reasonable_pev-0.15:.2f}x / {reasonable_pev:.2f}x / {reasonable_pev+0.15:.2f}x PEV',
            f'目标价: EVPS {ev_per_share:.2f} x {reasonable_pev:.1f} = {target:.2f} 元',
        ]

    elif method in ('pb', 'pb_cycle'):
        result['method_name'] = 'PB 估值法'
        bvps_calc = price / pb if pb else 0
        if bvps and bvps > 0:
            bvps_calc = bvps
        hist_pb_range = (pb * 0.8, pb * 1.5) if pb else (1.0, 2.0)
        reasonable_pb = round((hist_pb_range[0] + hist_pb_range[1]) / 2, 2)
        target = round(bvps_calc * reasonable_pb, 2) if bvps_calc else price
        result['target_price'] = target
        result['scenarios'] = {
            'bear': round(bvps_calc * hist_pb_range[0], 2),
            'base': target,
            'bull': round(bvps_calc * hist_pb_range[1], 2),
        }
        result['explanation'] = f'给予合理 PB {reasonable_pb:.2f}x，参考{comps}'
        result['details'] = [
            f'每股净资产 (BVPS): {bvps_calc:.2f} 元',
            f'当前 PB: {pb:.2f}x | ROE: {roe:.1f}%',
            f'PB 合理区间: {hist_pb_range[0]:.2f}x ~ {hist_pb_range[1]:.2f}x',
            f'合理 PB (中枢): {reasonable_pb:.2f}x',
            f'目标价: BVPS {bvps_calc:.2f} x PB {reasonable_pb:.2f} = {target:.2f} 元',
        ]

    elif method == 'ps_pe':
        result['method_name'] = 'PS / PE 综合估值法'
        if pe and pe > 0 and latest_eps and latest_eps > 0:
            reasonable_pe = pe * 1.15 if eps_growth and eps_growth > 20 else pe * 1.05
            reasonable_pe = round(reasonable_pe, 1)
            target = round(latest_eps * reasonable_pe, 2)
            bear_pe = round(reasonable_pe * 0.85, 1)
            bull_pe = round(reasonable_pe * 1.15, 1)
            result['scenarios'] = {
                'bear': round(latest_eps * bear_pe, 2),
                'base': target,
                'bull': round(latest_eps * bull_pe, 2),
            }
            result['explanation'] = f'给予合理 PE {reasonable_pe:.1f}x，参考{comps}'
            result['details'] = [
                f'TTM EPS: {latest_eps:.2f} 元',
                f'当前 PE(TTM): {pe:.1f}x',
                f'EPS 增速: {eps_growth:.1f}%' if eps_growth else 'EPS 增速: N/A',
                f'合理 PE: {reasonable_pe:.1f}x',
                f'悲观/基准/乐观 PE: {bear_pe:.1f}x / {reasonable_pe:.1f}x / {bull_pe:.1f}x',
                f'目标价: EPS {latest_eps:.2f} x PE {reasonable_pe:.1f} = {target:.2f} 元',
            ]
        else:
            target = price * 1.1
            result['explanation'] = f'公司尚未盈利/微利，参考 PS 估值，参考{comps}'
            result['details'] = ['PE: N/A (未盈利或微利)', f'参考价: {target:.2f} 元']
            result['scenarios'] = {'bear': round(price * 0.9, 2), 'base': round(target, 2), 'bull': round(price * 1.3, 2)}
        result['target_price'] = round(target, 2)

    elif method == 'pe_div':
        result['method_name'] = 'PE + 股息率 估值法'
        div_yield = data.dividend_yield
        reasonable_pe = pe * 1.1 if pe and pe > 0 else 15
        reasonable_pe = round(reasonable_pe, 1)
        target = round(latest_eps * reasonable_pe, 2) if latest_eps and latest_eps > 0 else price * 1.1
        bear_pe = round(reasonable_pe * 0.85, 1)
        bull_pe = round(reasonable_pe * 1.15, 1)
        result['target_price'] = round(target, 2)
        result['scenarios'] = {
            'bear': round(latest_eps * bear_pe, 2) if latest_eps and latest_eps > 0 else round(price * 0.9, 2),
            'base': round(target, 2),
            'bull': round(latest_eps * bull_pe, 2) if latest_eps and latest_eps > 0 else round(price * 1.2, 2),
        }
        result['explanation'] = f'给予合理 PE {reasonable_pe:.1f}x，当前股息率 {div_yield:.1f}%，参考{comps}'
        result['details'] = [
            f'TTM EPS: {latest_eps:.2f} 元' if latest_eps else 'EPS: N/A',
            f'当前 PE(TTM): {pe:.1f}x' if pe else 'PE: N/A',
            f'股息率: {div_yield:.1f}%',
            f'合理 PE: {reasonable_pe:.1f}x',
            f'悲观/基准/乐观 PE: {bear_pe:.1f}x / {reasonable_pe:.1f}x / {bull_pe:.1f}x',
            f'目标价: {result["target_price"]:.2f} 元',
        ]

    else:  # pe, pe_pb, nav, default
        result['method_name'] = 'PE 估值法'
        if pe and pe > 0 and latest_eps and latest_eps > 0:
            premium = 1.15 if (eps_growth and eps_growth > 15) else 1.05
            reasonable_pe = round(pe * premium, 1)
            target = round(latest_eps * reasonable_pe, 2)
            bear_pe = round(reasonable_pe * 0.85, 1)
            bull_pe = round(reasonable_pe * 1.15, 1)
            result['scenarios'] = {
                'bear': round(latest_eps * bear_pe, 2),
                'base': target,
                'bull': round(latest_eps * bull_pe, 2),
            }
            result['explanation'] = f'给予合理 PE {reasonable_pe:.1f}x，参考{comps}'
            result['details'] = [
                f'TTM EPS: {latest_eps:.2f} 元',
                f'当前 PE(TTM): {pe:.1f}x',
                f'EPS 增速: {eps_growth:.1f}%' if eps_growth else 'EPS 增速: N/A',
                f'合理 PE: {reasonable_pe:.1f}x',
                f'悲观/基准/乐观 PE: {bear_pe:.1f}x / {reasonable_pe:.1f}x / {bull_pe:.1f}x',
                f'目标价: EPS {latest_eps:.2f} x PE {reasonable_pe:.1f} = {target:.2f} 元',
            ]
        else:
            reasonable_pe = 15
            target = price * 1.1
            result['explanation'] = f'参考行业平均 PE {reasonable_pe}x，参考{comps}'
            result['details'] = [f'当前价: {price:.2f} 元', f'参考目标价: {target:.2f} 元']
            result['scenarios'] = {'bear': round(price * 0.9, 2), 'base': round(target, 2), 'bull': round(price * 1.3, 2)}
        result['target_price'] = round(target, 2)

    # Calculate upside & rating (multi-factor scoring)
    if result['target_price'] and price:
        result['upside'] = round((result['target_price'] / price - 1) * 100, 1)

    upside = result['upside']
    score = 0
    rating_factors = {}

    # Factor 1: Valuation upside (max ±3)
    if upside >= 20:
        f1 = 3
    elif upside >= 10:
        f1 = 2
    elif upside >= 0:
        f1 = 1
    elif upside >= -10:
        f1 = -1
    else:
        f1 = -2
    score += f1
    rating_factors['valuation_upside'] = {'score': f1, 'value': upside, 'label': f'估值空间 {upside:.1f}%'}

    # Factor 2: Profitability (max ±2)
    roe_val = data.roe
    if roe_val > 15:
        f2 = 2
    elif roe_val > 8:
        f2 = 1
    elif roe_val > 0:
        f2 = 0
    elif roe_val > -5:
        f2 = -1
    else:
        f2 = -2
    score += f2
    rating_factors['profitability'] = {'score': f2, 'value': roe_val, 'label': f'ROE {roe_val:.1f}%'}

    # Factor 3: Growth trend (max ±2)
    if eps_growth and eps_growth > 20:
        f3 = 2
    elif eps_growth and eps_growth > 5:
        f3 = 1
    elif eps_growth and eps_growth > -5:
        f3 = 0
    elif eps_growth and eps_growth > -20:
        f3 = -1
    elif eps_growth is not None:
        f3 = -2
    else:
        f3 = 0  # No data, neutral
    score += f3
    rating_factors['growth'] = {'score': f3, 'value': eps_growth, 'label': f'EPS增速 {eps_growth:.1f}%' if eps_growth is not None else 'EPS增速 N/A'}

    # Factor 4: Financial health — use latest period (quarterly or annual)
    f4 = 0
    latest_bal = data.latest_balance()
    debt_val = None
    if latest_bal:
        ta = latest_bal.get('TOTAL_ASSETS') or 0
        tl = latest_bal.get('TOTAL_LIABILITIES') or 0
        debt_val = round(tl / ta * 100, 2) if ta else None
        if debt_val is not None and debt_val > 80:
            f4 = -1
        elif debt_val is not None and debt_val < 50:
            f4 = 1
    score += f4
    bal_period = data._period_label(latest_bal.get('REPORT_DATE', '')[:10]) if latest_bal else ''
    rating_factors['financial_health'] = {'score': f4, 'value': debt_val, 'label': f'资产负债率 {debt_val:.1f}% ({bal_period})' if debt_val is not None else '资产负债率 N/A'}

    # Factor 5: Cash flow quality — use latest annual (quarterly CF is cumulative YTD, not comparable)
    f5 = 0
    cf = [r for r in data.cashflow_list if '12-31' in r.get('REPORT_DATE', '')]
    op_cf_val = None
    if cf:
        op_cf_val = (cf[0].get('NETCASH_OPERATE') or 0)
        if op_cf_val > 0:
            f5 = 1
        else:
            f5 = -1
    score += f5
    rating_factors['cashflow'] = {'score': f5, 'value': round(op_cf_val / 1e8, 1) if op_cf_val is not None else None, 'label': f'经营现金流 {op_cf_val/1e8:.1f}亿' if op_cf_val is not None else '经营现金流 N/A'}

    # Factor 6: Interim trend (max ±1)
    f6 = 0
    interim = data.interim_financials()
    interim_py_val = None
    if interim:
        interim_py_val = interim[0].get('profit_yoy')
        if interim_py_val is not None and interim_py_val > 10:
            f6 = 1
        elif interim_py_val is not None and interim_py_val < -10:
            f6 = -1
    score += f6
    rating_factors['interim_trend'] = {'score': f6, 'value': interim_py_val, 'label': f'最新季度利润同比 {interim_py_val:.1f}%' if interim_py_val is not None else '最新季度 N/A'}

    # Map score to rating
    if score >= 5:
        result['rating'] = '买入'
    elif score >= 2:
        result['rating'] = '增持'
    elif score >= -1:
        result['rating'] = '中性'
    else:
        result['rating'] = '减持'

    rating_factors['total_score'] = score
    result['rating_factors'] = rating_factors

    return result


# ══════════════════════════════════════════════════════════════
#  Investment Thesis Generator
# ══════════════════════════════════════════════════════════════

def generate_thesis(data: StockData, valuation: dict):
    """Generate a 3-5 sentence investment thesis that reads like a human analyst wrote it.

    Holistically assesses revenue trend, profitability, ROE, cash flow, debt,
    dividend, interim data, and industry context to tell a coherent story about
    the company's actual situation.
    """
    name = data.name
    industry = data.industry
    annuals = data.compute_annual_financials(3)
    pe = data.pe_ttm
    pb = data.pb
    roe = data.roe
    mc = data.market_cap
    price = data.price
    dy = data.dividend_yield
    interim = data.interim_financials()

    # --- Gather all key metrics ---
    latest = annuals[0] if annuals else {}
    rev = latest.get('revenue', 0)
    net_profit = latest.get('net_profit', 0)
    rg = latest.get('revenue_growth')
    pg = latest.get('profit_growth')
    net_margin = latest.get('net_margin')
    debt_ratio = latest.get('debt_ratio')
    year = latest.get('year', '')

    # Cash flow
    cf_list = [r for r in data.cashflow_list if '12-31' in r.get('REPORT_DATE', '')]
    op_cf = (cf_list[0].get('NETCASH_OPERATE') or 0) / 1e8 if cf_list else None

    # Format helpers
    def fmt_yi(v):
        """Format a value in 亿元."""
        yi = abs(v) / 1e8
        if yi >= 1:
            return f'{yi:.0f}亿元' if yi >= 10 else f'{yi:.1f}亿元'
        return f'{yi:.2f}亿元'

    def fmt_wan(v):
        """Format a value in 万元 for small amounts."""
        wan = abs(v) / 1e4
        return f'{wan:.0f}万元'

    # --- Detect company situation archetype ---
    is_loss = net_profit < 0
    is_deep_loss = roe < -10
    is_turnaround = pg is not None and pg > 50 and (not is_loss)
    is_high_growth = rg is not None and rg > 20 and pg is not None and pg > 20
    is_stable = rg is not None and abs(rg) < 10 and pg is not None and abs(pg) < 15 and roe > 5
    is_declining = rg is not None and rg < -5 and pg is not None and pg < -10
    is_cyclical_recovery = rg is not None and rg > 10 and pg is not None and pg > 30 and roe > 0 and roe < 12

    sentences = []

    # --- Sentence 1: Company identity + core financial performance ---
    if mc > 5000:
        scale_desc = f'作为{industry}行业龙头'
    elif mc > 1000:
        scale_desc = f'作为{industry}行业重要参与者'
    elif mc > 200:
        scale_desc = f'{name}深耕{industry}领域'
    else:
        scale_desc = f'{name}是{industry}行业小型上市公司'

    if is_loss:
        rev_str = f'营收{fmt_yi(rev)}' if rev else ''
        profit_str = f'归母净利润亏损{fmt_yi(net_profit)}'
        s1 = f'{scale_desc}，{year}年{rev_str}，{profit_str}，ROE为{roe:.1f}%'
        # Check consecutive losses
        loss_years = sum(1 for a in annuals if (a.get('net_profit') or 0) < 0)
        if loss_years > 1:
            s1 += f'，已连续{loss_years}年未能实现盈利'
        s1 += '。'
    elif is_high_growth:
        s1 = f'{scale_desc}，{year}年实现营收{fmt_yi(rev)}，同比增长{rg:.1f}%，归母净利润{fmt_yi(net_profit)}，同比大增{pg:.1f}%，业绩进入快速释放期。'
    elif is_turnaround:
        s1 = f'{scale_desc}，{year}年归母净利润{fmt_yi(net_profit)}，同比大幅增长{pg:.1f}%，盈利修复趋势明确。'
    elif is_declining:
        rev_part = f'营收同比下降{abs(rg):.1f}%' if rg is not None else '营收承压'
        profit_part = f'归母净利润同比下降{abs(pg):.1f}%' if pg is not None else ''
        s1 = f'{scale_desc}，{year}年{rev_part}'
        if profit_part:
            s1 += f'，{profit_part}'
        s1 += '，主营业务承压明显。'
    elif is_stable:
        s1 = f'{scale_desc}，{year}年实现营收{fmt_yi(rev)}'
        if rg is not None:
            s1 += f'（同比{"+" if rg > 0 else ""}{rg:.1f}%）'
        s1 += f'，归母净利润{fmt_yi(net_profit)}'
        if pg is not None:
            s1 += f'（同比{"+" if pg > 0 else ""}{pg:.1f}%）'
        s1 += '，经营保持稳健。'
    else:
        # Generic but with real numbers
        s1 = f'{scale_desc}，{year}年实现营收{fmt_yi(rev)}'
        if rg is not None:
            s1 += f'，同比{"增长" if rg > 0 else "下降"}{abs(rg):.1f}%'
        s1 += f'，归母净利润{fmt_yi(net_profit)}'
        if pg is not None:
            s1 += f'，同比{"增长" if pg > 0 else "下降"}{abs(pg):.1f}%'
        s1 += '。'
    sentences.append(s1)

    # --- Sentence 2: Interim data trend (if available) ---
    if interim:
        it = interim[0]
        iry = it.get('revenue_yoy')
        ipy = it.get('profit_yoy')
        label = it.get('label', '')
        it_parts = []
        if iry is not None:
            it_parts.append(f'营收同比{"+" if iry > 0 else ""}{iry:.1f}%')
        if ipy is not None:
            it_parts.append(f'净利润同比{"+" if ipy > 0 else ""}{ipy:.1f}%')
        if it_parts:
            trend_word = ''
            if len(interim) >= 2:
                prev_py = interim[1].get('profit_yoy')
                if ipy is not None and prev_py is not None:
                    if ipy > prev_py + 5:
                        trend_word = '，增长提速'
                    elif ipy < prev_py - 5:
                        trend_word = '，增速有所放缓'
                    else:
                        trend_word = '，增长延续'
            sentences.append(f'最新{label}数据显示{"、".join(it_parts)}{trend_word}。')

    # --- Sentence 3: Profitability + financial health ---
    health_parts = []
    if is_loss:
        if debt_ratio is not None and debt_ratio > 60:
            health_parts.append(f'资产负债率{debt_ratio:.1f}%，财务杠杆偏高，需关注偿债风险')
        elif debt_ratio is not None:
            health_parts.append(f'资产负债率{debt_ratio:.1f}%，财务状况尚可')
        if op_cf is not None and op_cf < 0:
            health_parts.append('经营现金流为负，造血能力不足')
    else:
        if roe > 15:
            health_parts.append(f'公司ROE为{roe:.1f}%，盈利质量优异')
        elif roe > 8:
            health_parts.append(f'公司ROE为{roe:.1f}%，盈利能力良好')
        elif roe > 0:
            health_parts.append(f'公司ROE为{roe:.1f}%，盈利能力一般')

        if dy and dy > 3:
            health_parts.append(f'维持稳定分红（股息率{dy:.1f}%）')
        elif dy and dy > 1:
            health_parts.append(f'股息率{dy:.1f}%')

        if op_cf is not None:
            if op_cf > 0 and net_profit > 0:
                cf_ratio = op_cf / (net_profit / 1e8)
                if cf_ratio > 1.2:
                    health_parts.append('经营现金流充裕')
            elif op_cf < 0:
                health_parts.append('经营现金流为负，需关注回款质量')

    if health_parts:
        sentences.append('，'.join(health_parts) + '。')

    # --- Sentence 4: Valuation assessment ---
    target = valuation['target_price']
    upside = valuation['upside']
    method_name = valuation['method_name']

    if is_loss or (pe is not None and pe < 0):
        # Loss-making: use PB-based commentary
        if pb and pb > 0:
            sentences.append(f'当前股价对应PB为{pb:.2f}倍'
                             + (f'，相对净资产溢价较高' if pb > 3 else (f'，估值处于较低水平' if pb < 1 else f'，估值处于合理区间'))
                             + f'，{method_name}下目标价{target:.2f}元。')
        else:
            sentences.append(f'{method_name}下目标价{target:.2f}元，较现价{"上行" if upside > 0 else "下行"}{abs(upside):.1f}%。')
    elif pe and pe > 0:
        if pe < 10:
            val_desc = f'当前PE(TTM)仅{pe:.1f}倍，估值处于历史低位'
        elif pe < 20:
            val_desc = f'当前PE(TTM) {pe:.1f}倍，估值合理'
        elif pe < 40:
            val_desc = f'当前PE(TTM) {pe:.1f}倍，估值已部分反映增长预期'
        else:
            val_desc = f'当前PE(TTM) {pe:.1f}倍，估值偏高'
        sentences.append(f'{val_desc}，{method_name}下目标价{target:.2f}元，较现价有{abs(upside):.1f}%{"上行空间" if upside > 0 else "下行风险"}。')

    # --- Sentence 5: Rating conclusion with context ---
    rating = valuation['rating']
    factors = valuation.get('rating_factors', {})
    total_score = factors.get('total_score', 0) if factors else 0

    if is_loss:
        if rating in ('减持', '中性'):
            sentences.append(f'公司当前处于经营调整期，综合评分{total_score}分，给予"{rating}"评级，建议等待基本面拐点信号。')
        else:
            sentences.append(f'尽管公司尚处亏损，但估值具备安全边际，综合评分{total_score}分，给予"{rating}"评级。')
    elif rating == '买入':
        sentences.append(f'综合盈利能力、成长性与估值水平，综合评分{total_score}分，首次覆盖给予"{rating}"评级。')
    elif rating == '增持':
        sentences.append(f'综合考虑基本面与估值，综合评分{total_score}分，首次覆盖给予"{rating}"评级。')
    elif rating == '中性':
        sentences.append(f'当前估值与基本面基本匹配，综合评分{total_score}分，给予"{rating}"评级。')
    else:
        sentences.append(f'基本面或估值存在压力，综合评分{total_score}分，给予"{rating}"评级，建议谨慎关注。')

    return ''.join(sentences)


def generate_section_commentary(data, computed_financials, section):
    """Generate contextual, analytical commentary for each report section.

    Each section's commentary interprets the data rather than merely restating
    numbers. Negative or abnormal data points are called out directly.
    """

    if section == 'price_chart':
        klines = data.kline_parsed(250)
        if len(klines) < 2:
            return ''
        start_price = klines[0]['close']
        end_price = klines[-1]['close']
        change = (end_price / start_price - 1) * 100
        high = max(k['high'] for k in klines)
        low = min(k['low'] for k in klines)
        direction = '上涨' if change > 0 else '下跌'
        pos_ratio = (end_price - low) / (high - low) if high != low else 0.5
        amplitude = (high - low) / low * 100

        parts = []
        # Core price trend
        parts.append(f'过去一年股价累计{direction}{abs(change):.1f}%，期间最高{high:.2f}元、最低{low:.2f}元')

        # Volatility assessment
        if amplitude > 80:
            parts.append(f'振幅高达{amplitude:.0f}%，波动剧烈')
        elif amplitude > 40:
            parts.append(f'振幅{amplitude:.0f}%，波动较大')
        else:
            parts.append(f'振幅{amplitude:.0f}%')

        # Position relative to range with support/resistance context
        if pos_ratio > 0.8:
            parts.append(f'当前价位接近52周高点，上方压力位{high:.2f}元')
        elif pos_ratio > 0.6:
            parts.append(f'当前价位处于52周区间中上水平，上方压力位{high:.2f}元')
        elif pos_ratio > 0.4:
            parts.append(f'当前价位处于52周区间中部，上下空间均衡')
        elif pos_ratio > 0.2:
            parts.append(f'当前价位处于52周区间中下水平，下方支撑位{low:.2f}元')
        else:
            parts.append(f'当前价位接近52周低点，下方支撑位{low:.2f}元')

        # Recent momentum (last 20 trading days)
        if len(klines) >= 20:
            recent_change = (end_price / klines[-20]['close'] - 1) * 100
            if recent_change > 5:
                parts.append(f'近一个月上涨{recent_change:.1f}%，短期动能偏强')
            elif recent_change < -5:
                parts.append(f'近一个月下跌{abs(recent_change):.1f}%，短期承压')

        return '。'.join(parts) + '。'

    elif section == 'financial_table':
        if len(computed_financials) < 2:
            return ''
        latest = computed_financials[-1] if not computed_financials[-1].get('is_projected') else computed_financials[-2]
        prev = None
        for f in computed_financials:
            if f['year'] != latest['year'] and not f.get('is_projected'):
                prev = f
                break

        parts = []
        rg = latest.get('revenue_growth')
        pg = latest.get('profit_growth')
        roe = latest.get('roe')
        net_profit = latest.get('net_profit', 0)
        net_margin = latest.get('net_margin')

        # Revenue trend with acceleration/deceleration
        if rg is not None:
            prev_rg = prev.get('revenue_growth') if prev else None
            if rg > 0:
                if prev_rg is not None and rg > prev_rg + 5:
                    trend = '增速加快'
                elif prev_rg is not None and rg < prev_rg - 5:
                    trend = '增速放缓'
                else:
                    trend = '保持增长'
                parts.append(f'{latest["year"]}年营收同比增长{rg:.1f}%，{trend}')
            else:
                parts.append(f'{latest["year"]}年营收同比下降{abs(rg):.1f}%，收入端承压')

        # Profit interpretation - handle loss-making
        if pg is not None:
            if net_profit < 0:
                parts.append(f'归母净利润亏损{abs(net_profit)/1e8:.1f}亿元，盈利能力不足')
            elif pg > 0:
                parts.append(f'归母净利润同比增长{pg:.1f}%')
            else:
                parts.append(f'归母净利润同比下降{abs(pg):.1f}%')

        # ROE quality - never say "尚可" for losses
        if roe is not None:
            if roe > 15:
                parts.append(f'ROE为{roe:.1f}%，盈利能力优秀')
            elif roe > 10:
                parts.append(f'ROE为{roe:.1f}%，盈利能力良好')
            elif roe > 5:
                parts.append(f'ROE为{roe:.1f}%，盈利能力一般')
            elif roe > 0:
                parts.append(f'ROE仅{roe:.1f}%，资本回报率偏低')
            else:
                parts.append(f'ROE为{roe:.1f}%，公司处于亏损状态')

        # Net margin trend
        if net_margin is not None and prev:
            prev_margin = prev.get('net_margin')
            if prev_margin is not None:
                margin_chg = net_margin - prev_margin
                if abs(margin_chg) > 2:
                    parts.append(f'净利率{net_margin:.1f}%，同比{"提升" if margin_chg > 0 else "下降"}{abs(margin_chg):.1f}个百分点')

        # Projection reasonableness check
        projected = [f for f in computed_financials if f.get('is_projected')]
        if projected and rg is not None:
            proj = projected[0]
            proj_rg = proj.get('revenue_growth')
            if proj_rg is not None and abs(proj_rg - rg) > 15:
                parts.append(f'预测{proj["year"]}年营收增速{proj_rg:.1f}%，与实际趋势偏差较大，需谨慎看待')

        # Latest interim data
        interim = data.interim_financials()
        if interim:
            it = interim[0]
            iry = it.get('revenue_yoy')
            ipy = it.get('profit_yoy')
            it_parts = []
            if iry is not None:
                it_parts.append(f'营收同比{"+" if iry > 0 else ""}{iry:.1f}%')
            if ipy is not None:
                it_parts.append(f'净利润同比{"+" if ipy > 0 else ""}{ipy:.1f}%')
            if it_parts:
                parts.append(f'最新{it["label"]}数据显示{"、".join(it_parts)}')

        return '。'.join(parts) + '。' if parts else ''

    elif section == 'interim':
        interim = data.interim_financials()
        if not interim:
            return ''
        latest = interim[0]
        ry = latest.get('revenue_yoy')
        py = latest.get('profit_yoy')
        rev = latest.get('revenue', 0)
        profit = latest.get('net_profit', 0)

        parts = [f'{latest["label"]}期间']
        if ry is not None:
            parts.append(f'营收同比{"增长" if ry > 0 else "下降"}{abs(ry):.1f}%')
        if py is not None:
            if profit < 0:
                parts.append(f'归母净利润亏损{abs(profit)/1e8:.2f}亿元')
            else:
                parts.append(f'归母净利润同比{"增长" if py > 0 else "下降"}{abs(py):.1f}%')

        # Quarter-over-quarter trend comparison
        if len(interim) >= 2:
            labels = [it.get('label', '') for it in interim[:3]]
            rev_yoys = [it.get('revenue_yoy') for it in interim[:3]]
            profit_yoys = [it.get('profit_yoy') for it in interim[:3]]
            valid_py = [(l, p) for l, p in zip(labels, profit_yoys) if p is not None]

            if len(valid_py) >= 2:
                trend_vals = [p for _, p in valid_py]
                if all(trend_vals[i] >= trend_vals[i + 1] for i in range(len(trend_vals) - 1)):
                    parts.append('利润增速逐季改善，经营趋势向好')
                elif all(trend_vals[i] <= trend_vals[i + 1] for i in range(len(trend_vals) - 1)):
                    parts.append('利润增速逐季放缓，需关注后续趋势')
                else:
                    if ry is not None and interim[1].get('revenue_yoy') is not None:
                        if ry > interim[1]['revenue_yoy']:
                            parts.append('营收增速环比改善')
                        else:
                            parts.append('营收增速环比放缓')

            # Divergence between revenue and profit
            if ry is not None and py is not None:
                if py > ry + 10:
                    parts.append('利润增速显著高于营收增速，盈利能力改善')
                elif py < ry - 10:
                    parts.append('利润增速落后于营收增速，费用端或成本端承压')

        return '，'.join(parts) + '。'

    elif section == 'balance_sheet':
        financials = computed_financials
        if not financials:
            return ''
        latest = financials[-1] if not financials[-1].get('is_projected') else financials[-2]
        prev = None
        for f in financials:
            if f['year'] != latest['year'] and not f.get('is_projected'):
                prev = f
                break

        # Prefer latest quarterly balance data if available
        latest_bal = data.latest_balance()
        latest_bal_date = latest_bal.get('REPORT_DATE', '')[:10] if latest_bal else ''
        last_annual_date = (data.annual_balance(1)[0].get('REPORT_DATE', '')[:10]) if data.annual_balance(1) else ''
        use_quarterly = latest_bal_date > last_annual_date and '12-31' not in latest_bal_date

        if use_quarterly and latest_bal:
            q_ta = (latest_bal.get('TOTAL_ASSETS') or 0)
            q_tl = (latest_bal.get('TOTAL_LIABILITIES') or 0)
            q_eq = (latest_bal.get('TOTAL_PARENT_EQUITY') or 0) or (q_ta - q_tl)
            dr = round(q_tl / q_ta * 100, 2) if q_ta else latest.get('debt_ratio')
            ta = q_ta
            equity = q_eq
            q_label = data._period_label(latest_bal_date)
        else:
            dr = latest.get('debt_ratio')
            ta = latest.get('total_assets', 0)
            equity = latest.get('parent_equity', 0)
            q_label = None

        roe = latest.get('roe')
        roa = latest.get('roa')
        industry = data.industry

        parts = []

        # Period label prefix if quarterly
        if q_label:
            parts.append(f'截至{q_label}')

        # Leverage assessment with industry context
        if dr is not None:
            # Financial companies normally have high leverage
            is_financial = any(k in industry for k in ('银行', '保险', '证券', '金融'))
            if is_financial:
                parts.append(f'资产负债率{dr:.1f}%，符合金融行业特征')
            elif dr > 80:
                parts.append(f'资产负债率高达{dr:.1f}%，杠杆水平偏高，偿债压力较大')
            elif dr > 65:
                parts.append(f'资产负债率{dr:.1f}%，杠杆水平中等偏高')
            elif dr > 50:
                parts.append(f'资产负债率{dr:.1f}%，杠杆水平适中')
            elif dr > 30:
                parts.append(f'资产负债率{dr:.1f}%，财务结构稳健')
            else:
                parts.append(f'资产负债率仅{dr:.1f}%，几乎无财务杠杆')

        # Asset scale
        if ta:
            parts.append(f'总资产规模{ta/1e8:.0f}亿元')

        # Balance sheet trend (strengthening or weakening)
        if prev and dr is not None:
            prev_dr = prev.get('debt_ratio')
            if prev_dr is not None:
                dr_chg = dr - prev_dr
                if dr_chg > 5:
                    parts.append(f'杠杆率同比上升{dr_chg:.1f}个百分点，资产负债表有所恶化')
                elif dr_chg < -5:
                    parts.append(f'杠杆率同比下降{abs(dr_chg):.1f}个百分点，资产负债表改善')

        # Capital efficiency
        if roe is not None and roa is not None:
            if roe > 0 and roa > 0:
                leverage_multiplier = roe / roa if roa > 0 else 0
                parts.append(f'ROE {roe:.1f}%/ROA {roa:.2f}%')
                if leverage_multiplier > 5:
                    parts.append('高杠杆放大了资本回报')
            elif roe < 0:
                parts.append(f'ROE {roe:.1f}%，净资产收益为负')

        return '，'.join(parts) + '。' if parts else ''

    elif section == 'cashflow':
        cf_list = [r for r in data.cashflow_list if '12-31' in r.get('REPORT_DATE', '')]
        if not cf_list:
            return ''
        latest = cf_list[0]
        annual_year = latest.get('REPORT_DATE', '')[:4]
        op = (latest.get('NETCASH_OPERATE') or 0) / 1e8
        inv = (latest.get('NETCASH_INVEST') or 0) / 1e8
        fin = (latest.get('NETCASH_FINANCE') or 0) / 1e8

        # Get net profit for cash flow quality assessment
        annuals = data.compute_annual_financials(1)
        net_profit_yi = (annuals[0].get('net_profit', 0) / 1e8) if annuals else 0

        parts = []

        # First mention latest quarterly CF if available and newer
        latest_cf = data.latest_cashflow()
        latest_cf_date = latest_cf.get('REPORT_DATE', '')[:10] if latest_cf else ''
        if latest_cf_date and '12-31' not in latest_cf_date and latest_cf_date > (latest.get('REPORT_DATE', '')[:10]):
            q_op = (latest_cf.get('NETCASH_OPERATE') or 0) / 1e8
            q_label = data._period_label(latest_cf_date)
            parts.append(f'最新{q_label}经营现金流{q_op:.1f}亿元（累计）')

        # Operating cash flow quality (annual)
        if op > 0:
            parts.append(f'经营现金流净额{op:.0f}亿元')
            if net_profit_yi > 0:
                cf_coverage = op / net_profit_yi
                if cf_coverage > 1.5:
                    parts.append(f'是净利润的{cf_coverage:.1f}倍，现金创造能力优异')
                elif cf_coverage > 1:
                    parts.append('高于净利润，盈利含金量较高')
                elif cf_coverage > 0.5:
                    parts.append('低于净利润，部分利润未转化为现金')
                else:
                    parts.append('远低于净利润，盈利质量存疑')
            else:
                parts.append(f'现金创造能力{"强劲" if op > 100 else "稳健"}')
        else:
            parts.append(f'经营现金流为负（{op:.0f}亿元），造血能力不足，这是一个明显的风险信号')

        # Capex coverage
        if op > 0 and inv < 0:
            capex_coverage = op / abs(inv)
            if capex_coverage > 2:
                parts.append(f'经营现金流可覆盖投资支出{capex_coverage:.1f}倍，自由现金流充裕')
            elif capex_coverage > 1:
                parts.append('经营现金流可覆盖投资支出')
            else:
                parts.append(f'经营现金流不足以覆盖投资支出（覆盖率{capex_coverage:.0%}），需依赖外部融资')

        # Investment activity
        if inv < 0 and abs(inv) > 10:
            parts.append(f'投资净流出{abs(inv):.0f}亿元')
        elif inv > 0:
            parts.append(f'投资活动净流入{inv:.0f}亿元，可能涉及资产处置')

        # Financing activity
        if fin > 10:
            parts.append(f'筹资净流入{fin:.0f}亿元，融资活动活跃')
        elif fin < -10:
            parts.append(f'筹资净流出{abs(fin):.0f}亿元，以偿债或分红为主')

        # YoY comparison
        if len(cf_list) >= 2:
            prev_op = (cf_list[1].get('NETCASH_OPERATE') or 0) / 1e8
            if prev_op != 0:
                op_chg = (op / prev_op - 1) * 100 if prev_op > 0 else 0
                if abs(op_chg) > 20 and prev_op > 0:
                    parts.append(f'经营现金流同比{"增长" if op_chg > 0 else "下降"}{abs(op_chg):.0f}%')

        return '；'.join(parts) + '。' if parts else ''

    elif section == 'dividend':
        divs = data.dividends[:5]
        dy = data.dividend_yield
        if not divs:
            return '公司近年未进行现金分红，股东回报有待加强。'

        bonuses = [d.get('PRETAX_BONUS_RMB', 0) or 0 for d in divs]
        bonuses_valid = [b for b in bonuses if b > 0]

        if not bonuses_valid:
            return '公司近年虽有分红记录但派现金额较低，股东回报力度有限。'

        # Dividend trend
        if len(bonuses_valid) >= 2:
            consecutive_up = all(bonuses_valid[i] >= bonuses_valid[i + 1] for i in range(len(bonuses_valid) - 1))
            consecutive_down = all(bonuses_valid[i] <= bonuses_valid[i + 1] for i in range(len(bonuses_valid) - 1))
            if consecutive_up:
                trend = '逐年提升'
            elif consecutive_down:
                trend = '逐年下降'
            elif bonuses_valid[0] >= bonuses_valid[1]:
                trend = '近期有所提升'
            else:
                trend = '近期有所下降'
        else:
            trend = '分红记录较少'

        avg_bonus = sum(bonuses_valid) / len(bonuses_valid)
        parts = []
        parts.append(f'公司近{len(bonuses_valid)}次分红每10股平均派现{avg_bonus:.1f}元，分红水平{trend}')

        # Yield assessment vs market average (~2% for A-share)
        if dy > 4:
            parts.append(f'当前股息率{dy:.1f}%，显著高于市场平均水平，具备较强的类固收配置价值')
        elif dy > 2:
            parts.append(f'当前股息率{dy:.1f}%，高于市场平均，分红回报较好')
        elif dy > 1:
            parts.append(f'当前股息率{dy:.1f}%，接近市场平均水平')
        elif dy > 0:
            parts.append(f'当前股息率仅{dy:.1f}%，低于市场平均')
        else:
            parts.append('当前股息率接近零')

        # Sustainability check: compare dividend vs profit
        annuals = data.compute_annual_financials(1)
        if annuals and bonuses_valid:
            net_profit = annuals[0].get('net_profit', 0)
            eps = annuals[0].get('eps')
            if eps and eps > 0:
                payout_per_share = bonuses_valid[0] / 10
                payout_ratio = payout_per_share / eps * 100
                if payout_ratio > 80:
                    parts.append(f'派息率约{payout_ratio:.0f}%，分红慷慨但可持续性需观察')
                elif payout_ratio > 30:
                    parts.append(f'派息率约{payout_ratio:.0f}%，分红可持续')
                elif payout_ratio > 0:
                    parts.append(f'派息率约{payout_ratio:.0f}%，仍有提升分红空间')
            elif net_profit < 0:
                parts.append('公司当前处于亏损状态，分红持续性存疑')

        return '。'.join(parts) + '。'

    return ''


# ══════════════════════════════════════════════════════════════
#  Risk Generator
# ══════════════════════════════════════════════════════════════


def build_wordcloud_data(data: StockData):
    """Build word cloud data from guba posts using jieba TF-IDF + bigram phrases."""
    import jieba
    import jieba.analyse

    raw = data._load('guba')
    posts = raw.get('posts', []) if raw else []
    if not posts:
        return '[]', '暂无股吧数据'

    all_text = '。'.join(p.get('title', '') for p in posts)

    stop_words = set('的 了 是 在 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 自己 这 '
                     '吗 吧 啊 呢 嘛 哦 呀 哈 啥 咋 咯 哟 喔 嗯 哪 那 这个 那个 什么 怎么 为什么 怎么样 '
                     '股票 公司 股 元 万 亿 个 只 还 又 再 已 已经 可以 应该 可能 觉得 感觉 知道 '
                     '今天 明天 昨天 现在 时候 以后 之后 之前 最近 大家 各位 股民 散户 '
                     '东方 财富 网友 评论 转发 阅读 置顶 资讯 真的 不是 就是 这样'.split())

    # --- Method 1: TF-IDF keywords (extracts longer meaningful phrases) ---
    tfidf_words = jieba.analyse.extract_tags(all_text, topK=40, withWeight=True)
    word_count = {}
    for w, weight in tfidf_words:
        if len(w) >= 2 and w not in stop_words and not w.isdigit():
            word_count[w] = round(weight * 100)

    # --- Method 2: Bigram/trigram phrases from segmentation ---
    for title in [p.get('title', '') for p in posts]:
        segs = [s for s in jieba.lcut(title) if len(s) >= 2 and s not in stop_words and not s.isdigit()]
        # Generate bigrams (2-word phrases like "股价下跌", "利好消息")
        for i in range(len(segs) - 1):
            bigram = segs[i] + segs[i + 1]
            if 3 <= len(bigram) <= 8:
                word_count[bigram] = word_count.get(bigram, 0) + 3
        # Generate trigrams
        for i in range(len(segs) - 2):
            trigram = segs[i] + segs[i + 1] + segs[i + 2]
            if 4 <= len(trigram) <= 10:
                word_count[trigram] = word_count.get(trigram, 0) + 2

    # Filter out low-quality phrases: too long ngrams, or substrings of top phrases
    sorted_all = sorted(word_count.items(), key=lambda x: x[1], reverse=True)
    # Deduplicate: if a shorter phrase is fully contained in a higher-ranked longer one, skip shorter
    seen_texts = set()
    filtered = []
    for w, c in sorted_all:
        if c < 2 or len(w) > 8:  # Skip very long unnatural concatenations
            continue
        # Skip if this word is a substring of an already-added higher-ranked phrase
        is_sub = any(w in s and w != s for s in seen_texts)
        if not is_sub:
            filtered.append((w, c))
            seen_texts.add(w)
        if len(filtered) >= 60:
            break
    cloud_data = [{'name': w, 'value': max(c, 1)} for w, c in filtered]

    # --- Sentiment analysis ---
    words_flat = jieba.lcut(all_text)
    pos_words = set('涨 利好 买入 加仓 看好 反弹 上涨 牛 突破 机会 强势 翻倍 龙头 低估 分红 增持 回购 盈利 增长 看涨 抄底'.split())
    neg_words = set('跌 利空 卖出 减仓 看空 下跌 熊 破位 套牢 亏损 割肉 垃圾 崩 暴跌 退市 减持 高估 风险 暴雷 坑 骗'.split())
    pos_count = sum(1 for w in words_flat if w in pos_words)
    neg_count = sum(1 for w in words_flat if w in neg_words)
    total_sentiment = pos_count + neg_count
    if total_sentiment > 0:
        pos_pct = round(pos_count / total_sentiment * 100)
        neg_pct = round(neg_count / total_sentiment * 100)
        mood = '偏乐观' if pos_pct > 60 else ('偏悲观' if neg_pct > 60 else '多空分歧')
        sentiment = f'基于{len(posts)}条股吧帖子分析，市场情绪{mood}（正面{pos_pct}%/负面{neg_pct}%）。'
    else:
        sentiment = f'基于{len(posts)}条股吧帖子生成。'

    return json.dumps(cloud_data, ensure_ascii=False), sentiment


def analyze_announcements(data: StockData):
    """Analyze recent announcements and generate a summary paragraph."""
    anns = data.recent_announcements(20)
    if not anns:
        return '近期无重大公告披露。'

    # Categorize announcements by type
    categories = {
        '业绩': [], '年报': [], '季报': [], '半年报': [],
        '分红': [], '股东': [], '董事': [], '回购': [],
        '增持': [], '减持': [], '融资': [], '诉讼': [],
        '股权': [], '投资': [], '并购': [], '合作': [],
        '评级': [], '临时股东会': [], '债券': [],
    }
    uncategorized = []

    for a in anns:
        title = a['title']
        matched = False
        for key in categories:
            if key in title:
                categories[key].append(a)
                matched = True
                break
        if not matched:
            uncategorized.append(a)

    # Build analysis paragraphs
    parts = []
    date_range = f"{anns[-1]['date']}至{anns[0]['date']}" if len(anns) > 1 else anns[0]['date']
    parts.append(f'<b>公告动态</b>（{date_range}，共{len(anns)}条重要公告）：')

    # Performance related
    perf = categories['业绩'] + categories['年报'] + categories['季报'] + categories['半年报']
    if perf:
        titles = '、'.join([f'"{a["title"][:20]}"' for a in perf[:3]])
        parts.append(f'<b>业绩披露</b>：公司近期发布了{len(perf)}份业绩相关公告，包括{titles}等，建议关注最新财务数据变化。')

    # Dividend
    if categories['分红']:
        parts.append(f'<b>分红派息</b>：公司发布了分红相关公告{len(categories["分红"])}条，体现了公司对股东回报的重视。')

    # Governance (shareholders meeting, board changes)
    gov = categories['股东'] + categories['董事'] + categories['临时股东会']
    if gov:
        titles = '、'.join([f'{a["title"][:25]}' for a in gov[:2]])
        parts.append(f'<b>公司治理</b>：涉及{titles}等事项。')

    # Capital operations
    cap = categories['回购'] + categories['增持'] + categories['减持'] + categories['融资'] + categories['债券']
    if cap:
        actions = []
        if categories['回购']:
            actions.append('回购')
        if categories['增持']:
            actions.append('增持')
        if categories['减持']:
            actions.append('减持')
        if categories['融资'] or categories['债券']:
            actions.append('融资/发债')
        parts.append(f'<b>资本运作</b>：近期涉及{"、".join(actions)}等动作，需关注对股本结构和资金面的影响。')

    # M&A / Investment
    ma = categories['投资'] + categories['并购'] + categories['合作'] + categories['股权']
    if ma:
        parts.append(f'<b>战略动态</b>：涉及投资/并购/合作相关公告{len(ma)}条，可能影响公司未来业务版图。')

    # If nothing categorized well, give a generic summary
    if len(parts) <= 1:
        recent_titles = '；'.join([a['title'][:30] for a in anns[:5]])
        parts.append(f'近期主要公告包括：{recent_titles}。整体来看公司经营活动正常，未见重大风险事项。')

    return ' '.join(parts)


def generate_risks(data: StockData):
    """Generate 3 risk items based on industry."""
    industry = data.industry
    base_risks = [
        f'宏观经济下行可能影响{data.industry}行业整体表现',
        '公司经营业绩不及预期的风险',
        '市场系统性风险导致估值下行',
    ]

    if '银行' in industry:
        return [
            '资产质量恶化风险：宏观经济下行可能导致不良贷款率上升',
            '净息差持续收窄风险：利率下行周期中银行盈利能力承压',
            '房地产等重点领域信用风险暴露',
        ]
    elif '保险' in industry:
        return [
            '长端利率超预期下行，加大再投资压力和利差损风险',
            '新单销售增速放缓，新业务价值增长不及预期',
            '权益市场大幅波动，拖累投资收益与利润表现',
        ]
    elif '证券' in industry:
        return [
            '市场交投活跃度下降导致经纪业务收入减少',
            '自营投资亏损风险',
            '资本市场改革政策变动对行业格局的影响',
        ]
    elif any(k in industry for k in ['电子', '计算机', '通信', '半导体']):
        return [
            '技术迭代加速，产品竞争力下降风险',
            '下游需求不及预期，行业景气度回落',
            '国际贸易摩擦和供应链安全风险',
        ]
    elif any(k in industry for k in ['医药', '生物']):
        return [
            '药品/器械集采政策导致产品价格大幅下降',
            '研发管线进展不及预期或临床试验失败',
            '行业政策变动风险（医保谈判、合规监管等）',
        ]
    elif any(k in industry for k in ['食品', '饮料', '消费']):
        return [
            '消费需求疲软，终端动销不及预期',
            '原材料成本上涨压缩利润空间',
            '食品安全事件或品牌声誉风险',
        ]
    elif any(k in industry for k in ['房地产']):
        return [
            '房地产市场持续低迷，销售回款不及预期',
            '融资环境收紧，流动性压力加大',
            '政策调控进一步加码的风险',
        ]
    elif any(k in industry for k in ['钢铁', '煤炭', '有色', '化工']):
        return [
            '大宗商品价格大幅波动影响盈利',
            '下游需求走弱，产能过剩加剧',
            '环保政策趋严带来的合规成本上升',
        ]
    elif any(k in industry for k in ['电力', '水务', '燃气', '公用事业']):
        return [
            '电价/气价等政策调整风险',
            '燃料成本上涨侵蚀利润空间',
            '新能源替代加速带来的转型风险',
        ]
    elif any(k in industry for k in ['汽车']):
        return [
            '汽车行业价格竞争加剧压缩利润空间',
            '新能源转型不及预期的风险',
            '芯片等核心零部件供应链风险',
        ]
    return base_risks


# ══════════════════════════════════════════════════════════════
#  HTML Generation — Dense Professional 2-Page Report
# ══════════════════════════════════════════════════════════════

def fmt(val, precision=2, unit=''):
    """Format a number for display."""
    if val is None:
        return 'N/A'
    if isinstance(val, str):
        return val
    if abs(val) >= 1e8:
        return f'{val/1e8:.{precision}f}亿{unit}'
    if abs(val) >= 1e4:
        return f'{val/1e4:.{precision}f}万{unit}'
    return f'{val:.{precision}f}{unit}'


def pct(val):
    if val is None:
        return 'N/A'
    return f'{val:.1f}%' if isinstance(val, (int, float)) else str(val)


def safe_f(val, fmt_str='.2f'):
    if val is None:
        return 'N/A'
    try:
        return f'{val:{fmt_str}}'
    except (ValueError, TypeError):
        return str(val)


def generate_simple_html(data: StockData, valuation: dict):
    """Generate dense 2-page professional report HTML."""
    today = datetime.now().strftime('%Y-%m-%d')

    # Rating
    rating = valuation['rating']
    rating_colors = {'买入': '#c0392b', '增持': '#d35400', '中性': '#7f8c8d', '减持': '#27ae60'}
    rating_color = rating_colors.get(rating, '#333')
    rating_bg = {'买入': '#fdecea', '增持': '#fef5ec', '中性': '#f2f3f4', '减持': '#eafaf1'}.get(rating, '#f2f3f4')

    # 52-week range
    w52_low, w52_high = data.week52_range()

    # Investment thesis
    thesis = generate_thesis(data, valuation)
    # Prefer AI analysis if available
    if data.analysis.get('core_thesis'):
        thesis = data.analysis['core_thesis']

    # Risks
    risks = generate_risks(data)
    # Prefer AI analysis if available
    if data.analysis.get('risk_factors'):
        risks = data.analysis['risk_factors']

    # Business overview from company survey
    intro = data.company_intro
    if intro:
        # Clean HTML tags if present
        import re
        intro = re.sub(r'<[^>]+>', '', intro)
        intro_short = intro[:200] + '...' if len(intro) > 200 else intro
        intro_long = intro[:250] + '...' if len(intro) > 250 else intro
    else:
        intro_short = f'{data.name}是{data.industry}行业的A股上市公司。'
        intro_long = intro_short

    # Prefer AI analysis if available
    if data.analysis.get('business_summary'):
        intro_long = data.analysis['business_summary']

    biz_scope = data.business_scope
    if biz_scope:
        import re
        biz_scope = re.sub(r'<[^>]+>', '', biz_scope)
        biz_scope_short = biz_scope[:100] + '...' if len(biz_scope) > 100 else biz_scope
    else:
        biz_scope_short = ''

    # ── Prepare chart data ──
    klines = data.kline_parsed(250)
    kline_dates = json.dumps([k['date'] for k in klines])
    kline_closes = json.dumps([k['close'] for k in klines])
    kline_volumes = json.dumps([round(k['volume'] / 1e4, 0) for k in klines])

    # Revenue/profit chart (annual)
    annuals_for_chart = data.annual_income(5)
    annuals_for_chart.reverse()
    chart_years = []
    chart_revenues = []
    chart_profits = []
    for r in annuals_for_chart:
        date = r.get('REPORT_DATE', '')[:4]
        rev = r.get('TOTAL_OPERATE_INCOME') or r.get('OPERATE_INCOME') or 0
        prof = r.get('PARENT_NETPROFIT') or r.get('NETPROFIT') or 0
        chart_years.append(date)
        chart_revenues.append(round(rev / 1e8, 2))
        chart_profits.append(round(prof / 1e8, 2))
    rev_years_json = json.dumps(chart_years)
    rev_data_json = json.dumps(chart_revenues)
    profit_data_json = json.dumps(chart_profits)

    # ── Key financials table (from computed data) ──
    computed = data.compute_annual_financials(4)
    computed.reverse()  # oldest first

    # Project 1 year forward (simple growth extrapolation)
    if len(computed) >= 2:
        last = computed[-1]
        prev = computed[-2]
        proj_year = str(int(last['year']) + 1) + 'E'
        # Use average growth of last 2 years or latest
        rg = last.get('revenue_growth')
        pg = last.get('profit_growth')
        proj_rev = last['revenue'] * (1 + (rg or 5) / 100) if last['revenue'] else 0
        proj_profit = last['net_profit'] * (1 + (pg or 5) / 100) if last['net_profit'] else 0
        proj_eps = last.get('eps')
        if proj_eps and pg is not None:
            proj_eps = round(proj_eps * (1 + (pg or 5) / 100), 2)
        proj_roe = last.get('roe') or data.roe
        # PE for projection
        proj_pe = round(data.price / proj_eps, 1) if proj_eps and proj_eps > 0 and data.price else None
        proj_pb = data.pb  # assume stable
        computed.append({
            'year': proj_year,
            'revenue': proj_rev,
            'revenue_growth': rg,  # carry forward
            'net_profit': proj_profit,
            'profit_growth': pg,
            'eps': proj_eps,
            'roe': proj_roe,
            'pe': proj_pe,
            'pb': proj_pb,
            'is_projected': True,
        })

    fin_rows = ''
    for r in computed:
        year = r['year']
        is_proj = r.get('is_projected', False)
        year_display = f'<b>{year}</b>' if is_proj else year
        rev_str = f'{r["revenue"]/1e8:.1f}' if r.get("revenue") else 'N/A'
        rg_str = pct(r.get('revenue_growth'))
        np_str = f'{r["net_profit"]/1e8:.1f}' if r.get("net_profit") else 'N/A'
        pg_str = pct(r.get('profit_growth'))
        eps_str = safe_f(r.get('eps'))
        roe_str = pct(r.get('roe'))
        pe_str = safe_f(r.get('pe'), '.1f')
        pb_str = safe_f(r.get('pb'))
        style = ' style="background:#fffde7;"' if is_proj else ''
        fin_rows += f'<tr{style}><td>{year_display}</td><td>{rev_str}</td><td>{rg_str}</td><td>{np_str}</td><td>{pg_str}</td><td>{eps_str}</td><td>{roe_str}</td><td>{pe_str}</td><td>{pb_str}</td></tr>'

    # ── Balance sheet metrics table for page 2 (annual + latest quarterly) ──
    bal_annuals = data.annual_balance(2)
    bal_annuals_rev = list(reversed(bal_annuals))
    # Add latest quarterly if newer than last annual
    latest_bal = data.latest_balance()
    latest_bal_date = latest_bal.get('REPORT_DATE', '')[:10] if latest_bal else ''
    last_annual_bal_date = bal_annuals[0].get('REPORT_DATE', '')[:10] if bal_annuals else ''
    bal_display = list(bal_annuals_rev)
    if latest_bal_date > last_annual_bal_date and '12-31' not in latest_bal_date:
        bal_display.append(latest_bal)

    inc_annuals = data.annual_income(5)
    inc_by_date = {}
    for inc in data.income_list:
        rd = inc.get('REPORT_DATE', '')[:10]
        if rd:
            inc_by_date[rd] = inc

    asset_rows = ''
    for b in bal_display:
        rd = b.get('REPORT_DATE', '')[:10]
        label = data._period_label(rd)
        ta = (b.get('TOTAL_ASSETS') or 0) / 1e8
        eq = (b.get('TOTAL_PARENT_EQUITY') or 0) / 1e8
        tl = (b.get('TOTAL_LIABILITIES') or 0) / 1e8
        if eq == 0 and ta and tl:
            eq = ta - tl
        dar = tl / ta * 100 if ta else 0
        # ROE/ROA from matching income period
        inc = inc_by_date.get(rd, {})
        np_val = inc.get('PARENT_NETPROFIT') or inc.get('NETPROFIT') or 0
        roe_val = round(np_val / (eq * 1e8) * 100, 2) if eq else 0
        roa_val = round(np_val / (ta * 1e8) * 100, 2) if ta else 0
        asset_rows += f'<tr><td>{label}</td><td>{ta:.1f}</td><td>{eq:.1f}</td><td>{dar:.1f}%</td><td>{roe_val:.1f}%</td><td>{roa_val:.2f}%</td></tr>'

    # ── Cash flow table for page 2 (annual + latest quarterly) ──
    cf_annuals = data.annual_cashflow(2)
    cf_annuals_rev = list(reversed(cf_annuals))
    # Add latest quarterly if newer than last annual
    latest_cf = data.latest_cashflow()
    latest_cf_date = latest_cf.get('REPORT_DATE', '')[:10] if latest_cf else ''
    last_annual_cf_date = cf_annuals[0].get('REPORT_DATE', '')[:10] if cf_annuals else ''
    cf_display = list(cf_annuals_rev)
    if latest_cf_date > last_annual_cf_date and '12-31' not in latest_cf_date:
        cf_display.append(latest_cf)

    cf_rows = ''
    for r in cf_display:
        rd = r.get('REPORT_DATE', '')[:10]
        label = data._period_label(rd)
        op = (r.get('NETCASH_OPERATE') or 0) / 1e8
        inv = (r.get('NETCASH_INVEST') or 0) / 1e8
        fin = (r.get('NETCASH_FINANCE') or 0) / 1e8
        cf_rows += f'<tr><td>{label}</td><td>{op:.1f}</td><td>{inv:.1f}</td><td>{fin:.1f}</td></tr>'

    # ── Dividend history table for page 2 (compact: 4 columns) ──
    divs = data.dividends[:5]
    div_rows = ''
    for d in divs:
        bonus = d.get('PRETAX_BONUS_RMB')
        # Simplified: just show "10派X元"
        plan_short = f'10派{bonus:.1f}元' if bonus else (d.get('IMPL_PLAN_PROFILE') or '-')[:12]
        eps_d = d.get('BASIC_EPS')
        dy = ''
        if bonus and data.price and data.price > 0:
            dy = f'{bonus / 10 / data.price * 100:.1f}%'
        ex_date = (d.get('EX_DIVIDEND_DATE') or '')[:10]
        div_rows += f'<tr><td>{ex_date}</td><td>{plan_short}</td><td>{safe_f(eps_d)}</td><td>{dy or "-"}</td></tr>'

    # ── Valuation details ──
    # AI can override rating if analysis.json provides one
    if data.analysis.get('rating'):
        valuation['rating'] = data.analysis['rating']
        # Re-derive rating display variables
        rating = valuation['rating']
        rating_color = rating_colors.get(rating, '#333')
        rating_bg = {'买入': '#fdecea', '增持': '#fef5ec', '中性': '#f2f3f4', '减持': '#eafaf1'}.get(rating, '#f2f3f4')
    if data.analysis.get('rating_reason'):
        valuation['explanation'] = data.analysis['rating_reason']

    val_details_html = '<br>'.join(valuation['details'])
    # Add AI valuation commentary if available
    if data.analysis.get('valuation_analysis'):
        val_details_html = data.analysis['valuation_analysis'] + '<br>' + val_details_html

    # Scenarios
    scenarios = valuation.get('scenarios', {})
    bear = scenarios.get('bear', 0)
    base = scenarios.get('base', valuation['target_price'])
    bull = scenarios.get('bull', 0)

    # ── Interim (2025 Q1/H1/Q3) data rows ──
    interim = data.interim_financials()
    interim_rows = ''
    for r in interim:
        rev_str = f'{r["revenue"]/1e8:.1f}' if r.get("revenue") else 'N/A'
        ry_str = pct(r.get('revenue_yoy'))
        np_str = f'{r["net_profit"]/1e8:.1f}' if r.get("net_profit") else 'N/A'
        py_str = pct(r.get('profit_yoy'))
        interim_rows += f'<tr style="background:#e8f8f5;"><td><b>{r["label"]}</b></td><td>{rev_str}</td><td>{ry_str}</td><td>{np_str}</td><td>{py_str}</td></tr>'

    # ── Word cloud from guba (股吧) ──
    wordcloud_data_json, sentiment_summary = build_wordcloud_data(data)
    sentiment_summary = data.analysis.get('guba_analysis') or sentiment_summary

    # ── Main business composition (for bar chart) ──
    mainop_segments = data.mainop_by_segment()
    mainop_segments.sort(key=lambda x: x['revenue'])  # ascending for horizontal bar
    mainop_names_json = json.dumps([s['name'] for s in mainop_segments], ensure_ascii=False)
    mainop_values_json = json.dumps([round(s['revenue'] / 1e8, 1) for s in mainop_segments])
    has_mainop = len(mainop_segments) > 0

    # ── Company info cards ──
    company_cards = []
    if data.founding_date:
        company_cards.append(('成立', data.founding_date))
    if data.ipo_date:
        company_cards.append(('上市', data.ipo_date))
    if data.registered_capital:
        company_cards.append(('注册资本', data.registered_capital))
    if data.employee_count:
        company_cards.append(('员工', f'{int(data.employee_count):,}人' if str(data.employee_count).isdigit() else data.employee_count))
    if data.chairman:
        company_cards.append(('董事长', data.chairman))
    company_cards_html = ''.join(f'<span class="info-tag"><b>{k}:</b> {v}</span>' for k, v in company_cards)

    # ── Section commentaries ──
    price_commentary = data.analysis.get('price_commentary') or generate_section_commentary(data, computed, 'price_chart')
    fin_commentary = data.analysis.get('financial_commentary') or generate_section_commentary(data, computed, 'financial_table')
    interim_commentary = data.analysis.get('interim_commentary') or generate_section_commentary(data, computed, 'interim')
    balance_commentary = data.analysis.get('balance_commentary') or generate_section_commentary(data, computed, 'balance_sheet')
    cashflow_commentary = data.analysis.get('cashflow_commentary') or generate_section_commentary(data, computed, 'cashflow')
    dividend_commentary = data.analysis.get('dividend_commentary') or generate_section_commentary(data, computed, 'dividend')

    # ── Compose the full HTML ──
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{data.name}({data.code}) 个股研究报告</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/echarts-wordcloud@2/dist/echarts-wordcloud.min.js"></script>
<style>
@page {{
    size: A4;
    margin: 0;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: "STKaiti", "KaiTi", "楷体", "Kaiti SC", serif;
    font-size: 10pt;
    color: #000;
    font-weight: 600;
    line-height: 1.5;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
}}

.page {{
    page-break-after: always;
    width: 100%;
    height: 297mm;
    box-sizing: border-box;
    overflow: hidden;
    padding: 12px 45px 20px 45px;
    position: relative;
}}
.page:last-child {{ page-break-after: avoid; }}

/* ── Header ── */
.header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    border-bottom: 2.5px solid #1a5276;
    padding-bottom: 5px;
    margin-bottom: 6px;
}}
.header-left h1 {{
    font-size: 17pt;
    color: #1a5276;
    font-weight: 800;
    letter-spacing: 0.5px;
    margin-bottom: 1px;
}}
.header-left .code-line {{
    font-size: 9pt;
    color: #555;
}}
.header-left .code-line span {{
    margin-right: 10px;
}}
.header-right {{
    text-align: right;
    min-width: 130px;
}}
.rating-badge {{
    display: inline-block;
    font-size: 15pt;
    font-weight: 800;
    color: {rating_color};
    border: 2.5px solid {rating_color};
    background: {rating_bg};
    padding: 2px 16px;
    border-radius: 4px;
    letter-spacing: 2px;
}}
.header-right .target-line {{
    font-size: 8.5pt;
    color: #333;
    margin-top: 3px;
    font-weight: 600;
}}
.header-right .date-line {{
    font-size: 7.5pt;
    color: #999;
    margin-top: 1px;
}}

/* ── Metrics bar ── */
.metrics-bar {{
    display: grid;
    grid-template-columns: repeat(9, 1fr);
    gap: 0;
    border: 1px solid #ddd;
    border-radius: 3px;
    margin-bottom: 6px;
    background: #f8f9fa;
}}
.metric-cell {{
    text-align: center;
    padding: 4px 3px;
    border-right: 1px solid #e0e0e0;
}}
.metric-cell:last-child {{ border-right: none; }}
.metric-cell .ml {{ font-size: 8pt; color: #666; }}
.metric-cell .mv {{
    font-size: 11pt;
    font-weight: 800;
    color: #1a5276;
}}

/* ── Thesis box ── */
.thesis-box {{
    background: #fdfefe;
    border-left: 3px solid #1a5276;
    padding: 5px 8px;
    margin-bottom: 6px;
    font-size: 9.5pt;
    color: #222;
    line-height: 1.55;
}}
.thesis-box .thesis-title {{
    font-size: 10pt;
    font-weight: 700;
    color: #1a5276;
    margin-bottom: 2px;
}}

/* ── Section titles ── */
.sec-title {{
    font-size: 11pt;
    font-weight: 700;
    color: #1a5276;
    border-left: 3px solid #1a5276;
    padding-left: 6px;
    margin-bottom: 4px;
    margin-top: 2px;
}}

/* ── Charts ── */
.chart-container {{
    margin-bottom: 4px;
}}

/* ── Tables ── */
table.ft {{
    width: 100%;
    border-collapse: collapse;
    font-size: 9pt;
    margin-bottom: 5px;
}}
table.ft th {{
    background: #1a5276;
    color: white;
    padding: 3px 5px;
    text-align: center;
    font-weight: 700;
    font-size: 9pt;
    white-space: nowrap;
}}
table.ft td {{
    padding: 3px 5px;
    text-align: center;
    border-bottom: 1px solid #ddd;
    font-size: 9pt;
    color: #111;
    white-space: nowrap;
}}
table.ft tr:nth-child(even) {{ background: #fafbfc; }}

/* ── Business text ── */
.biz-text {{
    font-size: 9pt;
    color: #222;
    line-height: 1.5;
    margin-bottom: 4px;
    text-align: justify;
}}
.biz-scope {{
    font-size: 8.5pt;
    color: #444;
    line-height: 1.4;
    margin-bottom: 3px;
}}

/* ── Valuation box ── */
.val-box {{
    border: 1px solid #d4ac0d;
    background: linear-gradient(135deg, #fefef3 0%, #fef9e7 100%);
    border-radius: 4px;
    padding: 6px 10px;
    margin-bottom: 5px;
}}
.val-box .val-title {{
    font-size: 10pt;
    font-weight: 700;
    color: #7d6608;
    margin-bottom: 3px;
}}
.val-box .val-detail {{
    font-size: 9pt;
    color: #333;
    line-height: 1.5;
}}
.val-box .val-target {{
    font-size: 11pt;
    font-weight: 700;
    color: #c0392b;
    margin-top: 3px;
}}
.scenarios {{
    display: flex;
    gap: 12px;
    margin-top: 3px;
    font-size: 9pt;
}}
.scenarios .sc {{
    padding: 2px 8px;
    border-radius: 3px;
    font-weight: 700;
}}
.sc-bear {{ background: #fadbd8; color: #922b21; }}
.sc-base {{ background: #fdebd0; color: #7e5109; }}
.sc-bull {{ background: #d5f5e3; color: #1e8449; }}

/* ── Rating box ── */
.rating-box {{
    display: flex;
    align-items: center;
    gap: 16px;
    background: linear-gradient(135deg, #1a5276, #2471a3);
    color: white;
    border-radius: 4px;
    padding: 7px 14px;
    margin-bottom: 5px;
}}
.rating-box .rb-label {{ font-size: 9pt; opacity: 0.9; }}
.rating-box .rb-value {{ font-size: 20pt; font-weight: 800; letter-spacing: 2px; }}
.rating-box .rb-info {{ font-size: 9pt; opacity: 0.9; line-height: 1.5; }}

/* ── Risks ── */
.risk-list {{
    list-style: none;
    padding: 0;
}}
.risk-list li {{
    font-size: 9pt;
    color: #333;
    padding: 1.5px 0;
    padding-left: 10px;
    position: relative;
}}
.risk-list li::before {{
    content: "\\25B6";
    position: absolute;
    left: 0;
    color: #c0392b;
    font-size: 5pt;
    top: 3px;
}}

/* ── Footer ── */
.footer {{
    font-size: 7pt;
    color: #aaa;
    text-align: center;
    border-top: 1px solid #eee;
    padding-top: 3px;
    position: absolute;
    bottom: 8px;
    left: 45px;
    right: 45px;
}}

/* ── Two-column layout ── */
.two-col {{
    display: flex;
    gap: 10px;
}}
.two-col > div {{ flex: 1; }}

.three-col {{
    display: flex;
    gap: 8px;
}}
.commentary {{
    font-size: 9pt;
    color: #222;
    line-height: 1.35;
    padding: 1px 0 3px 0;
    border-left: 2px solid #ccc;
    padding-left: 6px;
    margin: 3px 0;
}}
.info-tag {{
    display: inline-block;
    font-size: 8.5pt;
    background: #f0f4f8;
    border: 1px solid #d5dde5;
    border-radius: 3px;
    padding: 2px 6px;
    color: #1a5276;
    font-weight: 600;
}}
</style>
</head>
<body>

<!-- ════════════════════════════════════════ PAGE 1 ════════════════════════════════════════ -->
<div class="page">
    <!-- Header -->
    <div class="header">
        <div class="header-left">
            <h1>{data.name}</h1>
            <div class="code-line">
                <span>{data.full_code}</span>
                <span>{data.industry}</span>
                <span>{data.company_name}</span>
            </div>
        </div>
        <div class="header-right">
            <div class="rating-badge">{rating}</div>
            <div class="target-line">目标价: {valuation['target_price']:.2f} 元</div>
            <div class="date-line">{today} | AI 研究报告</div>
        </div>
    </div>

    <!-- Key Metrics Bar -->
    <div class="metrics-bar">
        <div class="metric-cell">
            <div class="ml">股价(元)</div>
            <div class="mv">{data.price:.2f}</div>
        </div>
        <div class="metric-cell">
            <div class="ml">总市值(亿)</div>
            <div class="mv">{data.market_cap:.0f}</div>
        </div>
        <div class="metric-cell">
            <div class="ml">营收(亿)</div>
            <div class="mv">{computed[-2]["revenue"]/1e8:.0f}</div>
        </div>
        <div class="metric-cell">
            <div class="ml">归母净利(亿)</div>
            <div class="mv">{computed[-2]["net_profit"]/1e8:.0f}</div>
        </div>
        <div class="metric-cell">
            <div class="ml">EPS(TTM)</div>
            <div class="mv">{safe_f(data.eps_ttm)}</div>
        </div>
        <div class="metric-cell">
            <div class="ml">PE(TTM)</div>
            <div class="mv">{data.pe_ttm:.1f}</div>
        </div>
        <div class="metric-cell">
            <div class="ml">PB</div>
            <div class="mv">{data.pb:.2f}</div>
        </div>
        <div class="metric-cell">
            <div class="ml">ROE</div>
            <div class="mv">{data.roe:.1f}%</div>
        </div>
        <div class="metric-cell">
            <div class="ml">股息率</div>
            <div class="mv">{data.dividend_yield:.1f}%</div>
        </div>
    </div>

    <!-- Investment Thesis -->
    <div class="thesis-box">
        <div class="thesis-title">&#9654; 核心观点</div>
        {thesis}
    </div>

    <!-- Stock Price Chart -->
    <div class="chart-container">
        <div class="sec-title">近一年股价与成交量走势</div>
        <div id="priceChart" style="height:165px;"></div>
    </div>
    <div class="commentary">{price_commentary}</div>

    <!-- Key Financials Table -->
    <div>
        <div class="sec-title">关键财务预测与估值</div>
        <table class="ft">
            <thead><tr>
                <th>年度</th><th>营收(亿)</th><th>营收增速</th>
                <th>归母净利(亿)</th><th>净利增速</th>
                <th>EPS(元)</th><th>ROE</th><th>PE(x)</th><th>PB(x)</th>
            </tr></thead>
            <tbody>{fin_rows}</tbody>
        </table>
        <div class="commentary">{fin_commentary}</div>
    </div>

    <!-- Business Overview -->
    <div>
        <div class="sec-title">业务概述</div>
        <div class="biz-text">{intro_long}</div>
        {'<div class="biz-scope"><b>经营范围:</b> ' + biz_scope_short + '</div>' if biz_scope_short else ''}
        <div style="margin-top:4px;display:flex;flex-wrap:wrap;gap:4px;">{company_cards_html}</div>
    </div>

    <!-- Main Business Composition -->
    {'<div><div class="sec-title">主营业务构成 (亿元)</div><div id="mainopChart" style="height:115px;"></div></div>' if has_mainop else ''}

    <div class="footer">数据来源: 东方财富 | 报告由 AI 自动生成，仅供学习参考，不构成投资建议 | {today} | 第 1 页</div>
</div>

<!-- ════════════════════════════════════════ PAGE 2 ════════════════════════════════════════ -->
<div class="page">
    <!-- Latest Interim Data (2025 Q1/H1/Q3) -->
    {'<div><div class="sec-title">最新季度/半年度数据 (亿元)</div><table class="ft"><thead><tr><th>期间</th><th>营收</th><th>同比</th><th>归母净利</th><th>同比</th></tr></thead><tbody>' + interim_rows + '</tbody></table><div class="commentary">' + interim_commentary + '</div></div>' if interim_rows else ''}

    <!-- Two side-by-side tables: Asset & Cash Flow -->
    <div style="display:flex;gap:6px;">
        <div style="flex:1.2;">
            <div class="sec-title">资产负债与盈利能力</div>
            <table class="ft">
                <thead><tr><th>年度</th><th>总资产(亿)</th><th>净资产(亿)</th><th>负债率</th><th>ROE</th><th>ROA</th></tr></thead>
                <tbody>{asset_rows}</tbody>
            </table>
        </div>
        <div style="flex:1;">
            <div class="sec-title">现金流概况 (亿元)</div>
            <table class="ft">
                <thead><tr><th>年度</th><th>经营</th><th>投资</th><th>筹资</th></tr></thead>
                <tbody>{cf_rows}</tbody>
            </table>
        </div>
    </div>
    <div class="commentary">{balance_commentary} {cashflow_commentary}</div>

    <!-- Revenue chart full width -->
    <div>
        <div class="sec-title">营收与归母净利润趋势 (亿元)</div>
        <div id="revenueChart" style="height:120px;"></div>
    </div>

    <!-- Dividend + Word Cloud side by side -->
    <div style="display:flex;gap:8px;">
        <div style="flex:1;min-width:0;background:#fafbfc;border-radius:4px;padding:4px 6px;">
            <div class="sec-title">分红历史</div>
            <table class="ft">
                <thead><tr><th>除息日</th><th>方案</th><th>EPS</th><th>股息率</th></tr></thead>
                <tbody>{div_rows if div_rows else '<tr><td colspan="4" style="color:#999;">暂无</td></tr>'}</tbody>
            </table>
            <div class="commentary">{dividend_commentary}</div>
        </div>
        <div style="flex:1.2;min-width:0;background:#fafbfc;border-radius:4px;padding:4px 6px;">
            <div class="sec-title">股吧舆情词云</div>
            <div style="display:flex;justify-content:center;"><div id="wordcloudChart" style="height:170px;width:170px;"></div></div>
            <div class="commentary">{sentiment_summary}</div>
        </div>
    </div>

    <!-- Valuation + Rating in one row (same ratio as dividend+wordcloud above) -->
    <div style="display:flex;gap:8px;align-items:stretch;">
        <div style="flex:1;min-width:0;">
            <div class="sec-title">估值分析</div>
            <div class="val-box">
                <div class="val-title">{valuation['method_name']} | {valuation.get('comps', '')}</div>
                <div class="val-detail">{val_details_html}</div>
                <div style="display:flex;align-items:center;gap:12px;margin-top:3px;">
                    <div class="val-target" style="margin:0;">目标价: {valuation['target_price']:.2f} 元 ({'+'if valuation['upside']>0 else ''}{valuation['upside']:.1f}%)</div>
                    <span class="sc sc-bear">悲观 {bear:.2f}</span>
                    <span class="sc sc-base">基准 {base:.2f}</span>
                    <span class="sc sc-bull">乐观 {bull:.2f}</span>
                </div>
            </div>
        </div>
        <div style="flex:1.2;min-width:0;display:flex;flex-direction:column;gap:4px;">
            <div class="rating-box" style="flex:1;">
                <div>
                    <div class="rb-label">投资评级</div>
                    <div class="rb-value">{rating}</div>
                </div>
                <div>
                    <div class="rb-info">
                        目标 {valuation['target_price']:.2f} | 现价 {data.price:.2f}<br>
                        涨幅 {'+'if valuation['upside']>0 else ''}{valuation['upside']:.1f}%<br>
                        52周 {w52_low:.2f}~{w52_high:.2f}
                    </div>
                </div>
            </div>
            <div style="background:#fff5f5;border:1px solid #f5c6cb;border-radius:4px;padding:4px 6px;">
                <div style="font-size:9pt;font-weight:700;color:#c0392b;margin-bottom:2px;">风险提示</div>
                <ul class="risk-list" style="margin:0;">
                    {''.join(f'<li>{r}</li>' for r in risks)}
                </ul>
            </div>
        </div>
    </div>

    <div class="footer">
        数据来源于东方财富，本报告由AI自动生成，仅供学习研究，不构成投资建议。 | {today} | 第 2 页
    </div>
</div>

<!-- ════════════════════════════════════════ ECharts Scripts ════════════════════════════════ -->
<script>
// ── Price + Volume Chart ──
var priceChart = echarts.init(document.getElementById('priceChart'));
priceChart.setOption({{
    tooltip: {{
        trigger: 'axis',
        axisPointer: {{ type: 'cross' }},
        textStyle: {{ fontSize: 10 }},
    }},
    grid: {{ left: 48, right: 48, top: 12, bottom: 32 }},
    xAxis: {{
        type: 'category',
        data: {kline_dates},
        axisLabel: {{
            fontSize: 6.5,
            interval: 'auto',
            formatter: function(v) {{ return v.substring(5); }}
        }},
        axisLine: {{ lineStyle: {{ color: '#ccc' }} }},
    }},
    yAxis: [
        {{
            type: 'value',
            scale: true,
            axisLabel: {{ fontSize: 6.5 }},
            splitLine: {{ lineStyle: {{ type: 'dashed', color: '#f0f0f0' }} }},
            axisLine: {{ show: false }},
        }},
        {{
            type: 'value',
            axisLabel: {{ fontSize: 6.5, formatter: function(v) {{ return (v/10000).toFixed(0)+'万'; }} }},
            splitLine: {{ show: false }},
            axisLine: {{ show: false }},
        }}
    ],
    series: [
        {{
            name: '收盘价',
            type: 'line',
            data: {kline_closes},
            lineStyle: {{ width: 1.5, color: '#c0392b' }},
            itemStyle: {{ color: '#c0392b' }},
            symbol: 'none',
            areaStyle: {{
                color: new echarts.graphic.LinearGradient(0,0,0,1,[
                    {{offset:0,color:'rgba(192,57,43,0.12)'}},
                    {{offset:1,color:'rgba(192,57,43,0.01)'}}
                ])
            }}
        }},
        {{
            name: '成交量(手)',
            type: 'bar',
            yAxisIndex: 1,
            data: {kline_volumes},
            itemStyle: {{ color: 'rgba(52,152,219,0.20)' }},
            barWidth: '60%',
        }}
    ]
}});

// ── Word Cloud Chart ──
var wcEl = document.getElementById('wordcloudChart');
if (wcEl) {{
    var wcChart = echarts.init(wcEl);
    wcChart.setOption({{
        series: [{{
            type: 'wordCloud',
            shape: 'square',
            layoutAnimation: false,
            left: '0',
            top: '0',
            width: '100%',
            height: '100%',
            sizeRange: [8, 20],
            rotationRange: [0, 0],
            rotationStep: 0,
            gridSize: 3,
            drawOutOfBound: false,
            textStyle: {{
                fontFamily: 'STKaiti, KaiTi, serif',
                fontWeight: '600',
                color: function() {{
                    var colors = ['#1a5276','#2980b9','#c0392b','#e67e22','#27ae60','#8e44ad','#2c3e50','#d35400','#16a085'];
                    return colors[Math.floor(Math.random() * colors.length)];
                }}
            }},
            data: {wordcloud_data_json}
        }}]
    }});
}}

// ── Main Business Composition Bar Chart ──
var mainopEl = document.getElementById('mainopChart');
if (mainopEl) {{
    var mainopChart = echarts.init(mainopEl);
    mainopChart.setOption({{
        tooltip: {{ trigger: 'axis', textStyle: {{ fontSize: 9 }} }},
        grid: {{ left: 80, right: 45, top: 5, bottom: 5, containLabel: false }},
        xAxis: {{ type: 'value', axisLabel: {{ fontSize: 7, formatter: function(v){{ return v >= 0 ? v : v; }} }}, splitLine: {{ lineStyle: {{ type: 'dashed', color: '#eee' }} }} }},
        yAxis: {{ type: 'category', data: {mainop_names_json}, axisLabel: {{ fontSize: 7 }} }},
        series: [{{
            type: 'bar',
            data: {mainop_values_json}.map(function(v) {{
                return {{
                    value: v,
                    itemStyle: v < 0 ? {{ color: '#e74c3c', borderRadius: [3,0,0,3] }} : {{
                        color: new echarts.graphic.LinearGradient(0,0,1,0,[
                            {{offset:0,color:'#85c1e9'}},{{offset:1,color:'#1a5276'}}
                        ]),
                        borderRadius: [0, 3, 3, 0],
                    }}
                }};
            }}),
            barWidth: '55%',
            label: {{ show: true, fontSize: 7, position: 'right',
                formatter: function(p) {{ return p.value + '亿'; }},
                color: function(p) {{ return p.value < 0 ? '#e74c3c' : '#333'; }}
            }},
        }}]
    }});
}}

// ── Revenue & Profit Chart ──
var revChart = echarts.init(document.getElementById('revenueChart'));
revChart.setOption({{
    tooltip: {{
        trigger: 'axis',
        textStyle: {{ fontSize: 10 }},
    }},
    legend: {{
        top: 0,
        textStyle: {{ fontSize: 7 }},
        itemWidth: 12,
        itemHeight: 8,
    }},
    grid: {{ left: 50, right: 50, top: 22, bottom: 22 }},
    xAxis: {{
        type: 'category',
        data: {rev_years_json},
        axisLabel: {{ fontSize: 7 }},
        axisLine: {{ lineStyle: {{ color: '#ccc' }} }},
    }},
    yAxis: {{
        type: 'value',
        name: '亿元',
        nameTextStyle: {{ fontSize: 6.5 }},
        axisLabel: {{ fontSize: 6.5 }},
        splitLine: {{ lineStyle: {{ type: 'dashed', color: '#f0f0f0' }} }},
    }},
    series: [
        {{
            name: '营业收入',
            type: 'bar',
            data: {rev_data_json},
            itemStyle: {{
                color: new echarts.graphic.LinearGradient(0,0,0,1,[
                    {{offset:0,color:'#3498db'}},{{offset:1,color:'#85c1e9'}}
                ])
            }},
            barWidth: '30%',
        }},
        {{
            name: '归母净利润',
            type: 'bar',
            data: {profit_data_json}.map(function(v) {{
                return {{
                    value: v,
                    itemStyle: v < 0 ? {{
                        color: new echarts.graphic.LinearGradient(0,1,0,0,[
                            {{offset:0,color:'#e74c3c'}},{{offset:1,color:'#f1948a'}}
                        ])
                    }} : {{
                        color: new echarts.graphic.LinearGradient(0,0,0,1,[
                            {{offset:0,color:'#e74c3c'}},{{offset:1,color:'#f1948a'}}
                        ])
                    }}
                }};
            }}),
            barWidth: '30%',
        }}
    ]
}});

</script>
</body>
</html>'''
    return html



# ══════════════════════════════════════════════════════════════
#  PDF Conversion
# ══════════════════════════════════════════════════════════════

def html_to_pdf(html_path, pdf_path):
    """Convert HTML to PDF using Playwright."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
        print(f"HTML saved to: {html_path}")
        return False

    with sync_playwright() as p:
        browser = p.chromium.launch()
        # Set viewport to match A4 width at 96dpi: (210mm - 22mm margins) * 96/25.4 ≈ 710px
        page = browser.new_page(viewport={'width': 710, 'height': 1000})
        page.goto(f'file://{os.path.abspath(html_path)}')
        # Wait for ECharts to render fully
        page.wait_for_timeout(5000)
        page.pdf(
            path=pdf_path,
            format='A4',
            print_background=True,
            margin={'top': '8mm', 'bottom': '6mm', 'left': '5mm', 'right': '5mm'},
        )
        browser.close()
    return True


# ══════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print("Usage: python generate_report.py <data_dir> [output.pdf]")
        print("  output defaults to <data_dir>/report.pdf")
        sys.exit(1)

    data_dir = sys.argv[1]
    output_pdf = sys.argv[2] if len(sys.argv) >= 3 else os.path.join(data_dir, 'report.pdf')

    if not os.path.isdir(data_dir):
        print(f"Error: data directory not found: {data_dir}")
        sys.exit(1)

    # Ensure output directory exists
    out_dir = os.path.dirname(output_pdf)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    print(f"Loading data from {data_dir}...")
    data = StockData(data_dir)
    print(f"  Stock: {data.name} ({data.code})")
    print(f"  Industry: {data.industry}")
    print(f"  Price: {data.price}, PE: {data.pe_ttm}, PB: {data.pb}")
    print(f"  ROE (computed): {data.roe:.1f}%")
    print(f"  EPS (annual): {data.latest_eps}, EPS (TTM): {data.eps_ttm}")

    print(f"\nCalculating valuation...")
    valuation = calc_valuation(data)
    print(f"  Method: {valuation['method_name']}")
    print(f"  Target: {valuation['target_price']:.2f} (upside: {valuation['upside']:.1f}%)")
    print(f"  Rating: {valuation['rating']}")
    scenarios = valuation.get('scenarios', {})
    if scenarios:
        print(f"  Scenarios: Bear={scenarios.get('bear',0):.2f} / Base={scenarios.get('base',0):.2f} / Bull={scenarios.get('bull',0):.2f}")

    print(f"\nGenerating report...")
    html = generate_simple_html(data, valuation)

    html_path = output_pdf.rsplit('.', 1)[0] + '.html'
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  HTML saved: {html_path}")

    print(f"  Converting to PDF...")
    if html_to_pdf(html_path, output_pdf):
        print(f"\n  Report saved: {output_pdf}")
    else:
        print(f"\n  PDF conversion failed. HTML is available at: {html_path}")


if __name__ == '__main__':
    main()
