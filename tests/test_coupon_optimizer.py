"""
测试契约：麦麦省钱助手 - 优惠券最优组合优化器

遵循 TDD 风格：先定义期望行为（契约），再实现 coupon_optimizer 使其全部通过。
运行：python -m pytest tests/ -q
"""

from src.coupon_optimizer import (
    Item,
    Coupon,
    optimize_coupons,
    total_price,
)


# ---------------------------------------------------------------------------
# 1. 满减券：达到门槛才生效
# ---------------------------------------------------------------------------
def test_threshold_coupon_applies_when_met():
    items = [Item("巨无霸", 25.0), Item("薯条", 12.0), Item("可乐", 10.0)]  # 47
    coupons = [Coupon("c1", kind="threshold", discount=10.0, threshold=40.0)]
    result = optimize_coupons(items, coupons, delivery_fee=0.0)
    assert result["best_total"] == 37.0
    assert set(result["best_coupons"]) == {"c1"}


def test_threshold_coupon_skipped_when_not_met():
    items = [Item("冰淇淋", 8.0)]
    coupons = [Coupon("c1", kind="threshold", discount=10.0, threshold=40.0)]
    result = optimize_coupons(items, coupons, delivery_fee=0.0)
    assert result["best_total"] == 8.0
    assert result["best_coupons"] == []


# ---------------------------------------------------------------------------
# 2. 折扣券：按比例减免，支持封顶
# ---------------------------------------------------------------------------
def test_percent_coupon_basic():
    items = [Item("套餐A", 50.0), Item("套餐B", 50.0)]  # 100
    coupons = [Coupon("p1", kind="percent", discount=0.85)]  # 85折 -> 省15
    result = optimize_coupons(items, coupons, delivery_fee=0.0)
    assert result["best_total"] == 85.0


def test_percent_coupon_with_cap():
    items = [Item("全家桶", 200.0)]
    coupons = [Coupon("p1", kind="percent", discount=0.8, max_discount=20.0)]  # 应省20封顶
    result = optimize_coupons(items, coupons, delivery_fee=0.0)
    assert result["best_total"] == 180.0


# ---------------------------------------------------------------------------
# 3. 免配送费券
# ---------------------------------------------------------------------------
def test_free_delivery_coupon():
    items = [Item("麦辣鸡腿堡", 21.0)]
    coupons = [Coupon("d1", kind="free_delivery")]
    result = optimize_coupons(items, coupons, delivery_fee=9.0)
    assert result["best_total"] == 21.0  # 配送费被免掉


# ---------------------------------------------------------------------------
# 4. 互斥券：同一 stack_group 只能选其一
# ---------------------------------------------------------------------------
def test_mutually_exclusive_coupons():
    items = [Item("套餐", 60.0)]
    # 两张互斥券：一张满60减15，一张85折(省9)；只能选一张，应取满减
    coupons = [
        Coupon("a", kind="threshold", discount=15.0, threshold=60.0, stack_group="g1"),
        Coupon("b", kind="percent", discount=0.85, stack_group="g1"),
    ]
    result = optimize_coupons(items, coupons, delivery_fee=0.0)
    assert result["best_total"] == 45.0
    assert result["best_coupons"] == ["a"]


# ---------------------------------------------------------------------------
# 5. 组合择优：多张券自动挑出最低价组合
# ---------------------------------------------------------------------------
def test_combination_optimization():
    items = [
        Item("巨无霸", 25.0, category="main"),
        Item("麦香鸡", 18.0, category="main"),
        Item("薯条", 12.0, category="side"),
        Item("可乐", 10.0, category="drink"),
    ]  # 65
    coupons = [
        Coupon("full", kind="threshold", discount=12.0, threshold=60.0),  # 满60减12
        Coupon("side_off", kind="fixed", discount=5.0, applies_to="side"),  # 小食减5
        Coupon("vip", kind="percent", discount=0.9),  # 9折
    ]
    result = optimize_coupons(items, coupons, delivery_fee=6.0)
    # 最优：full + side_off 组合 -> 65 + 6 - 12 - 5 = 54
    # （vip 9折省6.5，不如 full+side_off 省17）
    assert result["best_total"] == 54.0
    assert set(result["best_coupons"]) == {"full", "side_off"}


# ---------------------------------------------------------------------------
# 6. 类目限制：券只作用于指定类目
# ---------------------------------------------------------------------------
def test_category_restriction():
    items = [
        Item("巨无霸", 25.0, category="main"),
        Item("玩具", 30.0, category="toy"),  # 玩具不在餐饮优惠范围
    ]
    coupons = [Coupon("main_off", kind="threshold", discount=10.0, threshold=25.0, applies_to="main")]
    # 仅 main 类目 25 达到门槛 -> 减10；toy 不计入门槛也不享受减免
    result = optimize_coupons(items, coupons, delivery_fee=0.0)
    assert result["best_total"] == 45.0


# ---------------------------------------------------------------------------
# 7. 无券场景
# ---------------------------------------------------------------------------
def test_no_coupons():
    items = [Item("薯条", 12.0)]
    result = optimize_coupons(items, [], delivery_fee=5.0)
    assert result["best_total"] == 17.0
    assert result["best_coupons"] == []


# ---------------------------------------------------------------------------
# 8. total_price 纯函数校验
# ---------------------------------------------------------------------------
def test_total_price_pure():
    items = [Item("a", 10.0), Item("b", 20.0)]
    assert total_price(items, delivery_fee=3.0) == 33.0
