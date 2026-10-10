"""拆分下单（B1）：在「每单至多一张券」的真实规则下，把购物车拆成多单、
每单配一张最优券，求全局最低总价。

真实动机：麦当劳每单仅支持一张券（`calculate-price` 传两张返回 code=600022
「暂不支持多张券使用」）。当用户手里有两张作用于**不同商品**的高价值券时，
「拆成两单、各用一张」可能比「一单只用一张」更省；但外送场景每单都要付配送费，
拆单未必划算——由 `optimize_split_orders` 统一权衡后给出全局最低价。

本文件同时提供一份**暴力基准**（枚举所有商品划分 + 券分配），用于验证主实现
在测试规模下与「穷举」同值。
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.coupon_optimizer import (
    Coupon,
    Item,
    optimize_coupons,
    optimize_split_orders,
    _coupon_discount,
    _is_valid_subset,
)


# ---------------------------------------------------------------------------
# 测试内的暴力基准（枚举划分 + 券分配）
# ---------------------------------------------------------------------------
def _partitions(seq, max_blocks):
    """生成 seq 的所有「至多 max_blocks 个非空块」的集合划分。"""
    seq = list(seq)

    def rec(i, blocks):
        if i == len(seq):
            yield [list(b) for b in blocks]
            return
        x = seq[i]
        for b in blocks:
            b.append(x)
            yield from rec(i + 1, blocks)
            b.pop()
        if len(blocks) < max_blocks:
            blocks.append([x])
            yield from rec(i + 1, blocks)
            blocks.pop()

    yield from rec(0, [])


def _bruteforce_split(items, coupons, delivery_fee, max_orders=3):
    """穷举所有划分 + 每块分配互不重复的券（每块 <=1 张），返回最小总价。"""
    best = [float("inf")]

    def rec_assign(part, i, used_ids, total):
        if total - 1e-9 >= best[0]:
            return
        if i == len(part):
            best[0] = min(best[0], round(total, 2))
            return
        block = part[i]
        sub = sum(it.price for it in block)
        # 该块不用券
        rec_assign(part, i + 1, used_ids, total + sub + delivery_fee)
        # 该块用一张券（不与其他块重复）
        for c in coupons:
            if c.id in used_ids:
                continue
            if not _is_valid_subset([c], block, delivery_fee, 1):
                continue
            d = delivery_fee if c.kind == "free_delivery" else _coupon_discount(c, block)
            rec_assign(part, i + 1, used_ids | {c.id}, total + sub + delivery_fee - d)

    for part in _partitions(items, max_orders):
        rec_assign(part, 0, set(), 0.0)
    return best[0]


# ---------------------------------------------------------------------------
# 固定场景
# ---------------------------------------------------------------------------
def _two_binding_cart():
    """美式(绑定券A) + 奶铁(绑定券B)，两券作用于不同商品。"""
    items = [
        Item("美式中杯", 19.0, category="drink", product_code="A"),
        Item("奶铁中杯", 21.0, category="drink", product_code="B"),
    ]
    coupons = [
        Coupon("cA", kind="percent", discount=0.7, product_codes=["A"]),
        Coupon("cB", kind="percent", discount=0.7, product_codes=["B"]),
    ]
    return items, coupons


def test_no_coupons_stays_single():
    """无券时不会拆分，总价 = 商品 + 配送费。"""
    items = [Item("巨无霸", 25.0, "main"), Item("薯条", 12.0, "side")]
    res = optimize_split_orders(items, [], delivery_fee=5.0)
    assert res["best_total"] == 42.0
    assert res["n_orders"] == 1
    assert res["split"] is False
    assert res["orders"][0]["coupon_ids"] == []


def test_two_binding_coupons_split_at_store():
    """到店无配送费：拆成两单可各用一张绑定券，比一单省更多。"""
    items, coupons = _two_binding_cart()
    res = optimize_split_orders(items, coupons, delivery_fee=0.0)
    # 不拆只能省一张（33.7）；拆开各用一张：13.3 + 14.7 = 28.0
    assert res["single_order_total"] == 33.7
    assert res["best_total"] == 28.0
    assert res["n_orders"] == 2
    assert res["split"] is True
    assert res["saved"] == 12.0
    used = [cid for o in res["orders"] for cid in o["coupon_ids"]]
    assert sorted(used) == ["cA", "cB"]


def test_delivery_fee_blocks_split():
    """外送场景每单都付配送费：多付一份配送费反而更贵，应保持单订单。"""
    items, coupons = _two_binding_cart()
    res = optimize_split_orders(items, coupons, delivery_fee=6.0)
    # 不拆：40+6-6.3 = 39.7；拆：19.3 + 20.7 = 40.0 > 39.7
    assert res["best_total"] == 39.7
    assert res["n_orders"] == 1
    assert res["split"] is False


def test_threshold_plus_category_split():
    """一张绑定券 + 一张类目券作用于不同商品，拆单可同时吃到两张券的优惠。"""
    items = [
        Item("美式中杯", 19.0, category="drink", product_code="A"),
        Item("巨无霸", 25.0, category="main"),
        Item("薯条", 12.0, category="side"),
    ]
    coupons = [
        Coupon("cA", kind="percent", discount=0.7, product_codes=["A"]),      # 美式7折
        Coupon("cSide", kind="threshold", discount=8.0, threshold=10.0, applies_to="side"),
    ]
    res = optimize_split_orders(items, coupons, delivery_fee=0.0)
    # 不拆：最多省一张（cSide 省8 → 48）；拆：{美式}用cA 13.3 + {巨无霸+薯条}用cSide 29 = 42.3
    assert res["single_order_total"] == 48.0
    assert res["best_total"] == 42.3
    assert res["n_orders"] == 2


def test_coupons_never_reused_across_orders():
    """同一张券绝不可跨单重复使用。"""
    items, coupons = _two_binding_cart()
    res = optimize_split_orders(items, coupons, delivery_fee=0.0)
    used = [cid for o in res["orders"] for cid in o["coupon_ids"]]
    assert len(used) == len(set(used))


def test_max_orders_limit():
    """max_orders=1 时退化为单订单。"""
    items = [
        Item("美式中杯", 19.0, category="drink", product_code="A"),
        Item("奶铁中杯", 21.0, category="drink", product_code="B"),
        Item("可乐", 9.0, category="drink", product_code="C"),
    ]
    coupons = [
        Coupon("cA", kind="percent", discount=0.7, product_codes=["A"]),
        Coupon("cB", kind="percent", discount=0.7, product_codes=["B"]),
        Coupon("cC", kind="percent", discount=0.7, product_codes=["C"]),
    ]
    res = optimize_split_orders(items, coupons, delivery_fee=0.0, max_orders=1)
    assert res["n_orders"] == 1
    assert res["best_total"] == res["single_order_total"]
    # 对照：放开到 3 单，可三券齐用
    res3 = optimize_split_orders(items, coupons, delivery_fee=0.0, max_orders=3)
    assert res3["n_orders"] == 3
    assert res3["best_total"] < res["best_total"]


def test_free_delivery_split_tradeoff():
    """外送含配送费：把免配送费券拆到单独一单并不划算（另一单仍要付配送费）。"""
    items = [
        Item("美式中杯", 19.0, category="drink", product_code="A"),
        Item("巨无霸", 25.0, category="main"),
    ]
    coupons = [
        Coupon("cA", kind="percent", discount=0.7, product_codes=["A"]),
        Coupon("cFree", kind="free_delivery"),
    ]
    res = optimize_split_orders(items, coupons, delivery_fee=9.0)
    # 不拆：cFree 全免配送费 → 44+9-9 = 44（优于 cA 的 47.3）
    assert res["best_total"] == 44.0
    assert res["n_orders"] == 1


def test_single_order_total_matches_optimize_coupons():
    """single_order_total 应与 optimize_coupons(max_coupons=1) 完全一致。"""
    items, coupons = _two_binding_cart()
    res = optimize_split_orders(items, coupons, delivery_fee=3.0)
    base = optimize_coupons(items, coupons, delivery_fee=3.0, max_coupons_per_order=1)
    assert res["single_order_total"] == base["best_total"]


def test_best_never_worse_than_single():
    """拆分是单订单的超集（单块划分即单订单），最优不可能更差。"""
    items, coupons = _two_binding_cart()
    res = optimize_split_orders(items, coupons, delivery_fee=0.0)
    assert res["best_total"] <= res["single_order_total"] + 1e-9


def test_random_equivalence_with_bruteforce():
    """随机小规模：与暴力基准同值（含门槛/类目/产品级绑定券）。"""
    rng = random.Random(20261010)
    cats = ["main", "side", "drink"]
    codes = ["A", "B", "C"]
    for case in range(30):
        n = rng.randint(1, 5)
        items = [
            Item(f"i{k}", float(rng.randint(8, 30)), rng.choice(cats), rng.choice(codes))
            for k in range(n)
        ]
        m = rng.randint(1, 3)
        coupons = []
        for j in range(m):
            kind = rng.choice(["threshold", "percent", "fixed"])
            if kind == "percent":
                coupons.append(Coupon(f"c{j}", kind, discount=rng.choice([0.7, 0.85, 0.9])))
            elif kind == "threshold":
                coupons.append(Coupon(f"c{j}", kind, discount=float(rng.randint(5, 15)),
                                      threshold=float(rng.randint(15, 40))))
            else:
                c = Coupon(f"c{j}", kind, discount=float(rng.randint(3, 10)))
                if rng.random() < 0.5:
                    c.applies_to = rng.choice(cats)
                elif rng.random() < 0.5:
                    c.product_codes = [rng.choice(codes)]
                coupons.append(c)
        fee = rng.choice([0.0, 6.0])
        got = optimize_split_orders(items, coupons, delivery_fee=fee, max_orders=3)
        want = _bruteforce_split(items, coupons, fee, max_orders=3)
        assert got["best_total"] == want, f"case {case} mismatch: got {got['best_total']} want {want}"
