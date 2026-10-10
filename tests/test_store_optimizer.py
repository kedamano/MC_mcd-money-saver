"""多店比价 + 距离权衡 —— 契约测试（Task 24）。

真实依据（2026-10-10 实测，上海南京东路商圈）：
  - 同城同品不同价：中薯条(4810) 多数门店 ¥13.50，上海食品一店(1450056) ¥14.50。
  - query-nearby-stores(searchType=2) 返回带 distance(米) 的门店列表。
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.store_optimizer import (  # noqa: E402
    StoreQuote,
    best_coupon_saving,
    collect_store_quotes,
    coupon_from_store_json,
    evaluate_quote,
    optimize_across_stores,
)

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _read_json(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


RAW = _read_json("store_quotes.json")


def _quotes_from_real():
    return [
        StoreQuote(
            store_code=str(r["store_code"]),
            store_name=r["store_name"],
            distance_m=float(r["distance_m"]),
            prices={c: v["price"] for c, v in r["prices"].items()},
            coupons=r["coupons"] if isinstance(r["coupons"], list) else [],
        )
        for r in RAW
    ]


# ------------------------------------------------------------- 真实数据：同品不同价
def test_real_same_item_different_price():
    """真实事实：薯条 4810 在食品一店 ¥14.50，其余门店 ¥13.50。"""
    prices = {r["store_code"]: r["prices"].get("4810", {}).get("price") for r in RAW}
    assert prices["1450056"] == 14.5
    assert sum(1 for v in prices.values() if v == 13.5) >= 3


def test_evaluate_quote_reflects_store_price():
    qs = {q.store_code: q for q in _quotes_from_real()}
    ev_a = evaluate_quote(qs["1450104"], {"4810": 1})
    ev_b = evaluate_quote(qs["1450056"], {"4810": 1})
    assert ev_a["payable"] == 13.5
    assert ev_b["payable"] == 14.5
    assert ev_a["feasible"] and ev_b["feasible"]


def test_optimize_across_stores_never_picks_pricier_store():
    """便宜店在更近处时，应选便宜店而非贵店。"""
    res = optimize_across_stores(_quotes_from_real(), {"4810": 1})
    assert res["best"]["payable"] == 13.5
    assert res["best"]["store_code"] != "1450056"
    # 排序升序 & 并列取近者
    payables = [e["payable"] for e in res["ranked"]]
    assert payables == sorted(payables)
    assert res["ranked"][0]["store_code"] == "1450104"  # 194m，13.5


def test_distance_filter_excludes_far_cheaper_store():
    """若唯一便宜店很远，可接受距离内应退而求其次（不盲目推荐远店）。"""
    quotes = [
        StoreQuote("near", "近店", 100, {"X": 15.0}),
        StoreQuote("far", "远店", 3000, {"X": 10.0}),
    ]
    res = optimize_across_stores(quotes, {"X": 1}, max_distance_m=1000)
    assert res["best"]["store_code"] == "near"
    assert any("超出可接受距离" in n for n in res["notes"])


def test_trade_off_quantifies_extra_distance():
    """远的更便宜时，应量化「多走多少米、省多少钱」。"""
    quotes = [
        StoreQuote("near", "近店", 200, {"X": 15.0}),
        StoreQuote("far", "远店", 800, {"X": 10.0}),
    ]
    res = optimize_across_stores(quotes, {"X": 1})
    assert res["best"]["store_code"] == "far"
    assert res["nearest"]["store_code"] == "near"
    assert res["trade_off"]["extra_distance_m"] == 600
    assert res["trade_off"]["saved"] == 5.0


def test_infeasible_store_is_skipped_with_note():
    quotes = [
        StoreQuote("a", "缺货店", 100, {"Y": 5.0}),
        StoreQuote("b", "有货店", 300, {"X": 9.0}),
    ]
    res = optimize_across_stores(quotes, {"X": 1})
    assert res["best"]["store_code"] == "b"
    assert any("不可行" in n or "缺少商品" in n for n in res["notes"])


def test_empty_when_all_infeasible():
    res = optimize_across_stores([StoreQuote("a", "店A", 100, {"Y": 1.0})], {"X": 1})
    assert res["best"] is None
    assert res["ranked"] == []


# ------------------------------------------------------------- 门店券解析
def test_coupon_percent_from_title():
    j = {"title": "新人专享-中杯美式7折", "couponId": "CID", "couponCode": "MCDX",
         "products": [{"productCode": "9900000119", "productName": "美式中杯"}]}
    c = coupon_from_store_json(j, {"9900000119": 19.0})
    assert c.kind == "percent"
    assert abs(c.discount - 0.7) < 1e-9
    assert c.product_codes == ["9900000119"]
    assert c.coupon_code == "MCDX" and c.coupon_id == "CID"


def test_coupon_special_price_from_title():
    j = {"title": "9.9元中杯冰美式", "couponCode": "MCDY",
         "products": [{"productCode": "507411", "productName": "麦咖啡冰美式中杯"}]}
    c = coupon_from_store_json(j, {"507411": 16.9})
    assert c.kind == "fixed"
    assert c.discount == 7.0  # 16.9 - 9.9


def test_coupon_threshold_and_cut_from_title():
    j1 = {"title": "满60减12", "products": [{"productCode": "X"}]}
    c1 = coupon_from_store_json(j1, {})
    assert c1.kind == "threshold" and c1.threshold == 60.0 and c1.discount == 12.0
    j2 = {"title": "立减5元", "products": [{"productCode": "X"}]}
    c2 = coupon_from_store_json(j2, {})
    assert c2.kind == "fixed" and c2.discount == 5.0


def test_coupon_special_price_no_products_returns_none():
    assert coupon_from_store_json({"title": "9.9元超值", "products": []}, {}) is None


def test_best_coupon_saving_with_bound_product():
    """真实券「中杯美式7折」作用于 9900000119(¥19) → 省 ¥5.70。"""
    coupons = [{"title": "新人专享-中杯美式7折", "couponCode": "MCDX", "promotionId": "1",
                "products": [{"productCode": "9900000119", "productName": "美式中杯"}]}]
    saving = best_coupon_saving(coupons, {"9900000119": 1}, {"9900000119": 19.0})
    assert saving == 5.70


def test_best_coupon_saving_zero_when_no_match():
    coupons = [{"title": "新人专享-中杯美式7折",
                "products": [{"productCode": "9900000119"}]}]
    assert best_coupon_saving(coupons, {"4810": 1}, {"4810": 13.5}) == 0.0


def test_store_quote_payable_includes_coupon_and_delivery():
    q = StoreQuote("s", "店", 100, {"9900000119": 19.0},
                   coupons=[{"title": "中杯美式7折", "products": [{"productCode": "9900000119"}]}],
                   delivery_fee=6.0)
    ev = evaluate_quote(q, {"9900000119": 1})
    assert ev["coupon_saving"] == 5.70
    assert ev["payable"] == 19.0 - 5.70 + 6.0


# ------------------------------------------------------------- 采集（离线 Fake）
class FakeClient:
    def __init__(self, menu_by_store, coupons_by_store):
        self.menu = menu_by_store
        self.coupons = coupons_by_store

    def call_tool(self, name, args):
        code = args["storeCode"]
        if name == "query-meals":
            return {"meals": self.menu.get(code, {})}
        if name == "query-store-coupons":
            return self.coupons.get(code, [])
        raise AssertionError(name)


def test_collect_store_quotes():
    stores = [
        {"storeCode": "s1", "storeName": "店1", "distance": 100},
        {"storeCode": "s2", "storeName": "店2", "distance": 200},
    ]
    client = FakeClient(
        {"s1": {"4810": {"name": "薯条", "currentPrice": 13.5}},
         "s2": {"4810": {"name": "薯条", "currentPrice": 14.5}}},
        {"s1": [], "s2": []},
    )
    quotes = collect_store_quotes(client, stores, {"4810": 1})
    assert len(quotes) == 2
    assert quotes[0].prices["4810"] == 13.5
    assert quotes[1].prices["4810"] == 14.5
    res = optimize_across_stores(quotes, {"4810": 1})
    assert res["best"]["store_code"] == "s1"
