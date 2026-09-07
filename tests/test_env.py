"""env 环境过滤测试：

- 单元：``resolve_server`` 的 (name, env) 组合解析规则、``ServerInfo.uid``、
  配置加载时的 (name, env) 唯一性校验；
- 集成：同一服务名部署在两个环境（local 通道 + 不同日志根目录），
  验证 env 参数能路由到准确的服务器。
"""

import datetime as dt
import json

import pytest

from log_mcp.config import AppConfig, ServerInfo, load_config
from log_mcp.mcp.handler import McpRequestHandler
from log_mcp.server import build_handler

TODAY = dt.date.today().strftime("%Y-%m-%d")


def _server(name: str, env: str = "default", **kw) -> ServerInfo:
    kw.setdefault("connector", "local")
    return ServerInfo(name=name, log_root_path="/logs", env=env, **kw)


# ============================================================ 单元：uid / 解析
class TestServerUid:
    def test_default_env_uid_is_name(self):
        assert _server("app").uid == "app"

    def test_env_uid_has_suffix(self):
        assert _server("app", "prod").uid == "app@prod"

    def test_env_case_preserved_in_uid(self):
        assert _server("app", "Prod").uid == "app@Prod"


class TestResolveServerEnv:
    def make_config(self, *servers: ServerInfo) -> AppConfig:
        return AppConfig(servers=list(servers))

    def test_name_and_env_exact(self):
        config = self.make_config(_server("app", "prod"), _server("app", "test"))
        assert config.resolve_server("app", "test").env == "test"
        assert config.resolve_server("app", "prod").env == "prod"

    def test_env_match_is_case_insensitive(self):
        config = self.make_config(_server("app", "prod"), _server("app", "test"))
        assert config.resolve_server("app", "PROD").env == "prod"
        assert config.resolve_server("app", " Test ").env == "test"

    def test_name_env_miss_lists_available_envs(self):
        config = self.make_config(_server("app", "dev"), _server("app", "prod"))
        with pytest.raises(ValueError, match=r"available envs: dev, prod"):
            config.resolve_server("app", "staging")

    def test_name_only_unique(self):
        config = self.make_config(_server("app", "prod"), _server("db", "prod"))
        assert config.resolve_server("db").env == "prod"

    def test_name_only_prefers_default_env(self):
        config = self.make_config(_server("app", "prod"), _server("app", "default"))
        assert config.resolve_server("app").env == "default"

    def test_name_only_prefers_is_default_flag(self):
        config = self.make_config(_server("app", "prod"), _server("app", "test", is_default=True))
        assert config.resolve_server("app").env == "test"

    def test_name_only_ambiguous_raises(self):
        config = self.make_config(_server("app", "dev"), _server("app", "test"))
        with pytest.raises(ValueError, match="Ambiguous server: app"):
            config.resolve_server("app")

    def test_env_only_picks_default_in_env(self):
        config = self.make_config(
            _server("app", "prod", is_default=True), _server("db", "prod"), _server("cache", "dev")
        )
        assert config.resolve_server(None, "prod").name == "app"

    def test_env_only_falls_back_to_first(self):
        config = self.make_config(_server("app", "prod"), _server("db", "prod"))
        assert config.resolve_server(None, "prod").name == "app"

    def test_env_only_unknown(self):
        config = self.make_config(_server("app", "prod"))
        with pytest.raises(ValueError, match="Unknown env: staging"):
            config.resolve_server(None, "staging")

    def test_no_name_no_env_returns_default(self):
        config = self.make_config(_server("app", "prod"), _server("db", "dev", is_default=True))
        assert config.resolve_server(None, None).name == "db"

    def test_unknown_server(self):
        config = self.make_config(_server("app", "prod"))
        with pytest.raises(ValueError, match="Unknown server: ghost"):
            config.resolve_server("ghost")


# ============================================================ 单元：配置加载
class TestConfigLoadEnv:
    def _write(self, tmp_path, servers: list[dict]) -> str:
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"servers": servers}), encoding="utf-8")
        return str(path)

    def test_env_field_parsed_and_defaulted(self, tmp_path):
        path = self._write(
            tmp_path,
            [
                {"name": "app", "env": "prod", "connector": "local", "logRootPath": "/a"},
                {"name": "db", "connector": "local", "logRootPath": "/b"},
            ],
        )
        config = load_config(path)
        assert config.get_server("app").env == "prod"
        assert config.get_server("db").env == "default"

    def test_duplicate_name_env_rejected(self, tmp_path):
        path = self._write(
            tmp_path,
            [
                {"name": "app", "env": "prod", "connector": "local", "logRootPath": "/a"},
                {"name": "app", "env": "Prod", "connector": "local", "logRootPath": "/b"},
            ],
        )
        with pytest.raises(ValueError, match="重复的 server name\\+env"):
            load_config(path)

    def test_same_name_different_env_allowed(self, tmp_path):
        path = self._write(
            tmp_path,
            [
                {"name": "app", "env": "prod", "connector": "local", "logRootPath": "/a"},
                {"name": "app", "env": "test", "connector": "local", "logRootPath": "/b"},
            ],
        )
        config = load_config(path)
        assert len(config.servers) == 2


