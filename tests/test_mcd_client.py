"""
麦当劳 MCP 客户端单元测试 + 可选真实冒烟测试。

离线部分（默认运行）：测试请求/响应解析，不触网。
真实冒烟（`pytest -m live`，需设置 MCD_MCP_TOKEN 环境变量）：
  实际连接 https://mcp.mcd.cn 完成 initialize -> list_tools -> call_tool(now-time-info)，
  验证「真实接入麦当劳 MCP」可端到端跑通。
"""

import json

import pytest

from src.mcd_client import (
    McDonaldMCPClient,
    extract_business_data,
    parse_mcp_envelope,
)


# ---------------------------------------------------------------------------
# 离线：协议解析
# ---------------------------------------------------------------------------
def test_parse_mcp_envelope_json():
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})
    env = parse_mcp_envelope(body)
    assert env["result"]["ok"] is True


def test_extract_business_data_from_text_payload():
    # 真实 observe：tools/call 返回 content[0].text 内含业务 JSON + 说明文字，
    # 业务 JSON 为 {success, code, message, data:{...实际字段...}}，
    # extract_business_data 应拆到最内层 data（含 price 等真实字段）。
    payload = '{"success":true,"code":200,"message":"请求成功","data":{"price":1330}}'
    text = f"以下是计算结果：\n{payload}\n（仅供参考）"
    envelope = {"jsonrpc": "2.0", "result": {"content": [{"type": "text", "text": text}]}}
    data = extract_business_data(envelope)
    assert data["price"] == 1330  # 已拆到内层 data
    assert "success" not in data  # 外层标记已被剥离


def test_extract_business_data_list_payload():
    # 真实 observe：query-nearby-stores / query-store-coupons 的业务 data 是**列表**，
    # 外层仍是 {success, code, message, ..., data:[...]}。修复前只拆 dict，
    # 列表会原样返回外层信封 -> 上层拿到非列表、门店数为 0（真机联调踩到的坑）。
    payload = '{"success":true,"code":200,"message":"请求成功","data":[{"storeCode":"1450104","storeName":"悦荟","distance":194}]}'
    text = f"门店列表如下：\n{payload}\n（完）"
    envelope = {"jsonrpc": "2.0", "result": {"content": [{"type": "text", "text": text}]}}
    data = extract_business_data(envelope)
    assert isinstance(data, list)  # 已拆到业务层列表
    assert data[0]["storeCode"] == "1450104"


def test_extract_business_data_prefix_with_braces():
    # 真实 observe：query-meals 的说明文字含 `{code}` 占位符（字段表），
    # 若按「第一个 {」解析会取到占位符 -> JSONDecodeError（真机联调踩到的坑）。
    # 修复后按 `{"success"` 精确锚定业务 JSON。
    payload = '{"success":true,"code":200,"message":"请求成功","data":{"meals":{"1100":{"name":"巨无霸","currentPrice":"25.5"}}}}'
    text = f"字段说明：data.meals.{{code}}.withOrder.cardId 见下\n{payload}\n（完）"
    envelope = {"jsonrpc": "2.0", "result": {"content": [{"type": "text", "text": text}]}}
    data = extract_business_data(envelope)
    assert data["meals"]["1100"]["name"] == "巨无霸"


def test_extract_business_data_no_text_raises():
    with pytest.raises(ValueError):
        extract_business_data({"jsonrpc": "2.0", "result": {}})


# ---------------------------------------------------------------------------
# 离线：请求体构造（确定性断言，便于回归）
# ---------------------------------------------------------------------------
def test_build_initialize_body():
    c = McDonaldMCPClient(token="dummy")
    # build_body 是通用构造器：只负责包裹 method/params/id/jsonrpc，
    # protocolVersion 等具体字段由 initialize() 在 params 中填充。
    body = c.build_body("initialize", {"protocolVersion": "2025-03-26"}, req_id=1)
    assert body["method"] == "initialize"
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 1
    assert body["params"]["protocolVersion"] == "2025-03-26"


def test_build_tools_call_body():
    c = McDonaldMCPClient(token="dummy")
    body = c.build_body("tools/call", {"name": "now-time-info", "arguments": {}}, req_id=2)
    assert body["method"] == "tools/call"
    assert body["params"]["name"] == "now-time-info"


# ---------------------------------------------------------------------------
# 真实冒烟（默认跳过）
# ---------------------------------------------------------------------------
@pytest.mark.live
def test_live_end_to_end():
    import os

    token = os.environ.get("MCD_MCP_TOKEN")
    if not token:
        pytest.skip("需要 MCD_MCP_TOKEN 环境变量")
    client = McDonaldMCPClient(token=token)
    info = client.initialize()
    assert info.get("serverInfo", {}).get("name") == "mcd-mcp"
    tools = client.list_tools()
    assert len(tools) >= 30  # 联调实测 35 个工具
    now = client.call_tool("now-time-info", {})
    assert isinstance(now, dict) and now  # 返回已拆到内层的业务 data 字典
