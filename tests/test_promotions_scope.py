"""query-promotions 适用范围 —— 真实结论契约（Task 23）。

真实依据（2026-10-10 实测 mcp.mcd.cn，上海悦荟广场 1450104）：
  - `query-promotions` 返回的促销规则 **beTypes 全部为 ["6"]**（企业团餐专属），
    普通到店（beType=1）/ 外送（beType=2）拿不到。
  - 外送（orderType=2）缺 beCode 时返回 code=600048。

结论：促销**不能**作为面向普通用户的省钱渠道接入优化器——本项目据此把
省钱候选收缩为「券 + 套餐」，把力气花在真实可用的渠道上（避免虚假承诺）。
"""

from __future__ import annotations

import json
import os

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _load():
    with open(os.path.join(FIX, "promotions_by_context.json"), encoding="utf-8") as f:
        return json.load(f)


def test_promotions_are_enterprise_only():
    """真实事实：所有促销规则的 beTypes 恒为 ["6"]（企业团餐），普通用户不可用。"""
    data = _load()
    to_store = data["1_1"]  # orderType=1 到店, beType=1
    assert isinstance(to_store, list) and to_store, "到店应能取到促销规则清单"
    all_types = set()
    for p in to_store:
        for t in p.get("beTypes") or []:
            all_types.add(str(t))
    assert all_types == {"6"}, f"促销应为企业团餐专属，实际 beTypes={sorted(all_types)}"


def test_delivery_promotions_require_becode():
    """外送查促销缺 beCode → code=600048（与其它外送接口一致）。"""
    data = _load()
    d = data["2_1"]
    assert isinstance(d, dict)
    assert d.get("code") == 600048
    assert "beCode" in (d.get("message") or "")
