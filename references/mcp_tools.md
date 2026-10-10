# 麦当劳 MCP 工具参考（省钱场景）

本文件供 WorkBuddy 在执行"麦麦省钱助手"时按需加载，列出与省钱/优惠最相关的麦当劳 MCP Tool 及其用途。完整工具列表见麦当劳 MCP Server 仓库：https://github.com/M-China/mcd-mcp-server

## 省钱核心链路用到的工具

| Tool 名称 | 用途 | 在省钱流程中的角色 |
|---|---|---|
| `query-nearby-stores` | 查询附近可用门店 | 选定下单门店 |
| `delivery-query-stores` | 查询收货地址附近可配送门店 | 外送场景选店 |
| `query-meals` | 查询当前门店可售卖餐品（分类/编码/标签） | 选品、构建购物项 |
| `query-meal-detail` | 查询餐品详情/套餐组成 | 查看套餐内容、可替换项 |
| `query-store-coupons` | 查询当前门店可用优惠券 | 候选券来源 ① |
| `query-my-coupons` | 查询账户下全部可用券 | 候选券来源 ② |
| `available-coupons` | 查询可领取的麦麦省券列表 | 候选券来源 ③ |
| `auto-bind-coupons` | 一键领取所有可领麦麦省券 | 扩充可用券池 |
| `calculate-price` | 按商品+券计算金额/配送费/应付总价 | 权威核价（与优化器结果对照） |
| `now-time-info` | 获取当前时间 | 判断券有效期/活动时效 |
| `create-order` | 创建订单并返回支付链接 | 最终下单 |
| `query-order` / `order-list` | 查询订单/历史订单 | 售后与核对 |

## 券类型映射（供 coupon_optimizer 建模）

- `threshold` 满减券：满 X 减 Y（对应 `discount=Y, threshold=X`）
- `percent` 折扣券：折扣率（对应 `discount=0.85` 表示 85 折）
- `fixed` 立减券：直接减固定金额
- `free_delivery` 免配送费券

> 注：麦当劳实际下单中，全单通用型订单级券（满减/折扣/立减）通常一次仅可用一张；
> 类目限定券与免配送费券可与一张订单级券叠加。`coupon_optimizer` 已按此约束实现。
> 最终以 `calculate-price` 返回的权威金额为准。

## 真实联调关键参数（2026-10-10 实测）

以下字段名经真机联调核对，作为 SKILL.md 调用时的权威依据。

### query-nearby-stores（选门店）

- 必填：`beType`（1=到店自提 / 5=得来速）、`searchType`（1=收藏 / 2=按位置）
- **`searchType=2` 必须同时传 `city` 与 `keyword`**，否则报 600058
- 返回 `data[]`：`storeCode`（后续入参）、`storeName`、`address`、`distance`、`reservation`、`reservationTimeOptions`
- ⚠️ `beType=1` 门店**无 beCode**，后续工具不传 beCode

### query-meals（菜单）

- 必填：`storeCode`、`orderType`（1=到店 / 2=外送）、`beType`
- 返回：`data.categories[].meals[].code`（= 售卖 productCode）、`data.meals[code].name / currentPrice / originalPrice / discountType`

### query-store-coupons / query-my-coupons（券）

- `query-store-coupons` 必填：`orderType`、`beType`、`storeCode`；返回 `couponId`、`couponCode`、`tradeDateTime`、`products[].productCode`
- `query-my-coupons` 无必填（可选 `page`/`pageSize`）；返回卡包券（含有效期、适用商品）

### calculate-price（核价，省钱闭环核心）

- 必填：`storeCode`、`orderType`、`beType`；可选 `needTableware`、`items`、`beCode`（非到店必传）
- `items[]` 元素字段：**`productCode`**（非 code，与菜单 code 一致）、`quantity`、`couponCode`、`couponId`、`modification`（特制）、`roundList`（套餐子项）
- 返回金额字段单位均为**分**：`originalPrice`、`discount`、`price`、`packingPrice`、`deliveryPrice`、`tablewarePrice`
- `productList[]`：`productCode / productName / quantity / originalSubtotal / subtotal`
- `takeWayList[]`：`code`（eat-in 堂食 / locker-out 外带）、`title`、`subtitle`
- ✅ 实测：传入 `couponCode + couponId` 后 `discount` 正确体现优惠（如美式中杯7折：19.00→13.30）
