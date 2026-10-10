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
| FR-11 | 两阶段核价 | 本地求解 Top-K 候选（小券池暴力枚举、大券池分支限界），仅对 K 个调官方 `calculate-price` 取权威价（`two_stage_optimize`），规避 2^n 次调用；**默认每单至多一张券（`max_coupons_per_order=1`）**，与真实 MCP 规则一致 |
| FR-12 | 生效时间与时段窗 | 按 `valid_from`（未生效）、每日 `time_windows`（如仅 05:00-23:59 可用，支持跨零点）与 `expires_at` 三重过滤（`filter_active_coupons`）|
| FR-13 | 下单链路 | 到店下单须先由 `calculate-price` 取 `takeWayList[].code` 作为 `takeWayCode`，再调 `create-order`（`mcd_client.create_order` / `pick_take_way`）；须用户显式确认 |
| FR-14 | 拆分下单 | 真实「每单至多一张券」下，把购物车拆成多单、每单配一张最优券，权衡每单配送费，求全局最低总价（`optimize_split_orders`）；无券/单券或拆分无收益时退化为单订单；`max_orders` 限制拆分规模；券不可跨单复用 |
| FR-15 | 外送场景 | 外送链路：`delivery-create-address`（建地址）→ `delivery-query-stores`（取门店 `beCode`）→ `query-meals`/`query-store-coupons`/`calculate-price`（**全程必传 `beCode`**）。外送价 = 商品 + 配送费(`deliveryPrice`) + 打包服务费(`packingPrice`)；须校验券渠道（到店专用券外送不可用，`code=600012`）|
| FR-16 | 套餐纳入优化 | 从 `query-meals`(套餐商品) + `query-meal-detail`(`rounds[].choices[]` 默认项) 解析套餐组件，比较「套餐价 vs 组件单点」，在「套餐/单点」间求全局最低价（`optimize_purchase`）；`plan_order_with_combos` 将套餐与券二选一。**口径**：单点合计仅累计能与菜单对上编码的组件 → 节省为**下界**（`is_lower_bound`）|
| FR-17 | 多店比价 + 距离权衡 | 在可接受距离（`max_distance_m`）内比较多家门店同品到手价（商品 + 配送 − 最优券），求最低并量化「多走 N 米省 ¥X」（`optimize_across_stores`）；缺货门店跳过并提示 |
| FR-18 | 一键领券扩池 | `auto-bind-coupons` 领取可领券 → 重查三池 → 再比价（`collect_and_bind_coupons`）；该接口返回**纯文本非 JSON**，须用 `call_tool_text`，异常须容错不中断 |

## 3. 真实业务规则（来自联调观测，具约束力）

