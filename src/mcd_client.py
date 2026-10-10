"""
麦麦省钱助手 - 麦当劳 MCP 真实客户端（Streamable HTTP）

这是「真实接入麦当劳 MCP」的代码载体：仓库之前仅有 SKILL.md 中的 LLM 调用指令，
本模块提供可在 Python 中直接运行的客户端，覆盖 initialize / list_tools / call_tool，
并把真实的「外层 JSON-RPC 信封 + content[0].text 内嵌业务 JSON」双层结构解析干净。

仅依赖标准库（urllib），无需第三方包，便于离线单测与任意环境部署。

Author: 麦麦省钱助手参赛项目
"""

from __future__ import annotations

import json
import re
import urllib.request
from typing import Any, Dict, List, Optional


class McDonaldMCPClient:
    """麦当劳中国 MCP Server 的 Streamable HTTP 客户端。

    用法：
        client = McDonaldMCPClient(token="<MCD_MCP_TOKEN>")
        client.initialize()                       # 建立会话，获取 Mcp-Session-Id
        tools = client.list_tools()               # 拉取全部工具
        data = client.call_tool("now-time-info", {})  # 调用工具，返回业务 data 字典
    """

    def __init__(
        self,
        token: str,
        base_url: str = "https://mcp.mcd.cn/",
        protocol_version: str = "2025-03-26",
    ) -> None:
        self.token = token
        self.base_url = base_url
        self.protocol_version = protocol_version
        self._session_id: Optional[str] = None
        self._req_id = 0

    # ----- 请求体构造（可单测）-----
    def build_body(self, method: str, params: Dict[str, Any], req_id: int) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    # ----- 底层 POST -----
    def _post(self, body: Dict[str, Any]) -> str:
        data = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.token}",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        req = urllib.request.Request(self.base_url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if not self._session_id:
                    self._session_id = resp.headers.get("Mcp-Session-Id")
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:  # 401/403/500 等
            detail = e.read().decode("utf-8", "ignore")[:300]
            raise RuntimeError(f"MCP HTTP {e.code}: {detail}") from e

    # ----- 高层调用 -----
    def initialize(self) -> Dict[str, Any]:
        body = self.build_body(
            "initialize",
            {
                "protocolVersion": self.protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "mcd-money-saver", "version": "1.0.0"},
            },
            req_id=self._next_id(),
        )
        envelope = parse_mcp_envelope(self._post(body))
        return envelope.get("result", {})

    def list_tools(self) -> List[Dict[str, Any]]:
        body = self.build_body("tools/list", {}, req_id=self._next_id())
        envelope = parse_mcp_envelope(self._post(body))
        return envelope.get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """调用工具，返回业务 data 字典（已剥离外层信封与 text 内嵌 JSON）。"""
        body = self.build_body(
            "tools/call", {"name": name, "arguments": arguments}, req_id=self._next_id()
        )
        envelope = parse_mcp_envelope(self._post(body))
        return extract_business_data(envelope)

    # ----- 省钱核心：官方核价（D 两阶段校验的真实实现）-----
    def price_combo(
        self,
        store_code: str,
        items: List[Dict[str, Any]],
        coupons: Optional[List[Dict[str, Any]]] = None,
        order_type: int = 1,
        be_type: int = 1,
        need_tableware: bool = False,
    ) -> Dict[str, Any]:
        """调用 calculate-price 获取官方权威金额（单位：分）。

        参数：
            items:   [{"product_code": "520689", "quantity": 1}, ...]
            coupons: [{"coupon_code": "MCD...", "coupon_id": "365A..."}, ...]（可选）
        返回业务 data：含 originalPrice / discount / price / packingPrice 等（分）。
        """
        priced_items = []
        for it in items:
            entry: Dict[str, Any] = {
                "productCode": it["product_code"],
                "quantity": it.get("quantity", 1),
            }
            priced_items.append(entry)
        # 把券按 item 维度挂接（麦当劳 calculate-price 在 items[].couponCode/couponId 传券）
        if coupons:
            # 简单策略：所有券挂到第一个商品上由官方判定能否叠加
            first = priced_items[0]
            for c in coupons:
                first.setdefault("couponCode", c["coupon_code"])
                first.setdefault("couponId", c["coupon_id"])
        arguments = {
            "storeCode": store_code,
            "orderType": order_type,
            "beType": be_type,
            "needTableware": need_tableware,
            "items": priced_items,
        }
        return self.call_tool("calculate-price", arguments)

    @staticmethod
    def price_combo_as_fn(store_code: str, order_type: int = 1, be_type: int = 1):
        """生成一个可直接作为 two_stage_optimize(pricing_fn=...) 的回调。

        回调签名 (subset_coupons: List[Coupon], items: List[Item]) -> float（元）。
        内部用环境变量 MCD_MCP_TOKEN 初始化客户端，对 Top-K 候选逐一核价。
        """
        import os
        from src.coupon_optimizer import Coupon, Item

        token = os.environ.get("MCD_MCP_TOKEN", "")
        client = McDonaldMCPClient(token=token)

        def _fn(subset_coupons: List[Coupon], items: List[Item]) -> float:
            product_items = [
                {"product_code": i.product_code or "", "quantity": 1}
                for i in items
                if i.product_code
            ]
            coupon_args = [
                {
                    "coupon_code": c.coupon_code or c.id,
                    "coupon_id": c.coupon_id or c.id,
                }
                for c in subset_coupons
            ]
            data = client.price_combo(store_code, product_items, coupon_args, order_type, be_type)
            price_fen = data.get("price") or data.get("originalPrice") or 0
            return round(price_fen / 100.0, 2)

        return _fn


