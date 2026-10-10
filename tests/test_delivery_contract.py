"""外送场景真实返回的离线合同测试（基于 fixtures 黄金基准）。

锁定 2026-10-10 真机实测得到的外送「价格构成」与「券渠道限制」规则，
防止解析/建模回归。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _load(name):
    with open(os.path.join(FIX, name), "r", encoding="utf-8") as f:
        return json.load(f)


def test_delivery_price_composition():
    """价格构成：originalPrice = 商品原价 + 配送费 + 打包费；price = originalPrice - discount。

    注：productPrice 已扣除 discount（商品自身促销），不再二次相减。
    """
    d = _load("calc_delivery_cart.json")
    assert d["deliveryPrice"] == 600      # 配送费 ¥6.00
    assert d["packingPrice"] == 300       # 打包服务费 ¥3.00
    assert d["originalPrice"] == (
        d["productOriginalPrice"] + d["deliveryOriginalPrice"] + d["packingOriginalPrice"]
    )
    assert d["productPrice"] == d["productOriginalPrice"] - d["discount"]
    assert d["price"] == d["originalPrice"] - d["discount"]
    # equal: 商品价(已扣折扣) + 配送费 + 打包费
    assert d["price"] == d["productPrice"] + d["deliveryPrice"] + d["packingPrice"]


def test_delivery_has_extra_fees_vs_instore():
    """外送相较到店多出配送费与打包服务费（到店无这两项）。"""
    d = _load("calc_delivery_cart.json")
    assert d["deliveryPrice"] > 0 and d["packingPrice"] > 0


def test_packing_fee_is_separate_zero_subtotal_line():
    """打包服务费作为独立商品行出现，且 subtotal 为 0（不重复计入商品小计）。"""
    d = _load("calc_delivery_cart.json")
    packing = [p for p in d["productList"] if p["productCode"] == "920174"]
    assert packing, "打包服务费应作为独立行存在"
    assert packing[0]["subtotal"] == 0


def test_delivery_discount_from_item_promo():
    """外送折扣可来自商品自身促销价（奶铁 2100→1390，discount 710），非券。"""
    d = _load("calc_delivery_cart.json")
    assert d["discount"] == 710
    milk = [p for p in d["productList"] if p["productCode"] == "507328"][0]
    assert milk["originalSubtotal"] == 2100 and milk["subtotal"] == 1390


def test_coupon_channel_restriction_rejected():
    """到店专用券用于外送核价被官方拒绝：code=600012「当前优惠券不可用！」"""
    d = _load("delivery_coupon_rejected.json")
    assert d["success"] is False
    assert d["code"] == 600012
    assert "不可用" in d["message"]
