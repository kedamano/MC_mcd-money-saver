"""
麦麦省钱助手 - 多店比价 + 距离权衡（Task 24）

背景（2026-10-10 真机实测，上海南京东路商圈）：
  - **同城同品不同价**是真的：中薯条(4810) 在多数门店 ¥13.50，但在
    「上海食品一店(1450056)」为 ¥14.50；门店间距仅几百米。
  - 之前的逻辑只取「最近门店」，会系统性错过更便宜的门店（或更划算的券）。

本模块在「可接受距离内」比较多家门店的**到手价**（商品 + 配送 - 最优券），
求全局最低，并给出**为省这笔钱要多走多少米**的权衡，避免盲目推荐远店。

纯函数（不联网）；真实数据采集见 `collect_store_quotes`。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.coupon_optimizer import Coupon, Item, optimize_coupons

_RE_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*折")
_RE_SPECIAL = re.compile(r"^(\d+(?:\.\d+)?)\s*元")
_RE_FULL_CUT = re.compile(r"满\s*(\d+(?:\.\d+)?)\s*减\s*(\d+(?:\.\d+)?)")
_RE_CUT = re.compile(r"立减\s*(\d+(?:\.\d+)?)")


@dataclass
class StoreQuote:
    """一家门店的报价（用于跨店比价）。

    prices:    {product_code: 单点价}（该店的菜单价）
    coupons:   该店可用门店券的原始 JSON 列表（结构见 references/mcp_tools.md）
    delivery_fee: 该店配送费（到店为 0）
    """

    store_code: str
    store_name: str
    distance_m: float
    prices: Dict[str, float] = field(default_factory=dict)
    coupons: List[dict] = field(default_factory=list)
    delivery_fee: float = 0.0


def coupon_from_store_json(j: dict, price_map: Dict[str, float]) -> Optional[Coupon]:
    """把门店券 JSON 转成优化器 Coupon（按标题推断券型）。

    可识别：
      - "…7折"        → percent（折扣率 0.7）
      - "9.9元中杯冰美式" → fixed（特价：优惠 = 绑定商品原价 - 9.9）
      - "满60减12"     → threshold
      - "立减5元"      → fixed
    券绑定 products[].productCode；无法识别或无绑定商品时返回 None。
    """
    title = (j.get("title") or "").strip()
    product_codes = [str(p.get("productCode")) for p in (j.get("products") or []) if p.get("productCode")]
    cid = j.get("couponId")
    ccode = j.get("couponCode")

    def _mk(kind, **kw):
        return Coupon(id=title or str(cid), kind=kind, coupon_code=ccode, coupon_id=cid,
                      product_codes=product_codes, **kw)

    m = _RE_FULL_CUT.search(title)
    if m:
        return _mk("threshold", threshold=float(m.group(1)), discount=float(m.group(2)))
    m = _RE_CUT.search(title)
    if m:
        return _mk("fixed", discount=float(m.group(1)))
    m = _RE_PERCENT.search(title)
    if m:
        return _mk("percent", discount=float(m.group(1)) / 10.0)
    m = _RE_SPECIAL.search(title)
    if m and len(product_codes) == 1:
        target = float(m.group(1))
        base = price_map.get(product_codes[0])
        if base is not None and base - target > 0:
            return _mk("fixed", discount=round(base - target, 2))
        return None
    return None


def best_coupon_saving(
    coupons_json: List[dict], wanted: Dict[str, int], price_map: Dict[str, float],
    name_map: Optional[Dict[str, str]] = None,
) -> float:
    """该店针对给定购物车的最优券节省（每单至多一张券）。"""
    name_map = name_map or {}
    coupons: List[Coupon] = []
    for j in coupons_json or []:
        c = coupon_from_store_json(j, price_map)
        if c is not None:
            coupons.append(c)
    if not coupons:
        return 0.0
    items: List[Item] = []
    for code, q in wanted.items():
        if code not in price_map:
            continue
        for _ in range(q):
            items.append(Item(name=name_map.get(code, code), price=float(price_map[code]), product_code=code))
    if not items:
        return 0.0
    return optimize_coupons(items, coupons, max_coupons_per_order=1)["saved"]


def evaluate_quote(
    quote: StoreQuote, wanted: Dict[str, int], name_map: Optional[Dict[str, str]] = None
) -> Dict:
    """计算单店到手价与可行性。缺少任一商品（不可售）则不可行。"""
    missing = [code for code in wanted if code not in quote.prices]
    if missing:
        return {
            "store_code": quote.store_code, "store_name": quote.store_name,
            "distance_m": quote.distance_m, "feasible": False,
            "missing": missing, "items_total": None, "coupon_saving": 0.0,
            "delivery_fee": quote.delivery_fee, "payable": None,
        }
    items_total = round(sum(float(quote.prices[c]) * q for c, q in wanted.items()), 2)
    saving = best_coupon_saving(quote.coupons, wanted, quote.prices, name_map)
    payable = round(items_total - saving + quote.delivery_fee, 2)
    return {
        "store_code": quote.store_code, "store_name": quote.store_name,
        "distance_m": quote.distance_m, "feasible": True, "missing": [],
        "items_total": items_total, "coupon_saving": round(saving, 2),
        "delivery_fee": round(quote.delivery_fee, 2), "payable": payable,
    }


def optimize_across_stores(
    quotes: List[StoreQuote],
    wanted: Dict[str, int],
    *,
    max_distance_m: Optional[float] = None,
    name_map: Optional[Dict[str, str]] = None,
) -> Dict:
    """在可接受距离内比较多家门店，求到手价最低的门店并量化距离权衡。

    max_distance_m: 可接受的最大距离（米）；超出者剔除（不推荐为省几毛钱走太远）。

    返回：
        {
          "best":       到手价最低且可行的门店（dict）或 None,
          "nearest":    最近且可行的门店（dict）或 None,
          "ranked":     可行门店按到手价升序（并列时近者优先）,
          "trade_off":  {"extra_distance_m","saved","best_store","nearest_store"},
          "notes":      [str...],
        }
    """
    notes: List[str] = []
    feasible: List[Dict] = []
    too_far: List[Dict] = []
    for q in quotes:
        ev = evaluate_quote(q, wanted, name_map)
        if not ev["feasible"]:
            notes.append(f"{q.store_name} 缺少商品 {ev['missing']}，不可行")
            continue
        if max_distance_m is not None and q.distance_m > max_distance_m:
            too_far.append(ev)
            continue
        feasible.append(ev)

    if too_far:
        notes.append(f"有 {len(too_far)} 家门店超出可接受距离 {int(max_distance_m)}m，已排除")

    ranked = sorted(feasible, key=lambda e: (e["payable"], e["distance_m"]))
    best = ranked[0] if ranked else None
    nearest = min(feasible, key=lambda e: e["distance_m"]) if feasible else None

    trade_off = None
    if best is not None and nearest is not None:
        trade_off = {
            "best_store": best["store_code"],
            "nearest_store": nearest["store_code"],
            "extra_distance_m": int(round(best["distance_m"] - nearest["distance_m"])),
            "saved": round(nearest["payable"] - best["payable"], 2),
        }

    return {"best": best, "nearest": nearest, "ranked": ranked,
            "excluded_far": too_far, "trade_off": trade_off, "notes": notes}


def collect_store_quotes(
    client,
    stores: List[dict],
    wanted: Dict[str, int],
    *,
    order_type: int = 1,
    be_type: int = 1,
    be_code: Optional[str] = None,
    include_coupons: bool = True,
) -> List[StoreQuote]:
    """从 MCP 客户端采集多店报价（真实数据）。

    stores: query-nearby-stores 返回的门店列表（含 storeCode / storeName / distance）。
    对每家门店拉取菜单价（wanted 涉及的商品）与门店券。
    """
    out: List[StoreQuote] = []
    for s in stores:
        code = s.get("storeCode")
        if not code:
            continue
        args = {"storeCode": code, "orderType": order_type, "beType": be_type}
        if be_code:
            args["beCode"] = be_code
        prices: Dict[str, float] = {}
        try:
            menu = client.call_tool("query-meals", args)
            meals = (menu or {}).get("meals", {}) if isinstance(menu, dict) else {}
            for w in wanted:
                if w in meals:
                    prices[w] = float(meals[w].get("currentPrice", 0))
        except Exception:  # noqa: BLE001 单店失败不影响其他门店
            pass
        coupons: List[dict] = []
        if include_coupons:
            try:
                cj = client.call_tool("query-store-coupons", args)
                if isinstance(cj, list):
                    coupons = cj
            except Exception:  # noqa: BLE001
                pass
        out.append(
            StoreQuote(
                store_code=str(code),
                store_name=s.get("storeName") or str(code),
                distance_m=float(s.get("distance") or 0),
                prices=prices,
                coupons=coupons,
            )
        )
    return out
