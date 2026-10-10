"""
麦麦省钱助手 · 三池优惠券聚合

真实 observe（2026-10-10 实测 mcp.mcd.cn）——三个券池的**返回结构完全不同**：

| 券池 | 工具 | 返回结构 | 能否直接核价 |
|---|---|---|---|
| 门店券 | `query-store-coupons` | 结构化 JSON（含 couponCode / couponId / products） | ✅ 直接送 calculate-price |
| 我的券 | `query-my-coupons` | **Markdown 文本**（券名 / 用券价格 / 有效期 / 标签） | ⚠️ 无 couponCode，仅供展示与交叉核对 |
| 麦麦省券 | `available-coupons` | **Markdown 文本**（券名 / 状态：可领取） | ❌ 需先 auto-bind-coupons 领取 |

因此三池聚合的价值不是「简单相加」，而是：
  1. 以「门店券」为**可核价主集**（唯一带 couponCode 的池）；
  2. 用「我的券」交叉核对用户是否**真的拥有**某券（按券名去重）；
  3. 把「麦麦省券」列为**可领取扩池**建议（先领再比价，可能新增可用券）。

本模块只做解析与聚合，权威判定仍以 calculate-price 为准。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# ---- 我的券（query-my-coupons）Markdown 解析 ----
_RE_MY_PRICE = re.compile(r"\*\*优惠\*\*:\s*(.+)")
_RE_MY_VALID = re.compile(r"\*\*有效期\*\*:\s*(.+)")
_RE_MY_TAG = re.compile(r"\*\*标签\*\*:\s*(.+)")
_RE_IMG = re.compile(r'<img src="([^"]+)"')
_RE_CID_IN_IMG = re.compile(r"/([0-9A-Fa-f]{32})\.png")
_RE_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_RE_TIME_WINDOW = re.compile(r"(\d{1,2}:\d{2})-(\d{1,2}:\d{2})")


def parse_valid_period(text: str):
    """解析有效期字符串 -> (valid_from, expires_at, time_windows)。

    真实 observe：我的券有效期形如
        "2026-10-10 00:00-2026-11-08 23:59 05:00-23:59"
    即「起-止日期」+「每日可用时段(05:00-23:59)」。
    日期取前两个；末段 HH:MM-HH:MM 为每日时段窗。
    """
    t = text or ""
    dates = _RE_DATE.findall(t)
    windows = [(s, e) for s, e in _RE_TIME_WINDOW.findall(t)]
    valid_from = dates[0] if dates else None
    expires_at = dates[1] if len(dates) > 1 else (dates[0] if dates else None)
    return valid_from, expires_at, windows


def parse_my_coupons_text(text: str) -> List[Dict[str, Any]]:
    """解析 `query-my-coupons` 的 Markdown，返回券条目列表。

    每条含：name / price_text / valid_period / expires_at / tag / image / coupon_id。
    coupon_id 仅在图片文件名是 32 位十六进制时可得（部分券图片是中文名，取不到）。
    """
    out: List[Dict[str, Any]] = []
    blocks = re.split(r"^##\s+", text, flags=re.MULTILINE)[1:]
    for b in blocks:
        name = b.splitlines()[0].strip()
        if not name:
            continue

        def field(rx):
            m = rx.search(b)
            return m.group(1).strip() if m else None

        price = field(_RE_MY_PRICE)
        valid = field(_RE_MY_VALID)
        tag = field(_RE_MY_TAG)
        img = _RE_IMG.search(b)
        image = img.group(1) if img else None
        cid = None
        if image:
            m = _RE_CID_IN_IMG.search(image)
            if m:
                cid = m.group(1).upper()
        # 有效期形如 "2026-10-10 00:00-2026-11-08 23:59 05:00-23:59"
        valid_from, expires_at, windows = parse_valid_period(valid)
        out.append(
            {
                "name": name,
                "price_text": price,
                "valid_period": valid,
                "valid_from": valid_from,
                "expires_at": expires_at,
                "time_windows": windows,
                "tag": tag,
                "image": image,
                "coupon_id": cid,
            }
        )
    return out


# ---- 麦麦省券（available-coupons）Markdown 解析 ----
def parse_available_coupons_text(text: str) -> List[Dict[str, Any]]:
    """解析 `available-coupons` 的 Markdown，返回可领取券条目。

    每条含：title / status / image。
    """
    out: List[Dict[str, Any]] = []
    chunks = re.split(r"^-\s*优惠券标题：", text, flags=re.MULTILINE)[1:]
    for ch in chunks:
        title = ch.split("\\")[0].strip()
        if not title:
            continue
        st = re.search(r"状态：\s*([^\s\\]+)", ch)
        img = _RE_IMG.search(ch)
        out.append(
            {
                "title": title,
                "status": st.group(1) if st else None,
                "image": img.group(1) if img else None,
            }
        )
    return out


def collect_coupon_pools(
    client,
    store_code: str,
    order_type: int = 1,
    be_type: int = 1,
    include_claimable: bool = True,
) -> Dict[str, Any]:
    """聚合三池券，返回结构化结果。

    返回：
        {
          "store":     [结构化券 dict ...],     # 可核价主集
          "mine":      [解析后的我的券 dict ...],
          "claimable": [可领取券 dict ...],
          "overlap":   [门店券与我的券重名的券名 ...],
          "warnings":  [str ...],
        }
    """
    pools: Dict[str, Any] = {"store": [], "mine": [], "claimable": [], "overlap": [], "warnings": []}

    store_raw = client.call_tool(
        "query-store-coupons", {"storeCode": store_code, "orderType": order_type, "beType": be_type}
    )
    if isinstance(store_raw, list):
        pools["store"] = store_raw
    elif isinstance(store_raw, dict) and isinstance(store_raw.get("data"), list):
        pools["store"] = store_raw["data"]

    mine_text = client.call_tool_text("query-my-coupons", {})
    pools["mine"] = parse_my_coupons_text(mine_text)

    if include_claimable:
        av_text = client.call_tool_text("available-coupons", {})
        pools["claimable"] = parse_available_coupons_text(av_text)

    # 交叉核对：门店券与我的券按券名去重
    store_titles = {(c.get("title") or "").strip() for c in pools["store"]}
    mine_names = {(c.get("name") or "").strip() for c in pools["mine"]}
    pools["overlap"] = sorted(store_titles & mine_names)

    if pools["claimable"]:
        pools["warnings"].append(
            f"有 {len(pools['claimable'])} 张『麦麦省』券可领取，"
            f"先调用 auto-bind-coupons 领取后券池可能扩大（再查一次门店券/我的券更准）"
        )
    if not pools["store"]:
        pools["warnings"].append("当前门店无可直接核价的门店券（门店券是唯一带 couponCode 的池）")

    return pools
