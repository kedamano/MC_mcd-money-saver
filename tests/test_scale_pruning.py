"""大规模券组合剪枝 + 分支限界契约测试（C 优化项 · 算法）。

覆盖：
1. 分支限界与暴力枚举**同解**（随机小规模对照，40 组种子）；
2. `strategy="auto"` 在券数超阈值时自动切到 B&B；
3. 0 优惠券剪枝**安全性**（不改变最优解）；
4. 大规模（40 张）时 B&B 秒级完成且结果正确；
5. 同组互斥 / 订单级券至多一张 / 满减门槛 约束在 B&B 下同样生效；
6. 剪枝确实大幅压缩了搜索空间（节点数 << 2^n）。
"""
import random
import time

import pytest

from src.coupon_optimizer import (
    Coupon,
    Item,
    optimize_coupons,
    total_price,
    _coupon_discount,
    _is_valid_subset,
    _optimal_subset_bnb,
    _prune_zero_value,
)


def _payable_of(items, chosen, delivery_fee):
    """按与暴力枚举一致的语义（免配送费最多减一次）复算应付价。"""
    disc = sum(_coupon_discount(c, items) for c in chosen if c.kind != "free_delivery")
    if any(c.kind == "free_delivery" for c in chosen):
        disc += delivery_fee
    return max(0.0, total_price(items, delivery_fee) - disc)


def _rand_case(seed: int):
    """按固定种子生成随机券组合场景（可复现）。"""
    rnd = random.Random(seed)
    items = [
        Item(name="A", price=30.0, category="主食", product_code="A"),
        Item(name="B", price=20.0, category="小食", product_code="B"),
        Item(name="C", price=12.0, category="饮料", product_code="C"),
    ]
    coupons = []
    for i in range(rnd.randint(4, 11)):
        k = rnd.choice(["threshold", "percent", "fixed", "free_delivery"])
        grp = rnd.choice([None, None, "g1", "g2"])
        cat = rnd.choice([None, "主食", "小食", "饮料"])
        if k == "threshold":
            coupons.append(
                Coupon(id=f"c{i}", kind="threshold", discount=rnd.choice([5.0, 8.0, 12.0]),
                       threshold=rnd.choice([10.0, 25.0, 40.0]), applies_to=cat, stack_group=grp)
            )
        elif k == "percent":
            coupons.append(
                Coupon(id=f"c{i}", kind="percent", discount=rnd.choice([0.7, 0.8, 0.9]),
                       max_discount=rnd.choice([0.0, 10.0]), applies_to=cat, stack_group=grp)
            )
        elif k == "fixed":
            coupons.append(
                Coupon(id=f"c{i}", kind="fixed", discount=rnd.choice([3.0, 5.0]),
                       applies_to=cat, stack_group=grp)
            )
        else:
            coupons.append(Coupon(id=f"c{i}", kind="free_delivery", stack_group=grp))
    return items, coupons


def _with_unique_ids(coupons):
    """给券重新编号，避免 dataclass 完全相等导致的 in/去重歧义。"""
    return [Coupon(**{**c.__dict__, "id": f"{c.id}_{i}"}) for i, c in enumerate(coupons)]


# ---------------------------------------------------------------------------
# 1. 同解性：B&B vs 暴力枚举
# ---------------------------------------------------------------------------
def test_bnb_matches_bruteforce_random_cases():
    for seed in range(40):
        items, coupons = _rand_case(seed)
        bf = optimize_coupons(items, coupons, delivery_fee=6.0, strategy="bruteforce")
        bb = optimize_coupons(items, coupons, delivery_fee=6.0, strategy="bnb")
        assert bb["best_total"] == bf["best_total"], f"seed={seed} total 不一致"
        assert bb["saved"] == bf["saved"], f"seed={seed} saved 不一致"
        # B&B 选出的子集必须合法，且复算价确实等于最优价（允许多解同价）
        chosen = [c for c in coupons if c.id in set(bb["best_coupons"])]
        assert _is_valid_subset(chosen, items, 6.0), f"seed={seed} 子集非法"
        assert abs(_payable_of(items, chosen, 6.0) - bf["best_total"]) < 1e-9, f"seed={seed} 价不符"


