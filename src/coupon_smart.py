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
    filter_coupons_by_channel,
    filter_valid_coupons,
    optimize_coupons,
    rank_candidates,
    total_price,
)
from src.errors import CouponRejectedError


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
    allow_existing: bool = True,
) -> List[dict]:
    """为未达门槛的满减券生成凑单建议。

    参数：
        cart:           当前购物车（Item 列表）
        coupons:        候选券（仅 threshold 类且未过期者参与）
        catalog:        可加购目录（CatalogItem 列表，建议传真实菜单目录）
        now:            当前日期 YYYY-MM-DD（用于过期过滤）
        max_items:      允许的最大加购件数（限制搜索空间，默认 2）
        top_k:          返回建议条数上限
        allow_existing: 是否允许对**购物车已有商品加量**（默认 True）。
                        真实场景里「再点一份同款薯条」往往是最便宜的凑单路径，
                        旧实现无条件排除车内商品，会系统性漏掉这类建议。

    返回（按净收益降序）：
        [{
            "target_coupon": str,
            "gap": float,                 # 距门槛还差多少
            "add_items": [{code,name,price,quantity,is_existing}],
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

        # 可加购候选：目录中「对该券可作用」的商品。
        # allow_existing=True 时**允许对购物车已有商品加量**（如「再点一份同款薯条」）；
        # allow_existing=False 时保持旧行为（排除车内商品）。
        def _selectable(ci: CatalogItem) -> bool:
            return allow_existing or ci.code not in cart_codes

        if c.product_codes:
            pc_set = set(c.product_codes)
            cand = [ci for ci in catalog if ci.code in pc_set and _selectable(ci)]
        else:
            cand = [ci for ci in catalog if _selectable(ci)]

        best_combo = _min_cost_to_reach(cand, gap, max_items)
        if not best_combo:
            continue
        added_cost = round(sum(ci.price for ci in best_combo), 2)
        net = round(c.discount - added_cost, 2)
        if net <= 0:
            continue  # 加购代价超过券面额，不推荐

        # 合并同 code（凑单可能选两件同款）；is_existing 标注是否为「车内已有商品加量」
        merged = {}
        for ci in best_combo:
            m = merged.setdefault(
                ci.code,
                {
                    "code": ci.code,
                    "name": ci.name,
                    "price": ci.price,
                    "quantity": 0,
                    "is_existing": ci.code in cart_codes,
                },
            )
            m["quantity"] += 1
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
    max_coupons_per_order: Optional[int] = 1,
    order_channel: Optional[str] = None,
) -> dict:
    """本地粗排 Top-K + 仅对 Top-K 调官方核价，返回权威最优方案。

    参数：
        pricing_fn: 官方核价回调，签名 (subset_coupons: List[Coupon], items) -> 权威总价(float)。
                    为 None 时退化为纯本地最优（不联网）。
        top_k:      进入官方核价阶段的候选数量上限。
        max_coupons_per_order: 每单最大券数。**默认 1**：真实麦当劳 MCP 实测
                    每单仅支持一张券（传两张返回 code=600022「暂不支持多张券使用」），
                    故本地粗排也必须遵守，否则会排出官方必然拒绝的组合。
                    传 None 可关闭该限制。
        order_channel: 下单渠道；渠道不符的券在**进入核价前**即被排除。

    关于失败的两类区分（缺口 2 修复）：
        - 官方**业务拒绝**（`CouponRejectedError`，如 600012 渠道不符 / 600022 多券叠加）
          → 该候选**无效**，直接剔除，绝不降级（否则被拒方案会因估计更便宜而胜出）；
        - **网络/未知异常** → 降级为本地估计（单候选失败不影响其他候选）。

    返回：
        {
            "original_total": float,
            "best_total": float,        # 权威核价（无回调时为本地估计）
            "best_coupons": List[str],
            "saved": float,
            "validated": bool,          # 是否经过官方核价
            "validated_count": int,     # 实际核价成功数
            "rejected": int,            # 被官方拒绝的候选数
            "errored": int,             # 核价异常（降级）的候选数
            "all_rejected": bool,       # 是否所有带券候选都被拒（退化为不用券）
            "channel_excluded": List[str],
            "channel_warnings": List[str],
        }
    """
    original_total = total_price(items, delivery_fee)
    channel_result = filter_coupons_by_channel(coupons, order_channel)
    channel_excluded = [c.id for c in channel_result["excluded"]]
    channel_warnings = list(channel_result["warnings"])

    candidates = rank_candidates(
        items, channel_result["valid"], delivery_fee, top_k=top_k,
        max_coupons_per_order=max_coupons_per_order,
    )

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
            "rejected": 0,
            "errored": 0,
            "all_rejected": False,
            "channel_excluded": channel_excluded,
            "channel_warnings": channel_warnings,
        }

    best_total = float("inf")
    best_cand = None
    validated_count = 0
    rejected = 0
    errored = 0
    for cand in candidates:
        try:
            auth_total = pricing_fn(cand["best_coupon_objs"], items)
            validated_count += 1
        except CouponRejectedError:
            # 官方明确拒绝该券（渠道不符 600012 / 多券叠加 600022）→ 候选**无效**，剔除。
            # 必须与「网络异常」区别对待：否则被拒方案会因本地估计更便宜而胜出。
            rejected += 1
            continue
        except Exception:
            # 网络抖动 / 未知异常 → 该候选暂无法核价，退化为本地估计（不影响其他候选）
            errored += 1
            auth_total = cand["best_total"]
        if auth_total < best_total:
            best_total = auth_total
            best_cand = cand

    if best_cand is None:
        # 所有候选都因被拒而不可用 → 退化为「不使用优惠券」
        best_total = original_total
        best_coupons: List[str] = []
    else:
        best_coupons = best_cand["best_coupons"]

    all_rejected = rejected > 0 and not best_coupons

    return {
        "original_total": round(original_total, 2),
        "best_total": round(best_total, 2),
        "best_coupons": best_coupons,
        "saved": round(original_total - best_total, 2),
        "validated": True,
        "validated_count": validated_count,
        "rejected": rejected,
        "errored": errored,
        "all_rejected": all_rejected,
        "channel_excluded": channel_excluded,
        "channel_warnings": channel_warnings,
    }


def _build_addon_items(add_items: List[dict]) -> List[Item]:
    """把凑单条目展开为 Item 列表（按 quantity 重复）。"""
    out: List[Item] = []
    for ai in add_items or []:
        q = int(ai.get("quantity", 1) or 1)
        for _ in range(q):
            out.append(
                Item(
                    name=ai.get("name") or str(ai.get("code", "")),
                    price=float(ai.get("price", 0.0)),
                    product_code=ai.get("code"),
                )
            )
    return out


def optimize_with_addons(
    items: List[Item],
    coupons: List[Coupon],
    catalog: List[CatalogItem],
    delivery_fee: float = 0.0,
    *,
    now: Optional[str] = None,
    max_items: int = 2,
    order_channel: Optional[str] = None,
    max_coupons_per_order: Optional[int] = 1,
) -> dict:
    """把「凑单」纳入主流程：与「不凑单的最优方案」比较，只有真实更省才推荐。

    为什么必须放进主流程：`suggest_threshold_addons` 是孤立函数，不显式调用就不会
    触发；且它用「券面额 − 加购花费」近似，未考虑加购后可能触发**另一张**更优券。
    这里直接以「加购后重新求最优的到手价」为准，与基线**同口径**比较（加购花费已
    包含在新总价里，无需另行近似）。

    返回：
        {
          "baseline_total":   float,   # 不凑单时的最优到手价
          "best_total":       float,   # 最优（可能含凑单）
          "saved":            float,   # baseline - best
          "used_addons":      bool,
          "add_items":        [...],   # 采用的凑单条目（未采用为 []）
          "best_coupons":     [...],   # 最优方案用到的券 id
          "channel_excluded": [...],
          "channel_warnings": [...],
          "reason":           str,
        }
    """
    channel_result = filter_coupons_by_channel(coupons, order_channel)
    usable = channel_result["valid"]

    base = optimize_coupons(
        items, usable, delivery_fee,
        max_coupons_per_order=max_coupons_per_order, order_channel=order_channel,
    )
    baseline_total = base["best_total"]
    best = {
        "total": baseline_total,
        "add_items": [],
        "coupons": base["best_coupons"],
        "reason": "不凑单已是最优",
    }

    suggestions = suggest_threshold_addons(
        items, usable, catalog, now=now, max_items=max_items, top_k=8,
        allow_existing=True,
    )
    for s in suggestions:
        addon_items = _build_addon_items(s["add_items"])
        if not addon_items:
            continue
        plan = optimize_coupons(
            list(items) + addon_items, usable, delivery_fee,
            max_coupons_per_order=max_coupons_per_order, order_channel=order_channel,
        )
        if plan["best_total"] < best["total"] - 1e-9:
            best = {
                "total": plan["best_total"],
                "add_items": s["add_items"],
                "coupons": plan["best_coupons"],
                "reason": f"凑单「{s['target_coupon']}」后再用券更省",
            }

    used = bool(best["add_items"])
    return {
        "baseline_total": round(baseline_total, 2),
        "best_total": round(best["total"], 2),
        "saved": round(baseline_total - best["total"], 2),
        "used_addons": used,
        "add_items": best["add_items"] if used else [],
        "best_coupons": best["coupons"] if used else base["best_coupons"],
        "channel_excluded": [c.id for c in channel_result["excluded"]],
        "channel_warnings": list(channel_result["warnings"]),
        "reason": best["reason"],
    }
