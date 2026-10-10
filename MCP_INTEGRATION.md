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
| `query-nearby-stores` / `delivery-query-stores` | 流程开始 | 确定下单门店（到店/外送）；外送须先建地址，再取门店 `beCode` |
| `delivery-create-address` / `delivery-query-addresses` | 外送前置 | 创建/查询配送地址，为外送门店查询提供 `addressId` |
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

## 6. 真机联调验证记录（2026-10-10）

已使用真实 MCP Token 完成端到端联调，以下结论为本项目与官方 MCP 对接的权威依据。

### 6.1 验证通过的能力链路

| 环节 | Tool | 真实结果 |
|---|---|---|
| 时间 | `now-time-info` | 返回服务器时间 2026-10-10（北京时间） |
| 可领券 | `available-coupons` | 返回麦麦省可领券（如"巧克力味厚松饼猪柳蛋套餐"） |
| 我的券 | `query-my-coupons` | 返回卡包券（如"新人专享-中杯美式7折 ¥13.3"） |
| 选门店 | `query-nearby-stores` | 成功返回门店列表，如 storeCode=1450713（上海黄浦华旭国际大厦餐厅） |
| 门店券 | `query-store-coupons` | 返回门店可用券（含 couponCode / couponId / productCode） |
| 菜单 | `query-meals` | 返回分类与商品映射（code=productCode、currentPrice 等） |
| 核价 | `calculate-price` | 基础价与带券价均正确（见 6.3） |

### 6.2 对接中踩过的真实坑（已在 SKILL.md 中规避）

1. **鉴权格式**：必须是 `Authorization: Bearer <token>`，缺少 `Bearer ` 前缀会被服务器拒绝。Token 须通过 open.mcd.cn/mcp 控制台"一键复制"获取——手动选中复制易截断导致 401「鉴权码不存在或已失效」。
2. **门店搜索**：`query-nearby-stores` 在 `searchType=2` 下必须**同时传 `city` 与 `keyword`**，否则报 600058「城市名或者关键词不能为空」；`searchType=1`（收藏）在无收藏时也会要求 city+keyword。
3. **到店门店无 beCode**：`beType=1`（到店自提）返回的门店**不带 beCode**，后续 `query-store-coupons` / `query-meals` / `calculate-price` 调用时**不传 beCode**（外送/得来速/团餐才需要）。
4. **算价商品字段**：`calculate-price` 的 `items[]` 用 **`productCode`**（与菜单 `code` 一致），不是 `code`；金额以**分**为单位返回。
5. **券可直传算价**：`items[]` 支持直接带 `couponCode` + `couponId`，优惠券会在 `discount` 字段正确体现——这正是本助手"最优组合核价"的实现基础。
6. **券商品需带券**：以 `990000` 开头的券商品（如 9900000119 美式中杯）基础算价返回空，必须配合对应券；常规售卖商品（如 520689 鲜萃咖啡）可直接基础算价。
7. **外送全程必传 `beCode`**：外送(beType=2)下 `query-meals` / `query-store-coupons` / `calculate-price` 缺 `beCode` 报 `code=600048`；`beCode` 来自 `delivery-query-stores`（须先 `delivery-create-address` 建地址）。外送商品 `code` 与到店不通用（到店下单报 `60006 不可售`）。
8. **券有渠道限制**：到店专用券用于外送核价返回 `code=600012「当前优惠券不可用！」`，到店则正常生效。外送价额外含 `deliveryPrice`（配送费）与 `packingPrice`（打包服务费），且折扣可能来自商品自身促销价而非券。

### 6.3 实测核价样例

- 美式中杯 `9900000119` + 新人专享7折券（couponCode `MCD689H051J0J01C0Y078`）→ 原价 ¥19.00 / 优惠 ¥5.70 / **现价 ¥13.30**
- 小杯鲜萃咖啡 `520689` 基础算价 → 原价 ¥9.50 / 优惠 ¥0.00 / **现价 ¥9.50**

> 结论：优惠券在 `calculate-price` 中可正确生效，本项目的"三池比券 + 最优组合 + 官方核价"省钱闭环在真实 MCP 上成立。

### 6.4 外送（麦乐送）链路验证

| 环节 | Tool | 真实结果 |
|---|---|---|
| 建地址 | `delivery-create-address` | 上海测试地址 → 返回 `addressId` |
| 外送门店 | `delivery-query-stores`(beType=2) | `storeCode=1450056 / beCode=145005602`（上海食品一店） |
| 外送菜单 | `query-meals`(orderType=2, beCode) | 外送专属菜单 121 项（商品 code 与到店不同） |
| 外送核价 | `calculate-price`(orderType=2, beCode) | 汉堡包×2+奶铁+脆薯饼 → 原价 ¥69.50 / 优惠 ¥7.10 / **到手 ¥62.40**（商品 ¥53.40 + **配送费 ¥6.00** + **打包费 ¥3.00**） |
| 券渠道 | 同一张「到店专用」券 | 到店：19.00→**13.30** 生效；外送：`code=600012 当前优惠券不可用！` |

> 结论：外送链路（含配送费/打包费）与「券有渠道限制」均已在真实 MCP 上验证；本项目的
> 「到店/外送双场景 + 拆分下单」在真实规则下成立。
