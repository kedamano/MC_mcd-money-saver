"""
TDD 契约：麦麦省钱助手 · 优化项 B/C/D/E

B. 产品级绑定建模   - 券按 product_codes 精确匹配，避免错配
C. 凑单建议         - 对未达门槛的满减券，反推最小代价加购组合
D. 两阶段校验       - 本地枚举 Top-K + 仅对 Top-K 调官方核价
E. 时效与库存       - 过期券剔除、不可售商品提示

运行：python -m pytest tests/ -q
"""

from src.coupon_optimizer import (
    Item,
    Coupon,
    optimize_coupons,
    filter_valid_coupons,
    check_item_availability,
    rank_candidates,
)
from src.coupon_smart import (
    CatalogItem,
    load_catalog,
    suggest_threshold_addons,
    two_stage_optimize,
)


# ===========================================================================
# B. 产品级绑定建模
# ===========================================================================
def test_product_coupon_only_applies_to_bound_item():
    """产品券只对本店绑定的商品生效，错配到其他商品应被忽略。"""
    # 「中杯美式7折」绑定 9900000119
    coffee_coupon = Coupon(
        "amer7", kind="percent", discount=0.7, product_codes=["9900000119"]
    )
    items = [
        Item("麦咖啡美式", 19.0, product_code="9900000119"),  # 绑定商品
        Item("巨无霸", 25.0, product_code="507401"),          # 非绑定
    ]
    res = optimize_coupons(items, [coffee_coupon], delivery_fee=0.0)
    # 仅美式 19 * 0.7 省 5.7 -> 13.3；巨无霸不参与折扣
    assert res["best_total"] == 38.3
    assert res["best_coupons"] == ["amer7"]


def test_product_coupon_ignored_when_bound_item_absent():
    """绑定的商品不在购物车，则产品券无效（不误套到其他商品）。"""
    coffee_coupon = Coupon(
        "amer7", kind="percent", discount=0.7, product_codes=["9900000119"]
    )
    items = [Item("巨无霸", 25.0, product_code="507401")]
    res = optimize_coupons(items, [coffee_coupon], delivery_fee=0.0)
    assert res["best_total"] == 25.0
    assert res["best_coupons"] == []


def test_product_threshold_coupon_uses_bound_subtotal():
    """产品级满减券：门槛只统计绑定商品的金额。"""
    # 绑定 9900000119 的满减：满 18 减 6
    c = Coupon("p_th", kind="threshold", discount=6.0, threshold=18.0,
               product_codes=["9900000119"])
    items = [
        Item("美式", 19.0, product_code="9900000119"),  # 绑定 19 >= 18
        Item("巨无霸", 25.0, product_code="507401"),     # 非绑定不计入门槛
    ]
    res = optimize_coupons(items, [c], delivery_fee=0.0)
    assert res["best_total"] == 38.0  # 44 - 6


def test_category_coupon_still_works_without_product_codes():
    """未绑定产品的类目券仍按 category 生效（兼容旧逻辑）。"""
    c = Coupon("side5", kind="fixed", discount=5.0, applies_to="side")
    items = [Item("薯条", 12.0, category="side", product_code="520001")]
    res = optimize_coupons(items, [c], delivery_fee=0.0)
    assert res["best_total"] == 7.0


def test_adapter_populates_product_codes_field():
    from src.coupon_adapter import adapt_coupon

    raw = {
        "couponId": "365A627ABDC435D840984F03055DF097",
        "couponCode": "MCD689H051J0J01C0Y078",
        "productCode": "9900000119",
        "description": "新人专享-中杯美式7折",
    }
    c = adapt_coupon(raw)
    assert c.product_codes == ["9900000119"]
    assert c.kind == "percent"
    assert abs(c.discount - 0.7) < 1e-9


# ===========================================================================
# E. 时效与库存
# ===========================================================================
def test_expired_coupon_filtered_out():
    coupons = [
        Coupon("valid", kind="fixed", discount=5.0),
        Coupon("old", kind="fixed", discount=10.0, expires_at="2026-09-30"),
    ]
    res = filter_valid_coupons(coupons, now="2026-10-10")
    assert [c.id for c in res["valid"]] == ["valid"]
    assert [c.id for c in res["expired"]] == ["old"]
    assert any("old" in w for w in res["warnings"])


def test_unexpired_coupon_kept():
    coupons = [
        Coupon("future", kind="fixed", discount=5.0, expires_at="2026-12-31"),
    ]
    res = filter_valid_coupons(coupons, now="2026-10-10")
    assert res["expired"] == []
    assert [c.id for c in res["valid"]] == ["future"]


def test_unavailable_item_warning():
    items = [
        Item("巨无霸", 25.0, available=True),
        Item("限量麦旋风", 18.0, available=False),
    ]
    warns = check_item_availability(items)
    assert any("限量麦旋风" in w for w in warns)


# ===========================================================================
# C. 凑单建议
# ===========================================================================
def _small_catalog():
    return [
        CatalogItem("520689", "鲜萃咖啡", 9.5),
        CatalogItem("515837", "圆筒冰淇淋", 5.0),
        CatalogItem("6102", "苹果片", 7.0),
        CatalogItem("520001", "薯条", 12.0),
        CatalogItem("507401", "麦辣鸡腿堡", 21.0),
    ]


