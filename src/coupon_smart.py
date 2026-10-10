"""
麦麦省钱助手 - 智能决策增强模块（优化项 C / D）

C. 凑单建议（suggest_threshold_addons）
   对当前未达门槛的满减券，从真实菜单目录中反推「最小代价加购组合」，
   使你刚好跨过门槛并净省钱；净收益为负则不推荐（不诱导盲目凑单）。

D. 两阶段校验（two_stage_optimize + rank_candidates）
   本地枚举先粗排 Top-K 候选，再仅对这 K 个候选调用官方 calculate-price
   取权威金额，避免 2^n 次网络调用（见 SPEC §3.6 限流约束）。

本模块为纯函数（不联网），真实核价回调由调用方注入（见 mcd_client）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import combinations
from typing import Callable, List, Optional

from src.coupon_optimizer import (
    Coupon,
    Item,
    _eligible_items,
    filter_valid_coupons,
    rank_candidates,
    total_price,
)


@dataclass
class CatalogItem:
    """目录中可加购的商品（用于凑单建议）。"""

    code: str
    name: str
    price: float


def load_catalog(path: str) -> List[CatalogItem]:
    """从 fixtures 目录 JSON 加载商品目录。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [
        CatalogItem(str(i["code"]), i["name"], float(i["price"]))
        for i in data.get("items", [])
    ]


# ---------------------------------------------------------------------------
# C. 凑单建议
# ---------------------------------------------------------------------------
def _min_cost_to_reach(candidates: List[CatalogItem], gap: float, max_items: int) -> Optional[List[CatalogItem]]:
    """从 candidates 中挑选 size ∈ [1, max_items] 的子集，使其总价 >= gap 且总价最小。

    返回最优子集；若无法达到 gap（候选总和不敷）返回 None。
    """
    if not candidates or gap <= 0:
        return []
    best: Optional[List[CatalogItem]] = None
    best_cost = float("inf")
    sorted_c = sorted(candidates, key=lambda x: x.price)
    for k in range(1, max_items + 1):
        for combo in combinations(sorted_c, k):
            s = sum(c.price for c in combo)
            if s >= gap - 1e-9 and s < best_cost:
                best_cost = s
                best = list(combo)
    return best


def suggest_threshold_addons(
    cart: List[Item],
    coupons: List[Coupon],
    catalog: List[CatalogItem],
    now: Optional[str] = None,
    max_items: int = 2,
    top_k: int = 3,
) -> List[dict]:
    """为未达门槛的满减券生成凑单建议。

    参数：
        cart:        当前购物车（Item 列表）
        coupons:     候选券（仅 threshold 类且未过期者参与）
        catalog:     可加购目录（CatalogItem 列表，建议传真实菜单目录）
        now:         当前日期 YYYY-MM-DD（用于过期过滤）
        max_items:   允许的最大加购件数（限制搜索空间，默认 2）
        top_k:       返回建议条数上限

    返回（按净收益降序）：
        [{
            "target_coupon": str,
            "gap": float,                 # 距门槛还差多少
            "add_items": [{code,name,price,quantity}],
            "added_cost": float,          # 加购总花费
            "coupon_discount": float,     # 券面额
            "net_saving": float,          # 券面额 - 加购花费（>0 才值得）
        }]
    """
    valid = filter_valid_coupons(coupons, now=now)["valid"]
    cart_codes = {i.product_code for i in cart if i.product_code}
    suggestions: List[dict] = []

    for c in valid:
        if c.kind != "threshold":
            continue
        # 该券可作用到的购物车商品（产品级绑定优先）
        eligible_cart = _eligible_items(c, cart)
        subtotal = sum(i.price for i in eligible_cart)
        gap = round(c.threshold - subtotal, 2)
        if gap <= 0:
            continue  # 已满足门槛，无需凑单

        # 可加购候选：目录中「对该券可作用」且「购物车尚未包含」的商品
        if c.product_codes:
            pc_set = set(c.product_codes)
            cand = [
                ci for ci in catalog
                if ci.code in pc_set and ci.code not in cart_codes
            ]
        else:
            cand = [ci for ci in catalog if ci.code not in cart_codes]

        best_combo = _min_cost_to_reach(cand, gap, max_items)
        if not best_combo:
            continue
        added_cost = round(sum(ci.price for ci in best_combo), 2)
        net = round(c.discount - added_cost, 2)
        if net <= 0:
            continue  # 加购代价超过券面额，不推荐

        # 合并同 code（凑单可能选两件同款）
        merged = {}
        for ci in best_combo:
            merged[ci.code] = merged.get(ci.code, {"code": ci.code, "name": ci.name, "price": ci.price, "quantity": 0})
            merged[ci.code]["quantity"] += 1
        suggestions.append(
            {
                "target_coupon": c.id,
                "gap": gap,
                "add_items": list(merged.values()),
                "added_cost": added_cost,
                "coupon_discount": c.discount,
                "net_saving": net,
            }
        )

    suggestions.sort(key=lambda x: x["net_saving"], reverse=True)
    return suggestions[:top_k]


# ---------------------------------------------------------------------------
# D. 两阶段校验
# ---------------------------------------------------------------------------
def two_stage_optimize(
    items: List[Item],
    coupons: List[Coupon],
    delivery_fee: float = 0.0,
    pricing_fn: Optional[Callable[[List[Coupon], List[Item]], float]] = None,
    top_k: int = 3,
) -> dict:
    """本地粗排 Top-K + 仅对 Top-K 调官方核价，返回权威最优方案。

    参数：
        pricing_fn: 官方核价回调，签名 (subset_coupons: List[Coupon], items) -> 权威总价(float)。
                    为 None 时退化为纯本地最优（不联网）。
        top_k:      进入官方核价阶段的候选数量上限。

    返回：
        {
            "original_total": float,
            "best_total": float,        # 权威核价（无回调时为本地估计）
            "best_coupons": List[str],
            "saved": float,
            "validated": bool,          # 是否经过官方核价
            "validated_count": int,     # 实际核价的候选数
        }
    """
    original_total = total_price(items, delivery_fee)
    candidates = rank_candidates(items, coupons, delivery_fee, top_k=top_k)

    if pricing_fn is None or not candidates:
        best = candidates[0] if candidates else {
            "best_total": round(original_total, 2),
            "best_coupons": [],
            "saved": 0.0,
        }
        return {
            "original_total": round(original_total, 2),
            "best_total": best["best_total"],
            "best_coupons": best["best_coupons"],
            "saved": best["saved"],
            "validated": False,
            "validated_count": 0,
        }

    best_total = float("inf")
    best_cand = candidates[0]
    validated_count = 0
    for cand in candidates:
        try:
            auth_total = pricing_fn(cand["best_coupon_objs"], items)
            validated_count += 1
        except Exception:
            # 单个候选核价失败不影响其他候选；退化为本地估计
            auth_total = cand["best_total"]
        if auth_total < best_total:
            best_total = auth_total
            best_cand = cand

    return {
        "original_total": round(original_total, 2),
        "best_total": round(best_total, 2),
        "best_coupons": best_cand["best_coupons"],
        "saved": round(original_total - best_total, 2),
        "validated": True,
        "validated_count": validated_count,
    }
