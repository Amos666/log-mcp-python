"""pyinfra 执行通道端到端测试：使用 pyinfra 的 @local 连接器，无需真实 SSH。

验证核心设计目标之一：connector=pyinfra 的服务器经由 pyinfra 的
Inventory/Host 体系执行统一命令，业务层与 MCP 接口行为与 ssh/local 通道完全一致。
"""

import datetime as dt
import json
import os

import pytest

from log_mcp.mcp.handler import McpRequestHandler
from log_mcp.server import build_handler

pytest.importorskip("pyinfra")

TODAY = dt.date.today().strftime("%Y-%m-%d")


@pytest.fixture(scope="module")
def handler(tmp_path_factory) -> McpRequestHandler:
    root = tmp_path_factory.mktemp("logs_pyinfra")
    level_dir = root / "info"
    level_dir.mkdir()
    with open(level_dir / f"log-info-{TODAY}.0.log", "w", encoding="utf-8") as fp:
        for i in range(1, 4):
            fp.write(f"{TODAY} 11:00:0{i} INFO pyinfra-line-{i}\n")

    config_path = root / "config.json"
    with open(config_path, "w", encoding="utf-8") as fp:
        json.dump(
            {
                "servers": [
                    {
                        "name": "pyinfra-local",
                        "connector": "pyinfra",
                        "pyinfraHost": "@local",
                        "logRootPath": str(root),
                        "description": "pyinfra @local 通道",
                        "default": True,
                    }
                ]
            },
            fp,
        )
    from log_mcp.config import load_config

    handler, _executor = build_handler(load_config(str(config_path)))
    return handler


def _call(handler: McpRequestHandler, name: str, arguments: dict) -> dict:
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    )
    response = json.loads(handler.handle_request(body))
    assert "error" not in response, response.get("error")
    return json.loads(response["result"]["content"][0]["text"])


def test_pyinfra_executor_pipeline(handler):
    # tail
    result = _call(handler, "tail_logs", {"level": "info", "lines": 2})
    assert result["totalLines"] == 2
    assert result["lines"][-1] == f"{TODAY} 11:00:03 INFO pyinfra-line-3"

    # search
    result = _call(handler, "search_logs", {"keyword": "pyinfra-line-2", "levels": ["info"]})
    assert result["summary"]["totalMatches"] == 1
    assert "pyinfra-line-2" in result["results"][0]["content"]

    # list files
    result = _call(handler, "list_log_files", {"level": "info"})
    assert f"info/log-info-{TODAY}.0.log" in [f["path"] for f in result["files"]]

    # read
    result = _call(
        handler, "read_log_file", {"filePath": f"info/log-info-{TODAY}.0.log", "startLine": 1, "maxLines": 1}
    )
    assert result["totalLines"] == 1
    assert result["lines"][0].endswith("pyinfra-line-1")