# ---------------------------------------------------------------------------
# 2. auto 策略在超阈值时切到 B&B
# ---------------------------------------------------------------------------
def test_auto_switches_to_bnb_when_exceeding_limit():
    items, coupons = _rand_case(0)
    base = _with_unique_ids(coupons)
    while len(base) < 16:
        base += _with_unique_ids([Coupon(**{**c.__dict__, "id": f"{c.id}_x{len(base)}"}) for c in coupons[:2]])
    big = base[:16]
    bf = optimize_coupons(items, big, delivery_fee=6.0, strategy="bruteforce")
    au = optimize_coupons(items, big, delivery_fee=6.0, strategy="auto", brute_force_limit=15)
    assert au["best_total"] == bf["best_total"]


# ---------------------------------------------------------------------------
# 3. 0 优惠券剪枝安全性
# ---------------------------------------------------------------------------
def test_zero_value_coupons_pruned_are_safe():
    items = [Item(name="A", price=10.0, category="主食", product_code="A")]
    coupons = [
        Coupon(id="big", kind="threshold", discount=5.0, threshold=1.0, applies_to="主食"),
        Coupon(id="dead", kind="threshold", discount=5.0, threshold=999.0, applies_to="主食"),
        Coupon(id="nofix", kind="fixed", discount=3.0, applies_to="饮料"),
    ]
    kept = _prune_zero_value(coupons, items, 0.0)
    assert {c.id for c in kept} == {"big"}

    res = optimize_coupons(items, coupons, strategy="bnb")
    assert res["best_coupons"] == ["big"]
    assert res["best_total"] == 5.0


# ---------------------------------------------------------------------------
# 4. 大规模可用性：40 张独立券应秒级且全选
# ---------------------------------------------------------------------------
def test_bnb_scales_on_large_coupon_set():
    items = [Item(name="A", price=200.0, category="主食", product_code="A")]
    # 40 张互不冲突的独立券（各自独立 stack_group）→ 最优为全部入选
    coupons = [
        Coupon(id=f"c{i}", kind="fixed", discount=1.0, applies_to="主食", stack_group=f"u{i}")
        for i in range(40)
    ]
    t0 = time.time()
    res = optimize_coupons(items, coupons, strategy="auto")
    dt = time.time() - t0
    assert dt < 1.0, f"B&B 过慢: {dt:.3f}s"
    assert res["best_total"] == 160.0
    assert len(res["best_coupons"]) == 40


# ---------------------------------------------------------------------------
# 5. 约束在 B&B 下同样生效
# ---------------------------------------------------------------------------
def test_bnb_respects_group_and_order_level_constraints():
    items = [Item(name="A", price=100.0, category="主食", product_code="A")]
    coupons = [
        Coupon(id="o1", kind="threshold", discount=10.0, threshold=50.0, applies_to=None),
        Coupon(id="o2", kind="threshold", discount=15.0, threshold=50.0, applies_to=None),
        Coupon(id="g1a", kind="fixed", discount=4.0, applies_to="主食", stack_group="g1"),
        Coupon(id="g1b", kind="fixed", discount=9.0, applies_to="主食", stack_group="g1"),
    ]
    res = optimize_coupons(items, coupons, strategy="bnb")
    # 订单级至多一张且取更优(o2)；同组互斥取更优(g1b)
    assert set(res["best_coupons"]) == {"o2", "g1b"}
    assert res["best_total"] == 100.0 - 15.0 - 9.0


# ---------------------------------------------------------------------------
# 6. 剪枝确实压缩了搜索空间
# ---------------------------------------------------------------------------
def test_bnb_prunes_search_space():
    items = [Item(name="A", price=100.0, category="主食", product_code="A")]
    # 20 张全部同组互斥 → 搜索空间本应 2^20，剪枝后节点数应远小于此
    coupons = [
        Coupon(id=f"c{i}", kind="fixed", discount=float(i + 1), applies_to="主食", stack_group="g")
        for i in range(20)
    ]
    total, subset, stats = _optimal_subset_bnb(items, coupons, 0.0)
    assert total == 80.0  # 取优惠最大的单张 = 20
    assert [c.id for c in subset] == ["c19"]
    assert stats["nodes"] < (2 ** 20) / 10, f"剪枝不足: nodes={stats['nodes']}"
    assert stats["pruned"] > 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