1. **鉴权**：`Authorization: Bearer <token>`，缺 `Bearer ` 前缀或被截断的 Token 会被拒（401「当前鉴权码不存在或已失效」）。Token 须控制台「一键复制」。
2. **金额单位**：`calculate-price` 返回金额均为**分（整数）**，换算元需 `/100`。
3. **券为产品级绑定**：如「新人专享-中杯美式7折」绑定 `productCode=9900000119`；该商品**裸算价为空（0）**，仅持券可计价。优惠以服务器为准，客户端模型只做候选生成。
4. **叠加以服务器为准**：客户端约束（满减/折扣/立减·全单通用至多一张、类目券可叠加、免配送费券互斥）为**启发式剪枝**，最终是否生效由 `calculate-price` 决定。
5. **到店 / 外送差异**：`beType=1` 到店不含 `beCode`；`beType=2` 外送含配送费与起送价，免配送费券在外送场景才有意义。
6. **限流**：每分钟请求上限 600 次（429），禁止在循环中高频刷接口。
7. **券有渠道限制**：标注「到店专用」的券用于外送核价返回 `code=600012「当前优惠券不可用！」`，到店正常生效；选券须校验 `orderType`。
8. **外送全程必传 `beCode`**：外送(beType=2/5/6)下 `query-meals` / `query-store-coupons` / `calculate-price` 缺 `beCode` 均报 `code=600048`；`beCode` 来自 `delivery-query-stores`（须先 `delivery-create-address` 建地址）。外送商品 `code` 与到店不通用（到店下单报 `60006 不可售`）。外送价额外含 `deliveryPrice`/`packingPrice`，且折扣可能来自商品自身促销价而非券。
9. **促销仅企业团餐**：`query-promotions` 返回的促销规则 `beTypes` 全部为 `["6"]`（企业团餐），普通到店/外送不可用 → **不作为省钱候选**（避免虚假承诺）。
10. **`auto-bind-coupons` 无入参且返回纯文本**：非 JSON，须用 `call_tool_text`；实测领取后门店券 2→3、我的券 2→7。
11. **同城同品不同价**：中薯条(4810) 在部分门店 ¥13.50、上海食品一店 ¥14.50 → 多店比价有真实收益。
12. **套餐组件编码与菜单编码可能不一致**：套餐内饮料 `3050` 与菜单独立商品 `9900008751` 编码不同 → 「套餐 vs 单点」只能按能对上编码的组件保守计（节省下界）。

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
| 规模单测 | `tests/test_scale_pruning.py` | 大规模券剪枝 + 分支限界：与暴力枚举同解（40 组随机种子）、0 优惠券剪枝安全性、约束一致性、剪枝节点压缩 |
| Top-K 单测 | `tests/test_topk_pruning.py` | `rank_candidates` 的 Top-K 分支限界：与暴力枚举同值（40 组随机种子 × K∈{1,3,5}）、K 名上界剪枝、大券池可用性 |
| 券数上限单测 | `tests/test_one_coupon_rule.py` | 真实规则「每单至多一张券」：默认保留组合能力、`max_coupons_per_order=1` 时暴力/分支限界同解、Top-K 候选与 `two_stage_optimize` 均遵守上限 |
| 拆分下单单测 | `tests/test_split_orders.py` | `optimize_split_orders`：无券/单券不拆、多绑定券到店拆单更省、外送配送费阻碍拆单、券不跨单复用、`max_orders` 限制、与暴力划分基准同值（30 组随机） |
| 外送链路单测 | `tests/test_delivery.py` | 外送请求体构造：`price_combo`/`create_order` 的 `beCode`、`addressId`、`takeWayCode` 分支与副作用调用禁用重试 |
| 外送合同测试 | `tests/test_delivery_contract.py` | 外送真实返回契约：价格构成（商品+配送+打包−折扣）、打包费独立零小计行、折扣来自商品促销、券渠道限制 `600012` |
| 合同测试 | `tests/test_real_contract.py` | 基于真实 `calculate-price` 返回，断言客户端模型与服务器一致 |
| 真实校准 | `tests/test_live_calibration.py`（`-m live`） | 用真实返回值校准本地价格模型与官方一致 |
| 真实冒烟 | `tests/test_mcd_client.py::test_live_end_to_end`（`-m live`） | 真实连接完成 `initialize→list_tools→call_tool`，默认跳过 |
| 真实下单 | `tests/test_mcd_client.py::test_create_order_live_guarded` | 默认跳过，需 `MCD_ALLOW_REAL_ORDER=1` 显式开启（避免误下单）|
| 领券扩池单测 | `tests/test_auto_bind.py` | `collect_and_bind_coupons`：`call_tool_text` 调用、前后三池对比、净增非负、`beCode` 透传、异常容错 |
| 套餐优化单测 | `tests/test_combo_optimizer.py` | `parse_meal_detail`/`combo_saving`（真实节省下界）/`optimize_purchase`（与暴力子集基准同解 30 组随机）/`plan_order_with_combos`（套餐 vs 券二选一）|
| 多店比价单测 | `tests/test_store_optimizer.py` | `optimize_across_stores`（同品不同价、距离过滤、权衡量化、缺货跳过）、门店券标题解析、采集器 |
| 促销范围合同 | `tests/test_promotions_scope.py` | 真实结论：`query-promotions` 的 `beTypes` 恒为 `["6"]`（企业团餐）；外送缺 `beCode` 报 `600048` |
| 券渠道合同 | `tests/test_coupon_channel.py` | `infer_channel_from_tag`（到店/外送标签推断）、`filter_coupons_by_channel`、`optimize_coupons`/`rank_candidates`/`optimize_split_orders` 的 `order_channel` 前置过滤；我的券解析带 `channel` |
| 核价拒绝合同 | `tests/test_pricing_rejection.py` | `raise_if_business_error` 区分 `CouponRejectedError`（券被拒）与 `MCPBusinessError`；两阶段校验中**被拒候选不得胜出**、全部被拒退化为不用券、网络异常仍降级 |
| 凑单加量合同 | `tests/test_addon_optimize.py` | `suggest_threshold_addons(allow_existing=True)` 支持对已点商品加量并标注 `is_existing`；`optimize_with_addons` 与「不凑单最优」同口径比较，净亏不推 |