def test_suggest_chooses_cheapest_addon_combo():
    """距门槛差 15，券减 25：算法应推荐最小代价组合（苹果片7+鲜萃9.5=16.5），净省 8.5。"""
    cart = [Item("巨无霸", 25.0, product_code="507402")]
    coupons = [Coupon("full40", kind="threshold", discount=25.0, threshold=40.0)]
    sugg = suggest_threshold_addons(cart, coupons, _small_catalog(), top_k=1)
    assert len(sugg) == 1
    s = sugg[0]
    assert s["target_coupon"] == "full40"
    assert s["gap"] == 15.0
    # 最小代价组合：鲜萃9.5 + 苹果片7 = 16.5，净省 25 - 16.5 = 8.5
    assert abs(s["net_saving"] - 8.5) < 1e-9
    assert abs(s["added_cost"] - 16.5) < 1e-9
    added_codes = {a["code"] for a in s["add_items"]}
    assert added_codes == {"520689", "6102"}


def test_suggest_rejects_negative_net_saving():
    """若加购代价超过券面额，则不给出（净收益为负）。"""
    cart = [Item("巨无霸", 25.0, product_code="507402")]
    # 门槛 40 减 10，gap=15，最小加购≥15 为 21（堡），net=-11 -> 不应推荐
    coupons = [Coupon("full40", kind="threshold", discount=10.0, threshold=40.0)]
    sugg = suggest_threshold_addons(cart, coupons, _small_catalog(), top_k=3)
    assert sugg == []


def test_suggest_uses_real_catalog_fixture():
    """用真实菜单目录做凑单，至少能产出一条正净收益建议。"""
    cat = load_catalog("tests/fixtures/menu_catalog.json")
    cart = [Item("巨无霸", 25.0, product_code="507402")]
    # 门槛 40 减 20，距门槛差 15；目录中存在 7+9.5 等组合可净赚
    coupons = [Coupon("full40", kind="threshold", discount=20.0, threshold=40.0)]
    sugg = suggest_threshold_addons(cart, coupons, cat, top_k=2)
    assert any(s["net_saving"] > 0 for s in sugg)


# ===========================================================================
# D. 两阶段校验
# ===========================================================================
def test_rank_candidates_returns_top_k():
    items = [
        Item("巨无霸", 25.0, category="main"),
        Item("薯条", 12.0, category="side"),
        Item("可乐", 10.0, category="drink"),
    ]  # 47
    coupons = [
        Coupon("full40", kind="threshold", discount=10.0, threshold=40.0),
        Coupon("side5", kind="fixed", discount=5.0, applies_to="side"),
        Coupon("vip9", kind="percent", discount=0.9),
    ]
    cands = rank_candidates(items, coupons, delivery_fee=0.0, top_k=3)
    assert len(cands) <= 3
    # 候选按本地估计节省降序
    savings = [c["saved"] for c in cands]
    assert savings == sorted(savings, reverse=True)


def test_two_stage_prefers_authoritative_pricing():
    """官方核价回调可能与本地估计不同：本地把组合排第一，但官方拒绝组合只认单券，two_stage 应基于权威值选单券。"""
    items = [
        Item("巨无霸", 25.0, category="main"),
        Item("薯条", 12.0, category="side"),
        Item("可乐", 10.0, category="drink"),
    ]  # 47
    coupons = [
        Coupon("full40", kind="threshold", discount=10.0, threshold=40.0),
        Coupon("side5", kind="fixed", discount=5.0, applies_to="side"),
    ]

    calls = []

    def pricing_fn(subset_coupons, _items):
        ids = {c.id for c in subset_coupons}
        calls.append(sorted(ids))
        if "full40" in ids and "side5" in ids:
            # 官方：两张券不兼容，组合整体不生效 -> 退回原价
            return 47.0
        if "full40" in ids:
            return 47.0 - 10.0  # 37
        if "side5" in ids:
            return 47.0 - 5.0   # 42
        return 47.0

    res = two_stage_optimize(items, coupons, delivery_fee=0.0,
                             pricing_fn=pricing_fn, top_k=2)
    # 本地估计组合省15排第一，但官方拒绝组合；权威最优为 full40 单券（省10）
    assert res["best_coupons"] == ["full40"]
    assert abs(res["best_total"] - 37.0) < 1e-9
    assert res["validated"] is True
    # 仅对 Top-K 候选调用核价，而非全部 2^n
    assert len(calls) <= 2


def test_two_stage_falls_back_when_pricing_fn_none():
    """未提供核价回调时，两阶段退化为本地最优（不联网）。"""
    items = [Item("巨无霸", 25.0, category="main"),
             Item("薯条", 12.0, category="side"),
             Item("可乐", 10.0, category="drink")]  # 47，已达门槛
    coupons = [Coupon("full40", kind="threshold", discount=10.0, threshold=40.0)]
    res = two_stage_optimize(items, coupons, delivery_fee=0.0, pricing_fn=None)
    assert res["best_coupons"] == ["full40"]
    assert res["validated"] is False
