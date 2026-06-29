---
name: tushare
description: 面向中文自然语言的 Tushare 数据研究技能。用于把“看看这只股票最近怎么样”“帮我查财报趋势”“最近哪个板块最强”“北向资金在买什么”“给我导出一份行情数据”这类请求，转成可执行的数据获取、清洗、对比、筛选、导出与简要分析流程。适用于 A 股、指数、ETF/基金、财务、估值、资金流、公告新闻、板块概念与宏观数据等研究场景。
author: tushare.pro
version: 1.1.12
credentials:
  - name: TUSHARE_TOKEN
    description: Tushare Token，用于认证和授权访问Tushare数据服务。
    how_to_get: "https://tushare.pro/register"
requirements:
  python: 3.7+
  packages:
    - name: tushare
  environment_variables:
    - name: TUSHARE_TOKEN
      required: false
      sensitive: true
  network_access: true
---

# tushare

把用户对 A 股/指数/ETF/基金/宏观的自然语言请求，转成 Tushare 数据获取 + 分析 + 交付流程。

## 核心原则

**所有分析从数据出发。** 没有拉到数据就不做结论，直接说明数据不足及原因（接口无数据/权限不够/非交易日/标的不存在）。禁止推测、禁止编造、禁止用通用知识补位。

## 触发条件

用户聊股票、基金、板块、宏观数据时触发。关键词：走势、行情、财报、估值、PE/PB/ROE、资金流、北向、龙虎榜、板块、涨停、公告、新闻、CPI/PMI、导出CSV、对比、筛选。

## 环境检查

数据请求前确认：Python 3.7+、`tushare` 包已安装、`TUSHARE_TOKEN` 可用。缺失时先提示修复路径。

## 意图 → 接口路由

### 1. 行情/趋势
关键词：走势、涨跌、放量、波动
接口：`daily`, `weekly`, `monthly`, `stk_mins`

### 2. 基本资料/标的识别
关键词：是什么公司、什么指数、ST、上市时间
接口：`stock_basic`, `stock_company`, `stock_st`, `index_basic`, `fund_basic`

### 3. 财务/公司质量
关键词：财报、利润、营收、ROE、毛利率、现金流
接口：`income`(营收利润), `fina_indicator`(ROE/毛利率), `balancesheet`, `cashflow`, `forecast`, `express`

### 4. 估值
关键词：PE、PB、估值高不高、便宜
接口：`daily_basic`, `fina_indicator`

### 5. 资金流/市场行为
关键词：资金流、北向、主力、龙虎榜、谁在买
接口：`moneyflow`, `moneyflow_hsgt`, `hsgt_top10`, `top_list`, `top_inst`

### 6. 板块/指数/主题
关键词：板块、行业、概念、成分股、轮动
接口：`index_basic`, `sw_daily`, `index_classify`, `ths_index`, `ths_member`, `dc_index`, `dc_member`, `index_member_all`

### 7. 打板/情绪
关键词：涨停、跌停、连板、炸板、热榜、情绪
接口：`limit_list_d`, `limit_step`, `kpl_list`, `dc_hot`, `ths_hot`

### 8. 公告/新闻/研报
关键词：公告、新闻、催化、研报、政策
接口：`anns_d`, `news`, `major_news`, `research_report`, `npr`

### 9. 宏观/跨市场
关键词：CPI、PPI、PMI、社融、利率、港股、美股
接口：`cn_cpi`, `cn_ppi`, `cn_pmi`, `cn_gdp`, `cn_m`, `sf_month`, `shibor`, `us_tycr`, `hk_daily`, `us_daily`, `index_global`

> 完整接口列表及参数字段见 `references/数据接口.md`，冷门接口或字段不确定时 Read 确认。

## 关键规则

**时间默认值**：走势→20交易日，一段时间→3个月，财报→8季度+最近年度，资金流→5~20交易日，宏观→6~12期。

**分段拉取**：日线/周线按月切片，财报按年份切片，分钟按周切片。大批量按标的分批。

**重试**：仅对网络超时/429重试。参数错误、权限不足不重试。分段失败要明确报告。

**输出结构**：一句话结论 → 数据范围与口径 → 关键指标/表格 → 异常点/风险 → 文件路径(如有)。

**数据质量**：合并去重、按主键排序、日期标准化、数值类型规范化。空结果区分：非交易日/未上市/权限不足，不说"接口坏了"。

**文件命名**：`{接口}_{代码}_{起止日期}_{生成日期}.csv`

## 不适用

- 买卖建议、自动交易、毫秒级实时决策
- 无 Tushare 权限时伪造数据
- 复杂回测引擎/组合优化系统

## 参考文档

- `references/数据接口.md` — 100+ 接口完整列表（含 URL、入参、出参）
- `scripts/stock_data_demo.py` — 股票数据获取示例
- `scripts/fund_data_demo.py` — 基金数据获取示例
