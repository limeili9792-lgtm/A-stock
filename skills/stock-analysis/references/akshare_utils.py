"""AKShare 财务数据提取工具 — 供 stock-analysis / stock-trading 技能使用"""
import akshare as ak
import pandas as pd


def get_financial_summary(ts_code: str) -> dict:
    """
    提取最新季度的核心财务指标，用于杜邦拆解和定量筛选。
    返回 dict: 报告期、营收、净利润、毛利率、净利率、ROE、资产负债率、总资产、归母净资产等
    """
    # 去掉后缀 (.SZ/.SH)
    symbol = ts_code.replace('.SZ', '').replace('.SH', '').replace('.BJ', '')
    df = ak.stock_financial_abstract_ths(symbol=symbol, indicator='按报告期')
    latest = df.iloc[-1]

    def pct(val) -> float:
        """ '40.77%' → 40.77 """
        if val is None or pd.isna(val) or str(val) == '--':
            return None
        return float(str(val).replace('%', ''))

    def to_float(val):
        """ '103.23亿' → 103.23 """
        if val is None or pd.isna(val) or str(val) == '--':
            return None
        s = str(val).replace('亿', '').replace('万', '').replace(',', '')
        return float(s)

    import pandas as pd
    roe = pct(latest.get('净资产收益率'))
    net_margin = pct(latest.get('销售净利率'))
    debt_ratio = pct(latest.get('资产负债率'))
    equity_multiplier = 1 / (1 - debt_ratio / 100) if debt_ratio else None
    roa = roe / equity_multiplier if roe and equity_multiplier else None

    return {
        '报告期': latest['报告期'],
        '营业总收入_亿': to_float(latest.get('营业总收入')),
        '营收同比': latest.get('营业总收入同比增长率'),
        '净利润_亿': to_float(latest.get('净利润')),
        '净利同比': latest.get('净利润同比增长率'),
        '扣非净利润_亿': to_float(latest.get('扣非净利润')),
        '扣非同同比': latest.get('扣非净利润同比增长率'),
        '毛利率': pct(latest.get('销售毛利率')),
        '净利率': net_margin,
        'ROE_加权': roe,
        'ROE_摊薄': pct(latest.get('净资产收益率-摊薄')),
        '资产负债率': debt_ratio,
        '权益乘数': round(equity_multiplier, 2) if equity_multiplier else None,
        'ROA': round(roa, 1) if roa else None,
        '每股收益': latest.get('基本每股收益'),
        '每股净资产': latest.get('每股净资产'),
        '每股经营现金流': latest.get('每股经营现金流'),
        '营业周期_天': latest.get('营业周期'),
        '存货周转率': latest.get('存货周转率'),
        '流动比率': latest.get('流动比率'),
        '速动比率': latest.get('速动比率'),
    }


def get_peers_financial(ts_codes: list[str]) -> list[dict]:
    """批量拉取同业的财务摘要，用于ROE杜邦横向对比"""
    results = []
    for code in ts_codes:
        try:
            results.append(get_financial_summary(code))
        except Exception as e:
            results.append({'ts_code': code, 'error': str(e)})
    return results


def get_index_status(index_symbol: str = 'sh000001') -> dict:
    """
    大盘环境定量判断。
    index_symbol: 'sh000001'=上证, 'sz399006'=创业板
    """
    df = ak.stock_zh_index_daily(symbol=index_symbol)
    df = df.tail(30)
    df['ma20'] = df['close'].rolling(20).mean()
    latest = df.iloc[-1]

    close = float(latest['close'])
    ma20 = float(latest['ma20'])
    deviation = (close / ma20 - 1) * 100

    if close > ma20 and deviation > 3:
        status = '向上'
    elif abs(deviation) <= 3:
        status = '震荡'
    else:
        status = '向下'

    return {
        '指数': index_symbol,
        '日期': str(latest['date']),
        '收盘': close,
        'MA20': round(ma20, 0),
        '乖离率': round(deviation, 1),
        '大盘状态': status,
    }


