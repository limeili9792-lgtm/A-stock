# Astock Skills

三款 Claude Code 技能，覆盖 A 股研究全流程：数据获取 → 基本面分析 → 交易决策。

## 技能列表

| 技能 | 触发 | 做什么 |
|:---|:---|:---|
| `tushare` | "查走势""拉财报""导出行情" | 数据获取、清洗、导出 |
| `stock-analysis` | "分析下XX""怎么看XX" | 三层递进基本面分析 |
| `stock-trading` | "XX交易分析""该买吗""还能拿吗" | 波段交易技术面分析 |

## 协作流程

```
用户提问
  ├─ "分析下兆易创新" → stock-analysis（基本面三层递进）
  │    └─ 需要数据 → tushare（行情/财务/估值）
  │    └─ "还能拿吗" → stock-trading（技术面/资金面/盈亏比）
  │
  ├─ "中天科技交易分析" → stock-trading（纯交易面）
  │
  └─ "拉一下半导体设备板块PE" → tushare（纯数据）
```

## 安装

```bash
# 复制到任意 Claude Code 项目的 .claude/skills/ 目录
cp -r skills/* /your-project/.claude/skills/
```

### 依赖

- **tushare**: Python 3.7+, `tushare` 包, `TUSHARE_TOKEN` 环境变量（[注册获取](https://tushare.pro/register)）
- **stock-analysis**: 无额外依赖，中证行业分类CSV需放在 `量化分析/references/` 下
- **stock-trading**: 无额外依赖

## 设计原则

1. **数据先行** — 不拉数据不做结论，禁止推测
2. **框架约束** — 每层有明确的"不可跳过"步骤，防止分析随意性
3. **基本面与交易面分离** — 两个框架独立运作，互不引用对方的指标
4. **按需加载** — 技能不触发不占上下文，比 memory 方式更高效

## License

MIT
