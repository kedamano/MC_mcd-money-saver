---
name: mcd-money-saver
description: >-
  麦麦省钱助手：基于麦当劳中国 MCP 的省钱点餐 Skill。当用户想在麦当劳点餐时
  自动比价、挑出最优优惠券组合（满减/折扣/立减/免配送费叠加）、核算最低到手价并下单时使用。
  典型触发："帮我点麦当劳省钱"、"麦当劳有什么优惠券能用"、"凑单怎么最划算"、
  "附近麦当劳帮我选最便宜的套餐"。This skill should be used when the user wants to
  save money, compare McDonald's coupons, or find the cheapest combo via McDonald's MCP.
agent_created: true
---

# 麦麦省钱助手（McDonald's Money-Saver）

## 目的

把"人工翻券比价"变成"一句话自动最优"。在用户点麦当劳（到店/外送）时，自动从
**门店券 + 我的券 + 麦麦省券** 三池子里挑出可叠加的最优组合，用官方 `calculate-price`
二次核价，确认后下单。

## 前置条件

- 已启用 `mcd-mcp` 连接器（麦当劳中国 MCP Server，Streamable HTTP，`https://mcp.mcd.cn`）。
- 连接器请求头携带 `Authorization: Bearer ${MCD_MCP_TOKEN}`，Token 来自 https://open.mcd.cn/mcp。
- 本 Skill 的辅助脚本位于 `src/coupon_optimizer.py`，用 Python 3.11+ 运行。

## 工作流（按序执行）

### 1. 选门店
- 到店：调用 `query-nearby-stores` 拿到附近门店，请用户确认目标门店。
- 外送：先 `delivery-query-addresses` 取配送地址（为空则 `delivery-create-address` 创建），
  再用 `delivery-query-stores`（`beType=2`）查可配送门店，**记下门店的 `beCode`**。
  > ⚠️ **外送全程必传 `beCode`**：`query-meals` / `query-store-coupons` / `calculate-price`
  > 在外送场景缺 `beCode` 一律报 `code=600048「外送场景下，beType=2/5/6时必传beCode」`；
  > `beCode` 只来自外送门店。外送商品 `code` 与到店**不通用**。

### 2. 选品，构造购物项
- 调用 `query-meals` 拉取该门店菜单；按用户需求确定商品。
- 将每个商品建模为一个 `Item(name, price, category)`，`category` 尽量映射到
  `main`(主餐) / `side`(小食) / `drink`(饮品) / `dessert`(甜品) 等，便于类目券匹配。
- 套餐可用 `query-meal-detail` 查看组成。

### 3. 收集候选券（三池并集）
依次调用：
- `query-store-coupons` —— 当前门店可用券
- `query-my-coupons` —— 账户已有券
- `available-coupons` —— 可领取的麦麦省券
- （可选）`auto-bind-coupons` —— 一键领取麦麦省券，扩充券池后再查一次 `query-my-coupons`

> ⚠️ **真实结构差异（真机实测）**：三池**返回格式不同**，不能一视同仁——
> - `query-store-coupons` 返回**结构化 JSON**（含 `couponCode`/`couponId`/`products`）
>   → 这是**唯一能直接送 `calculate-price` 核价**的池，作为最优化的**主集**；
> - `query-my-coupons` 返回 **Markdown 文本**（券名 / 用券价格 / 有效期 / 标签，无 couponCode）
>   → 按**券名**与门店券交叉核对、去重，用于确认"用户是否真的拥有"；
> - `available-coupons` 返回 **Markdown 文本**（券名 / 状态：可领取）
>   → 需先 `auto-bind-coupons` 领取才可能进入可用池，列为**扩池建议**。
>
> 上述解析与聚合已实现在 `src/coupon_pools.py`（`collect_coupon_pools`），可直接调用。

将门店券建模为 `Coupon(id, kind, ...)`：
- 满减 → `kind="threshold", discount=Y, threshold=X`
- 折扣 → `kind="percent", discount=0.85`（85 折），可设 `max_discount` 封顶
- 立减 → `kind="fixed", discount=Y`，类目券设 `applies_to`
- 免配送费 → `kind="free_delivery"`

