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

from dataclasses import dataclass, field
from itertools import combinations
from typing import List, Optional, Tuple


@dataclass
class Item:
    """购物项。

    category:     类目限定券（如仅限小食/仅限主餐）的匹配依据
    product_code: 商品编码；产品级绑定券通过该字段精确匹配
    available:    是否可售（False 表示缺货/停售，优化时应提示并从可优惠范围剔除）
    """

    name: str
    price: float
    category: Optional[str] = None
    product_code: Optional[str] = None
    available: bool = True


@dataclass
class Coupon:
    """优惠券定义。

    kind:
        "threshold"   满减券：eligible 小计 >= threshold 时，立减 discount
        "percent"     折扣券：discount 为折扣率(0.85=85折)，优惠 = eligible小计*(1-rate)，受 max_discount 封顶
        "fixed"       立减券：直接减 discount（需存在 eligible 项）
        "free_delivery" 免配送费：减免全部配送费（同类券自动互斥，仅生效一张）
    applies_to:   限定类目；None 表示全单通用
    product_codes: 产品级绑定；非空时**仅**对 product_code 命中的商品生效（见 B 优化项）
    stack_group:  同组券互斥，仅可叠加一张；None 表示无限制
    expires_at:   失效日期（YYYY-MM-DD）；非空且早于 now 视为过期（见 E 优化项）
    valid_from:   生效日期（YYYY-MM-DD）；非空且晚于 now 视为"未到生效时间"（见 B 优化项）
    time_windows: 每日可用时段，元素为 ("HH:MM","HH:MM")；非空且当前时刻不在任一区间内视为时段不符
    """

    id: str
    kind: str
    discount: float = 0.0
    threshold: float = 0.0
    max_discount: float = 0.0
    applies_to: Optional[str] = None
    product_codes: List[str] = field(default_factory=list)
    stack_group: Optional[str] = None
    expires_at: Optional[str] = None
    valid_from: Optional[str] = None
    time_windows: List[Tuple[str, str]] = field(default_factory=list)
    coupon_code: Optional[str] = None  # 真实券码（calculate-price 传参用）
    coupon_id: Optional[str] = None    # 真实券 ID（calculate-price 传参用）


def total_price(items: List[Item], delivery_fee: float = 0.0) -> float:
    """计算未使用任何券时的原始总价（商品 + 配送）。"""
    return round(sum(i.price for i in items) + delivery_fee, 2)


def _effective_group(coupon: Coupon) -> Optional[str]:
    """免配送费券内部强制互斥，避免重复减免配送费。"""
    if coupon.kind == "free_delivery" and coupon.stack_group is None:
        return "__free_delivery__"
    return coupon.stack_group


def _eligible_items(coupon: Coupon, items: List[Item]) -> List[Item]:
    """计算某张券可作用的商品集合。

    优先级：产品级绑定（product_codes 非空）> 类目限定（applies_to）> 全单通用。
    不可售商品（available=False）不计入任何券的作用范围（见 E 优化项）。
    """
    sellable = [i for i in items if i.available]
    if coupon.product_codes:
        pc_set = set(coupon.product_codes)
        return [i for i in sellable if i.product_code in pc_set]
    if coupon.applies_to is not None:
        return [i for i in sellable if i.category == coupon.applies_to]
    return sellable


def _coupon_discount(coupon: Coupon, items: List[Item]) -> float:
    """计算单张券对当前购物项的优惠金额（已通过门槛/类目前置校验）。"""
    eligible = _eligible_items(coupon, items)
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
        # 门槛校验（按产品级/类目作用集合统计）
        if c.kind == "threshold":
            eligible = _eligible_items(c, items)
            if sum(e.price for e in eligible) < c.threshold:
                return False
        if c.kind == "fixed":
            if not _eligible_items(c, items):
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


# ---------------------------------------------------------------------------
# E. 时效与库存校验
# ---------------------------------------------------------------------------
def filter_valid_coupons(
    coupons: List[Coupon], now: Optional[str] = None
) -> dict:
    """按失效日期过滤券。

    now: 当前日期字符串 YYYY-MM-DD（缺省视为不过滤，全部有效）。
    返回：
        {
            "valid":   List[Coupon]  未过期且可参与优化
            "expired": List[Coupon]  已过期（被剔除）
            "warnings": List[str]    人类可读提示
        }
    """
    valid: List[Coupon] = []
    expired: List[Coupon] = []
    warnings: List[str] = []
    for c in coupons:
        if c.expires_at and now and c.expires_at < now:
            expired.append(c)
            warnings.append(f"券 {c.id} 已于 {c.expires_at} 过期，已忽略")
        else:
            valid.append(c)
    return {"valid": valid, "expired": expired, "warnings": warnings}


