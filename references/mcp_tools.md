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
