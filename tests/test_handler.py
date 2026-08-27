import json

import pytest

from log_mcp.mcp.handler import McpRequestHandler
from log_mcp.tools import Tool


def _tools() -> list[Tool]:
    def echo(params):
        return {"echo": params.get("value")}

    def boom(params):  # noqa: ARG001
        raise ValueError("boom")

    return [
        Tool("echo_tool", "Echo value", {"type": "object", "properties": {}, "required": []}, echo),
        Tool("boom_tool", "Always fails", {"type": "object", "properties": {}, "required": []}, boom),
    ]


@pytest.fixture()
def handler() -> McpRequestHandler:
    return McpRequestHandler(_tools())


def _post(handler: McpRequestHandler, method: str, params=None, request_id=1) -> dict | None:
    body = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
    response = handler.handle_request(body)
    return json.loads(response) if response is not None else None


class TestProtocol:
    def test_initialize(self, handler):
        result = _post(handler, "initialize")["result"]
        assert result["protocolVersion"] == "2025-11-25"
        assert result["serverInfo"]["name"] == "log-mcp"
        assert result["capabilities"] == {"tools": {}}

    def test_tools_list(self, handler):
        result = _post(handler, "tools/list")["result"]
        names = [tool["name"] for tool in result["tools"]]
        assert names == ["echo_tool", "boom_tool"]
        for tool in result["tools"]:
            assert set(tool) == {"name", "description", "inputSchema"}

    def test_tool_call_success(self, handler):
        response = _post(handler, "tools/call", {"name": "echo_tool", "arguments": {"value": 42}})
        assert response["id"] == 1
        text = response["result"]["content"][0]["text"]
        assert json.loads(text) == {"echo": 42}

    def test_tool_call_unknown_tool(self, handler):
        response = _post(handler, "tools/call", {"name": "nope", "arguments": {}})
        assert response["error"]["code"] == -32602
        assert "Tool not found" in response["error"]["message"]

    def test_tool_call_execution_error(self, handler):
        response = _post(handler, "tools/call", {"name": "boom_tool", "arguments": {}})
        assert response["error"]["code"] == -32603
        assert "boom" in response["error"]["message"]

    def test_notification_returns_none(self, handler):
        body = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert handler.handle_request(body) is None

    def test_unknown_method(self, handler):
        response = _post(handler, "resources/list")
        assert response["error"]["code"] == -32601

    def test_invalid_json(self, handler):
        response = json.loads(handler.handle_request("{not-json"))
        assert response["error"]["code"] == -32603

    def test_id_preserved(self, handler):
        response = _post(handler, "initialize", request_id="abc-123")
        assert response["id"] == "abc-123"