运行：
```bash
python -m pytest tests/ -q                 # 离线：163 例全过
MCD_MCP_TOKEN=xxx pytest -m live -q        # 真实端到端（可选，4 例 live）
python examples/demo_smart.py              # B/C/D/E 离线演示
MCD_MCP_TOKEN=xxx python examples/demo_live.py           # 真实端到端演示（选店→三池→官方核价）
MCD_MCP_TOKEN=xxx python examples/demo_advanced.py       # 进阶：领券扩池 + 套餐省钱 + 多店比价
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
| **C2** | 大规模券剪枝 + 分支限界：券数 >16 自动切 B&B（先剔 0 优惠券，再按乐观上界剪枝），与暴力枚举**同解**；实测 n=20 提速 ~260× | `coupon_optimizer._optimal_subset_bnb` / `_prune_zero_value` / `optimize_coupons(strategy=...)` | ✅ |
| **C3** | Top-K 候选分支限界：`rank_candidates` 用「大小为 K 的最小堆 + 第 K 名上界剪枝」代替全枚举，与暴力枚举**同值**；实测 n=18 提速 ~180× | `coupon_optimizer._rank_candidates_bnb` / `rank_candidates(strategy=...)` | ✅ |
| **C4** | 真实规则「每单至多一张券」：真机实测传两张券返回 `code=600022「暂不支持多张券使用」`，优化器新增 `max_coupons_per_order`（真实核价路径默认 1），暴力/分支限界/两阶段一致遵守 | `coupon_optimizer.optimize_coupons` / `rank_candidates` / `coupon_smart.two_stage_optimize` | ✅ |
| **F1** | 拆分下单：真实「每单一张券」下把购物车拆成多单、每单配一张最优券，权衡外送配送费求全局最低价；与暴力划分基准同值 | `coupon_optimizer.optimize_split_orders` / `_assign_best` / `_partitions` | ✅ |
| **F2** | 外送场景：`price_combo`/`create_order` 支持 `beCode`，新增地址/外送门店封装；外送配送费+打包费建模与券渠道限制契约 | `mcd_client.price_combo` / `query_delivery_stores` / `create_delivery_address` | ✅ |
| **F3** | 一键领券扩池：`auto-bind-coupons` → 重查三池 → 再比价；修掉 README 早期「声称有、实际无」的能力 | `coupon_pools.collect_and_bind_coupons` | ✅ |
| **F4** | 套餐纳入优化：套餐 vs 单点求全局最低价，套餐与券二选一（真实最多省 ¥18.00） | `combo_optimizer.optimize_purchase` / `plan_order_with_combos` / `rank_combo_deals` | ✅ |
| **F5** | 多店比价 + 距离权衡：可接受距离内比较到手价，量化「多走几米省几元」 | `store_optimizer.optimize_across_stores` / `collect_store_quotes` | ✅ |
| **F6** | 促销范围核实：实测 `query-promotions` 仅企业团餐（`beTypes=["6"]`），诚实排除而非虚假承诺 | `tests/test_promotions_scope.py` | ✅ |
| **F7** | 券渠道建模 + 本地前置过滤：`Coupon.channel`（到店/外送）由券标签推断，`filter_coupons_by_channel` 在**求解前**排除渠道不符券（不靠官方 `600012` 事后兜底） | `coupon_optimizer.Coupon.channel` / `infer_channel_from_tag` / `filter_coupons_by_channel` / `coupon_pools.parse_my_coupons_text` | ✅ |
| **F8** | 核价失败语义区分：`CouponRejectedError`（业务拒绝：渠道不符/多券叠加）**剔除候选**，与网络异常（降级本地估计）严格分离，杜绝「被拒方案因估计更便宜而胜出」 | `errors.raise_if_business_error` / `mcd_client.price_combo` / `coupon_smart.two_stage_optimize` | ✅ |
| **F9** | 凑单加量 + 纳入主流程：`suggest_threshold_addons(allow_existing=True)` 允许对已点商品加量（标注 `is_existing`）；`optimize_with_addons` 与「不凑单最优」同口径比较，只有真实更省才推荐 | `coupon_smart.suggest_threshold_addons` / `optimize_with_addons` / `_build_addon_items` | ✅ |

> **关键 Bug 修复（真机联调发现，均补了回归测试）**：
> 1. `calculate-price` 返回 `{success,code,message,data:{...}}`，需拆到最内层 `data`，否则取到 `price=None` 核价归零；
> 2. `query-nearby-stores` / `query-store-coupons` 的 `data` 是**列表**，原实现只拆 dict，导致门店/券数为 0；
> 3. `query-meals` 的说明文字含 `{code}` 占位符，按「第一个 `{`」解析会 `JSONDecodeError`，改为锚定 `{"success"`。
> 4. 分支限界实现中发现**免配送费券被重复减免**：带显式 `stack_group` 的 free_delivery 券会绕过 `__free_delivery__` 合成互斥组，导致两券各减一次配送费。已统一为「免配送费最多减免一次」（与暴力枚举语义一致），并以 40 组随机用例锁定同解性。
> 5. **核价错误响应被当成 ¥0**：券被拒时 `calculate-price` 返回 `{success:false, code:600012, message:...}` 且**无 `price` 字段**，而 `price_combo_as_fn` 用 `data.get("price") or 0` 取值 → 返回 **¥0**，导致**被官方拒绝的方案反而"最便宜"而必然胜出**；`two_stage_optimize` 又对所有异常一律降级，进一步放大该问题。已改为 `errors.raise_if_business_error` 抛出 `CouponRejectedError`，两阶段校验将其**剔除**而非降级（网络异常仍降级）。真机验证：无效券码现返回 `CouponRejectedError 600012`，不再返回 ¥0。
> 6. **券渠道约束只靠官方兜底**：「到店专用」券曾被带入外送方案，仅靠官方 `600012` 事后拦截，而该拦截又会被上面的降级逻辑吃掉。已在 `Coupon` 上建 `channel` 属性并在**本地求解前**过滤（`filter_coupons_by_channel`），渠道信息从「我的券」标签（`parse_my_coupons_text`）与门店券查询入口（`coupon_from_store_json(channel=...)`）获取。
> 7. **凑单无法对已点商品加量**：旧 `suggest_threshold_addons` 无条件排除车内商品，导致最常见的「再点一份同款跨门槛」被系统性漏掉；且该函数从未被主流程调用。已加 `allow_existing` 并新增 `optimize_with_addons` 纳入主流程。
