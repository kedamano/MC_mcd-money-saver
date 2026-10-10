"""麦麦省钱助手 · 进阶能力真实演示（多店比价 + 套餐 + 领券扩池）

真跑 McDonald's MCP（需环境变量 MCD_MCP_TOKEN），串联 Task 22/23/24 三项新增能力：
  1. 一键领券扩池（auto-bind-coupons）：领券前后三池对比
  2. 套餐省钱（query-meals + query-meal-detail → combo_optimizer）
  3. 多店比价（query-nearby-stores → store_optimizer）
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.combo_optimizer import Combo, combo_from_detail, rank_combo_deals  # noqa: E402
from src.coupon_pools import collect_and_bind_coupons  # noqa: E402
from src.mcd_client import McDonaldMCPClient  # noqa: E402
from src.store_optimizer import collect_store_quotes, optimize_across_stores  # noqa: E402


def hr(t):
    print("\n" + "=" * 68 + f"\n{t}\n" + "=" * 68)


def main():
    token = os.environ.get("MCD_MCP_TOKEN")
    if not token:
        print("请设置 MCD_MCP_TOKEN 环境变量")
        return
    c = McDonaldMCPClient(token=token)

    # 1) 一键领券扩池
    hr("① 一键领券扩池（auto-bind-coupons）")
    r = collect_and_bind_coupons(c, "1450104")
    print(f"  领取前：门店券 {r['before']['store']} / 我的券 {r['before']['mine']} / 可领取 {r['before']['claimable']}")
    print(f"  领取后：门店券 {r['after']['store']} / 我的券 {r['after']['mine']} / 可领取 {r['after']['claimable']}")
    print(f"  净增：门店券 +{r['gained_store']}，我的券 +{r['gained_mine']}")

    # 2) 套餐省钱
    hr("② 套餐省钱（套餐 vs 单点）")
    menu = c.call_tool("query-meals", {"storeCode": "1450104", "orderType": 1, "beType": 1})
    meals = (menu or {}).get("meals", {})
    price_map = {code: float(m.get("currentPrice", 0)) for code, m in meals.items()}
    KEY = ("套餐", "三件套", "四件套", "随心选")
    combos = []
    for code, m in meals.items():
        if not any(k in (m.get("name") or "") for k in KEY):
            continue
        try:
            d = c.call_tool("query-meal-detail",
                            {"storeCode": "1450104", "code": code, "orderType": 1, "beType": 1})
        except Exception:
            continue
        if isinstance(d, dict) and "rounds" in d:
            combos.append(combo_from_detail(d, price=float(m.get("currentPrice", 0)), price_map=price_map))
    deals = rank_combo_deals(combos, price_map, top_k=5)
    print(f"  识别套餐 {len(combos)} 个，其中更划算 {len(deals)} 个：")
    for d in deals:
        print(f"    {d['name']}: 单点 ¥{d['matched_individual_sum']:.2f} → 套餐 ¥{d['combo_price']:.2f}"
              f"  至少省 ¥{d['saving']:.2f}（{d['saving_pct']*100:.1f}%）")

    # 3) 多店比价
    hr("③ 多店比价（可接受距离内求最优）")
    stores = c.call_tool("query-nearby-stores",
                         {"beType": 1, "searchType": 2, "city": "上海", "keyword": "南京东路"})
    stores = [s for s in stores if s.get("businessStatus")]
    wanted = {"4810": 1, "520689": 1}  # 中薯条 + 鲜萃咖啡
    quotes = collect_store_quotes(c, stores, wanted)
    res = optimize_across_stores(quotes, wanted, max_distance_m=1000)
    for e in res["ranked"]:
        flag = "  ← 最优" if res["best"] and e["store_code"] == res["best"]["store_code"] else ""
        print(f"    {e['distance_m']:>4.0f}m  {e['store_name'][:24]:24s} 到手 ¥{e['payable']:.2f}{flag}")
    if res["trade_off"]:
        t = res["trade_off"]
        print(f"  权衡：最优店比最近店多走 {t['extra_distance_m']}m，省 ¥{t['saved']:.2f}")


if __name__ == "__main__":
    main()
