"""
麦麦省钱助手 - 优惠券最优组合优化器

纯函数模块，不依赖任何外部服务，可独立测试与复用。
输入：购物项列表 + 候选优惠券列表 + 配送费
输出：在满足门槛与互斥约束下，使"商品+配送-优惠"总价最低的券组合。

设计目标：
- 支持麦当劳常见券类型：满减(threshold)、折扣(percent)、立减(fixed)、免配送费(free_delivery)
- 支持类目限制(applies_to)与互斥组(stack_group)
- 通过暴力枚举所有子集 + 约束剪枝保证结果最优（候选券数量通常为个位数，性能充足）

Author: 麦麦省钱助手参赛项目
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import List, Optional


@dataclass
class Item:
    """购物项。category 用于类目限定券（如仅限小食/仅限主餐）。"""

    name: str
    price: float
    category: Optional[str] = None


@dataclass
class Coupon:
    """优惠券定义。

    kind:
        "threshold"   满减券：eligible 小计 >= threshold 时，立减 discount
        "percent"     折扣券：discount 为折扣率(0.85=85折)，优惠 = eligible小计*(1-rate)，受 max_discount 封顶
        "fixed"       立减券：直接减 discount（需存在 eligible 项）
        "free_delivery" 免配送费：减免全部配送费（同类券自动互斥，仅生效一张）
    applies_to:  限定类目；None 表示全单通用
    stack_group: 同组券互斥，仅可叠加一张；None 表示无限制
    """

    id: str
    kind: str
    discount: float = 0.0
    threshold: float = 0.0
    max_discount: float = 0.0
    applies_to: Optional[str] = None
    stack_group: Optional[str] = None


def total_price(items: List[Item], delivery_fee: float = 0.0) -> float:
    """计算未使用任何券时的原始总价（商品 + 配送）。"""
    return round(sum(i.price for i in items) + delivery_fee, 2)


def _effective_group(coupon: Coupon) -> Optional[str]:
    """免配送费券内部强制互斥，避免重复减免配送费。"""
    if coupon.kind == "free_delivery" and coupon.stack_group is None:
        return "__free_delivery__"
    return coupon.stack_group


def _coupon_discount(coupon: Coupon, items: List[Item]) -> float:
    """计算单张券对当前购物项的优惠金额（已通过门槛/类目前置校验）。"""
    eligible = [
        i for i in items if coupon.applies_to is None or i.category == coupon.applies_to
    ]
    if coupon.kind == "threshold":
        if sum(e.price for e in eligible) >= coupon.threshold:
            return coupon.discount
        return 0.0
    if coupon.kind == "fixed":
        if coupon.applies_to is None or eligible:
            return coupon.discount
        return 0.0
    if coupon.kind == "percent":
        base = sum(e.price for e in eligible)
        d = base * (1.0 - coupon.discount)
        if coupon.max_discount and d > coupon.max_discount:
            d = coupon.max_discount
        return d
    if coupon.kind == "free_delivery":
        # 实际配送费在 optimize 中处理，这里返回 0，由调用方累加
        return 0.0
    return 0.0


def _is_order_level(coupon: Coupon) -> bool:
    """判断是否为"全单通用型订单级券"。

    现实约束：满减 / 折扣 / 立减 且 applies_to 为 None（作用于整单）的券，
    在麦当劳一次下单中通常只能使用一张；类目限定券(applies_to 非空)与免配送费券
    可与一张订单级券叠加。该规则通过以下校验实现。
    """
    if coupon.kind == "free_delivery":
        return False
    return coupon.applies_to is None


def _is_valid_subset(subset: List[Coupon], items: List[Item], delivery_fee: float) -> bool:
    """校验子集是否满足门槛、互斥与订单级券数量约束。"""
    seen_groups: set = set()
    order_level_count = 0
    for c in subset:
        grp = _effective_group(c)
        if grp is not None:
            if grp in seen_groups:
                return False  # 同组互斥冲突
            seen_groups.add(grp)
        if _is_order_level(c):
            order_level_count += 1
            if order_level_count > 1:
                return False  # 全单通用型订单级券至多一张
        # 门槛校验
        if c.kind == "threshold":
            eligible = [i for i in items if c.applies_to is None or i.category == c.applies_to]
            if sum(e.price for e in eligible) < c.threshold:
                return False
        if c.kind == "fixed" and c.applies_to is not None:
            eligible = [i for i in items if i.category == c.applies_to]
            if not eligible:
                return False
    return True


def optimize_coupons(
    items: List[Item],
    coupons: List[Coupon],
    delivery_fee: float = 0.0,
) -> dict:
    """枚举所有券组合，返回最低总价方案。

    返回结构：
    {
        "original_total": float,        # 未用券总价
        "best_total": float,            # 最优总价
        "best_coupons": List[str],      # 选用券 id（保持输入顺序）
        "saved": float,                 # 节省金额
        "breakdown": List[dict],        # 每张选用券的优惠明细
    }
    """
    original_total = total_price(items, delivery_fee)
    best_total = original_total
    best_subset: List[Coupon] = []

    n = len(coupons)
    # 暴力枚举 2^n 个子集（候选券通常为个位数，性能充足）
    for r in range(0, n + 1):
        for subset in combinations(coupons, r):
            subset_list = list(subset)
            if not _is_valid_subset(subset_list, items, delivery_fee):
                continue
            discount = 0.0
            has_free_delivery = False
            for c in subset_list:
                if c.kind == "free_delivery":
                    has_free_delivery = True
                    continue
                discount += _coupon_discount(c, items)
            if has_free_delivery:
                discount += delivery_fee
            # 优惠不得超过应付总额
            payable = max(0.0, original_total - discount)
            if payable < best_total - 1e-9:
                best_total = payable
                best_subset = subset_list

    # 构造明细（按输入顺序输出 id）
    coupon_order = {c.id: c for c in coupons}
    breakdown = []
    saved = round(original_total - best_total, 2)
    for cid in [c.id for c in coupons if c in best_subset]:
        c = coupon_order[cid]
        amt = delivery_fee if c.kind == "free_delivery" else _coupon_discount(c, items)
        breakdown.append({"id": cid, "kind": c.kind, "discount": round(amt, 2)})

    return {
        "original_total": round(original_total, 2),
        "best_total": round(best_total, 2),
        "best_coupons": [c.id for c in best_subset],
        "saved": saved,
        "breakdown": breakdown,
    }


if __name__ == "__main__":
    # 演示：一个典型点餐场景
    demo_items = [
        Item("巨无霸", 25.0, "main"),
        Item("麦香鸡", 18.0, "main"),
        Item("薯条", 12.0, "side"),
        Item("可乐", 10.0, "drink"),
    ]
    demo_coupons = [
        Coupon("full60", "threshold", discount=12.0, threshold=60.0),
        Coupon("side5", "fixed", discount=5.0, applies_to="side"),
        Coupon("vip9", "percent", discount=0.9),
    ]
    res = optimize_coupons(demo_items, demo_coupons, delivery_fee=6.0)
    print("原始总价:", res["original_total"])
    print("最优总价:", res["best_total"])
    print("选用券:", res["best_coupons"])
    print("节省:", res["saved"])
    print("明细:", res["breakdown"])
