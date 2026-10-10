"""
三池券聚合测试。

离线部分（默认运行）：用真实抓取的 Markdown（tests/fixtures/*.md）断言解析正确。
真实部分（`pytest -m live`）：真连 mcp.mcd.cn 聚合三池，验证真实接入。
"""

import os

import pytest

from src.coupon_pools import parse_available_coupons_text, parse_my_coupons_text

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _read(name):
    with open(os.path.join(FIX, name), "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# 离线：我的券 Markdown 解析
# ---------------------------------------------------------------------------
def test_parse_my_coupons_basic():
    coupons = parse_my_coupons_text(_read("my_coupons.md"))
    assert len(coupons) == 2
    c0 = coupons[0]
    assert c0["name"] == "新人专享-中杯美式7折"
    assert c0["price_text"] == "¥13.3 (用券价格)"
    assert c0["tag"] == "到店专用"
    assert c0["expires_at"] == "2026-11-08"


def test_parse_my_coupons_extracts_coupon_id_from_image():
    # 首张券图片文件名为 32 位十六进制 -> 即 couponId，可与门店券交叉核对
    coupons = parse_my_coupons_text(_read("my_coupons.md"))
    assert coupons[0]["coupon_id"] == "365A627ABDC435D840984F03055DF097"
    # 第二张图片是中文名，取不到 couponId（真实数据的不确定性）
    assert coupons[1]["coupon_id"] is None


# ---------------------------------------------------------------------------
# 离线：麦麦省券 Markdown 解析
# ---------------------------------------------------------------------------
def test_parse_available_coupons_basic():
    # 真实数据里有 6 张可领取券，且存在同名券（「巧克力味厚松饼猪柳蛋套餐」×3），
    # 说明麦麦省券池按「促销活动」而非「券」粒度返回——真实业务细节。
    avail = parse_available_coupons_text(_read("available_coupons.md"))
    assert len(avail) == 6
    assert avail[0]["title"] == "巧克力味厚松饼猪柳蛋套餐"
    assert avail[0]["status"] == "可领取"
    assert all(a["status"] == "可领取" for a in avail)


def test_parse_available_coupons_has_image():
    avail = parse_available_coupons_text(_read("available_coupons.md"))
    assert avail[0]["image"].startswith("https://")


# ---------------------------------------------------------------------------
# 真实聚合（默认跳过）
# ---------------------------------------------------------------------------
@pytest.mark.live
def test_live_three_pools():
    token = os.environ.get("MCD_MCP_TOKEN")
    if not token:
        pytest.skip("需要 MCD_MCP_TOKEN 环境变量")
    from src.mcd_client import McDonaldMCPClient
    from src.coupon_pools import collect_coupon_pools

    client = McDonaldMCPClient(token=token)
    pools = collect_coupon_pools(client, "1450104")
    assert len(pools["store"]) >= 1          # 门店券（可核价主集）
    assert isinstance(pools["mine"], list)   # 我的券
    assert isinstance(pools["claimable"], list)
