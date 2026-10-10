"""
麦麦省钱助手 - 优惠券最优组合优化器

纯函数模块，不依赖任何外部服务，可独立测试与复用。
输入：购物项列表 + 候选优惠券列表 + 配送费
输出：在满足门槛与互斥约束下，使"商品+配送-优惠"总价最低的券组合。

设计目标：
- 支持麦当劳常见券类型：满减(threshold)、折扣(percent)、立减(fixed)、免配送费(free_delivery)
- 支持类目限制(applies_to)与互斥组(stack_group)
- 小券池：暴力枚举所有子集 + 约束校验，保证全局最优
- 大券池：先剔 0 优惠券，再用**分支限界**（乐观上界剪枝）求得与暴力枚举同解的结果，
  避免 2^n 组合爆炸（见 `optimize_coupons(strategy=...)` 与 `_optimal_subset_bnb`）

Author: 麦麦省钱助手参赛项目
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations, count
import heapq
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


def _coupon_ideal_discount(coupon: Coupon, items: List[Item], delivery_fee: float) -> float:
    """单张券的「乐观优惠上界」（分支限界剪枝用）。

    刻意放宽门槛/前置条件，取该券可能达到的最大优惠，构成合法**上界**。
    上界只可高估、不可低估，否则会误剪最优解（剪枝的正确性前提）。
    """
    if coupon.kind == "free_delivery":
        return delivery_fee
    if coupon.kind in ("threshold", "fixed"):
        return coupon.discount
    if coupon.kind == "percent":
        return _coupon_discount(coupon, items)
    return 0.0


def _take_discount(coupon: Coupon, items: List[Item], delivery_fee: float) -> float:
    """券被选中后计入的实际优惠（免配送费按配送费计）。"""
    if coupon.kind == "free_delivery":
        return delivery_fee
    return _coupon_discount(coupon, items)


def _can_take(
    coupon: Coupon, items: List[Item], used_groups: frozenset, order_level_count: int
) -> bool:
    """在已选状态 (used_groups, order_level_count) 上，判断能否再选该券。

    与 `_is_valid_subset` 的约束一一对应且**与选择顺序无关**：
    同组互斥 / 订单级券至多一张 / 满减门槛 / 立减需有适用商品。
    """
    grp = _effective_group(coupon)
    if grp is not None and grp in used_groups:
        return False
    if _is_order_level(coupon) and order_level_count >= 1:
        return False
    if coupon.kind == "threshold":
        eligible = _eligible_items(coupon, items)
        if sum(e.price for e in eligible) < coupon.threshold:
            return False
    if coupon.kind == "fixed":
        if not _eligible_items(coupon, items):
            return False
    return True


def _prune_zero_value(
    coupons: List[Coupon], items: List[Item], delivery_fee: float
) -> List[Coupon]:
    """剔除单券实际优惠为 0 的券（安全剪枝）。

    各券优惠相互独立且可加：0 优惠券无论是否入选都不改变总价，却会参与
    互斥/门槛判定，因此求解前剔除不损失最优解（也不会误剪）。
    """
    return [c for c in coupons if _take_discount(c, items, delivery_fee) > 0]


def _optimal_subset_bnb(
    items: List[Item], coupons: List[Coupon], delivery_fee: float
) -> "tuple[float, List[Coupon], dict]":
    """分支限界求「优惠总额最大（即应付最低）」的券子集。

    返回 (best_total, best_subset, stats)。保证与暴力枚举**同解**，但在券数
    较大时通过「乐观上界剪枝 + 按上界降序分支」大幅压缩搜索节点。

    剪枝条件：当前优惠 + 剩余券乐观优惠上界 仍追不平已得最优 → 该分支不可能
    更优，直接剪掉（`optimistic >= best_total - eps`）。
    """
    original = total_price(items, delivery_fee)
    n = len(coupons)
    ideals = [_coupon_ideal_discount(c, items, delivery_fee) for c in coupons]
    # 按乐观优惠降序：好解更早出现 → 上界更紧 → 剪枝更狠
    order = sorted(range(n), key=lambda i: ideals[i], reverse=True)
    # suffix[k] = 排序后第 k..n-1 张券的乐观优惠之和（上界）
    suffix = [0.0] * (n + 1)
    for k in range(n - 1, -1, -1):
        suffix[k] = suffix[k + 1] + ideals[order[k]]

    best_total = original
    best_subset: List[Coupon] = []
    stats = {"nodes": 0, "pruned": 0}
    eps = 1e-9

    def dfs(idx: int, discount: float, chosen: List[Coupon],
            used_groups: frozenset, ol_count: int, fd_used: bool) -> None:
        nonlocal best_total, best_subset
        stats["nodes"] += 1
        # 乐观下界：剩余券全部入选也追不平当前最优 → 剪枝
        optimistic = max(0.0, original - (discount + suffix[idx]))
        if optimistic >= best_total - eps:
            stats["pruned"] += 1
            return
        if idx == n:
            # 走到叶子且通过剪枝检查，说明严格优于当前最优
            best_total = max(0.0, original - discount)
            best_subset = list(chosen)
            return
        c = coupons[order[idx]]
        # 分支 1：不选该券
        dfs(idx + 1, discount, chosen, used_groups, ol_count, fd_used)
        # 分支 2：选该券（若约束允许）
        if _can_take(c, items, used_groups, ol_count):
            grp = _effective_group(c)
            next_groups = used_groups | {grp} if grp is not None else used_groups
            next_ol = ol_count + (1 if _is_order_level(c) else 0)
            add = _take_discount(c, items, delivery_fee)
            next_fd = fd_used
            if c.kind == "free_delivery":
                # 与暴力枚举同语义：免配送费最多减免一次（避免重复减配送费）
                if fd_used:
                    add = 0.0
                next_fd = True
            chosen.append(c)
            dfs(idx + 1, discount + add, chosen, next_groups, next_ol, next_fd)
            chosen.pop()

    dfs(0, 0.0, [], frozenset(), 0, False)
    return best_total, best_subset, stats


def optimize_coupons(
    items: List[Item],
    coupons: List[Coupon],
    delivery_fee: float = 0.0,
    *,
    strategy: str = "auto",
    brute_force_limit: int = 16,
) -> dict:
    """求最低总价方案（支持暴力枚举 / 分支限界两种策略）。

    strategy:
      - "auto"（默认）：券数 <= `brute_force_limit` 走暴力枚举；超过则先做
        0 优惠券剪枝，再走分支限界（与暴力枚举同解但可扩展到大券池）。
      - "bruteforce"：强制暴力枚举 2^n（作为正确性基准）。
      - "bnb"：强制分支限界。

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
    n = len(coupons)
    use_bnb = strategy == "bnb" or (strategy == "auto" and n > brute_force_limit)

    if use_bnb:
        pruned = _prune_zero_value(coupons, items, delivery_fee)
        best_total, best_subset, _stats = _optimal_subset_bnb(items, pruned, delivery_fee)
    else:
        best_total = original_total
        best_subset: List[Coupon] = []
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
    ordered_subset = [c for c in coupons if c in best_subset]
    breakdown = []
    for c in ordered_subset:
        amt = delivery_fee if c.kind == "free_delivery" else _coupon_discount(c, items)
        breakdown.append({"id": c.id, "kind": c.kind, "discount": round(amt, 2)})

    return {
        "original_total": round(original_total, 2),
        "best_total": round(best_total, 2),
        "best_coupons": [c.id for c in ordered_subset],
        "saved": round(original_total - best_total, 2),
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
def _rank_candidates_bruteforce(
    items: List[Item], coupons: List[Coupon], delivery_fee: float, top_k: int
) -> List[dict]:
    """暴力枚举全部合法子集，按本地估计节省降序取前 K（正确性基准）。"""
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


def _rank_candidates_bnb(
    items: List[Item], coupons: List[Coupon], delivery_fee: float, top_k: int
) -> List[dict]:
    """Top-K 分支限界：维护大小为 K 的候选**最小堆**，用上界剪掉进不了 Top-K 的分支。

    与 `_optimal_subset_bnb` 同一套上界；区别在于剪枝阈值是「当前第 K 名节省额」
    而非「当前最优」，因此这里求的是节省额最高的 K 个组合。
    先剔除 0 优惠券（不影响任何候选的节省额，只去冗余）。
    """
    original = total_price(items, delivery_fee)
    coupons = _prune_zero_value(coupons, items, delivery_fee)
    n = len(coupons)
    ideals = [_coupon_ideal_discount(c, items, delivery_fee) for c in coupons]
    order = sorted(range(n), key=lambda i: ideals[i], reverse=True)
    suffix = [0.0] * (n + 1)
    for k in range(n - 1, -1, -1):
        suffix[k] = suffix[k + 1] + ideals[order[k]]

    heap: List[Tuple[float, int, List[Coupon]]] = []  # (saved, seq, subset) 最小堆
    seq = count()
    eps = 1e-9

    def dfs(idx: int, discount: float, chosen: List[Coupon],
            used_groups: frozenset, ol_count: int, fd_used: bool) -> None:
        # 乐观上界：剩余券全选也进不了 Top-K（堆已满且上界 <= 第 K 名）→ 剪枝
        if len(heap) >= top_k and (discount + suffix[idx]) <= heap[0][0] + eps:
            return
        if idx == n:
            saved = min(original, discount)
            item = (saved, next(seq), list(chosen))
            if len(heap) < top_k:
                heapq.heappush(heap, item)
            elif saved > heap[0][0] + eps:
                heapq.heapreplace(heap, item)
            return
        c = coupons[order[idx]]
        # 分支 1：不选
        dfs(idx + 1, discount, chosen, used_groups, ol_count, fd_used)
        # 分支 2：选（若约束允许）
        if _can_take(c, items, used_groups, ol_count):
            grp = _effective_group(c)
            next_groups = used_groups | {grp} if grp is not None else used_groups
            next_ol = ol_count + (1 if _is_order_level(c) else 0)
            add = _take_discount(c, items, delivery_fee)
            next_fd = fd_used
            if c.kind == "free_delivery":
                if fd_used:
                    add = 0.0  # 免配送费最多减免一次（与暴力枚举同语义）
                next_fd = True
            chosen.append(c)
            dfs(idx + 1, discount + add, chosen, next_groups, next_ol, next_fd)
            chosen.pop()

    dfs(0, 0.0, [], frozenset(), 0, False)

    out: List[dict] = []
    for saved, _, sl in sorted(heap, key=lambda x: x[0], reverse=True):
        payable = max(0.0, original - saved)
        out.append(
            {
                "best_total": round(payable, 2),
                "best_coupons": [c.id for c in sl],
                "best_coupon_objs": sl,
                "saved": round(saved, 2),
            }
        )
    return out


def rank_candidates(
    items: List[Item],
    coupons: List[Coupon],
    delivery_fee: float = 0.0,
    top_k: int = 3,
    *,
    strategy: str = "auto",
    brute_force_limit: int = 16,
) -> List[dict]:
    """返回本地估计节省额最高的 Top-K 券组合候选。

    仅供 D 的两阶段校验做初步筛选：先本地排出 Top-K，
    再仅对这 K 个候选调用官方 calculate-price 取权威金额，避免 2^n 次网络调用。

    strategy:
      - "auto"（默认）：券数 <= `brute_force_limit` 走暴力枚举；超过则走
        Top-K 分支限界（与暴力枚举同值）。
      - "bruteforce"：强制暴力枚举（正确性基准）。
      - "bnb"：强制 Top-K 分支限界。

    返回每个候选含 best_coupon_objs（Coupon 对象列表），供核价回调使用。
    """
    use_bnb = strategy == "bnb" or (strategy == "auto" and len(coupons) > brute_force_limit)
    if use_bnb:
        return _rank_candidates_bnb(items, coupons, delivery_fee, top_k)
    return _rank_candidates_bruteforce(items, coupons, delivery_fee, top_k)


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
