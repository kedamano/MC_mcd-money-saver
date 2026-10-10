"""
麦麦省钱助手 - 套餐/组合优化器（Task 23：把「买套餐」纳入省钱候选）

背景（2026-10-10 真机实测，上海悦荟广场 1450104）：
  - 「套餐」是比券更猛的省钱渠道：**龙焰鸡腿堡三件套 ¥26.90 vs 单点 ¥37.50**
    （即便只按能对上编码的组件保守计，也**至少省 ¥10.60**），而单张券最多省 ¥6.30。
  - 之前的优化器只枚举「商品 × 券」，**完全没把「买套餐」当作候选方案**
    → 白白漏掉更大的省钱空间。

真实约束（踩过的坑）：
  - `query-meals` 菜单里**独立商品编码**与套餐 `query-meal-detail` 里的
    **组件编码不一致**（例：可乐独立是 `9900008751`，套餐内是 `3050`），
    只有部分组件（如薯条 `4810`、汉堡）能按编码对上。
  - 因此本模块对「套餐 vs 单点」只累计**能按编码对上**的组件，得出**节省下界**
    （lower bound）：真实节省只会 ≥ 该值，绝不虚报。

本模块为纯函数（不联网）。`parse_meal_detail` 解析真实返回，
`optimize_purchase` 在「套餐 + 单点」之间求全局最低价。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.coupon_optimizer import Coupon, Item, optimize_coupons


@dataclass
class Combo:
    """一个套餐/组合商品：以固定组合价 `price` 提供一组组件。

    components:      product_code -> 数量（仅收录可独立定价的组件）
    component_names: product_code -> 展示名（可选）
    """

    code: str
    name: str
    price: float
    components: Dict[str, int] = field(default_factory=dict)
    component_names: Dict[str, str] = field(default_factory=dict)


def parse_meal_detail(detail: Dict) -> List[Dict]:
    """从 `query-meal-detail` 返回中解析**默认选中**的组件。

    真实结构：`rounds[].choices[]`，每轮 `quantity>0` 的那个 choice 即默认选中项
    （官网用 quantity=0 表示未选、isDefault=1 标记默认）。
    返回 [{"code","name","qty","diff_price"}...]。
    """
    comps: List[Dict] = []
    for r in detail.get("rounds") or []:
        for ch in r.get("choices") or []:
            q = ch.get("quantity")
            if not isinstance(q, (int, float)) or q <= 0:
                continue
            comps.append(
                {
                    "code": ch.get("code"),
                    "name": ch.get("name"),
                    "qty": int(q),
                    "diff_price": ch.get("diffPrice"),
                }
            )
    return comps


def combo_from_detail(detail: Dict, price: float, price_map: Optional[Dict[str, float]] = None) -> Combo:
    """由 `query-meal-detail` 返回构造 Combo。

    price_map 非空时**仅收录能在该表中按编码定价的组件**（其余组件无法独立比价，
    计入会虚增单点合计；排除后得到的是**节省下界**）。
    """
    comps = parse_meal_detail(detail)
    codes: Dict[str, int] = {}
    names: Dict[str, str] = {}
    for c in comps:
        code = c["code"]
        if price_map is not None and code not in price_map:
            continue
        codes[code] = codes.get(code, 0) + c["qty"]
        if c.get("name"):
            names[code] = c["name"]
    return Combo(
        code=str(detail.get("code", "")),
        name=detail.get("name") or "",
        price=float(price),
        components=codes,
        component_names=names,
    )


def combo_saving(combo: Combo, price_map: Dict[str, float]) -> Dict:
    """计算单个套餐相对「组件单点」的节省（保守下界）。

    只累计 price_map 中可按编码定价的组件。`missing_codes` 为套餐内含但无法独立
    定价的组件（如饮料的套餐内编码与菜单编码不一致）——它们**不计入**单点合计，
    因此 `saving` 是**下界**：真实节省 ≥ saving。
    """
    matched_sum = 0.0
    matched_codes: List[str] = []
    missing_codes: List[str] = []
    for code, qty in combo.components.items():
        if code in price_map:
            matched_sum += float(price_map[code]) * qty
            matched_codes.append(code)
        else:
            missing_codes.append(code)
    saving = round(matched_sum - combo.price, 2)
    pct = (saving / matched_sum) if matched_sum > 0 else 0.0
    return {
        "code": combo.code,
        "name": combo.name,
        "combo_price": round(combo.price, 2),
        "matched_individual_sum": round(matched_sum, 2),
        "saving": saving,
        "saving_pct": round(pct, 4),
        "matched_codes": matched_codes,
        "missing_codes": missing_codes,
        "is_lower_bound": True,  # 单点合计只算能对上编码的组件 → 节省为下界
    }


def rank_combo_deals(
    combos: List[Combo], price_map: Dict[str, float], top_k: Optional[int] = None
) -> List[Dict]:
    """按节省降序返回「真正更划算」（saving>0）的套餐列表。"""
    deals = []
    for cb in combos:
        if not cb.components:  # 无可定价组件，无法比较
            continue
        s = combo_saving(cb, price_map)
        if s["saving"] > 0:
            deals.append(s)
    deals.sort(key=lambda x: x["saving"], reverse=True)
    return deals if top_k is None else deals[:top_k]


def _plan_cost(
    selected: List[Combo], wanted: Dict[str, int], price_map: Dict[str, float]
):
    """给定所选套餐集合，计算总价与仍需单点的商品。不可行返回 None。"""
    provided: Dict[str, int] = {}
    total = 0.0
    for cb in selected:
        total += cb.price
        for code, q in cb.components.items():
            provided[code] = provided.get(code, 0) + q
    singles: Dict[str, int] = {}
    for code, q in wanted.items():
        need = q - provided.get(code, 0)
        if need > 0:
            if code not in price_map:
                return None  # 既无套餐覆盖、又无法单点购买 → 不可行
            singles[code] = need
            total += float(price_map[code]) * need
    return round(total, 2), singles


def optimize_purchase(
    wanted: Dict[str, int],
    price_map: Dict[str, float],
    combos: List[Combo],
    *,
    max_search_combos: int = 16,
) -> Dict:
    """在「买套餐 / 单点」之间求全局最低价。

    wanted:    {product_code: 数量} —— 用户想吃到的东西
    price_map: {product_code: 单点价}
    combos:    可用套餐列表

    语义：套餐可**超额提供**（含用户没点的东西，视作赠品）；未被套餐覆盖的
    需求按单点价补齐。目标：覆盖全部需求的前提下总价最低。
    仅「与需求有交集」的套餐才可能省钱（无交集套餐只会徒增成本），故先过滤，
    再对小规模子集做精确搜索（DFS + 组合成本剪枝）。

    返回：
        {
          "baseline_total": 全单点总价（若有需求无法单点购买则为 None）,
          "best_total":     最低总价,
          "saved":          相对全单点的节省,
          "combos_bought":  [{"code","name","price","components"}...],
          "singles":        [{"code","qty","unit_price","line_total"}...],
          "infeasible":     bool（无套餐且无法单点补齐）,
          "notes":          [str...],
        }
    """
    notes: List[str] = []
    # 全单点基线
    baseline = 0.0
    baseline_ok = True
    for code, q in wanted.items():
        if code in price_map:
            baseline += float(price_map[code]) * q
        else:
            baseline_ok = False
            break
    baseline_total = round(baseline, 2) if baseline_ok else None

    # 仅保留与需求有交集的套餐
    relevant = [cb for cb in combos if set(cb.components) & set(wanted)]
    if len(relevant) > max_search_combos:
        # 规模保护：按「可命中的需求组件数」降序取前 N，避免子集爆炸
        relevant.sort(
            key=lambda cb: sum(1 for c in cb.components if c in wanted), reverse=True
        )
        notes.append(
            f"相关套餐 {len(relevant)} 个超过搜索上限 {max_search_combos}，"
            f"仅对前 {max_search_combos} 个做精确求解"
        )
        relevant = relevant[:max_search_combos]

    # 初始以「无穷大」起步，由 dfs 在根节点（不选任何套餐=纯单点）处填入基线方案，
    # 从而保证 best["singles"] 始终与所选方案一致（否则基线方案会丢失剩余单点）。
    best = {"total": float("inf"), "selected": [], "singles": {}}
    infeasible_seen = False

    def dfs(i: int, selected: List[Combo], combo_cost: float):
        nonlocal infeasible_seen
        if combo_cost >= best["total"] - 1e-9:
            return  # 组合成本已不低于当前最优 → 追加套餐只会更贵，剪枝
        plan = _plan_cost(selected, wanted, price_map)
        if plan is None:
            infeasible_seen = True
        else:
            total, singles = plan
            if total < best["total"] - 1e-9:
                best["total"] = total
                best["selected"] = list(selected)
                best["singles"] = singles
        for j in range(i, len(relevant)):
            cb = relevant[j]
            selected.append(cb)
            dfs(j + 1, selected, combo_cost + cb.price)
            selected.pop()

    dfs(0, [], 0.0)

    infeasible = best["total"] == float("inf")
    if infeasible:
        notes.append("需求中的商品既无套餐覆盖、也无法单点购买，无法给出可行方案")

    singles_out = [
        {
            "code": code,
            "qty": q,
            "unit_price": round(float(price_map[code]), 2),
            "line_total": round(float(price_map[code]) * q, 2),
        }
        for code, q in sorted(best["singles"].items())
    ]
    best_total = None if infeasible else round(best["total"], 2)
    saved = (
        round(baseline_total - best_total, 2)
        if (baseline_total is not None and best_total is not None)
        else 0.0
    )
    return {
        "baseline_total": baseline_total,
        "best_total": best_total,
        "saved": saved,
        "combos_bought": [
            {
                "code": cb.code,
                "name": cb.name,
                "price": round(cb.price, 2),
                "components": dict(cb.components),
            }
            for cb in best["selected"]
        ],
        "singles": singles_out,
        "infeasible": infeasible,
        "notes": notes,
    }


def plan_order_with_combos(
    wanted: Dict[str, int],
    price_map: Dict[str, float],
    combos: List[Combo],
    *,
    name_map: Optional[Dict[str, str]] = None,
    coupons: Optional[List[Coupon]] = None,
    delivery_fee: float = 0.0,
    max_coupons_per_order: Optional[int] = 1,
) -> Dict:
    """把「套餐」与「优惠券」串起来的最终决策：二选一取更省。

    方案 A（纯单点 + 券）：全车按单点，套用最优券组合。
    方案 B（套餐 + 剩余单点 + 券）：先买最省套餐，剩余单点再套用最优券组合。
    真实约束：**套餐是固定组合价，不再叠加券**（故套餐金额不参与券优化）。

    返回：
        {
          "best_plan": "combo" / "singles",
          "best_total": float,
          "saved_vs_singles": float,
          "singles_plan": {...},
          "combo_plan": {...},
        }
    """
    name_map = name_map or {}
    coupons = coupons or []

    def _items(mapping: Dict[str, int]) -> List[Item]:
        out = []
        for code, q in mapping.items():
            for _ in range(q):
                out.append(Item(name=name_map.get(code, code), price=float(price_map[code]), product_code=code))
        return out

    # 方案 A：全单点 + 券
    all_items = _items(wanted)
    singles_res = optimize_coupons(
        all_items, coupons, delivery_fee, max_coupons_per_order=max_coupons_per_order
    )

    # 方案 B：套餐 + 剩余单点 + 券
    combo_res = optimize_purchase(wanted, price_map, combos)
    combo_goods_cost = sum(c["price"] for c in combo_res["combos_bought"])
    remaining = {s["code"]: s["qty"] for s in combo_res["singles"]}
    if remaining:
        rem_res = optimize_coupons(
            _items(remaining), coupons, delivery_fee, max_coupons_per_order=max_coupons_per_order
        )
        combo_total = round(combo_goods_cost + rem_res["best_total"], 2)
        combo_coupons = rem_res["best_coupons"]
    else:
        combo_total = round(combo_goods_cost + delivery_fee, 2)
        combo_coupons = []

    best_plan = "combo" if combo_total < singles_res["best_total"] - 1e-9 else "singles"
    best_total = combo_total if best_plan == "combo" else singles_res["best_total"]

    return {
        "best_plan": best_plan,
        "best_total": round(best_total, 2),
        "saved_vs_singles": round(singles_res["best_total"] - best_total, 2),
        "singles_plan": {
            "total": singles_res["best_total"],
            "coupons": singles_res["best_coupons"],
            "original_total": singles_res["original_total"],
        },
        "combo_plan": {
            "total": combo_total,
            "combos_bought": combo_res["combos_bought"],
            "singles": combo_res["singles"],
            "coupons": combo_coupons,
        },
    }


if __name__ == "__main__":
    pm = {"521952": 24.0, "4810": 13.5, "3050": 9.5}
    cb = Combo("9900016073", "龙焰鸡腿堡三件套", 26.90, {"521952": 1, "4810": 1, "3050": 1})
    print("套餐节省:", combo_saving(cb, pm))
    print("最优购买:", optimize_purchase({"521952": 1}, pm, [cb]))
