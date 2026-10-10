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
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

try:  # 兼容「从项目根导入(src.xxx)」与「包内直接导入」两种方式
    from src.errors import (  # noqa: F401
        CouponRejectedError,
        MCPBusinessError,
        raise_if_business_error,
    )
except ImportError:  # pragma: no cover
    from errors import (  # type: ignore
        CouponRejectedError,
        MCPBusinessError,
        raise_if_business_error,
    )


class MCPTransientError(RuntimeError):
    """MCP 瞬时错误（网络抖动 / 5xx / 偶发 404 / 429 限流），可重试。"""


class MCPCircuitOpen(RuntimeError):
    """熔断器打开：连续失败过多，冷却期内直接拒绝，避免雪崩。"""


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
        retries: int = 2,
        circuit_threshold: int = 3,
        circuit_cooldown: float = 30.0,
    ) -> None:
        self.token = token
        self.base_url = base_url
        self.protocol_version = protocol_version
        self._session_id: Optional[str] = None
        self._req_id = 0
        # 健壮性参数（见 C 优化项）
        self.retries = retries
        self.circuit_threshold = circuit_threshold
        self.circuit_cooldown = circuit_cooldown
        self._fail_count = 0
        self._circuit_open_until = 0.0
        # 读接口 TTL 缓存：(name, args_json) -> (expire_at, value)
        self._cache: Dict[Tuple[str, str], Tuple[float, Any]] = {}

    # ----- 请求体构造（可单测）-----
    def build_body(self, method: str, params: Dict[str, Any], req_id: int) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    # ----- 底层 POST -----
    # 可重试的瞬时 HTTP 状态（含联调中实测的「偶发 404」与 429 限流）
    _TRANSIENT_CODES = {404, 408, 425, 429, 500, 502, 503, 504}

    def _post_once(self, body: Dict[str, Any]) -> str:
        """单次 POST（不含重试），供重试器与测试桩替换。"""
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
            if e.code in self._TRANSIENT_CODES:
                raise MCPTransientError(f"MCP HTTP {e.code}: {detail}") from e
            raise RuntimeError(f"MCP HTTP {e.code}: {detail}") from e

    def _post(self, body: Dict[str, Any], retry: bool = True) -> str:
        """带「重试 + 熔断」的 POST。

        - 仅对**瞬时错误**（网络抖动 / 5xx / 偶发 404 / 429）重试，指数退避；
        - 连续失败达阈值后**熔断**，冷却期内直接拒绝，避免雪崩；
        - `retry=False` 用于**非幂等/有副作用**的调用（如 create-order 下单），杜绝重试导致重复下单。
        """
        if time.time() < self._circuit_open_until:
            raise MCPCircuitOpen(
                f"MCP 熔断中，{self._circuit_open_until - time.time():.0f}s 后重试"
                f"（连续失败 {self._fail_count} 次）"
            )
        attempt = 0
        while True:
            try:
                result = self._post_once(body)
                self._fail_count = 0
                return result
            except MCPTransientError as e:
                if not retry or attempt >= self.retries:
                    self._fail_count += 1
                    if self._fail_count >= self.circuit_threshold:
                        self._circuit_open_until = time.time() + self.circuit_cooldown
                    raise
                attempt += 1
                time.sleep(min(0.5 * (2 ** (attempt - 1)), 4.0))

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

    def call_tool(self, name: str, arguments: Dict[str, Any], retry: bool = True) -> Any:
        """调用工具，返回业务 data（已剥离外层信封与 text 内嵌 JSON，可能是 dict 或 list）。

        retry=False 用于有副作用的调用（如 create-order），避免重试导致重复执行。
        """
        body = self.build_body(
            "tools/call", {"name": name, "arguments": arguments}, req_id=self._next_id()
        )
        envelope = parse_mcp_envelope(self._post(body, retry=retry))
        return extract_business_data(envelope)

    def call_tool_cached(
        self, name: str, arguments: Dict[str, Any], ttl: float = 300.0
    ) -> Any:
        """带 TTL 缓存的读接口调用（C 优化项）。

        门店 / 菜单 / 券在短时间内变化不大，缓存可减少重复 MCP 调用、节省配额并降低限流风险。
        仅用于**读接口**；勿用于 create-order 等有副作用的调用。
        """
        key = (name, json.dumps(arguments, sort_keys=True, ensure_ascii=False))
        now = time.time()
        hit = self._cache.get(key)
        if hit and now < hit[0]:
            return hit[1]
        value = self.call_tool(name, arguments)
        self._cache[key] = (now + ttl, value)
        return value

    def call_tool_text(self, name: str, arguments: Dict[str, Any], retry: bool = True) -> str:
        """调用工具，返回 content[0].text 原始文本。

        真实 observe：并非所有工具都返回结构化 JSON——例如
        `query-my-coupons` / `available-coupons` 返回的是 **Markdown 文本**，
        没有 {success,...} 信封，须用本方法取原文后再做文本解析（见 coupon_pools）。
        """
        body = self.build_body(
            "tools/call", {"name": name, "arguments": arguments}, req_id=self._next_id()
        )
        envelope = parse_mcp_envelope(self._post(body, retry=retry))
        content = envelope.get("result", {}).get("content")
        if not content or not isinstance(content, list):
            raise ValueError(f"{name} 返回缺少 content[0].text")
        return content[0].get("text", "")

    # ----- 省钱核心：官方核价（D 两阶段校验的真实实现）-----
    def price_combo(
        self,
        store_code: str,
        items: List[Dict[str, Any]],
        coupons: Optional[List[Dict[str, Any]]] = None,
        order_type: int = 1,
        be_type: int = 1,
        need_tableware: bool = False,
        be_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """调用 calculate-price 获取官方权威金额（单位：分）。

        参数：
            items:   [{"product_code": "520689", "quantity": 1}, ...]
            coupons: [{"coupon_code": "MCD...", "coupon_id": "365A..."}, ...]（可选）
            be_code: 外送场景必传（beType=2/5/6）。真实 observe：外送不传 beCode
                     返回 code=600048「外送场景下，beType=2/5/6时必传beCode」；
                     beCode 来自 `delivery-query-stores` 返回的外送门店。
        返回业务 data：含 originalPrice / discount / price / packingPrice /
                     deliveryPrice（配送费，分）等。
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
        if be_code:
            arguments["beCode"] = be_code
        data = self.call_tool("calculate-price", arguments)
        # 真实 observe：券被拒时返回 {"success":false,"code":600012,...} 且**无 price 字段**。
        # 若不在此拦截，调用方取值会退化为 ¥0，导致「被官方拒绝的方案反而最便宜」。
        raise_if_business_error(data)
        return data

    # ----- 外送场景（麦乐送）链路封装 -----
    def query_delivery_addresses(self) -> Any:
        """查询用户配送地址列表（delivery-query-addresses）。

        返回 {"addresses": [...]}；地址簿为空时返回 {"addresses": []}。
        """
        return self.call_tool("delivery-query-addresses", {})

    def create_delivery_address(
        self,
        city: str,
        address: str,
        address_detail: str,
        contact_name: str,
        phone: str,
        gender: Optional[str] = None,
    ) -> Any:
        """创建配送地址（delivery-create-address）。

        ⚠️ 有副作用：会真实写入用户 McDonald's 账户地址簿。调用前须经用户确认。
        phone 必须为 11 位纯数字。返回新地址（含 addressId，供 delivery-query-stores 使用）。
        """
        args: Dict[str, Any] = {
            "city": city,
            "address": address,
            "addressDetail": address_detail,
            "contactName": contact_name,
            "phone": phone,
        }
        if gender:
            args["gender"] = gender
        return self.call_tool("delivery-create-address", args, retry=False)

    def query_delivery_stores(self, address_id: str, be_type: int = 2) -> Any:
        """按地址查询可配送门店（delivery-query-stores）。

        be_type：2=麦乐送，6=团餐。返回的门店含 **beCode**（外送核价/下单必传）。
        """
        return self.call_tool(
            "delivery-query-stores", {"beType": be_type, "addressId": address_id}
        )

    @staticmethod
    def pick_take_way(price_data: Dict[str, Any], prefer: str = "take-in-store") -> Optional[str]:
        """从 calculate-price 返回的 takeWayList 中选取取餐方式 code。

        真实 observe：到店场景 calculate-price 返回
        `takeWayList: [{"code":"eat-in","title":"堂食"},{"code":"take-in-store","title":"外带"}]`，
        到店下单(create-order, orderType=1)必须传 takeWayCode，取值即此处的 code。
        """
        lst = (price_data or {}).get("takeWayList") or []
        if not lst:
            return None
        codes = [x.get("code") for x in lst if isinstance(x, dict)]
        if prefer in codes:
            return prefer
        return codes[0] if codes else None

    def create_order(
        self,
        store_code: str,
        items: List[Dict[str, Any]],
        *,
        take_way_code: Optional[str] = None,
        order_type: int = 1,
        be_type: int = 1,
        need_tableware: bool = False,
        address_id: Optional[str] = None,
        be_code: Optional[str] = None,
        remark: Optional[str] = None,
    ) -> Dict[str, Any]:
        """调用 create-order 创建订单（⚠️ 真实下单，会生成待支付订单）。

        ⚠️ 安全提示：本方法会真实创建麦当劳订单并返回支付链接，**调用前必须经用户显式确认**。
        到店(orderType=1) 必须提供 take_way_code（取自 calculate-price 的 takeWayList[].code）。

        参数：
            items: [{"product_code": "1100", "quantity": 1, "coupon_code"?: ..., "coupon_id"?: ...}, ...]
        返回业务 data：含订单号 / 支付链接等。
        """
        priced_items = []
        for it in items:
            entry: Dict[str, Any] = {
                "productCode": it["product_code"],
                "quantity": it.get("quantity", 1),
            }
            if it.get("coupon_code"):
                entry["couponCode"] = it["coupon_code"]
            if it.get("coupon_id"):
                entry["couponId"] = it["coupon_id"]
            priced_items.append(entry)

        arguments: Dict[str, Any] = {
            "storeCode": store_code,
            "orderType": order_type,
            "beType": be_type,
            "needTableware": need_tableware,
            "items": priced_items,
        }
        if order_type == 1:
            if not take_way_code:
                raise ValueError(
                    "到店(orderType=1)下单必须提供 take_way_code"
                    "（取自 calculate-price 的 takeWayList[].code，可用 pick_take_way 获取）"
                )
            arguments["takeWayCode"] = take_way_code
        else:
            if address_id:
                arguments["addressId"] = address_id
            if be_code:
                arguments["beCode"] = be_code
            if remark:
                arguments["remark"] = remark
        # 下单为非幂等操作，禁用重试，杜绝重复下单
        return self.call_tool("create-order", arguments, retry=False)

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