# ============================================================ 集成：local 通道
def _make_log_root(base, tag: str) -> str:
    root = base / tag
    info = root / "info"
    info.mkdir(parents=True)
    with open(info / f"log-info-{TODAY}.0.log", "w", encoding="utf-8") as fp:
        for i in range(1, 4):
            fp.write(f"{TODAY} 12:00:0{i} INFO {tag}-line-{i}\n")
    return str(root)


@pytest.fixture(scope="module")
def handler(tmp_path_factory) -> McpRequestHandler:
    prod_root = _make_log_root(tmp_path_factory.mktemp("env_prod"), "PROD")
    test_root = _make_log_root(tmp_path_factory.mktemp("env_test"), "TEST")

    config_path = tmp_path_factory.mktemp("env_config") / "config.json"
    with open(config_path, "w", encoding="utf-8") as fp:
        json.dump(
            {
                "servers": [
                    {
                        "name": "app",
                        "env": "prod",
                        "connector": "local",
                        "logRootPath": prod_root,
                        "default": True,
                    },
                    {
                        "name": "app",
                        "env": "test",
                        "connector": "local",
                        "logRootPath": test_root,
                    },
                ]
            },
            fp,
        )
    handler, _executor = build_handler(load_config(str(config_path)))
    return handler


def _call(handler: McpRequestHandler, name: str, arguments: dict) -> dict:
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    )
    response = json.loads(handler.handle_request(body))
    assert "error" not in response, response.get("error")
    return json.loads(response["result"]["content"][0]["text"])


def _call_error(handler: McpRequestHandler, name: str, arguments: dict) -> str:
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    )
    response = json.loads(handler.handle_request(body))
    assert "error" in response
    return response["error"]["message"]


class TestEnvRouting:
    def test_list_servers_includes_env(self, handler):
        result = _call(handler, "list_servers", {})
        by_env = {s["env"]: s for s in result["servers"]}
        assert set(by_env) == {"prod", "test"}
        assert by_env["prod"]["name"] == "app"
        assert by_env["prod"]["isDefault"] is True

    def test_tail_routes_by_env(self, handler):
        result = _call(handler, "tail_logs", {"level": "info", "env": "test", "lines": 1})
        assert result["env"] == "test"
        assert result["lines"][-1].endswith("TEST-line-3")

        result = _call(handler, "tail_logs", {"level": "info", "env": "prod", "lines": 1})
        assert result["env"] == "prod"
        assert result["lines"][-1].endswith("PROD-line-3")

    def test_env_case_insensitive(self, handler):
        result = _call(handler, "tail_logs", {"level": "info", "env": "PROD", "lines": 1})
        assert result["lines"][-1].endswith("PROD-line-3")

    def test_name_only_uses_default_server(self, handler):
        # 同名多环境：prod 标记了 default=true
        result = _call(handler, "tail_logs", {"level": "info", "server": "app", "lines": 1})
        assert result["env"] == "prod"
        assert result["lines"][-1].endswith("PROD-line-3")

    def test_no_server_no_env_uses_default(self, handler):
        result = _call(handler, "tail_logs", {"level": "info", "lines": 1})
        assert result["env"] == "prod"

    def test_env_only_resolves_default_in_env(self, handler):
        result = _call(handler, "tail_logs", {"level": "info", "env": "test", "lines": 1})
        assert result["server"] == "app"
        assert result["env"] == "test"

    def test_search_routes_by_env(self, handler):
        result = _call(handler, "search_logs", {"keyword": "TEST-line-2", "env": "test"})
        assert result["env"] == "test"
        assert result["summary"]["totalMatches"] == 1

        result = _call(handler, "search_logs", {"keyword": "TEST-line-2", "env": "prod"})
        assert result["summary"]["totalMatches"] == 0

    def test_read_routes_by_env(self, handler):
        result = _call(
            handler,
            "read_log_file",
            {"filePath": f"info/log-info-{TODAY}.0.log", "env": "test", "startLine": 1, "maxLines": 1},
        )
        assert result["env"] == "test"
        assert result["lines"][0].endswith("TEST-line-1")

    def test_list_log_files_routes_by_env(self, handler):
        result = _call(handler, "list_log_files", {"level": "info", "env": "test"})
        assert result["env"] == "test"
        assert result["totalFiles"] >= 1

    def test_wrong_env_reports_available_envs(self, handler):
        message = _call_error(handler, "tail_logs", {"server": "app", "env": "staging"})
        assert "available envs: prod, test" in message

    def test_unknown_server_still_reports(self, handler):
        message = _call_error(handler, "tail_logs", {"server": "ghost", "env": "prod"})
        assert "Unknown server: ghost" in message
