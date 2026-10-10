"""
B 优化项：生效时间 / 每日时段窗 过滤测试。

真实依据：我的券有效期字符串形如
    "2026-10-10 00:00-2026-11-08 23:59 05:00-23:59"
即「起-止日期」+「每日可用时段」。只判过期会漏掉"
未到生效时间"与"时段不符"两种情况。
"""

from src.coupon_optimizer import Coupon, filter_active_coupons
from src.coupon_pools import parse_valid_period


def test_parse_valid_period_real_string():
    vf, ex, wins = parse_valid_period("2026-10-10 00:00-2026-11-08 23:59 05:00-23:59")
    assert vf == "2026-10-10"
    assert ex == "2026-11-08"
    assert wins == [("05:00", "23:59")]


def test_filter_active_keeps_in_window():
    c = Coupon("c", "fixed", discount=5.0, valid_from="2026-10-01",
               expires_at="2026-11-08", time_windows=[("05:00", "23:59")])
    res = filter_active_coupons([c], now="2026-10-10 12:00")
    assert res["valid"] == [c]
    assert not res["warnings"]


def test_filter_active_expired():
    c = Coupon("c", "fixed", discount=5.0, expires_at="2026-09-30")
    res = filter_active_coupons([c], now="2026-10-10 12:00")
    assert res["expired"] == [c]
    assert res["valid"] == []


def test_filter_active_not_effective():
    c = Coupon("c", "fixed", discount=5.0, valid_from="2026-11-01")
    res = filter_active_coupons([c], now="2026-10-10 12:00")
    assert res["not_effective"] == [c]
    assert any("未生效" in w for w in res["warnings"])


def test_filter_active_outside_window():
    # 券限 05:00-23:59，凌晨 03:00 下单则时段不符
    c = Coupon("c", "fixed", discount=5.0, time_windows=[("05:00", "23:59")])
    res = filter_active_coupons([c], now="2026-10-10 03:00")
    assert res["outside_window"] == [c]
    assert any("时段" in w for w in res["warnings"])


def test_filter_active_cross_midnight_window():
    # 跨零点时段 22:00-02:00：23:30 与 01:00 都应命中
    c = Coupon("c", "fixed", discount=5.0, time_windows=[("22:00", "02:00")])
    assert filter_active_coupons([c], now="2026-10-10 23:30")["valid"] == [c]
    assert filter_active_coupons([c], now="2026-10-10 01:00")["valid"] == [c]
    assert filter_active_coupons([c], now="2026-10-10 12:00")["outside_window"] == [c]


def test_filter_active_no_now_keeps_all():
    c = Coupon("c", "fixed", discount=5.0, expires_at="2000-01-01")
    assert filter_active_coupons([c])["valid"] == [c]  # 不传 now 不过滤
