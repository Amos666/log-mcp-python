"""本地通道全链路集成测试：临时日志目录 + local 执行通道，走完整 MCP 流程。

不依赖任何真实 SSH，同时验证：命令统一层生成的命令在真实 shell 中可用、
解析层与命令输出吻合、MCP 协议行为正确。
"""

import datetime as dt
import json
import os
import shutil

import pytest

from log_mcp.config import AppConfig, ServerInfo, load_config
from log_mcp.mcp.handler import McpRequestHandler
from log_mcp.server import build_handler
from log_mcp.tools import build_tools

TODAY = dt.date.today().strftime("%Y-%m-%d")
LOG_ROOT = None  # 由 fixture 注入


@pytest.fixture(scope="module")
def log_root(tmp_path_factory) -> str:
    """构造日志树: <root>/{level}/log-{level}-{date}.{seq}.log"""
    root = tmp_path_factory.mktemp("logs")
    root.chmod(0o755)
    lines = {
        "info": [f"{TODAY} 10:00:0{i} [main] INFO message-{i}" for i in range(1, 6)],
        "error": [
            f"{TODAY} 04:22:28.774 [http-nio-8888-exec-9] ERROR NullPointerException at com.example.Service",
            f"{TODAY} 04:22:29.100 [http-nio-8888-exec-9] ERROR follow-up error line",
        ],
    }
    for level, content in lines.items():
        level_dir = root / level
        level_dir.mkdir()
        with open(level_dir / f"log-{level}-{TODAY}.0.log", "w", encoding="utf-8") as fp:
            fp.write("\n".join(content) + "\n")
    return str(root)


@pytest.fixture(scope="module")
def config_file(log_root) -> str:
    path = os.path.join(os.path.dirname(log_root), "config.json")
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(
            {
                "servers": [
                    {
                        "name": "test-local",
                        "connector": "local",
                        "logRootPath": log_root,
                        "description": "本地测试",
                        "default": True,
                    }
                ],
                "logFilePattern": "{level}/log-{level}-{date}.{seq}.log",
            },
            fp,
        )
    return path


@pytest.fixture(scope="module")
def handler(config_file) -> McpRequestHandler:
    config = load_config(config_file)
    handler, _executor = build_handler(config)
    return handler


def _call(handler: McpRequestHandler, name: str, arguments: dict) -> dict:
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    )
    response = json.loads(handler.handle_request(body))
    assert "error" not in response, response.get("error")
    return json.loads(response["result"]["content"][0]["text"])


