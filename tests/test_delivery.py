"""外送场景（麦乐送）链路封装的离线契约测试。

真实 observe：
- `delivery-query-stores` 需要 `addressId`（来自 `delivery-create-address`），返回的门店含 **beCode**；
- `calculate-price` 外送(beType=2)不传 beCode 返回 code=600048「必传beCode」；
- 外送核价返回含 `deliveryPrice`（配送费，分）。

本文件用「捕获 call_tool 参数」的方式离线校验请求体构造，不发起真实网络调用。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.mcd_client import McDonaldMCPClient


def _spy():
    c = McDonaldMCPClient(token="t")
    calls = []

    def fake_call(name, arguments, retry=True):
        calls.append({"name": name, "args": arguments, "retry": retry})
        return {"ok": True}

    c.call_tool = fake_call
    return c, calls


def test_price_combo_delivery_includes_be_code():
    """外送核价必须带上 beCode（否则官方返回 600048）。"""
    c, calls = _spy()
    c.price_combo(
        "S1", [{"product_code": "520689", "quantity": 1}],
        order_type=2, be_type=2, be_code="BE9",
    )
    a = calls[-1]["args"]
    assert calls[-1]["name"] == "calculate-price"
    assert a["orderType"] == 2 and a["beType"] == 2 and a["beCode"] == "BE9"
    assert a["items"][0]["productCode"] == "520689"


def test_price_combo_instore_has_no_be_code():
    """到店核价不携带 beCode（保持原有行为）。"""
    c, calls = _spy()
    c.price_combo("S1", [{"product_code": "520689", "quantity": 1}], order_type=1, be_type=1)
    assert "beCode" not in calls[-1]["args"]


def test_create_order_delivery_includes_address_and_be_code():
    """外送下单：携带 addressId + beCode，且禁用重试（副作用）。"""
    c, calls = _spy()
    c.create_order(
        "S1", [{"product_code": "520689", "quantity": 1}],
        order_type=2, be_type=2, address_id="A123", be_code="BE9",
    )
    a = calls[-1]["args"]
    assert a["addressId"] == "A123" and a["beCode"] == "BE9" and a["orderType"] == 2
    assert "takeWayCode" not in a
    assert calls[-1]["retry"] is False


def test_create_order_instore_requires_take_way_code():
    """到店下单必须提供 takeWayCode。"""
    c, calls = _spy()
    c.create_order("S1", [{"product_code": "520689", "quantity": 1}],
                   order_type=1, take_way_code="eat-in")
    assert calls[-1]["args"]["takeWayCode"] == "eat-in"
    with pytest.raises(ValueError):
        c.create_order("S1", [{"product_code": "520689", "quantity": 1}], order_type=1)


def test_query_delivery_stores_arguments():
    """delivery-query-stores 的入参字段名与取值。"""
    c, calls = _spy()
    c.query_delivery_stores("A123", be_type=2)
    assert calls[-1]["name"] == "delivery-query-stores"
    assert calls[-1]["args"] == {"beType": 2, "addressId": "A123"}


def test_create_delivery_address_fields_and_no_retry():
    """创建地址：字段齐全，且禁用重试（副作用）。"""
    c, calls = _spy()
    c.create_delivery_address("上海市", "南京东路", "1号", "张三", "13800000000")
    a = calls[-1]["args"]
    assert a["city"] == "上海市" and a["address"] == "南京东路"
    assert a["addressDetail"] == "1号" and a["phone"] == "13800000000"
    assert calls[-1]["retry"] is False


def test_query_delivery_addresses_calls_with_empty_args():
    """查地址列表：无必填参数。"""
    c, calls = _spy()
    c.query_delivery_addresses()
    assert calls[-1]["name"] == "delivery-query-addresses"
    assert calls[-1]["args"] == {}
