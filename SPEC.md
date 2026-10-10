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
| FR-3 | 多池收券 | 聚合 `query-store-coupons` + `query-my-coupons` + `available-coupons`；**三池返回结构不同**（门店券为 JSON，我的券/麦麦省券为 Markdown），须分别解析（`coupon_pools.collect_coupon_pools`）|
| FR-3a | 三池结构差异 | 门店券含 `couponCode/couponId` 可直接核价（主集）；我的券按券名与门店券去重交叉核对；麦麦省券需 `auto-bind-coupons` 领取后方可能进入可用池 |
| FR-4 | 券建模 | 真实券 JSON → 领域 `Coupon`：从 `description` 推断 `kind`（满减/折扣/立减/免配送）；记录 `product_codes` 产品级绑定 |
| FR-5 | 最优组合 | 枚举所有券组合，在约束下求最低到手价；返回 `original_total / best_total / best_coupons / saved / breakdown` |
| FR-6 | 官方核价 | 用 FR-5 结果调用 `calculate-price`（支持在 `items[].couponCode`+`couponId` 传券），**以服务器返回值作为权威金额** |
| FR-7 | 确认下单 | 向用户展示省钱方案，确认后 `create-order` 获取支付链接，`query-order` 核对 |
| FR-8 | 产品级绑定 | 券 `product_codes` 非空时仅作用于绑定商品（`_eligible_items`），避免错配类目 |
| FR-9 | 凑单建议 | 对未达门槛的满减券，从目录反推最小代价加购组合，`net_saving<=0` 不推荐 |
| FR-10 | 时效与库存 | 按 `expires_at` 剔除过期券（`filter_valid_coupons`）；`Item.available=False` 提示并移出优惠范围 |
| FR-11 | 两阶段核价 | 本地枚举 Top-K 候选，仅对 K 个调官方 `calculate-price` 取权威价（`two_stage_optimize`），规避 2^n 次调用 |
| FR-12 | 生效时间与时段窗 | 按 `valid_from`（未生效）、每日 `time_windows`（如仅 05:00-23:59 可用，支持跨零点）与 `expires_at` 三重过滤（`filter_active_coupons`）|
| FR-13 | 下单链路 | 到店下单须先由 `calculate-price` 取 `takeWayList[].code` 作为 `takeWayCode`，再调 `create-order`（`mcd_client.create_order` / `pick_take_way`）；须用户显式确认 |

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
| 单元测试 | `tests/test_coupon_optimizer.py` | 优化器：满减门槛、折扣封顶、互斥、组合择优、类目限制等 |
| 增强单测 | `tests/test_enhancements.py` | B/C/D/E 契约：产品级绑定、凑单、两阶段、时效库存 |
| 适配单测 | `tests/test_mcd_client.py`（离线部分） | 协议解析、请求体构造、业务 JSON 抽取（含 data 拆层/列表拆层/占位符文本） |
| 券池单测 | `tests/test_coupon_pools.py` | 三池 Markdown 解析（我的券/麦麦省券）与聚合去重 |
| 时效单测 | `tests/test_time_window.py` | 生效日期 / 每日时段窗 / 跨零点窗过滤 |
| 合同测试 | `tests/test_real_contract.py` | 基于真实 `calculate-price` 返回，断言客户端模型与服务器一致 |
| 真实校准 | `tests/test_live_calibration.py`（`-m live`） | 用真实返回值校准本地价格模型与官方一致 |
| 真实冒烟 | `tests/test_mcd_client.py::test_live_end_to_end`（`-m live`） | 真实连接完成 `initialize→list_tools→call_tool`，默认跳过 |
| 真实下单 | `tests/test_mcd_client.py::test_create_order_live_guarded` | 默认跳过，需 `MCD_ALLOW_REAL_ORDER=1` 显式开启（避免误下单）|

运行：
```bash
python -m pytest tests/ -q                 # 离线：52 例全过
MCD_MCP_TOKEN=xxx pytest -m live -q        # 真实端到端（可选，4 例 live）
python examples/demo_smart.py              # B/C/D/E 离线演示
MCD_MCP_TOKEN=xxx python examples/demo_live.py           # 真实端到端演示（选店→三池→官方核价）
MCD_MCP_TOKEN=xxx python examples/demo_smart.py --live   # D 真实官方核价演示
```

## 6. 优化项交付状态（SDD+TDD 落地）

| 项 | 能力 | 实现位置 | 状态 |
|---|---|---|---|
| **B** | 产品级绑定：券按 `product_codes` 精确匹配，误配即失效；适配器正式字段化 | `coupon_optimizer.Coupon.product_codes` / `_eligible_items` / `coupon_adapter.adapt_coupon` | ✅ |
| **C** | 凑单建议：对未达门槛满减券，从真实目录反推最小代价加购组合，净收益为负则不推 | `coupon_smart.suggest_threshold_addons` / `CatalogItem` / `load_catalog` | ✅ |
| **D** | 两阶段校验：本地枚举 Top-K → 仅对 K 个候选调官方 `calculate-price` 取权威价；客户端提供真实 `price_combo` / `price_combo_as_fn` | `coupon_optimizer.rank_candidates` / `coupon_smart.two_stage_optimize` / `mcd_client.price_combo` | ✅ |
| **E** | 时效与库存：按 `expires_at` 剔除过期券；`available=False` 商品提示并移出优惠范围 | `coupon_optimizer.filter_valid_coupons` / `check_item_availability` / `Item.available` | ✅ |
| **A1** | 三池聚合：门店券(JSON)/我的券/麦麦省券(Markdown) 分别解析、按券名去重、标注可领取扩池 | `coupon_pools.collect_coupon_pools` / `parse_my_coupons_text` / `parse_available_coupons_text` | ✅ |
| **A2** | 下单链路：到店先取 `takeWayList[].code` 作 `takeWayCode`，再 `create-order`；受保护默认不真下单 | `mcd_client.create_order` / `pick_take_way` | ✅ |
| **B1** | 生效时间/时段窗：`valid_from` + 每日 `time_windows`（支持跨零点）+ `expires_at` 三重过滤 | `coupon_optimizer.filter_active_coupons` / `Coupon.valid_from` / `time_windows` | ✅ |
| **D1** | CI 绿徽章：每次 push 自动跑离线测试（Py3.11/3.13 矩阵） | `.github/workflows/ci.yml` | ✅（已推送，首次运行 success）|
| **D2** | 真实核价 demo + 文档 | `examples/demo_live.py` / `DEMO.md` | ✅ |
| **C1** | 健壮性：瞬时错误(404/5xx/429)指数退避重试 + 熔断（副作用调用禁用重试）；读接口 TTL 缓存；环境自检脚本 | `mcd_client._post`/`call_tool_cached` / `scripts/doctor.py` | ✅ |

> **关键 Bug 修复（真机联调发现，均补了回归测试）**：
> 1. `calculate-price` 返回 `{success,code,message,data:{...}}`，需拆到最内层 `data`，否则取到 `price=None` 核价归零；
> 2. `query-nearby-stores` / `query-store-coupons` 的 `data` 是**列表**，原实现只拆 dict，导致门店/券数为 0；
> 3. `query-meals` 的说明文字含 `{code}` 占位符，按「第一个 `{`」解析会 `JSONDecodeError`，改为锚定 `{"success"`。
