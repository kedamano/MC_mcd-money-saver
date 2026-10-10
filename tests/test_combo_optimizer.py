"""套餐/组合优化器 —— 契约测试（Task 23）。

真实依据（2026-10-10 实测，上海悦荟广场 1450104）：
  - 套餐是比券更猛的省钱渠道：龙焰鸡腿堡三件套 ¥26.90 vs 单点（可对上编码组件）
    ¥37.50，**至少省 ¥10.60**；而单张券最多省 ¥6.30。
  - 菜单独立商品编码与套餐内部组件编码不一致（可乐独立 9900008751 / 套餐内 3050），
    故「套餐 vs 单点」只累计能对上编码的组件 → 节省为**下界**。
"""

from __future__ import annotations

import itertools
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.combo_optimizer import (  # noqa: E402
    Combo,
    combo_from_detail,
    combo_saving,
    optimize_purchase,
    parse_meal_detail,
    plan_order_with_combos,
    rank_combo_deals,
)
from src.coupon_optimizer import Coupon  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _read_json(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


ROWS = _read_json("meal_combos.json")
DETAIL_SAMPLE = _read_json("meal_detail_sample.json")


def _price_map_from_rows(rows):
    pm = {}
    for r in rows:
        for c in r["components"]:
            pm[c["code"]] = c["unit_price"]
    return pm


def _combos_from_rows(rows):
    out = []
    for r in rows:
        comps = {}
        names = {}
        for c in r["components"]:
            comps[c["code"]] = comps.get(c["code"], 0) + c["qty"]
            names[c["code"]] = c["name"]
        out.append(Combo(r["code"], r["name"], r["combo_price"], comps, names))
    return out


PRICE_MAP = _price_map_from_rows(ROWS)
COMBOS = _combos_from_rows(ROWS)


# ------------------------------------------------------------- 解析真实返回
def test_parse_meal_detail_extracts_default_components():
    detail = DETAIL_SAMPLE["9900016075"]
    comps = parse_meal_detail(detail)
    codes = {c["code"]: c["qty"] for c in comps}
    assert codes == {"521953": 1, "4810": 1, "3050": 1}
    names = {c["code"]: c["name"] for c in comps}
    assert names["521953"] == "龙焰芝士棒鸡腿堡"
    assert names["4810"] == "中薯条"


def test_combo_from_detail_filters_unpriced_components():
    detail = DETAIL_SAMPLE["9900016075"]
    # price_map 只含薯条/汉堡，不含饮料 3050 → 构造的套餐组件应排除 3050
    cb = combo_from_detail(detail, price=29.9, price_map={"521953": 27.0, "4810": 13.5})
    assert cb.components == {"521953": 1, "4810": 1}
    assert "3050" not in cb.components
    assert cb.price == 29.9


def test_combo_from_detail_without_pricemap_keeps_all():
    cb = combo_from_detail(DETAIL_SAMPLE["9900016075"], price=29.9, price_map=None)
    assert set(cb.components) == {"521953", "4810", "3050"}


# ------------------------------------------------------------- 真实数据：节省下界
def test_real_combo_saving_lower_bound():
    """真实事实：龙焰鸡腿堡三件套至少省 ¥10.60（保守计）。"""
    cb = next(c for c in COMBOS if c.name == "龙焰鸡腿堡三件套")
    s = combo_saving(cb, PRICE_MAP)
    assert s["combo_price"] == 26.90
    assert s["matched_individual_sum"] == 37.50  # 龙焰鸡腿堡 24 + 中薯条 13.5
    assert s["saving"] == 10.60
    assert s["is_lower_bound"] is True


def test_missing_codes_are_reported_and_not_counted():
    """含无法定价的组件（饮料 3050）时，它以 missing_codes 报出且不计入单点合计。"""
    cb = Combo("9900016073", "龙焰鸡腿堡三件套", 26.90,
               {"521952": 1, "4810": 1, "3050": 1})
    s = combo_saving(cb, PRICE_MAP)  # PRICE_MAP 无 3050
    assert "3050" in s["missing_codes"]
    assert s["matched_individual_sum"] == 37.50
    assert s["saving"] == 10.60


def test_rank_combo_deals_top_is_10_60():
    deals = rank_combo_deals(COMBOS, PRICE_MAP)
    assert deals, "真实数据中应存在更划算的套餐"
    assert deals[0]["saving"] == 10.60
    # 全部严格降序且都为正
    sav = [d["saving"] for d in deals]
    assert sav == sorted(sav, reverse=True)
    assert all(x > 0 for x in sav)


def test_rank_top_k_limit():
    assert len(rank_combo_deals(COMBOS, PRICE_MAP, top_k=3)) == 3


# ------------------------------------------------------------- optimize_purchase
def test_optimize_purchase_picks_cheaper_combo():
    """想要 1 个龙焰鸡腿堡（单点 ¥24）；有「三件套 ¥26.9」含它+薯条。
    套餐比单点贵 → 不应买套餐。"""
    cb = Combo("c1", "龙焰鸡腿堡三件套", 26.90, {"521952": 1, "4810": 1})
    r = optimize_purchase({"521952": 1}, PRICE_MAP, [cb])
    assert r["best_total"] == 24.0
    assert r["combos_bought"] == []
    assert r["saved"] == 0.0


def test_optimize_purchase_prefers_combo_when_cheaper():
    """想要「龙焰鸡腿堡 + 薯条」单点合计 ¥37.5；三件套 ¥26.9 更省 → 买套餐。"""
    cb = Combo("c1", "龙焰鸡腿堡三件套", 26.90, {"521952": 1, "4810": 1})
    r = optimize_purchase({"521952": 1, "4810": 1}, PRICE_MAP, [cb])
    assert r["baseline_total"] == 37.5
    assert r["best_total"] == 26.90
    assert r["saved"] == 10.60
    assert len(r["combos_bought"]) == 1
    assert r["singles"] == []


def test_optimize_purchase_allows_over_provision():
    """套餐超额提供（含没点的薯条）但更便宜时，仍应被选。"""
    cb = Combo("c1", "三件套", 26.90, {"521952": 1, "4810": 1})
    r = optimize_purchase({"521952": 1}, PRICE_MAP, [cb])
    # 单点 24 < 26.9 → 不买套餐
    assert r["best_total"] == 24.0

    cb2 = Combo("c2", "特惠堡+薯条", 20.00, {"521952": 1, "4810": 1})
    r2 = optimize_purchase({"521952": 1}, PRICE_MAP, [cb2])
    assert r2["best_total"] == 20.00  # 只想要堡，但套餐 20 < 单点 24
    assert len(r2["combos_bought"]) == 1


def test_optimize_purchase_multi_needs_and_multi_combos():
    """两个堡需求：两个套餐各覆盖一个，应各买一个（券不跨单，这里同理不跨套餐）。"""
    c1 = Combo("c1", "A套餐", 20.0, {"521952": 1})
    c2 = Combo("c2", "B套餐", 20.0, {"1406": 1})
    r = optimize_purchase({"521952": 1, "1406": 1}, PRICE_MAP, [c1, c2])
    assert r["best_total"] == 40.0
    assert len(r["combos_bought"]) == 2


def test_optimize_purchase_ignores_irrelevant_combos():
    """与需求无交集的套餐不应被选中。"""
    c_rel = Combo("c1", "相关", 20.0, {"521952": 1})
    c_irr = Combo("c2", "无关", 1.0, {"1600": 1})  # 超便宜但用不上
    r = optimize_purchase({"521952": 1}, PRICE_MAP, [c_rel, c_irr])
    assert r["best_total"] == 20.0
    assert [c["code"] for c in r["combos_bought"]] == ["c1"]


def test_optimize_purchase_infeasible():
    c = Combo("c1", "无关套餐", 20.0, {"1600": 1})
    r = optimize_purchase({"999999": 1}, PRICE_MAP, [c])
    assert r["infeasible"] is True
    assert r["best_total"] is None
    assert r["baseline_total"] is None


def test_optimize_purchase_empty_wanted():
    r = optimize_purchase({}, PRICE_MAP, COMBOS)
    assert r["best_total"] == 0.0
    assert r["baseline_total"] == 0.0
    assert r["combos_bought"] == []


def test_optimize_purchase_search_cap_note():
    """相关套餐超过搜索上限时应给出提示（规模保护）。"""
    combos = [Combo(f"c{i}", "套餐", 10.0, {"521952": 1}) for i in range(5)]
    r = optimize_purchase({"521952": 1}, PRICE_MAP, combos, max_search_combos=2)
    assert any("搜索上限" in n for n in r["notes"])


def test_optimize_purchase_matches_bruteforce():
    """与「枚举全部套餐子集」的暴力基准同解（30 组随机）。"""
    rng = random.Random(20261010)
    codes = ["A", "B", "C", "D"]

    def brute(wanted, price_map, combos):
        relevant = [c for c in combos if set(c.components) & set(wanted)]
        best = None
        for r in range(0, len(relevant) + 1):
            for sub in itertools.combinations(relevant, r):
                provided = {}
                total = 0.0
                for cb in sub:
                    total += cb.price
                    for k, q in cb.components.items():
                        provided[k] = provided.get(k, 0) + q
                ok = True
                for k, q in wanted.items():
                    need = q - provided.get(k, 0)
                    if need > 0:
                        if k in price_map:
                            total += price_map[k] * need
                        else:
                            ok = False
                            break
                if ok and (best is None or total < best):
                    best = total
        return None if best is None else round(best, 2)

    for _ in range(30):
        price_map = {c: round(rng.uniform(5, 30), 1) for c in codes}
        nc = rng.randint(1, 4)
        combos = []
        for i in range(nc):
            comp = {c: rng.randint(1, 2) for c in rng.sample(codes, rng.randint(1, 3))}
            combos.append(Combo(f"c{i}", f"套餐{i}", round(rng.uniform(8, 40), 1), comp))
        wanted = {c: rng.randint(1, 2) for c in rng.sample(codes, rng.randint(1, 3))}
        got = optimize_purchase(wanted, price_map, combos)["best_total"]
        assert got == brute(wanted, price_map, combos), (wanted, price_map, combos)


# ------------------------------------------------------------- plan_order_with_combos
def test_plan_prefers_combo_when_combo_saving_beats_coupon():
    """套餐省 ¥10.60；「龙焰鸡腿堡 7 折」券只省 ¥7.20 → 应选套餐方案。"""
    cb = Combo("c1", "龙焰鸡腿堡三件套", 26.90, {"521952": 1, "4810": 1})
    coupon = Coupon("p7", "percent", discount=0.7, product_codes=["521952"])
    r = plan_order_with_combos(
        {"521952": 1, "4810": 1}, PRICE_MAP, [cb],
        name_map={"521952": "龙焰鸡腿堡", "4810": "薯条"},
        coupons=[coupon],
    )
    assert r["best_plan"] == "combo"
    assert r["singles_plan"]["total"] == 37.5 - 7.2  # 30.3
    assert r["best_total"] == 26.90
    assert r["best_total"] < r["singles_plan"]["total"]


def test_plan_prefers_singles_when_no_combo_helps():
    cb = Combo("c1", "贵套餐", 99.0, {"521952": 1, "4810": 1})
    r = plan_order_with_combos(
        {"521952": 1, "4810": 1}, PRICE_MAP, [cb],
        name_map={"521952": "龙焰鸡腿堡", "4810": "薯条"},
        coupons=[Coupon("f5", "fixed", discount=5.0)],
    )
    assert r["best_plan"] == "singles"
    assert r["best_total"] == 37.5 - 5.0


def test_plan_without_combos_is_pure_singles():
    r = plan_order_with_combos(
        {"521952": 1}, PRICE_MAP, [],
        name_map={"521952": "龙焰鸡腿堡"},
        coupons=[Coupon("f3", "fixed", discount=3.0)],
    )
    assert r["best_plan"] == "singles"
    assert r["best_total"] == 24.0 - 3.0
    assert r["combo_plan"]["combos_bought"] == []


def test_plan_counts_delivery_fee_once_on_combo_plan():
    cb = Combo("c1", "龙焰鸡腿堡三件套", 26.90, {"521952": 1, "4810": 1})
    r = plan_order_with_combos(
        {"521952": 1, "4810": 1}, PRICE_MAP, [cb],
        name_map={"521952": "龙焰鸡腿堡", "4810": "薯条"},
        delivery_fee=6.0,
    )
    # 套餐 26.9 + 配送费 6.0（一单一次）
    assert r["combo_plan"]["total"] == 32.90