# ---------------------------------------------------------------------------
# 协议解析（纯函数，可单测）
# ---------------------------------------------------------------------------
def parse_mcp_envelope(raw: str) -> Dict[str, Any]:
    """解析 MCP Streamable HTTP 响应。

    兼容两种形态：
    - 纯 JSON：{"jsonrpc":..., "result":...}
    - SSE：多行 `data: {...}` —— 取最后一个 data 块
    返回 JSON 对象字典。
    """
    raw = raw.strip()
    if raw.startswith("{"):
        return json.loads(raw)
    # SSE 形态
    blocks = re.findall(r"data:\s*(\{.*\})", raw, flags=re.DOTALL)
    if blocks:
        return json.loads(blocks[-1])
    return json.loads(raw)  # 兜底


def extract_business_data(envelope: Dict[str, Any]) -> Any:
    """从 tools/call 信封中取出业务 JSON（可能是 dict 或 list）。

    真实 observe：result.content[0].text 是一段「说明文字 + 业务 JSON + 说明文字」，
    需用 raw_decode 从第一个 '{' 精确解析，不能直接 json.loads 整段。
    """
    result = envelope.get("result")
    if not isinstance(result, dict):
        raise ValueError("缺少 result 字段")
    content = result.get("content")
    if not content or not isinstance(content, list):
        raise ValueError("缺少 content[0].text")
    text = content[0].get("text", "")
    if not text:
        raise ValueError("content[0].text 为空")
    decoder = json.JSONDecoder()
    # 真实 observe：text = 「人读说明 + 业务 JSON + 尾部说明」。
    # 说明文字里可能含有 `{code}` 这类占位符（如 query-meals 的字段表），
    # 直接取「第一个 {」会解析到占位符而抛 JSONDecodeError。
    # 业务 JSON 固定以 `{"success"` 开头，优先据此精确定位；否则回退逐个 { 试解。
    idx = text.find('{"success"')
    if idx >= 0:
        data, _ = decoder.raw_decode(text, idx)
    else:
        data = None
        pos = 0
        while True:
            i = text.find("{", pos)
            if i < 0:
                break
            try:
                data, _ = decoder.raw_decode(text, i)
                break
            except json.JSONDecodeError:
                pos = i + 1
        if data is None:
            raise ValueError("text 中未找到业务 JSON")
    # 真实 observe：外层为网关信封 {success, code, message, data:{...}} 
    # 业务 data 既可能是 dict（如 now-time-info / query-meals），
    # 也可能是 **list**（如 query-nearby-stores / query-store-coupons）。
    # 只要是「网关信封形态」(含 success/code/message) 且 data 为 dict/list，就拆到业务层。
    if (
        isinstance(data, dict)
        and ("success" in data or "code" in data or "message" in data)
        and isinstance(data.get("data"), (dict, list))
    ):
        return data["data"]
    return data