> 券面字段（门槛、折扣率、适用类目、有效期）以 MCP 实际返回为准；用 `now-time-info` 校验时效。
>
> ⚠️ **券有渠道限制**：标注「到店专用」的券**不能用于外送**——外送核价会返回
> `code=600012「当前优惠券不可用！」`（同一张券到店则正常生效）。选券时必须按当前
> `orderType` 过滤，避免报出"算得省、下单废"的假方案。

### 4. 跑优化器，挑最优组合
> ⏱️ **先按时间有效性过滤**：用 `now-time-info` 拿到当前时间，调用
> `filter_active_coupons(coupons, now="YYYY-MM-DD HH:MM")` 剔除「已过期 / 未生效 /
> 不在每日时段窗（如仅 05:00-23:59 可用）」的券，再送优化器，避免算出用不了的券。

将 `Item` 列表、`Coupon` 列表与 `delivery_fee` 写入临时输入，运行：

```bash
python src/coupon_optimizer.py            # 内置演示
# 或自定义：参见下方"自定义调用"片段
```

优化器会暴力枚举所有券组合，在满足「门槛校验 + 订单级券至多一张 + 免配送费券互斥」
约束下输出最低总价、选用券与节省金额。

**自定义调用片段**（由 WorkBuddy 在运行时生成并写入临时文件执行）：

```python
from src.coupon_optimizer import Item, Coupon, optimize_coupons
items = [Item("巨无霸", 25.0, "main"), Item("薯条", 12.0, "side")]
coupons = [Coupon("c1", "threshold", discount=12.0, threshold=30.0),
           Coupon("c2", "fixed", discount=5.0, applies_to="side")]
print(optimize_coupons(items, coupons, delivery_fee=6.0))
```

> 🔀 **多张券时考虑拆分下单**：真实规则「每单仅一张券」——当手里有多张作用于**不同商品**的券时，
> 调 `optimize_split_orders(items, coupons, delivery_fee, max_orders=3)` 求「拆成多单、每单配一张券」
> 的**全局最低价**；外送时每单都要付配送费，算法会自动判断拆分是否真的划算。
> 返回 `orders[]` 给出每单的商品与用券明细。

### 5. 用官方接口核价（关键）
用优化器给出的 `best_coupons` 调用 `calculate-price`，传入商品列表与对应券，
将返回金额与优化器 `best_total` 对照。**以 `calculate-price` 官方结果为准**；
若不一致，向用户说明差异（如某些券实际不可叠加/已过期）。

### 6. 确认后下单（两阶段，注意取餐方式依赖）
向用户展示："原价 X，用券后 Y，省 Z，组合为 …… 是否下单？"
用户确认后：
1. **先取取餐方式**：到店场景 `calculate-price` 返回 `takeWayList`
   （如 `[{"code":"eat-in","title":"堂食"},{"code":"take-in-store","title":"外带"}]`），
   选一个 `code` 作为 `takeWayCode`（用 `McDonaldMCPClient.pick_take_way` 获取）；
2. 调用 `create-order`（到店 `orderType=1` 必传 `takeWayCode`；外送 `orderType=2` 传 `addressId` + `beCode`），
   接口实现见 `src/mcd_client.py` 的 `create_order`；
3. 返回支付链接后引导用户支付，再用 `query-order` 核对订单状态。

> ⚠️ **`create-order` 是真实下单**：务必在用户**显式确认**后再调用，避免误产生待支付订单。

## 约束与边界

- 绝不展示/存储真实 Token；配置文件只用 `${MCD_MCP_TOKEN}` 占位符。
- 优惠券叠加规则以麦当劳实际 `calculate-price` 返回为最终权威。
- 项目为参赛作品、非官方产品，餐品/价格/优惠以官方实时结果为准，不构成专业建议。
- 每分钟请求上限 600 次（429 限流），合理控制调用频率，避免在循环中高频刷接口。