def _get_val(df, metric, date, col='value'):
    """从长格式DataFrame提取指定指标的值。内置yoy/single_yoy可直接取值。"""
    rows = df[(df['metric_name'] == metric) & (df['report_date'] == date)]
    if len(rows) == 0:
        return None
    val = rows[col].iloc[0]
    return float(val) if pd.notna(val) else None


def get_profit_quality(ts_code: str) -> dict:
    """
    季度利润质量拆解（框架2.5节）。
    数据源：AKShare stock_financial_benefit_new_ths + stock_financial_cash_new_ths。
    yoy列是AKShare自带同比，single=单季值，value=报告期累计值。
    返回：净利率桥接各要素、CFO/净利润、非主营比重、增速一致性、综合判断。
    """
    symbol = ts_code.replace('.SZ', '').replace('.SH', '').replace('.BJ', '')

    benefit = ak.stock_financial_benefit_new_ths(symbol=symbol, indicator='按报告期')
    cash = ak.stock_financial_cash_new_ths(symbol=symbol, indicator='按报告期')

    # 最新报告期
    cur_date = sorted(benefit['report_date'].unique())[-1]

    # 用yoy列获取同比增速（AKShare已算好），value取累计值（Q1=单季值）
    rev = _get_val(benefit, 'operating_income_total', cur_date, 'value')
    rev_yoy = _get_val(benefit, 'operating_income_total', cur_date, 'yoy')
    cost = _get_val(benefit, 'operating_costs_total', cur_date, 'value')
    sales_fee = _get_val(benefit, 'sales_fee', cur_date, 'value')
    manage_fee = _get_val(benefit, 'manage_fee', cur_date, 'value')
    fin_fee = _get_val(benefit, 'benefit_finance_fee', cur_date, 'value')
    rd_fee = _get_val(benefit, 'research_and_development_expenses', cur_date, 'value')
    tax_sur = _get_val(benefit, 'taxes_and_surcharges', cur_date, 'value')
    op_profit = _get_val(benefit, 'operating_profit', cur_date, 'value')
    profit_t = _get_val(benefit, 'profit_total', cur_date, 'value')
    net_p = _get_val(benefit, 'net_profit', cur_date, 'value')
    parent_np = _get_val(benefit, 'parent_holder_net_profit', cur_date, 'value')
    np_yoy = _get_val(benefit, 'net_profit', cur_date, 'yoy')
    impair = _get_val(benefit, 'assets_impairment_loss', cur_date, 'value')
    non_op_inc = _get_val(benefit, 'non_operating_income', cur_date, 'value')
    non_op_exp = _get_val(benefit, 'non_operating_expenses', cur_date, 'value')
    invest_inc = _get_val(benefit, 'invest_income', cur_date, 'value')
    fair_chg = _get_val(benefit, 'fair_changes_income', cur_date, 'value')

    # 现金流：用single列取单季经营现金流净额
    cfo = _get_val(cash, 'act_cash_flow_net', cur_date, 'single')

    # === 净利率桥接 ===
    gross_margin = (rev - cost) / rev * 100 if rev and cost and rev > 0 else None
    fee_rate = ((sales_fee or 0) + (manage_fee or 0) + (fin_fee or 0) +
                (rd_fee or 0) + (tax_sur or 0)) / rev * 100 if rev and rev > 0 else None
    non_op_rate = ((non_op_inc or 0) - (non_op_exp or 0) + (invest_inc or 0) +
                   (fair_chg or 0)) / rev * 100 if rev and rev > 0 else None
    net_margin = net_p / rev * 100 if net_p and rev and rev > 0 else None
    bridge_gap = (net_margin - (gross_margin - fee_rate + non_op_rate)
                  ) if all(v is not None for v in [net_margin, gross_margin, fee_rate, non_op_rate]) else None

    # === CFO / 净利润 ===
    cfo_np_ratio = cfo / net_p if cfo and net_p and net_p != 0 else None

    # === 非主营比重 ===
    non_recurring = (profit_t - op_profit) / abs(profit_t) * 100 if profit_t and op_profit and profit_t != 0 else None

    # === 增速一致性 ===
    # 用yoy对比方向，不手算YoY
    rev_yoy_val = rev_yoy * 100 if rev_yoy is not None else None
    np_yoy_val = np_yoy * 100 if np_yoy is not None else None
    # 毛利率方向需要上一期数据
    prev_dates = sorted(benefit['report_date'].unique())[-2:]
    if len(prev_dates) > 1:
        prev_rev = _get_val(benefit, 'operating_income_total', prev_dates[0], 'value')
        prev_cost = _get_val(benefit, 'operating_costs_total', prev_dates[0], 'value')
        gross_prev = (prev_rev - prev_cost) / prev_rev * 100 if prev_rev and prev_cost and prev_rev > 0 else None
        gm_dir = '↑' if gross_margin and gross_prev and gross_margin > gross_prev else (
            '↓' if gross_margin and gross_prev and gross_margin < gross_prev else '→')
    else:
        gm_dir = '→'

    # === 综合判断 ===
    if cfo_np_ratio is not None and cfo_np_ratio < 0:
        verdict = '红色预警'
    elif cfo_np_ratio is not None and cfo_np_ratio < 0.3:
        verdict = '黄色预警'
    elif rev_yoy_val is not None and np_yoy_val is not None and np_yoy_val > rev_yoy_val * 2.5:
        verdict = '黄色预警'
    else:
        verdict = '健康'

    return {
        '报告期': str(cur_date),
        '营收_亿': round(rev / 1e8, 2) if rev else None,
        '营收同比': f'{rev_yoy_val:.1f}%' if rev_yoy_val is not None else None,
        '归母净利_亿': round(parent_np / 1e8, 2) if parent_np else None,
        '净利同比': f'{np_yoy_val:.1f}%' if np_yoy_val is not None else None,
        '净利率桥接': {
            '毛利率': round(gross_margin, 2) if gross_margin else None,
            '费用率': round(fee_rate, 2) if fee_rate else None,
            '非主营比重': round(non_op_rate, 2) if non_op_rate else None,
            '实际净利率': round(net_margin, 2) if net_margin else None,
            '缺口(税金/减值/少数股东)': round(bridge_gap, 2) if bridge_gap is not None else None,
        },
        '利润质量': {
            'CFO_亿': round(cfo / 1e8, 2) if cfo else None,
            'CFO_NP比率': round(cfo_np_ratio, 2) if cfo_np_ratio else None,
            '非经常性损益占比': round(non_recurring, 1) if non_recurring else None,
            '资产减值_亿': round(impair / 1e8, 2) if impair else None,
        },
        '增速一致性': {
            '营收增速': f'{rev_yoy_val:.1f}%' if rev_yoy_val is not None else None,
            '净利增速': f'{np_yoy_val:.1f}%' if np_yoy_val is not None else None,
            '毛利率方向': gm_dir,
        },
        '判断': verdict,
    }


def get_index_volume_status(index_symbol: str = 'sh000001') -> dict:
    """大盘量能判断，返回缩量/正常/放量及量比"""
    df = ak.stock_zh_index_daily(symbol=index_symbol)
    df = df.tail(30)
    df['vol_ma20'] = df['volume'].rolling(20).mean()
    latest = df.iloc[-1]
    ratio = float(latest['volume']) / float(latest['vol_ma20']) if latest['vol_ma20'] > 0 else 1

    if ratio < 0.7:
        status = '缩量'
    elif ratio > 1.5:
        status = '放量'
    else:
        status = '正常'

    return {'指数量比': round(ratio, 2), '量能状态': status}
