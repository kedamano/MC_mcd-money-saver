"""TDD 契约：核价「业务拒绝」与「网络异常」必须区分（缺口 2）

真实依据：到店专用券做外送核价，官方返回
    {"success": false, "code": 600012, "message": "当前优惠券不可用！"}
见 `fixtures/delivery_coupon_rejected.json`。

旧实现的严重缺陷（本契约锁死）：
  1. `price_combo_as_fn` 用 `data.get("price") or 0` 取值 → 错误响应无 price 字段
     → 返回 **¥0.00** → 被官方拒绝的候选反而"最便宜"而必然胜出；
  2. `two_stage_optimize` 把所有异常一律降级为本地估计，同样让无效候选有机会胜出。

正确语义：**被官方拒绝的候选 = 方案无效，直接剔除**；只有网络类异常才降级。

运行：python -m pytest tests/test_pricing_rejection.py -q
"""

import json
import os

from src.coupon_optimizer import Coupon, Item
from src.coupon_smart import two_stage_optimize
from src.errors import (
    CouponRejectedError,
    MCPBusinessError,
    raise_if_business_error,
)

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    with open(os.path.join(FIX, name), "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 业务信封失败识别
# ---------------------------------------------------------------------------
def test_raise_if_business_error_on_rejected_coupon():
    data = _load("delivery_coupon_rejected.json")
    try:
        raise_if_business_error(data)
        assert False, "应抛出 CouponRejectedError"
    except CouponRejectedError as e:
        assert e.code == 600012
        assert "券" in e.message


def test_raise_if_business_error_ok_for_success_payload():
    """成功响应（已剥信封，无 success 字段）不应抛异常。"""
    raise_if_business_error(_load("calc_coupon.json"))


def test_raise_if_business_error_non_coupon_business_failure():
    """非券类业务失败应抛通用业务异常，而非券拒绝。"""
    try:
        raise_if_business_error({"success": False, "code": 600048, "message": "必传beCode"})
        assert False, "应抛出 MCPBusinessError"
    except MCPBusinessError as e:
        assert not isinstance(e, CouponRejectedError)
        assert e.code == 600048


# ---------------------------------------------------------------------------
# 两阶段校验：被拒候选不得胜出
# ---------------------------------------------------------------------------
def _items():
    return [Item("美式中杯", 19.0, product_code="9900000119")]


def test_two_stage_rejected_candidate_never_wins():
    """本地最便宜的候选被官方拒绝时，应改选官方可用的方案。"""
    cheap = Coupon("dine7", kind="percent", discount=0.7, product_codes=["9900000119"],
                   coupon_code="C1", coupon_id="I1")
    other = Coupon("any3", kind="fixed", discount=3.0, coupon_code="C2", coupon_id="I2")

    def pricing_fn(subset, _items):
        ids = {c.id for c in subset}
        if "dine7" in ids:
            raise CouponRejectedError(600012, "当前优惠券不可用！")
        if not ids:
            return 19.0
        return 16.0  # any3 的官方权威价

    res = two_stage_optimize(_items(), [cheap, other], pricing_fn=pricing_fn, top_k=3)
    assert res["best_coupons"] == ["any3"]
    assert res["best_total"] == 16.0
    assert res["rejected"] >= 1
    assert res["all_rejected"] is False


def test_two_stage_all_rejected_falls_back_to_no_coupon():
    """全部候选都被拒绝时，退化为「不使用优惠券」而非返回被拒方案。"""
    c = Coupon("dine7", kind="percent", discount=0.7, product_codes=["9900000119"],
               coupon_code="C1", coupon_id="I1")

    def pricing_fn(subset, _items):
        if subset:
            raise CouponRejectedError(600012, "当前优惠券不可用！")
        return 19.0

    res = two_stage_optimize(_items(), [c], pricing_fn=pricing_fn, top_k=3)
    assert res["best_coupons"] == []
    assert res["best_total"] == 19.0
    assert res["all_rejected"] is True


def test_two_stage_network_error_still_degrades():
    """网络/未知异常仍降级为本地估计（与业务拒绝区别对待）。"""
    c = Coupon("any3", kind="fixed", discount=3.0, coupon_code="C2", coupon_id="I2")

    def pricing_fn(_subset, _items):
        raise TimeoutError("network jitter")

    res = two_stage_optimize(_items(), [c], pricing_fn=pricing_fn, top_k=3)
    assert res["best_coupons"] == ["any3"]
    assert res["best_total"] == 16.0  # 本地估计：19 - 3
    assert res["errored"] >= 1
    assert res["rejected"] == 0


def test_two_stage_channel_filtered_before_pricing():
    """渠道不符的券应在进入官方核价前就被排除，天然不消耗核价次数。"""
    from src.coupon_optimizer import CHANNEL_DINE_IN, CHANNEL_DELIVERY

    dine = Coupon("dine7", kind="percent", discount=0.7, product_codes=["9900000119"],
                  channel=CHANNEL_DINE_IN, coupon_code="C1", coupon_id="I1")
    calls = []

    def pricing_fn(subset, _items):
        calls.append([c.id for c in subset])
        return 19.0

    res = two_stage_optimize(_items(), [dine], pricing_fn=pricing_fn,
                             order_channel=CHANNEL_DELIVERY)
    assert res["best_coupons"] == []
    assert res["channel_excluded"] == ["dine7"]
    assert all("dine7" not in c for c in calls)
