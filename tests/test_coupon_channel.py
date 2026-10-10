"""TDD 契约：券渠道建模与前置过滤（缺口 1）

真实依据（2026-10-10 实测 mcp.mcd.cn）：
  - 「到店专用」券用于外送核价被官方拒绝：`code=600012「当前优惠券不可用！」`
  - 我的券 Markdown 的 **标签** 字段会标注渠道（如「到店专用」）

旧实现的缺口：券的渠道属性没有进入 `Coupon` 模型，优化器选券时不知道渠道，
渠道约束完全外包给官方核价报错——一旦官方拒绝就成了"事后兜底"，且可能被
降级逻辑吃掉（见缺口 2）。本契约要求**本地求解前即按渠道过滤**。

运行：python -m pytest tests/test_coupon_channel.py -q
"""

from src.coupon_optimizer import (
    CHANNEL_DELIVERY,
    CHANNEL_DINE_IN,
    Coupon,
    Item,
    filter_coupons_by_channel,
    infer_channel_from_tag,
    optimize_coupons,
    optimize_split_orders,
    rank_candidates,
)


def _amer():
    """一件绑定门店券商品（9900000119 美式中杯），单价 ¥19。"""
    return [Item("美式中杯", 19.0, product_code="9900000119")]


# ---------------------------------------------------------------------------
# 渠道推断
# ---------------------------------------------------------------------------
def test_channel_constants_are_distinct():
    assert CHANNEL_DINE_IN != CHANNEL_DELIVERY


def test_infer_channel_from_tag():
    assert infer_channel_from_tag("到店专用") == CHANNEL_DINE_IN
    assert infer_channel_from_tag("仅限堂食") == CHANNEL_DINE_IN
    assert infer_channel_from_tag("外送专用") == CHANNEL_DELIVERY
    assert infer_channel_from_tag("麦乐送专享") == CHANNEL_DELIVERY


def test_infer_channel_unknown_returns_none():
    assert infer_channel_from_tag("新人专享") is None
    assert infer_channel_from_tag("") is None
    assert infer_channel_from_tag(None) is None


def test_infer_channel_both_tags_is_unrestricted():
    """真实 observe（2026-10-10）：9.9元中杯冰美式 标签为「到店专用、外送专用」。

    这是**双渠道通用券**（到店、外送都能用），语义上等同「不限渠道」。
    旧实现先命中「外送」关键词即返回 delivery，会把这张券误判成外送专用，
    导致**到店场景被本地过滤掉**——真实深圳案例里正是这张券贡献了 ¥9.10 优惠。
    """
    assert infer_channel_from_tag("到店专用、外送专用") is None
    assert infer_channel_from_tag("外送、到店通用") is None
    assert infer_channel_from_tag("堂食/麦乐送均可用") is None


def test_dual_channel_coupon_kept_in_both_channels():
    """双标签券在到店与外送两个场景都必须保留（不得被单渠道判定剔除）。"""
    c = Coupon(
        "both", kind="fixed", discount=9.0,
        channel=infer_channel_from_tag("到店专用、外送专用"),
    )
    assert [x.id for x in filter_coupons_by_channel([c], CHANNEL_DINE_IN)["valid"]] == ["both"]
    assert [x.id for x in filter_coupons_by_channel([c], CHANNEL_DELIVERY)["valid"]] == ["both"]


# ---------------------------------------------------------------------------
# 过滤
# ---------------------------------------------------------------------------
def test_filter_excludes_mismatched_channel():
    coupons = [
        Coupon("dine", kind="fixed", discount=5.0, channel=CHANNEL_DINE_IN),
        Coupon("any", kind="fixed", discount=3.0, channel=None),
        Coupon("del", kind="fixed", discount=4.0, channel=CHANNEL_DELIVERY),
    ]
    r = filter_coupons_by_channel(coupons, CHANNEL_DELIVERY)
    assert [c.id for c in r["valid"]] == ["any", "del"]
    assert [c.id for c in r["excluded"]] == ["dine"]
    assert any("dine" in w for w in r["warnings"])


def test_filter_noop_when_order_channel_none():
    coupons = [Coupon("dine", kind="fixed", discount=5.0, channel=CHANNEL_DINE_IN)]
    r = filter_coupons_by_channel(coupons, None)
    assert [c.id for c in r["valid"]] == ["dine"]
    assert r["excluded"] == []


