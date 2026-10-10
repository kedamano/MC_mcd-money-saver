"""真实规则：每单至多一张券（麦当劳 MCP 实测 code=600022「暂不支持多张券使用」）。

本地优化器默认保留通用组合能力（max_coupons_per_order=None），
但真实核价路径（two_stage_optimize）默认 max_coupons_per_order=1。
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.coupon_optimizer import Coupon, Item, optimize_coupons, rank_candidates
from src.coupon_smart import two_stage_optimize


def _cart():
    return [
        Item("巨无霸", 25.0, category="main"),
        Item("薯条", 12.0, category="side"),
        Item("可乐", 10.0, category="drink"),
    ]


def _coupons():
    return [
        Coupon("full", kind="threshold", discount=12.0, threshold=40.0),   # 满40减12（订单级）
        Coupon("side", kind="fixed", discount=5.0, applies_to="side"),     # 小食减5
    ]


def test_default_still_allows_stacking():
    """缺省 None：保留通用组合能力，允许两张券叠加（向后兼容）。"""
    res = optimize_coupons(_cart(), _coupons(), max_coupons_per_order=None)
    assert set(res["best_coupons"]) == {"full", "side"}


def test_max_one_coupon_bruteforce():
    """每单一张：只能在两张券中挑优惠更大的一张（full 省12 > side 省5）。"""
    res = optimize_coupons(_cart(), _coupons(), max_coupons_per_order=1, strategy="bruteforce")
    assert res["best_coupons"] == ["full"]
    assert res["saved"] == 12.0


def test_max_one_coupon_bnb_matches_bruteforce():
    """分支限界在券数上限约束下与暴力枚举同解。"""
    bf = optimize_coupons(_cart(), _coupons(), max_coupons_per_order=1, strategy="bruteforce")
    bb = optimize_coupons(_cart(), _coupons(), max_coupons_per_order=1, strategy="bnb")
    assert bf["best_total"] == bb["best_total"]
    assert bf["best_coupons"] == bb["best_coupons"]


def test_rank_candidates_respects_cap():
    """Top-K 候选全部满足每单一张券约束。"""
    cands = rank_candidates(_cart(), _coupons(), top_k=3, max_coupons_per_order=1)
    assert cands, "应至少有一个候选"
    for c in cands:
        assert len(c["best_coupons"]) <= 1
    assert cands[0]["best_coupons"] == ["full"]


def test_two_stage_defaults_to_one_coupon():
    """two_stage_optimize 默认按真实规则限制为每单一张券。"""
    seen = []

    def fake_pricing(subset, items):
        seen.append(subset)
        return 40.0

    res = two_stage_optimize(
        _cart(), _coupons(), delivery_fee=0.0, pricing_fn=fake_pricing, top_k=3
    )
    assert res["validated"] is True
    assert all(len(s) <= 1 for s in seen), "官方核价回调不应收到多券组合"
    assert len(res["best_coupons"]) <= 1
