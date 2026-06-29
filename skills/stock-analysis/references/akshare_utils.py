"""AKShare 财务数据提取工具 — 供 stock-analysis 技能使用"""
import akshare as ak


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
