"""
麦麦省钱助手 - 领域异常（供 MCP 客户端与优化器共享，避免循环依赖）

为什么必须区分这两类失败（真实依据 2026-10-10 实测）：
  - `calculate-price` 传入「到店专用」券做外送核价时，官方返回
        {"success": false, "code": 600012, "message": "当前优惠券不可用！"}
    这是**业务拒绝**——该券在该渠道根本用不了，属于「方案无效」。
  - 另一类失败是网络抖动 / 5xx / 429，属于「暂时算不出来」，可降级为本地估计。

若二者混为一谈，会出现最坏结果：**被官方明确拒绝的方案，因为降级/解析出的
估计价更便宜而胜出**（旧实现中该错误响应甚至会被解析成 ¥0.00）。
"""

from __future__ import annotations

# 官方明确「因券被拒」的业务码：渠道不符 / 多券叠加
BUSINESS_REJECT_CODES: frozenset = frozenset({600012, 600022})


class MCPBusinessError(RuntimeError):
    """MCP 业务层失败（信封 success=false），如门店不可售、参数缺失。"""

    def __init__(self, code=None, message: str = "", raw=None) -> None:
        self.code = code
        self.message = message or ""
        self.raw = raw
        super().__init__(f"[{code}] {self.message}".strip())


class CouponRejectedError(MCPBusinessError):
    """官方明确拒绝该优惠券（渠道不符 600012 / 多券叠加 600022 等）。

    语义：该候选方案**无效**。优化器必须将其剔除，绝不可降级为本地估计。
    """


def raise_if_business_error(data) -> None:
    """检测 MCP 业务信封是否为失败；失败则抛出对应异常。

    仅当传入 dict 且 ``success is False`` 时才视为业务失败——成功响应会被
    ``extract_business_data`` 剥成业务 data，不含 ``success`` 字段。
    """
    if not isinstance(data, dict) or data.get("success") is not False:
        return
    code = data.get("code")
    message = data.get("message") or ""
    if code in BUSINESS_REJECT_CODES or "券" in message:
        raise CouponRejectedError(code, message, data)
    raise MCPBusinessError(code, message, data)
