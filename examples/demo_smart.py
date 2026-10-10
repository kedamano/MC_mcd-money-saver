"""
麦麦省钱助手 · 优化项 B/C/D/E 端到端演示

离线运行（默认）：使用 tests/fixtures 下的真实菜单目录与内置券，演示
  B. 产品级绑定  C. 凑单建议  E. 时效/库存  的真实行为
在线运行（--live）：额外用真实 MCP 跑 D. 两阶段官方核价

运行：
    python examples/demo_smart.py                 # 离线
    MCD_MCP_TOKEN=xxx python examples/demo_smart.py --live   # 真实核价
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.coupon_optimizer import Item, Coupon, optimize_coupons, filter_valid_coupons, check_item_availability
from src.coupon_smart import load_catalog, suggest_threshold_addons, two_stage_optimize


def demo_b_product_binding():
    print("\n===== B. 产品级绑定建模 =====")
    # 真实券：「中杯美式7折」绑定 9900000119
    coffee = Coupon("amer7", kind="percent", discount=0.7, product_codes=["9900000119"])
    items = [
        Item("麦咖啡美式", 19.0, product_code="9900000119"),
        Item("巨无霸", 25.0, product_code="507401"),
    ]
    res = optimize_coupons(items, [coffee])
    print(f"  购物车: 美式19 + 巨无霸25 = 44")
    print(f"  仅美式享受7折 -> 最优总价 ¥{res['best_total']}（巨无霸未被误套折扣）")
    assert res["best_total"] == 38.3


def demo_c_addon():
    print("\n===== C. 凑单建议 =====")
    cat = load_catalog("tests/fixtures/menu_catalog.json")
    cart = [Item("巨无霸", 25.0, product_code="507402")]
    coupons = [Coupon("full40", kind="threshold", discount=20.0, threshold=40.0)]
    sugg = suggest_threshold_addons(cart, coupons, cat, top_k=1)
    if sugg:
        s = sugg[0]
        print(f"  现状: 巨无霸25，距『满40减20』还差 ¥{s['gap']}")
        for a in s["add_items"]:
            print(f"  建议加购: {a['name']} x{a['quantity']} ¥{a['price']}")
        print(f"  加购花费 ¥{s['added_cost']}，券减 ¥{s['coupon_discount']}，净省 ¥{s['net_saving']}")
    else:
        print("  无净收益为正的凑单方案（不诱导盲目凑单）")


def demo_e_validity():
    print("\n===== E. 时效与库存 =====")
    coupons = [
        Coupon("valid", kind="fixed", discount=5.0),
        Coupon("old", kind="fixed", discount=10.0, expires_at="2026-09-30"),
    ]
    fr = filter_valid_coupons(coupons, now="2026-10-10")
    print(f"  过期券被剔除: {[c.id for c in fr['expired']]} -> {fr['warnings']}")
    items = [Item("巨无霸", 25.0, available=True),
             Item("限量麦旋风", 18.0, available=False)]
    print(f"  不可售提示: {check_item_availability(items)}")


def demo_d_two_stage(live: bool):
    print("\n===== D. 两阶段校验 =====")
    items = [
        Item("巨无霸", 25.0, category="main", product_code="507401"),
        Item("薯条", 12.0, category="side", product_code="520001"),
        Item("可乐", 10.0, category="drink", product_code="9900008751"),
    ]
    coupons = [
        Coupon("full40", kind="threshold", discount=10.0, threshold=40.0),
        Coupon("side5", kind="fixed", discount=5.0, applies_to="side"),
    ]
    if live:
        from src.mcd_client import McDonaldMCPClient
        pricing_fn = McDonaldMCPClient.price_combo_as_fn("1450713")
        res = two_stage_optimize(items, coupons, pricing_fn=pricing_fn, top_k=2)
        print(f"  本地粗排 Top-K -> 仅对 {res['validated_count']} 个候选调官方核价")
        print(f"  官方权威最优: 总价 ¥{res['best_total']}，用券 {res['best_coupons']}，省 ¥{res['saved']}")
    else:
        # 离线桩：模拟官方对组合不兼容，只认单券
        def stub(subset, _items):
            ids = {c.id for c in subset}
            if "full40" in ids and "side5" in ids:
                return 47.0
            if "full40" in ids:
                return 37.0
            if "side5" in ids:
                return 42.0
            return 47.0
        res = two_stage_optimize(items, coupons, pricing_fn=stub, top_k=2)
        print(f"  本地粗排 Top-K -> 仅对 {res['validated_count']} 个候选调核价（离线桩）")
        print(f"  权威最优: 总价 ¥{res['best_total']}，用券 {res['best_coupons']}（官方拒绝组合只认单券）")


def main():
    live = "--live" in sys.argv
    if live and not os.environ.get("MCD_MCP_TOKEN"):
        print("⚠️  --live 需要设置环境变量 MCD_MCP_TOKEN")
        sys.exit(1)
    demo_b_product_binding()
    demo_c_addon()
    demo_e_validity()
    demo_d_two_stage(live=live)
    print("\n✅ B/C/D/E 演示完成")


if __name__ == "__main__":
    main()
