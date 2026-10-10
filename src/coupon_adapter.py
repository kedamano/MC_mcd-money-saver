"""
麦麦省钱助手 - 麦当劳优惠券适配器

把麦当劳 MCP 返回的「真实优惠券 JSON」映射为领域对象 `Coupon`，
并尽量从 description 启发式推断券类型与面额。

真实 observe（来自 query-store-coupons / query-my-coupons）：
  字段含 couponCode / couponId / productCode / description（如「新人专享-中杯美式7折」）。
  关键事实：麦当劳券多为 **产品级绑定**（绑定到具体 productCode），而非泛类目；
  叠加是否生效、门槛是否满足，最终以 calculate-price 服务器返回为权威。

本适配器只做「建模」，不做权威判定；权威判定交给 calculate-price（见 mcd_client）。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from src.coupon_optimizer import Coupon

# 保留比例（0.7 = 7折，即顾客支付 70%）
_RE_THRESHOLD = re.compile(r"满\s*(\d+(?:\.\d+)?)\s*减\s*(\d+(?:\.\d+)?)")
_RE_ZHE = re.compile(r"(\d+(?:\.\d+)?)\s*折")
_RE_FIXED = re.compile(r"(?:立减|减)\s*(\d+(?:\.\d+)?)\s*元?")


def _infer_kind_and_amount(desc: str):
    """从券描述推断 (kind, discount, threshold, max_discount)。"""
    d = (desc or "").strip()
    if not d:
        return "fixed", 0.0, 0.0, 0.0

    if "免配送" in d or "免运费" in d:
        return "free_delivery", 0.0, 0.0, 0.0

    m = _RE_THRESHOLD.search(d)
    if m:
        threshold = float(m.group(1))
        discount = float(m.group(2))
        return "threshold", discount, threshold, 0.0

    m = _RE_ZHE.search(d)
    if m:
        keep = float(m.group(1)) / 10.0  # 7折 -> 0.7
        # 折扣券常见封顶（如「最高减XX元」）
        cap = 0.0
        mc = re.search(r"最高(?:减|省)\s*(\d+(?:\.\d+)?)", d)
        if mc:
            cap = float(mc.group(1))
        return "percent", keep, 0.0, cap

    m = _RE_FIXED.search(d)
    if m:
        return "fixed", float(m.group(1)), 0.0, 0.0

    # 兜底：无法识别的券按立减 0（不生效），避免误叠加
    return "fixed", 0.0, 0.0, 0.0


def adapt_coupon(raw: Dict[str, Any], *, order_type: int = 1) -> Coupon:
    """真实券 JSON -> 领域 Coupon。

    返回 Coupon 上会附加 `product_codes` 属性（产品级绑定），
    供后续 calculate-price 权威校验时按 productCode 匹配，避免错配类目。
    """
    desc = raw.get("description") or raw.get("name") or ""
    kind, discount, threshold, max_discount = _infer_kind_and_amount(desc)

    coupon_id = raw.get("couponId") or raw.get("couponCode") or desc
    coupon_code = raw.get("couponCode")
    product_codes: List[str] = []
    pc = raw.get("productCode")
    if pc:
        product_codes = [pc] if isinstance(pc, str) else list(pc)

    # 失效日期（真实券 JSON 可能含 validEnd / expireTime 等字段）
    expires_at = raw.get("validEnd") or raw.get("expireTime") or raw.get("endDate")

    coupon = Coupon(
        id=str(coupon_id),
        kind=kind,
        discount=discount,
        threshold=threshold,
        max_discount=max_discount,
        applies_to=None,  # 产品级绑定优先于泛类目，统一在校验阶段按 product_codes 处理
        product_codes=product_codes,
        expires_at=str(expires_at) if expires_at else None,
        coupon_code=str(coupon_code) if coupon_code else None,
        coupon_id=str(coupon_id) if coupon_id else None,
    )
    return coupon
