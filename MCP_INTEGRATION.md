# MCP_INTEGRATION.md — 麦当劳 MCP 集成说明

本文件说明「麦麦省钱助手」实际使用的麦当劳 MCP Server、调用的 Tool、调用流程与业务价值，满足《麦当劳程序员创意开发大赛》对参赛项目的 MCP 集成披露要求。

## 1. 接入的 MCP Server

- **Server 名称**：`mcd-mcp`（麦当劳中国 MCP Server）
- **接入地址**：`https://mcp.mcd.cn`
- **传输协议**：Streamable HTTP
- **鉴权方式**：请求头 `Authorization: Bearer ${MCD_MCP_TOKEN}`（Token 通过 https://open.mcd.cn/mcp 申请，配置文件中仅以环境变量占位符出现，绝不硬编码真实 Token）
- **配置示例**：见仓库根目录 `mcp-config.example.json`

## 2. 实际调用的 Tool 与用途

| Tool | 调用时机 | 业务作用 |
|---|---|---|
| `query-nearby-stores` / `delivery-query-stores` | 流程开始 | 确定下单门店（到店/外送） |
| `query-meals` | 选品阶段 | 拉取门店菜单，构造购物项列表（含价格、类目） |
| `query-meal-detail` | 套餐场景 | 查看套餐组成，辅助搭配 |
| `query-store-coupons` | 优惠收集 | 获取当前门店可用优惠券（候选券池 ①） |
| `query-my-coupons` | 优惠收集 | 获取账户已有券（候选券池 ②） |
| `available-coupons` | 优惠收集 | 列出可领取的麦麦省券（候选券池 ③） |
| `auto-bind-coupons` | 优惠扩充 | 一键领取麦麦省券，扩大可叠加选择 |
| `now-time-info` | 时效校验 | 校验券/活动有效期 |
| `calculate-price` | 核价对照 | 用真实 MCP 接口验证优化器给出组合的最终价，作为权威结果 |
| `create-order` | 最终执行 | 按最优方案创建订单并获取支付链接 |
| `query-order` / `order-list` | 售后核对 | 核对订单与历史记录 |

## 3. 调用流程

```
用户提出省钱点餐需求
   │
   ├─ 1) 选门店：query-nearby-stores / delivery-query-stores
   ├─ 2) 选品：  query-meals → 构造 Item 列表(名称/价格/类目)
   ├─ 3) 收券：  query-store-coupons + query-my-coupons + available-coupons
   │            （可选）auto-bind-coupons 扩券池
   ├─ 4) 优化：  将 Item + Coupon 喂给 src/coupon_optimizer.py
   │             → 输出最低价券组合（含节省金额与明细）
   ├─ 5) 核价：  calculate-price（带优化后的券） → 与优化器结果对照
   ├─ 6) 下单：  create-order（用户确认后）
   └─ 7) 核对：  query-order / order-list
```

## 4. 业务价值

- **真实省到钱**：不再靠人工比券，自动从「门店券 + 我的券 + 麦麦省券」三池子里挑出最优叠加方案，避免"用错券多花冤枉钱"。
- **降低决策成本**：用户只需说"我想点这些/帮我凑单省钱"，助手完成选店→选品→比券→核价→下单全流程。
- **可验证、可审计**：核心优惠组合由纯函数 `coupon_optimizer` 暴力枚举得出最优解，并再用官方 `calculate-price` 二次校验，结果可信。
- **契合大赛主题**：以麦当劳 MCP 真实能力（优惠/菜单/下单）解决"薅羊毛"这一高频真实痛点，兼具创意与实用价值。

## 5. 安全与合规

- 配置文件与仓库中**不包含任何真实 Token/密钥**，一律使用 `${MCD_MCP_TOKEN}` 环境变量占位符。
- 仅以非商业、参赛展示目的使用麦当劳 MCP，遵守《麦当劳 MCP 服务规则》。
- 项目输出仅供参考，餐品价格、供应与优惠以麦当劳官方实时结果为准。
