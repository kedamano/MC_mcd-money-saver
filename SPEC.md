# 麦麦省钱助手 · 规格说明书（SDD）

> 本文档为 **Specification-Driven Development** 的产物：先定义「要做什么 / 做到什么程度算对」，
> 再驱测试与实现。所有规则均来自 `references/mcp_tools.md` 与真实联调（2026-10-10）的客观观测，
> 而非主观假设。若麦当劳 MCP 行为变更，应优先更新本规格并同步契约测试。

---

## 1. 目标与范围

- **目标**：让用户在麦当劳点餐（到店 / 外送）时，用一句话自动完成「选店 → 选品 → 比券 → 核价 → 下单」，并保证所报优惠**与官方结算一致**。
- **范围**：本 Skill 是**优惠决策辅助**，不直接持有支付能力；下单动作依赖官方 `create-order` 返回的支付链接，由用户在官方渠道完成支付。
- **非目标**：不做会员体系、不做库存预测、不做非麦当劳业务。

## 2. 功能需求（FR）与验收标准

| 编号 | 功能 | 验收标准（可测） |
|---|---|---|
| FR-1 | 选门店 | `query-nearby-stores` 返回带 `storeCode` 的门店列表；`searchType=2` 必须同时传 `city`+`keyword`，否则返回错误码 600058 |
| FR-2 | 选品建模 | `query-meals` 返回 `categories`+`meals` 映射；商品 `code` 即 `calculate-price` 所需的 `productCode` |
| FR-3 | 多池收券 | 并集 `query-store-coupons` + `query-my-coupons` + `available-coupons`；可选 `auto-bind-coupons` 领券后重查 |
| FR-4 | 券建模 | 真实券 JSON → 领域 `Coupon`：从 `description` 推断 `kind`（满减/折扣/立减/免配送）；记录 `product_codes` 产品级绑定 |
| FR-5 | 最优组合 | 枚举所有券组合，在约束下求最低到手价；返回 `original_total / best_total / best_coupons / saved / breakdown` |
| FR-6 | 官方核价 | 用 FR-5 结果调用 `calculate-price`（支持在 `items[].couponCode`+`couponId` 传券），**以服务器返回值作为权威金额** |
| FR-7 | 确认下单 | 向用户展示省钱方案，确认后 `create-order` 获取支付链接，`query-order` 核对 |

## 3. 真实业务规则（来自联调观测，具约束力）

1. **鉴权**：`Authorization: Bearer <token>`，缺 `Bearer ` 前缀或被截断的 Token 会被拒（401「当前鉴权码不存在或已失效」）。Token 须控制台「一键复制」。
2. **金额单位**：`calculate-price` 返回金额均为**分（整数）**，换算元需 `/100`。
3. **券为产品级绑定**：如「新人专享-中杯美式7折」绑定 `productCode=9900000119`；该商品**裸算价为空（0）**，仅持券可计价。优惠以服务器为准，客户端模型只做候选生成。
4. **叠加以服务器为准**：客户端约束（满减/折扣/立减·全单通用至多一张、类目券可叠加、免配送费券互斥）为**启发式剪枝**，最终是否生效由 `calculate-price` 决定。
5. **到店 / 外送差异**：`beType=1` 到店不含 `beCode`；`beType=2` 外送含配送费与起送价，免配送费券在外送场景才有意义。
6. **限流**：每分钟请求上限 600 次（429），禁止在循环中高频刷接口。

## 4. 非功能需求（NFR）

- **可测性**：核心逻辑（`coupon_optimizer`、`coupon_adapter`、`mcd_client` 解析层）纯函数化，可离线单测。
- **契约稳定性**：以真实返回为黄金基准（`tests/fixtures/*.json`），离线合同测试锁定「客户端模型 == 服务器权威」。
- **安全**：绝不落盘真实 Token；仓库仅含 `${MCD_MCP_TOKEN}` 占位符。
- **容错**：MCP 调用失败 / Token 失效时，向用户明确报错而非静默给出错误优惠。

## 5. 测试策略（TDD）

| 层级 | 文件 | 说明 |
|---|---|---|
| 单元测试 | `tests/test_coupon_optimizer.py` | 优化器 10 例：满减门槛、折扣封顶、互斥、组合择优、类目限制等 |
| 适配单测 | `tests/test_mcd_client.py`（离线部分） | 协议解析、请求体构造、业务 JSON 抽取 |
| 合同测试 | `tests/test_real_contract.py` | 基于真实 `calculate-price` 返回，断言客户端模型与服务器一致 |
| 真实冒烟 | `tests/test_mcd_client.py::test_live_end_to_end`（`-m live`） | 真实连接完成 `initialize→list_tools→call_tool`，默认跳过 |

运行：
```bash
python -m pytest tests/ -q                 # 离线：19 例全过
MCD_MCP_TOKEN=xxx pytest -m live -q        # 真实端到端（可选）
```

## 6. 已知限制与后续优化（待办）

- **B. 产品级绑定建模**：当前 `Coupon.applies_to` 为泛类目；应升级为按 `product_codes` 精确匹配，避免把产品券误用到其他商品。
- **C. 凑单建议**：当距满减门槛差 X 元时，建议加购最小代价商品以跨门槛（高价值真实功能，当前缺失）。
- **D. 两阶段校验**：候选组合先本地剪枝，再仅对 Top-K 调 `calculate-price` 取权威值（避免 2^n 次网络调用）。
- **E. 时效与库存**：用 `now-time-info` 校验券有效期；对不可售商品（如裸算价为 0 的券绑定品）给出提示。
