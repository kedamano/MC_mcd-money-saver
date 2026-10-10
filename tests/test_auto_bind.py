"""auto-bind-coupons 一键领券扩池 —— 契约测试。

真实依据（2026-10-10 实测，上海悦荟广场 1450104）：
  - auto-bind-coupons **无入参**，返回**纯文本而非 JSON** → 必须用 call_tool_text，
    误用 call_tool 会抛「text 中未找到业务 JSON」。
  - 领取前：门店券 2 / 我的券 2；领取后：门店券 3 / 我的券 7 —— 券池实打实扩大。
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.coupon_pools import (  # noqa: E402
    collect_and_bind_coupons,
    collect_coupon_pools,
    parse_available_coupons_text,
    parse_my_coupons_text,
)

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _read(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def _read_json(name: str):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


class FakeClient:
    """按「是否已完成领取」切换返回前后两种真实数据的假客户端。"""

    def __init__(self, store_before, store_after, my_before, my_after, avail,
                 bind_raises=False, bind_text="自动领取成功"):
        self.store_before, self.store_after = store_before, store_after
        self.my_before, self.my_after = my_before, my_after
        self.avail = avail
        self.bind_raises = bind_raises
        self.bind_text = bind_text
        self.bind_calls = 0
        self.store_args_log = []

    def call_tool(self, name, arguments):
        assert name == "query-store-coupons", f"未预期的工具：{name}"
        self.store_args_log.append(dict(arguments))
        return self.store_after if self.bind_calls else self.store_before

    def call_tool_text(self, name, arguments):
        if name == "auto-bind-coupons":
            self.bind_calls += 1
            if self.bind_raises:
                raise RuntimeError("text 中未找到业务 JSON")
            return self.bind_text
        if name == "query-my-coupons":
            return self.my_after if self.bind_calls else self.my_before
        if name == "available-coupons":
            return self.avail
        raise AssertionError(f"未预期的工具：{name}")


MY_BEFORE = _read("my_coupons.md")
STORE_COUPONS_AFTER = _read_json("store_coupons_after_bind.json")
MY_AFTER = _read("my_coupons_after_bind.md")
AVAIL = _read("available_coupons.md")


def _store_coupon(title, cid=1):
    return {
        "couponId": f"CID{title}{cid}",
        "couponCode": f"MCD{title}{cid}",
        "title": title,
        "products": [{"productCode": "9900000119", "productName": "美式中杯"}],
    }


STORE_BEFORE_LIST = [
    _store_coupon("新人专享-中杯美式7折"),
    _store_coupon("新人专享-中杯奶铁7折"),
]


# ---------------------------------------------------------------- 真实 fixture 契约
def test_real_fixtures_bind_enlarges_mine_pool():
    """真实数据事实：领取后「我的券」确实变多（my_coupons.md → my_coupons_after_bind.md）。"""
    before = parse_my_coupons_text(MY_BEFORE)
    after = parse_my_coupons_text(MY_AFTER)
    assert len(before) >= 1
    assert len(after) > len(before), "领券后券池应扩大，否则 fixture 已失效"


def test_real_fixtures_store_coupons_after_bind():
    """领券后该门店可核价的门店券（真实返回）数量与结构。"""
    assert isinstance(STORE_COUPONS_AFTER, list)
    assert len(STORE_COUPONS_AFTER) >= 2
    codes = {(c.get("couponCode"), c.get("couponId")) for c in STORE_COUPONS_AFTER}
    assert (None, None) not in codes, "门店券必须带 couponCode / couponId 才能进核价"


def test_available_coupons_parse_has_claimable():
    cs = parse_available_coupons_text(AVAIL)
    assert len(cs) >= 1
    assert all(c["title"] for c in cs)


# ---------------------------------------------------------------- 业务逻辑
def _client(bind_raises=False):
    return FakeClient(
        store_before=STORE_BEFORE_LIST,
        store_after=STORE_COUPONS_AFTER,
        my_before=MY_BEFORE,
        my_after=MY_AFTER,
        avail=AVAIL,
        bind_raises=bind_raises,
    )


def test_bind_reports_before_after_and_gain():
    c = _client()
    r = collect_and_bind_coupons(c, "1450104")
    assert r["bound"] is True
    assert c.bind_calls == 1
    assert r["before"]["store"] == 2
    assert r["after"]["store"] == len(STORE_COUPONS_AFTER)
    assert r["gained_store"] == len(STORE_COUPONS_AFTER) - 2
    assert r["gained_mine"] == len(parse_my_coupons_text(MY_AFTER)) - len(parse_my_coupons_text(MY_BEFORE))
    assert r["gained_store"] >= 0 and r["gained_mine"] >= 0
    assert len(r["pools"]["store"]) == r["after"]["store"]  # pools 回传完整结果
    assert set(r["pools"]) >= {"store", "mine", "claimable", "overlap", "warnings"}


def test_gain_is_never_negative_even_if_pool_shrinks():
    """领券后若因过期导致券数下降，也不应报负数。"""
    c = FakeClient(
        store_before=STORE_BEFORE_LIST,
        store_after=[STORE_BEFORE_LIST[0]],   # 反而变少
        my_before=MY_BEFORE,
        my_after=MY_BEFORE[: MY_BEFORE.find("## 新人专享-中杯奶铁7折")] or MY_BEFORE,
        avail=AVAIL,
    )
    r = collect_and_bind_coupons(c, "1450104")
    assert r["gained_store"] == 0
    assert r["gained_mine"] >= 0


def test_do_bind_false_never_calls_autobind():
    c = _client()
    r = collect_and_bind_coupons(c, "1450104", do_bind=False)
    assert c.bind_calls == 0
    assert r["bound"] is False
    assert r["before"] == r["after"], "未领取时前后应一致"


@pytest.mark.parametrize("bind_raises", [True, False])
def test_bind_failure_is_fault_tolerant(bind_raises):
    """auto-bind 返回非 JSON 属真实情况：异常必须被吞掉，流程继续聚合。"""
    c = _client(bind_raises=bind_raises)
    r = collect_and_bind_coupons(c, "1450104")
    assert r["bound"] is (not bind_raises)
    assert isinstance(r["pools"], dict)
    assert "store" in r["pools"] and "mine" in r["pools"]
    if bind_raises:
        assert "未找到业务 JSON" in r["bind_message"]


def test_be_code_is_passed_through_for_delivery():
    """外送场景必传 beCode（缺失官方返回 code=600048）。"""
    c = _client()
    collect_and_bind_coupons(c, "1450056", order_type=2, be_type=2, be_code="145005602", do_bind=False)
    for args in c.store_args_log:
        assert args["beCode"] == "145005602"
        assert args["orderType"] == 2 and args["beType"] == 2


def test_collect_without_bind_still_warns_about_claimable():
    c = _client()
    pools = collect_coupon_pools(c, "1450104")
    assert pools["claimable"], "fixture 中应存在可领取券"
    assert any("collect_and_bind_coupons" in w for w in pools["warnings"])