def _to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _within_any_window(now_hhmm: str, windows: List[Tuple[str, str]]) -> bool:
    """当前时刻是否落在任一每日时段窗内（支持跨零点，如 22:00-02:00）。"""
    if not windows:
        return True
    now_min = _to_minutes(now_hhmm)
    for start, end in windows:
        s, e = _to_minutes(start), _to_minutes(end)
        if s <= e:
            if s <= now_min <= e:
                return True
        else:  # 跨零点
            if now_min >= s or now_min <= e:
                return True
    return False


def filter_active_coupons(coupons: List[Coupon], now: Optional[str] = None) -> dict:
    """按「生效日期 + 失效日期 + 每日时段」三重维度过滤券（B 优化项）。

    now: "YYYY-MM-DD HH:MM"（缺省视为不过滤，全部有效）。
    真实 observe：我的券有效期形如
        "2026-10-10 00:00-2026-11-08 23:59 05:00-23:59"
    即「起-止日期」+「每日可用时段(05:00-23:59)」。很多券只在特定时段可用，
    只判过期会漏掉"未到生效时间"和"时段不符"两种情况。

    返回：
        {
            "valid":          List[Coupon]  # 当前可用
            "expired":        List[Coupon]  # 已过期
            "not_effective":  List[Coupon]  # 未到生效时间
            "outside_window": List[Coupon]  # 不在可用时段
            "warnings":       List[str]
        }
    """
    valid: List[Coupon] = []
    expired: List[Coupon] = []
    not_effective: List[Coupon] = []
    outside_window: List[Coupon] = []
    warnings: List[str] = []

    date = time = None
    if now:
        parts = now.strip().split()
        date = parts[0] if parts else None
        time = parts[1] if len(parts) > 1 else None

    for c in coupons:
        if c.expires_at and date and date > c.expires_at:
            expired.append(c)
            warnings.append(f"券 {c.id} 已于 {c.expires_at} 过期，已忽略")
            continue
        if c.valid_from and date and date < c.valid_from:
            not_effective.append(c)
            warnings.append(f"券 {c.id} 于 {c.valid_from} 起生效（当前未生效），已忽略")
            continue
        if c.time_windows and time and not _within_any_window(time, c.time_windows):
            outside_window.append(c)
            wins = "、".join(f"{s}-{e}" for s, e in c.time_windows)
            warnings.append(f"券 {c.id} 仅限时段 {wins} 使用（当前 {time}），已忽略")
            continue
        valid.append(c)

    return {
        "valid": valid,
        "expired": expired,
        "not_effective": not_effective,
        "outside_window": outside_window,
        "warnings": warnings,
    }


def check_item_availability(items: List[Item]) -> List[str]:
    """返回不可售商品的提示列表（available=False）。"""
    warnings: List[str] = []
    for i in items:
        if not i.available:
            warnings.append(f"商品「{i.name}」当前不可售，已不计入优惠计算")
    return warnings


# ---------------------------------------------------------------------------
# D. 两阶段校验 - 本地候选枚举（Top-K）
# ---------------------------------------------------------------------------
def rank_candidates(
    items: List[Item],
    coupons: List[Coupon],
    delivery_fee: float = 0.0,
    top_k: int = 3,
) -> List[dict]:
    """本地枚举所有合法券组合，按"本地估计节省"降序返回 Top-K 候选。

    仅供 D 的两阶段校验做初步筛选：先本地剪枝排出 Top-K，
    再仅对这 K 个候选调用官方 calculate-price 取权威金额，避免 2^n 次网络调用。
    返回每个候选含 best_coupon_objs（Coupon 对象列表），供核价回调使用。
    """
    original_total = total_price(items, delivery_fee)
    candidates: List[dict] = []
    n = len(coupons)
    for r in range(0, n + 1):
        for subset in combinations(coupons, r):
            sl = list(subset)
            if not _is_valid_subset(sl, items, delivery_fee):
                continue
            discount = 0.0
            has_fd = False
            for c in sl:
                if c.kind == "free_delivery":
                    has_fd = True
                    continue
                discount += _coupon_discount(c, items)
            if has_fd:
                discount += delivery_fee
            payable = max(0.0, original_total - discount)
            candidates.append(
                {
                    "best_total": round(payable, 2),
                    "best_coupons": [c.id for c in sl],
                    "best_coupon_objs": sl,
                    "saved": round(original_total - payable, 2),
                }
            )
    candidates.sort(key=lambda x: x["saved"], reverse=True)
    return candidates[:top_k]


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
