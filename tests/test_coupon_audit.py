"""TDD 契约：券数核对（MCP 声明总数 vs 本地解析数 vs 当前可用数）

背景（2026-10-10 实测）：用户 APP 卡包显示 16 张，而 MCP `query-my-coupons`
一度只返回 7 张。核查后确认是**同一账号**，差异来自两个机制：

1. `query-my-coupons` 是「**可用**券」视图（原文自述「共 N 张**可用**优惠券」），
   已过期 / 尚未生效 / 不在每日时段窗内的券会被服务端过滤掉；
2. 卡包内容是**动态发放**的（早餐券按周逐日发放，标签「今日收到」）。

因此「MCP 张数 ≠ APP 张数」是**正常现象**，但 agent 必须能把这个差额说清楚，
而不是含糊其辞或误判为「账号不一致」。本模块提供可复现的核对口径。

运行：python -m pytest tests/test_coupon_audit.py -q
"""

from src.coupon_pools import (
    audit_my_coupon_items,
    parse_declared_total,
    parse_my_coupons_text,
)

# 真实节选（2026-10-10 16:02 实测 mcp.mcd.cn）
MY_TEXT = """# 您的优惠券列表

共 15 张可用优惠券 | 第 1/1 页 | 每页 200 条

## 9.9元中杯冰美式
- **优惠**: ¥9.9 (用券价格)
- **有效期**: 2026-10-10 00:00-2026-10-16 23:59
- **标签**: 到店专用、外送专用

## 火腿扒堡早餐两件套
- **优惠**: ¥9.9 (用券价格)
- **有效期**: 2026-10-12 05:00-2026-10-12 10:29 周一 05:00-10:29
- **标签**: 到店专用
"""

SAME_DAY_BREAKFAST = """# 您的优惠券列表

共 1 张可用优惠券 | 第 1/1 页 | 每页 200 条

## 火腿扒堡早餐两件套
- **优惠**: ¥9.9 (用券价格)
- **有效期**: 2026-10-10 05:00-2026-10-10 10:29 周六 05:00-10:29
- **标签**: 到店专用
"""


def test_parse_declared_total():
    """服务端自述总数可被解析，用于与本地解析数对账。"""
    assert parse_declared_total(MY_TEXT) == 15
    assert parse_declared_total("没有任何数字") is None
    assert parse_declared_total(None) is None


def test_audit_reconciles_declared_parsed_usable():
    items = parse_my_coupons_text(MY_TEXT)
    assert len(items) == 2
    r = audit_my_coupon_items(items, declared=15, now="2026-10-10 16:02")
    assert r["declared"] == 15
    assert r["parsed"] == 2
    # 冰美式当时可用；早餐券 10-12 尚未生效
    assert r["usable_now"] == 1
    assert r["not_effective"] == 1
    assert r["mismatch"] is True  # 解析数 != 服务端声明数，必须显式告警


def test_audit_flags_same_day_out_of_window():
    """当日早餐券过期时段后：服务端可能仍列出，但当前不可用（时段不符）。"""
    items = parse_my_coupons_text(SAME_DAY_BREAKFAST)
    r = audit_my_coupon_items(items, declared=1, now="2026-10-10 16:02")
    assert r["outside_window"] == 1
    assert r["usable_now"] == 0


def test_audit_no_mismatch_when_counts_equal():
    items = parse_my_coupons_text(SAME_DAY_BREAKFAST)
    r = audit_my_coupon_items(items, declared=1, now="2026-10-10 08:00")
    assert r["mismatch"] is False
    assert r["usable_now"] == 1  # 08:00 落在 05:00-10:29 内


def test_audit_without_now_keeps_all_as_usable():
    items = parse_my_coupons_text(MY_TEXT)
    r = audit_my_coupon_items(items, declared=2, now=None)
    assert r["usable_now"] == 2
    assert r["mismatch"] is False
