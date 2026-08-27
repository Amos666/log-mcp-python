"""JSON-RPC 2.0 / MCP 方法分发（行为与原 Java 版 McpRequestHandler 一致）。

- initialize: 返回固定 protocolVersion / serverInfo / capabilities
- tools/list: 注册工具的 name / description / inputSchema
- tools/call: 执行工具，结果序列化为 text 内容节点
- notifications/initialized: 返回 None（无响应体）
- 未知方法: -32601；工具不存在: -32602；执行/内部错误: -32603
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from log_mcp import PROTOCOL_VERSION, SERVER_NAME, __version__
from log_mcp.tools import Tool

logger = logging.getLogger(__name__)

_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603


def _error_body(request_id, code: int, message: str) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        ensure_ascii=False,
    )


class McpRequestHandler:
    def __init__(self, tools: list[Tool]):
        self._tools = {tool.name: tool for tool in tools}
        self._tool_order = list(tools)
        logger.info("Registered %d MCP tools", len(self._tools))

    def handle_request(self, request_json: str) -> Optional[str]:
        """处理一段 JSON-RPC 请求文本；通知类请求返回 None（无响应体）。"""
        try:
            request = json.loads(request_json)
        except (json.JSONDecodeError, TypeError):
            logger.error("Invalid JSON-RPC request: %r", request_json)
            return _error_body(None, _INTERNAL_ERROR, "Invalid JSON payload")

        if not isinstance(request, dict):
            return _error_body(None, _INTERNAL_ERROR, "Invalid JSON-RPC request")

        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params") or {}

        logger.debug("Handling request: method=%s, id=%s", method, request_id)

        try:
            if method == "initialize":
                return self._success(request_id, self._handle_initialize())
            if method == "tools/list":
                return self._success(request_id, self._handle_tools_list())
            if method and method.startswith("tools/call"):
                return self._handle_tool_call(request_id, params)
            if method == "notifications/initialized":
                return None
            return _error_body(request_id, _METHOD_NOT_FOUND, f"Method not found: {method}")
        except Exception as exc:  # noqa: BLE001
            logger.error("Error handling request", exc_info=True)
            return _error_body(request_id, _INTERNAL_ERROR, f"Internal error: {exc}")

    # ------------------------------------------------------------------ methods
    @staticmethod
    def _handle_initialize() -> dict:
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
            "capabilities": {"tools": {}},
        }

    def _handle_tools_list(self) -> dict:
        return {
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.input_schema,
                }
                for tool in self._tool_order
            ]
        }

    def _handle_tool_call(self, request_id, params: dict) -> str:
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}

        tool = self._tools.get(tool_name)
        if tool is None:
            return _error_body(request_id, _INVALID_PARAMS, f"Tool not found: {tool_name}")

        try:
            result = tool.handler(arguments)
        except Exception as exc:  # noqa: BLE001
            logger.error("Error executing tool %s: %s", tool_name, exc, exc_info=True)
            return _error_body(request_id, _INTERNAL_ERROR, f"Tool execution error: {exc}")

        # MCP 工具结果：结构化数据序列化为 text 内容节点（与原版一致）
        payload = {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}
        return self._success(request_id, payload)

    @staticmethod
    def _success(request_id, result) -> str:
        return json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "result": result}, ensure_ascii=False
        )
