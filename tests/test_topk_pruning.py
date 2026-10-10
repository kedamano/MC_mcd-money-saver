"""Top-K 候选枚举的剪枝与分支限界契约测试（C 优化项 · rank_candidates）。

背景：`rank_candidates` 供两阶段核价做初筛，需要返回**节省额最高的 K 个**券组合。
原先它枚举全部 2^n 子集再排序取前 K，大券池会组合爆炸。本测试锁定：

1. Top-K 分支限界与暴力枚举**结果同值**（相同 saved 多重集）；
2. `strategy="auto"` 超阈值时自动切 B&B；
3. 0 优惠券被安全剔除（不出现在候选里，也不改最优值）；
4. 大券池（n=24）秒级完成且仍返回正确 Top-K；
5. 结果按 saved 降序且数量不超过 K。
"""
import random
import time

import pytest

from src.coupon_optimizer import (
    Coupon,
    Item,
    rank_candidates,
)


def _rand_case(seed: int):
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
            coupons.append(Coupon(id=f"c{i}", kind="threshold", discount=rnd.choice([5.0, 8.0, 12.0]),
                                  threshold=rnd.choice([10.0, 25.0, 40.0]), applies_to=cat, stack_group=grp))
        elif k == "percent":
            coupons.append(Coupon(id=f"c{i}", kind="percent", discount=rnd.choice([0.7, 0.8, 0.9]),
                                  max_discount=rnd.choice([0.0, 10.0]), applies_to=cat, stack_group=grp))
        elif k == "fixed":
            coupons.append(Coupon(id=f"c{i}", kind="fixed", discount=rnd.choice([3.0, 5.0]),
                                  applies_to=cat, stack_group=grp))
        else:
            coupons.append(Coupon(id=f"c{i}", kind="free_delivery", stack_group=grp))
    return items, coupons


def _saved_multiset(cands):
    return sorted(round(c["saved"], 2) for c in cands)


# ---------------------------------------------------------------------------
# 1. 同值性：Top-K B&B vs 暴力枚举
# ---------------------------------------------------------------------------
def test_topk_bnb_matches_bruteforce_values():
    for seed in range(40):
        items, coupons = _rand_case(seed)
        for top_k in (1, 3, 5):
            bf = rank_candidates(items, coupons, 6.0, top_k, strategy="bruteforce")
            bb = rank_candidates(items, coupons, 6.0, top_k, strategy="bnb")
            assert _saved_multiset(bb) == _saved_multiset(bf), f"seed={seed} k={top_k}"


# ---------------------------------------------------------------------------
# 2. auto 策略超阈值自动切 B&B
# ---------------------------------------------------------------------------
def test_topk_auto_switches_to_bnb():
    items, coupons = _rand_case(1)
    base = []
    for i, c in enumerate(coupons * 3):
        base.append(Coupon(**{**c.__dict__, "id": f"{c.id}_{i}"}))
    big = base[:16]
    bf = rank_candidates(items, big, 6.0, 3, strategy="bruteforce")
    au = rank_candidates(items, big, 6.0, 3, strategy="auto", brute_force_limit=15)
    assert _saved_multiset(au) == _saved_multiset(bf)


# ---------------------------------------------------------------------------
# 3. 0 优惠券被剔除
# ---------------------------------------------------------------------------
def test_topk_excludes_zero_value_coupons():
    items = [Item(name="A", price=10.0, category="主食", product_code="A")]
    coupons = [
        Coupon(id="live", kind="threshold", discount=5.0, threshold=1.0, applies_to="主食"),
        Coupon(id="dead", kind="threshold", discount=5.0, threshold=999.0, applies_to="主食"),
    ]
    cands = rank_candidates(items, coupons, 0.0, top_k=3, strategy="bnb")
    assert cands, "应至少有 'live' 候选"
    for c in cands:
        assert "dead" not in c["best_coupons"]
    assert cands[0]["best_coupons"] == ["live"]
    assert cands[0]["best_total"] == 5.0


# ---------------------------------------------------------------------------
# 4. 大券池可用性
# ---------------------------------------------------------------------------
def test_topk_bnb_scales_on_large_set():
    items = [Item(name="A", price=200.0, category="主食", product_code="A")]
    # 24 张互不冲突的独立小额券（各自独立组）→ 最优组合为全部入选
    coupons = [
        Coupon(id=f"c{i}", kind="fixed", discount=1.0, applies_to="主食", stack_group=f"u{i}")
        for i in range(24)
    ]
    t0 = time.time()
    cands = rank_candidates(items, coupons, 0.0, top_k=3, strategy="auto")
    dt = time.time() - t0
    assert dt < 1.0, f"Top-K B&B 过慢: {dt:.3f}s"
    assert len(cands) == 3
    assert cands[0]["saved"] == 24.0  # 全部入选省 24
    savings = [c["saved"] for c in cands]
    assert savings == sorted(savings, reverse=True)


# ---------------------------------------------------------------------------
# 5. 数量与降序约束
# ---------------------------------------------------------------------------
def test_topk_shape_and_order():
    items, coupons = _rand_case(7)
    cands = rank_candidates(items, coupons, 6.0, top_k=4, strategy="bnb")
    assert len(cands) <= 4
    savings = [c["saved"] for c in cands]
    assert savings == sorted(savings, reverse=True)
    for c in cands:
        assert set(c.keys()) == {"best_total", "best_coupons", "best_coupon_objs", "saved"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
