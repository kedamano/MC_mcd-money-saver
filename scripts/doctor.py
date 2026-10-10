"""
麦麦省钱助手 · 环境自检（doctor）

一键排查最常见、最劝退的两个坑（均为真机实测踩过的）：
  1. mcp.json 里 `type` 写成 `streamablehttp`（缺连字符）→ WorkBuddy 一直显示"需要认证"；
  2. `Authorization` 缺 `Bearer ` 前缀 / Token 被截断 → 401「当前鉴权码不存在或已失效」。

用法：
    python scripts/doctor.py                 # 自动查找 mcp.json（~/.workbuddy/mcp.json 等）
    python scripts/doctor.py <path/to/mcp.json>
    MCD_MCP_TOKEN=xxx python scripts/doctor.py --probe   # 额外真实握手验证 Token
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OK = "✅"
BAD = "❌"
WARN = "⚠️"

CANDIDATES = [
    os.path.expanduser("~/.workbuddy/mcp.json"),
    os.path.expanduser("~/.workbuddy/mcp.json"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp-config.example.json"),
]


def find_config(argv):
    for a in argv:
        if a.endswith(".json"):
            return a
    for c in CANDIDATES:
        if os.path.isfile(c):
            return c
    return None


def check_server(name, cfg):
    problems = 0
    print(f"\n[{name}]")
    typ = cfg.get("type")
    if typ == "streamable-http":
        print(f"  {OK} type = streamable-http")
    elif typ == "streamablehttp":
        print(f"  {BAD} type = streamablehttp（缺连字符）→ 会导致『需要认证』，应为 streamable-http")
        problems += 1
    elif typ in ("sse", "stdio"):
        print(f"  {OK} type = {typ}")
    else:
        print(f"  {WARN} type = {typ!r}（未识别，合法值：streamable-http / sse / stdio）")
        problems += 1

    url = cfg.get("url")
    print(f"  {OK if url else BAD} url = {url}")
    if not url:
        problems += 1

    auth = (cfg.get("headers") or {}).get("Authorization", "")
    if not auth or auth.strip() == "":
        print(f"  {WARN} 未配置 Authorization 头")
    elif not auth.startswith("Bearer "):
        print(f"  {BAD} Authorization 缺 `Bearer ` 前缀（当前以 {auth[:12]}… 开头）→ 会 401")
        problems += 1
    elif "${" in auth:
        print(f"  {OK} Authorization = Bearer ${{...}}（环境变量占位符，正确）")
    else:
        print(f"  {OK} Authorization = Bearer <token>（已配置，长度 {len(auth)}）")
    return problems


def probe(url, token):
    print(f"\n[真实握手探测] {url}")
    if not token:
        print(f"  {WARN} 未提供 MCD_MCP_TOKEN，跳过（可用 MCD_MCP_TOKEN=xxx 重试）")
        return 0
    try:
        from src.mcd_client import McDonaldMCPClient

        client = McDonaldMCPClient(token=token, base_url=url)
        info = client.initialize()
        srv = info.get("serverInfo", {}).get("name")
        print(f"  {OK} initialize 成功，serverInfo.name = {srv}")
        tools = client.list_tools()
        print(f"  {OK} list_tools 返回 {len(tools)} 个工具")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"  {BAD} 握手失败：{e}")
        return 1


def main():
    argv = sys.argv[1:]
    path = find_config(argv)
    print("=" * 60)
    print("  麦麦省钱助手 · 环境自检 doctor")
    print("=" * 60)
    if not path:
        print(f"{BAD} 未找到 mcp.json，请显式传入路径：python scripts/doctor.py <path>")
        return 2
    print(f"配置文件：{path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    servers = data.get("mcpServers", {})
    if not servers:
        print(f"{BAD} 未找到 mcpServers 段")
        return 2

    problems = 0
    for name, cfg in servers.items():
        problems += check_server(name, cfg)

    if "--probe" in argv:
        # 以 mcd-mcp 或唯一 server 为准
        target = servers.get("mcd-mcp") or next(iter(servers.values()))
        problems += probe(target.get("url"), os.environ.get("MCD_MCP_TOKEN"))

    print("\n" + "=" * 60)
    if problems == 0:
        print(f"{OK} 自检通过：配置无常见问题")
    else:
        print(f"{BAD} 发现 {problems} 个问题，请按上方提示修复")
    print("=" * 60)
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