# ---------------------------------------------------------------------------
# 优化器前置过滤
# ---------------------------------------------------------------------------
def test_optimize_rejects_dinein_coupon_for_delivery():
    """外送场景下到店专用券必须**本地即被排除**（不靠官方 600012 兜底）。"""
    c = Coupon("dine7", kind="percent", discount=0.7,
               product_codes=["9900000119"], channel=CHANNEL_DINE_IN)
    res = optimize_coupons(_amer(), [c], order_channel=CHANNEL_DELIVERY)
    assert res["best_coupons"] == []
    assert res["best_total"] == 19.0
    assert res["channel_excluded"] == ["dine7"]
    assert any("dine7" in w for w in res["channel_warnings"])


def test_optimize_keeps_channel_match():
    """到店场景下同一张到店专用券正常生效（7 折：19 → 13.30）。"""
    c = Coupon("dine7", kind="percent", discount=0.7,
               product_codes=["9900000119"], channel=CHANNEL_DINE_IN)
    res = optimize_coupons(_amer(), [c], order_channel=CHANNEL_DINE_IN)
    assert res["best_coupons"] == ["dine7"]
    assert res["best_total"] == 13.3
    assert res["channel_excluded"] == []


def test_optimize_default_keeps_unrestricted_coupon():
    """未指定渠道时不改变既有行为（向后兼容）。"""
    c = Coupon("dine7", kind="percent", discount=0.7,
               product_codes=["9900000119"], channel=CHANNEL_DINE_IN)
    res = optimize_coupons(_amer(), [c])
    assert res["best_coupons"] == ["dine7"]


def test_rank_candidates_respects_channel():
    """Top-K 候选也不得混入渠道不符的券。"""
    coupons = [
        Coupon("dine7", kind="percent", discount=0.7,
               product_codes=["9900000119"], channel=CHANNEL_DINE_IN),
        Coupon("any3", kind="fixed", discount=3.0, channel=None),
    ]
    cands = rank_candidates(_amer(), coupons, top_k=3, order_channel=CHANNEL_DELIVERY)
    used = {i for c in cands for i in c["best_coupons"]}
    assert "dine7" not in used


def test_split_orders_respects_channel():
    """拆分下单同样遵守渠道约束，并在结果中回报被排除的券。"""
    items = [
        Item("美式中杯", 19.0, product_code="9900000119"),
        Item("薯条", 13.5, product_code="4810"),
    ]
    coupons = [
        Coupon("dine7", kind="percent", discount=0.7,
               product_codes=["9900000119"], channel=CHANNEL_DINE_IN),
        Coupon("side2", kind="fixed", discount=2.0,
               product_codes=["4810"], channel=None),
    ]
    res = optimize_split_orders(items, coupons, order_channel=CHANNEL_DELIVERY)
    assert res["channel_excluded"] == ["dine7"]
    used = {i for o in res["orders"] for i in o["coupon_ids"]}
    assert "dine7" not in used


# ---------------------------------------------------------------------------
# 链路完整性：我的券 / 门店券 都要能带上渠道
# ---------------------------------------------------------------------------
def test_my_coupons_text_exposes_channel():
    """我的券 Markdown 的「标签」应被解析成 channel（真实 fixture 含「到店专用」）。"""
    import os

    from src.coupon_pools import parse_my_coupons_text

    path = os.path.join(os.path.dirname(__file__), "fixtures", "my_coupons.md")
    with open(path, encoding="utf-8") as f:
        items = parse_my_coupons_text(f.read())
    assert items
    assert all("channel" in it for it in items)
    assert any(it["channel"] == CHANNEL_DINE_IN for it in items)


def test_store_coupon_json_can_be_channel_stamped():
    """门店券 JSON 本身无渠道字段，但可由查询入口标注渠道。"""
    from src.store_optimizer import coupon_from_store_json

    j = {"couponId": "I", "couponCode": "C", "title": "满60减12",
         "products": [{"productCode": "X"}]}
    c = coupon_from_store_json(j, {"X": 30.0}, channel=CHANNEL_DELIVERY)
    assert c is not None and c.channel == CHANNEL_DELIVERY