class TestMcpFullPipeline:
    def test_initialize_and_tools_list(self, handler):
        init = json.loads(handler.handle_request(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"})))
        assert init["result"]["serverInfo"]["name"] == "log-mcp"
        listed = json.loads(handler.handle_request(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})))
        names = {tool["name"] for tool in listed["result"]["tools"]}
        assert names == {"list_servers", "list_log_files", "read_log_file", "search_logs", "tail_logs"}

    def test_list_servers(self, handler):
        result = _call(handler, "list_servers", {})
        assert result["servers"][0]["name"] == "test-local"
        assert result["servers"][0]["connector"] == "local"

    def test_list_log_files(self, handler):
        result = _call(handler, "list_log_files", {"level": "error"})
        assert result["server"] == "test-local"
        paths = [f["path"] for f in result["files"]]
        assert f"error/log-error-{TODAY}.0.log" in paths
        file_info = next(f for f in result["files"] if f["level"] == "error")
        assert file_info["size"].endswith("B")
        assert TODAY in file_info["lastModified"]

    def test_tail_logs(self, handler):
        result = _call(handler, "tail_logs", {"level": "info", "lines": 3})
        assert result["file"] == f"info/log-info-{TODAY}.0.log"
        assert result["totalLines"] == 3
        assert result["lines"][-1].endswith("INFO message-5")

    def test_tail_logs_default(self, handler):
        result = _call(handler, "tail_logs", {})
        # 默认 info / 50 行，文件实际只有 5 行
        assert result["totalLines"] == 5

    def test_read_log_file(self, handler):
        result = _call(
            handler,
            "read_log_file",
            {"filePath": f"error/log-error-{TODAY}.0.log", "startLine": 1, "maxLines": 1},
        )
        assert result["totalLines"] == 1
        assert "NullPointerException" in result["lines"][0]

    def test_read_log_file_default_span(self, handler):
        result = _call(handler, "read_log_file", {"filePath": f"error/log-error-{TODAY}.0.log"})
        assert result["totalLines"] == 2

    def test_read_log_file_rejects_traversal(self, handler):
        body = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "read_log_file", "arguments": {"filePath": "../etc/passwd.log"}}}
        )
        response = json.loads(handler.handle_request(body))
        assert response["error"]["code"] == -32603
        assert "traversal" in response["error"]["message"]

    def test_search_logs_single_level(self, handler):
        result = _call(
            handler,
            "search_logs",
            {"keyword": "NullPointerException", "levels": ["error"], "startDate": TODAY, "endDate": TODAY},
        )
        assert result["summary"]["totalMatches"] == 1
        entry = result["results"][0]
        assert entry["lineNumber"] == 1
        assert entry["file"] == "multiple" or entry["file"].endswith(".log")

    def test_search_logs_context(self, handler):
        result = _call(
            handler,
            "search_logs",
            {"keyword": "NullPointerException", "levels": ["error"], "contextLines": 1},
        )
        entry = result["results"][0]
        assert entry["contextAfter"] == [f"{TODAY} 04:22:29.100 [http-nio-8888-exec-9] ERROR follow-up error line"]

    def test_search_logs_regex(self, handler):
        result = _call(
            handler,
            "search_logs",
            {"keyword": "message-[0-9]", "useRegex": True, "levels": ["info"]},
        )
        assert result["summary"]["totalMatches"] == 5

    def test_search_logs_no_match(self, handler):
        result = _call(handler, "search_logs", {"keyword": "NoSuchThingAtAll", "levels": ["info", "error"]})
        assert result["summary"]["totalMatches"] == 0
        assert result["results"] == []

    def test_search_logs_invalid_date(self, handler):
        body = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "search_logs", "arguments": {"keyword": "x", "startDate": "2026/01/01"}}}
        )
        response = json.loads(handler.handle_request(body))
        assert response["error"]["code"] == -32603

    def test_search_logs_dangerous_keyword_fixed_mode(self, handler):
        body = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "search_logs", "arguments": {"keyword": "x;rm -rf /"}}}
        )
        response = json.loads(handler.handle_request(body))
        assert response["error"]["code"] == -32603
        assert "dangerous characters" in response["error"]["message"]

    def test_unknown_server(self, handler):
        body = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "tail_logs", "arguments": {"server": "ghost"}}}
        )
        response = json.loads(handler.handle_request(body))
        assert response["error"]["code"] == -32603
        assert "Unknown server" in response["error"]["message"]


class TestConfigCompat:
    def test_original_java_config_shape(self, log_root):
        """原 Java 版配置字段（无 connector）原样可用，默认走 ssh 通道。"""
        raw = {
            "servers": [
                {
                    "name": "local-server",
                    "host": "192.168.5.169",
                    "port": 22,
                    "username": "root",
                    "privateKeyPath": "/nonexistent/${HOME}/id_rsa",
                    "logRootPath": log_root,
                    "description": "169",
                    "default": True,
                }
            ],
            "logLevels": ["info", "warn", "error", "debug"],
            "logFilePattern": "{level}/log-{level}-{date}.{seq}.log",
        }
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fp:
            json.dump(raw, fp)
            path = fp.name
        try:
            config = load_config(path)
            assert config.get_server("local-server").connector == "ssh"
            # ${HOME} 占位符被解析
            assert "/nonexistent/" + os.path.expanduser("~") in config.get_server("local-server").private_key_path
        finally:
            os.unlink(path)
