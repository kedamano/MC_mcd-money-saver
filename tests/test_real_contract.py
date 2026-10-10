"""
合同测试（Golden-Master）：麦麦省钱助手 真实业务场景契约

遵循 TDD + 真实业务场景：
- 用 联调时抓取的真实 `calculate-price` 返回（tests/fixtures/*.json）作为黄金基准，
  离线断言「优化器的独立优惠计算」与「麦当劳服务器权威金额」完全一致。
- 不依赖网络/Token 即可在 CI 运行；若服务器规则变化，这里会先红，提示我们更新模型。
- 可选真实冒烟见 tests/test_mcd_client.py（需 --live + MCD_MCP_TOKEN）。
"""

import json
import os

import pytest

from src.coupon_optimizer import Coupon, Item, optimize_coupons, total_price
from src.coupon_adapter import adapt_coupon

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    with open(os.path.join(FIXTURE_DIR, name), "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1. 基准价（无券）合同：原价 == 现价，优惠为 0
# ---------------------------------------------------------------------------
def test_base_price_contract():
    base = _load("calc_base.json")
    # 小杯鲜萃咖啡：原价 950 分 == 现价 950 分，优惠 0
    assert base["originalPrice"] == 950
    assert base["discount"] == 0
    assert base["price"] == base["originalPrice"]
    # 金额单位为「分」，换算元后与条目小计一致
    sub = base["productList"][0]["subtotal"]
    assert sub == 950


# ---------------------------------------------------------------------------
# 2. 带券价合同：优化器独立计算 == 服务器权威结果（核心契约）
# ---------------------------------------------------------------------------
def test_coupon_price_contract_matches_server():
    cou = _load("calc_coupon.json")
    # 服务器权威值（分）
    srv_original = cou["originalPrice"] / 100.0   # 19.00
    srv_discount = cou["discount"] / 100.0        # 5.70
    srv_price = cou["price"] / 100.0              # 13.30

    # 用真实券面「新人专享-中杯美式7折」建模：percent=0.7（保留70%）
    item = Item("美式中杯", srv_original, category="drink")
    coupon = Coupon("newbie_7off", kind="percent", discount=0.7)

    # 优化器独立计算
    res = optimize_coupons([item], [coupon], delivery_fee=0.0)
    our_discount = round(srv_original - res["best_total"], 2)

    # 合同断言：我们的优惠/到手价 必须等于 服务器权威值
    assert our_discount == pytest.approx(srv_discount, abs=0.01)
    assert res["best_total"] == pytest.approx(srv_price, abs=0.01)
    assert res["saved"] == pytest.approx(srv_discount, abs=0.01)


# ---------------------------------------------------------------------------
# 3. 适配层合同：真实券 JSON -> 领域 Coupon 推断正确
# ---------------------------------------------------------------------------
def test_adapt_real_coupon_7off():
    raw = {
        "couponCode": "MCD689H051J0J01C0Y078",
        "couponId": "365A627ABDC435D840984F03055DF097",
        "productCode": "9900000119",
        "description": "新人专享-中杯美式7折",
    }
    coupon = adapt_coupon(raw)
    assert coupon.kind == "percent"
    assert coupon.discount == pytest.approx(0.7, abs=1e-6)
    # 产品级绑定应被记录（供未来 calculate-price 校验使用）
    assert "9900000119" in getattr(coupon, "product_codes", [])


def test_adapt_real_coupon_threshold():
    raw = {"description": "满60减12", "productCode": "9900000001"}
    coupon = adapt_coupon(raw)
    assert coupon.kind == "threshold"
    assert coupon.threshold == 60.0
    assert coupon.discount == 12.0
