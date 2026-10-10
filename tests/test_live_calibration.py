"""
真实校准：本地价格模型 vs 官方 calculate-price（默认跳过，需 MCD_MCP_TOKEN）。

目的：用真实返回值校准本地算法，证明"本地算得准、且与官方一致"——
这是两阶段核价（本地枚举 → 官方核价）可信的前提。
"""

import os
import pytest

from src.mcd_client import McDonaldMCPClient
from src.coupon_adapter import adapt_coupon

STORE = "1450104"


@pytest.mark.live
def test_live_no_coupon_matches_sum():
    token = os.environ.get("MCD_MCP_TOKEN")
    if not token:
        pytest.skip("需要 MCD_MCP_TOKEN 环境变量")
    client = McDonaldMCPClient(token=token)
    # 巨无霸(1100)=25.5 + 薯条(4810)=13.5 -> 39.00 -> 3900 分
    data = client.price_combo(STORE, [
        {"product_code": "1100", "quantity": 1},
        {"product_code": "4810", "quantity": 1},
    ])
    assert data.get("price") == 3900


@pytest.mark.live
def test_live_percent_coupon_matches_local_model():
    token = os.environ.get("MCD_MCP_TOKEN")
    if not token:
        pytest.skip("需要 MCD_MCP_TOKEN 环境变量")
    client = McDonaldMCPClient(token=token)
    coupons_raw = client.call_tool(
        "query-store-coupons", {"storeCode": STORE, "orderType": 1, "beType": 1}
    )
    assert isinstance(coupons_raw, list) and coupons_raw
    c0 = next((c for c in coupons_raw if "折" in (c.get("title") or "")), coupons_raw[0])
    locked = (c0.get("products") or [{}])[0].get("productCode")

    data = client.price_combo(
        STORE,
        [{"product_code": locked, "quantity": 1}],
        coupons=[{"coupon_code": c0.get("couponCode"), "coupon_id": c0.get("couponId")}],
    )
    # 本地模型：券面为 X 折 -> 折扣率应能从券名推断
    adapted = adapt_coupon(c0)
    price = data.get("price")
    orig = data.get("productOriginalPrice") or data.get("originalPrice")
    assert price and price > 0

    # 官方成交价应与本地折扣率一致（如 7 折 -> price ≈ original * 0.7）
    if adapted.kind == "percent" and orig and orig > 0:
        ratio = price / orig
        assert abs(ratio - adapted.discount) < 0.02, (
            f"本地折扣率 {adapted.discount} 与官方 {ratio:.3f} 不一致"
        )
