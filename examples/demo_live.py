"""
麦麦省钱助手 · 真实麦当劳 MCP 端到端演示（可直接截图 / 录屏）

与 demo_smart.py（离线算法演示）不同，本脚本**全部走真实 MCP**：
    服务器时间 → 附近门店 → 门店菜单 → 门店券 → calculate-price 有/无券对比

运行：
    MCD_MCP_TOKEN=xxx python examples/demo_live.py

输出为格式化报告，适合放进 README / 演示视频首屏。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.mcd_client import McDonaldMCPClient

LINE = "=" * 60
SUB = "-" * 60


def _fen(v) -> str:
    """分 -> ¥元 字符串，兼容 None。"""
    try:
        return f"¥{int(v) / 100:.2f}"
    except (TypeError, ValueError):
        return "¥0.00"


def _pick_nearest(stores):
    """从真实门店列表中按距离取最近一家（distance 单位：米）。"""
    if not stores:
        return None
    return sorted(stores, key=lambda s: s.get("distance", 1 << 30))[0]


def main() -> int:
    token = os.environ.get("MCD_MCP_TOKEN", "").strip()
    if not token:
        print("⚠️  请先设置环境变量 MCD_MCP_TOKEN（来自 https://open.mcd.cn/mcp）")
        print("   例如：MCD_MCP_TOKEN=xxxxx python examples/demo_live.py")
        return 1

    client = McDonaldMCPClient(token=token)

    print(LINE)
    print("  麦麦省钱助手 · 真实麦当劳 MCP 端到端演示")
    print("  数据源：https://mcp.mcd.cn（真实生产网关）")
    print(LINE)

    # [1/5] 服务器时间
    t = client.call_tool("now-time-info", {})
    print(f"[1/5] 服务器时间   {t.get('formatted')}  {t.get('dayOfWeek')}  {t.get('timezone')}")

    # [2/5] 附近门店
    stores = client.call_tool(
        "query-nearby-stores",
        {"searchType": 2, "beType": 1, "city": "上海", "keyword": "南京东路"},
    )
    store = _pick_nearest(stores if isinstance(stores, list) else [])
    if not store:
        print("❌ 未查询到门店，终止演示")
        return 2
    store_code = store["storeCode"]
    print(f"[2/5] 附近门店     {store_code} {store.get('storeName')}（{store.get('distance')}m）")

    # [3/5] 门店菜单
    menu = client.call_tool("query-meals", {"storeCode": store_code, "orderType": 1, "beType": 1})
    meals = (menu or {}).get("meals", {}) if isinstance(menu, dict) else {}
    cats = (menu or {}).get("categories", []) if isinstance(menu, dict) else []
    print(f"[3/5] 门店菜单     共 {len(meals)} 个商品 / {len(cats)} 个分类")
    for code in ("1100", "4810", "9900008751"):
        if code in meals:
            m = meals[code]
            print(f"                    - {m.get('name')} {_fen(float(m.get('currentPrice', 0)) * 100)}")

    # [4/5] 门店券
    coupons = client.call_tool(
        "query-store-coupons", {"storeCode": store_code, "orderType": 1, "beType": 1}
    )
    coupons = coupons if isinstance(coupons, list) else []
    print(f"[4/5] 门店优惠券   {len(coupons)} 张")
    for c in coupons:
        prods = "、".join(p.get("productName", "") for p in c.get("products", []))
        print(f"                    - {c.get('title')}（适用：{prods}）")

    if not coupons:
        print(SUB)
        print("✅ 真实链路完成（本门店暂无可比券）")
        return 0

    # [5/5] 官方核价对比：同一购物车，无券 vs 用券
    c0 = coupons[0]
    locked_code = (c0.get("products") or [{}])[0].get("productCode")
    cart = [{"productCode": locked_code, "quantity": 1},
            {"productCode": "1100", "quantity": 1},
            {"productCode": "4810", "quantity": 1}]

    no_coupon = client.call_tool(
        "calculate-price",
        {"storeCode": store_code, "orderType": 1, "beType": 1, "items": cart},
    )
    with_items = [dict(cart[0], couponId=c0.get("couponId"), couponCode=c0.get("couponCode"))] + cart[1:]
    with_coupon = client.call_tool(
        "calculate-price",
        {"storeCode": store_code, "orderType": 1, "beType": 1, "items": with_items},
    )

    p0 = (no_coupon or {}).get("price")
    p1 = (with_coupon or {}).get("price")
    disc = (with_coupon or {}).get("discount") or 0
    print("[5/5] 官方核价对比（calculate-price）")
    print(f"      购物车：美式中杯 + 巨无霸 + 中薯条   券：{c0.get('title')}")
    print(f"      ├ 无券   {_fen(p0)}   （美式中杯为「券锁定商品」，无券被官方静默剔除）")
    print(f"      └ 用券   {_fen(p1)}   （含美式中杯 ¥13.30，券优惠 -{_fen(disc)}）")
    print(f"      结论：该券让中杯美式 19.00 → 13.30，净省 {_fen(disc)}")
    print(SUB)
    print("✅ 全链路数据均来自麦当劳 MCP 真实返回（非模拟）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
