"""TDD 契约：凑单支持「加量」并纳入主流程（缺口 3）

真实痛点：
  - 旧 `suggest_threshold_addons` 的候选会**排除购物车已有商品**（`ci.code not in cart_codes`），
    于是"差 3 元到门槛，再点一份同款薯条最划算"这种最常见的凑单建议被系统性漏掉。
  - 且该函数是**孤立的**，没有被 `optimize_coupons` / `two_stage_optimize` 这类主流程调用，
    不显式调用就永远不会触发凑单建议。

本契约要求：
  1. `suggest_threshold_addons(..., allow_existing=True)` 允许对已有商品**加量**，并标注 `is_existing`；
  2. 新增 `optimize_with_addons` 把「凑单后到手价」与「不凑单最优」放在一起比较，
     只有**真实更省**才推荐（加购花费已计入新总价，无需另行近似）。

运行：python -m pytest tests/test_addon_optimize.py -q
"""

from src.coupon_optimizer import Coupon, Item
from src.coupon_smart import (
    CatalogItem,
    optimize_with_addons,
    suggest_threshold_addons,
)


def _cart_fries():
    """购物车：一份薯条 ¥12（差 8 元到满 20 减 15 的门槛）。"""
    return [Item("薯条", 12.0, product_code="F1", category="side")]


# ---------------------------------------------------------------------------
# 1. 加量已有商品
# ---------------------------------------------------------------------------
def test_addon_can_add_existing_cart_item():
    """只能通过「再加一份已点薯条」跨门槛时，必须能给出该建议。"""
    c = Coupon("th20", kind="threshold", discount=15.0, threshold=20.0)
    catalog = [CatalogItem("F1", "薯条", 12.0)]
    r = suggest_threshold_addons(_cart_fries(), [c], catalog, allow_existing=True)
    assert r, "应给出加量建议"
    assert r[0]["add_items"][0]["code"] == "F1"
    assert r[0]["add_items"][0]["is_existing"] is True
    assert r[0]["added_cost"] == 12.0
    assert r[0]["net_saving"] == 3.0  # 券 15 - 加购 12


def test_addon_excludes_existing_when_disabled():
    """allow_existing=False 时保持旧行为（排除车内商品 → 无建议）。"""
    c = Coupon("th20", kind="threshold", discount=15.0, threshold=20.0)
    catalog = [CatalogItem("F1", "薯条", 12.0)]
    assert suggest_threshold_addons(_cart_fries(), [c], catalog, allow_existing=False) == []


def test_addon_prefers_cheapest_way_to_reach_threshold():
    """多种加购路径都可行时，选加购代价最小者。"""
    c = Coupon("th20", kind="threshold", discount=15.0, threshold=20.0)
    catalog = [CatalogItem("F1", "薯条", 12.0), CatalogItem("P1", "派", 8.0)]
    r = suggest_threshold_addons(_cart_fries(), [c], catalog, allow_existing=True)
    assert r[0]["add_items"][0]["code"] == "P1"  # 8 < 12，代价更小
    assert r[0]["add_items"][0]["is_existing"] is False


# ---------------------------------------------------------------------------
# 2. 纳入主流程：与「不凑单最优」比较
# ---------------------------------------------------------------------------
def test_optimize_with_addons_recommends_profitable_addon():
    c = Coupon("th20", kind="threshold", discount=15.0, threshold=20.0)
    catalog = [CatalogItem("F1", "薯条", 12.0)]
    r = optimize_with_addons(_cart_fries(), [c], catalog)
    assert r["used_addons"] is True
    assert r["baseline_total"] == 12.0   # 不凑单：券用不上
    assert r["best_total"] == 9.0        # 加一份薯条 24 - 15
    assert r["saved"] == 3.0
    assert r["add_items"][0]["code"] == "F1"
    assert r["best_coupons"] == ["th20"]


def test_optimize_with_addons_declines_when_not_profitable():
    """凑单后反而更贵时不推荐（净收益为负）。"""
    c = Coupon("th20", kind="threshold", discount=3.0, threshold=20.0)
    catalog = [CatalogItem("F1", "薯条", 12.0)]
    r = optimize_with_addons(_cart_fries(), [c], catalog)
    assert r["used_addons"] is False
    assert r["best_total"] == 12.0
    assert r["add_items"] == []


def test_optimize_with_addons_no_threshold_coupon_is_baseline():
    """没有门槛券时退化为纯基线（不产生凑单）。"""
    c = Coupon("any3", kind="fixed", discount=3.0)
    catalog = [CatalogItem("F1", "薯条", 12.0)]
    r = optimize_with_addons(_cart_fries(), [c], catalog)
    assert r["used_addons"] is False
    assert r["best_total"] == 9.0  # 12 - 3


def test_optimize_with_addons_respects_channel():
    """渠道不符的门槛券不得被凑单触发。"""
    from src.coupon_optimizer import CHANNEL_DINE_IN, CHANNEL_DELIVERY

    c = Coupon("th20", kind="threshold", discount=15.0, threshold=20.0,
               channel=CHANNEL_DINE_IN)
    catalog = [CatalogItem("F1", "薯条", 12.0)]
    r = optimize_with_addons(_cart_fries(), [c], catalog, order_channel=CHANNEL_DELIVERY)
    assert r["used_addons"] is False
    assert r["best_total"] == 12.0
    assert r["channel_excluded"] == ["th20"]
