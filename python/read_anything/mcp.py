#!/usr/bin/env python3
"""read-anything 的 MCP stdio 服务器。

把 ra.py 包装成三个模型可直接调用的工具：
    list_site  —— 在指定站点搜索，返回结构化条目
    read_url   —— 读单条详情（含评论）
    suggest    —— 把口语问题改写成各站查询词

协议：MCP over stdio，换行分隔的 JSON-RPC 2.0。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable

PROTOCOL = "2024-11-05"

TOOLS = [
    {
        "name": "list_site",
        "description": (
            "在指定站点搜索并返回结构化条目（标题/作者/链接/摘要）。"
            "站点：xhs(小红书)、zhihu(知乎)、csdn、v2ex、github、weibo、youtube、reddit、tieba、handshake。"
            "被墙/未登录时返回 ok:false 和 0_handoff——先照它改用你自己的搜索，搜到链接再回来 read_url，不要原站重试。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "site": {"type": "string", "description": "站点键，如 zhihu"},
                "query": {"type": "string", "description": "搜索词；先用 suggest 改写口语问题"},
                "limit": {"type": "integer", "default": 8, "minimum": 1, "maximum": 30},
            },
            "required": ["site", "query"],
        },
    },
    {
        "name": "read_url",
        "description": "读取单条详情页正文（可选评论）。只支持已在 sites.yaml 配置的站点。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "详情页 URL"},
                "site": {"type": "string", "description": "站点键，如 xhs"},
                "comments": {"type": "integer", "default": 0, "minimum": 0, "maximum": 50},
            },
            "required": ["url", "site"],
        },
    },
    {
        "name": "suggest",
        "description": "把一句口语问题改写成各站能搜到的查询词，并判断意图（学校/求职/技术/签证/钱）。",
        "inputSchema": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "用户的原话"}},
            "required": ["question"],
        },
    },
]


def run_ra(args: list[str], timeout: int = 180) -> tuple[str, bool]:
    try:
        p = subprocess.run(
            [PYTHON, "-m", "read_anything.ra", *args],
            capture_output=True, text=True, timeout=timeout, cwd=os.path.dirname(PKG_DIR),
        )
    except subprocess.TimeoutExpired:
        return json.dumps({"ok": False, "error": f"ra.py 超时（{timeout}s）"}, ensure_ascii=False), True
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    if not out:
        return json.dumps({"ok": False, "error": err or "无输出", "exit": p.returncode},
                          ensure_ascii=False), True
    return out, p.returncode != 0


def call_tool(name: str, args: dict) -> tuple[str, bool]:
    if name == "list_site":
        out, bad = run_ra(["list", args["site"], args.get("query", ""),
                           "--limit", str(int(args.get("limit", 8))), "--json"])
    elif name == "read_url":
        cmd = ["read", args["url"], "--site", args["site"], "--json"]
        if int(args.get("comments", 0)):
            cmd += ["--comments", str(int(args["comments"]))]
        out, bad = run_ra(cmd)
    elif name == "suggest":
        out, bad = run_ra(["suggest", args["question"], "--json"])
    else:
        return json.dumps({"ok": False, "error": f"未知工具 {name}"}, ensure_ascii=False), True
    return out, bad


def reply(mid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": mid}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = req.get("method")
        mid = req.get("id")

        if method == "initialize":
            reply(mid, {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "read-anything", "version": "2.0.0"},
            })
        elif method in ("notifications/initialized", "initialized"):
            continue
        elif method == "tools/list":
            reply(mid, {"tools": TOOLS})
        elif method == "tools/call":
            params = req.get("params") or {}
            text, bad = call_tool(params.get("name", ""), params.get("arguments") or {})
            reply(mid, {"content": [{"type": "text", "text": text}], "isError": bad})
        elif method == "ping":
            reply(mid, {})
        elif mid is not None:
            reply(mid, error={"code": -32601, "message": f"unsupported method {method}"})


if __name__ == "__main__":
    main()
