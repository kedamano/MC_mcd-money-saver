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


def extract_business_data(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """从 tools/call 信封中取出业务 JSON。

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
    idx = text.find("{")
    if idx < 0:
        raise ValueError("text 中未找到业务 JSON")
    data, _ = decoder.raw_decode(text, idx)
    return data
