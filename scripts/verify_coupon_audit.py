"""真机验证：券数核对 + 双标签渠道判定。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.mcd_client import McDonaldMCPClient  # noqa: E402
from src.coupon_pools import audit_my_coupons  # noqa: E402

TOKEN = os.environ.get("MCD_MCP_TOKEN", "")


def main() -> None:
    c = McDonaldMCPClient(token=TOKEN)
    c.initialize()
    now = "2026-10-10 16:02"

    r = audit_my_coupons(c, now=now)
    a = r["audit"]
    print("=== 券数核对（now = %s）===" % now)
    for k, v in a.items():
        print(f"  {k:>14}: {v}")

    print("\n=== 逐券分类 ===")
    for it in r["items"]:
        print(
            f"  {it['name']:<22} | {it.get('valid_from')}~{it.get('expires_at')}"
            f" | win={it.get('time_windows')} | ch={it.get('channel')}"
        )

    # 双标签券的渠道判定（修复前为 delivery）
    both = [it for it in r["items"] if it.get("name") == "9.9元中杯冰美式"]
    if both:
        print(f"\n[双标签券] 9.9元中杯冰美式 channel = {both[0].get('channel')!r}"
              f"  （修复目标：None = 不限渠道；修复前误判为 'delivery'）")


if __name__ == "__main__":
    main()
