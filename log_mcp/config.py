"""配置模型与加载。

兼容原 Java 版 config.json 结构，并扩展：
- 每台服务器可独立指定执行通道 ``connector``: ssh / pyinfra / local（默认 ssh）
- pyinfra 通道支持 ``pyinfraHost`` 主机 spec 与 ``pyinfraData`` 透传数据
- ``${VAR}`` 环境变量占位符解析
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

_ENV_PLACEHOLDER = re.compile(r"\$\{([^}]+)\}")

DEFAULT_QUERY_DEFAULTS = {
    "maxResults": 100,
    "maxResultsLimit": 1000,
    "maxReadLines": 500,
    "maxReadLinesLimit": 5000,
    "contextLines": 3,
    "searchTimeout": 30000,
    "defaultTailLines": 50,
}

DEFAULT_SSH_POOL = {
    "maxConnectionsPerServer": 3,
    "connectionTimeout": 30000,
    "idleTimeout": 300000,
    "maxRetries": 2,
}


@dataclass
class ServerInfo:
    name: str
    log_root_path: str
    connector: str = "ssh"
    host: str = ""
    port: int = 22
    username: str = ""
    private_key_path: str = ""
    description: str = ""
    is_default: bool = False
    # pyinfra 通道：可选的完整主机 spec（如 "root@192.168.5.20:22"）与透传数据
    pyinfra_host: str = ""
    pyinfra_data: dict = field(default_factory=dict)

    @staticmethod
    def from_dict(raw: dict) -> "ServerInfo":
        name = raw.get("name")
        if not name:
            raise ValueError("server 配置缺少 name 字段")
        log_root_path = raw.get("logRootPath")
        if not log_root_path:
            raise ValueError(f"server {name} 配置缺少 logRootPath 字段")
        return ServerInfo(
            name=name,
            log_root_path=log_root_path,
            connector=(raw.get("connector") or "ssh").lower(),
            host=raw.get("host", ""),
            port=int(raw.get("port", 22)),
            username=raw.get("username", ""),
            private_key_path=raw.get("privateKeyPath", ""),
            description=raw.get("description", ""),
            is_default=bool(raw.get("default", False)),
            pyinfra_host=raw.get("pyinfraHost", ""),
            pyinfra_data=dict(raw.get("pyinfraData", {}) or {}),
        )


@dataclass
class AppConfig:
    servers: list[ServerInfo]
    log_levels: list[str] = field(default_factory=lambda: ["info", "warn", "error", "debug"])
    log_file_pattern: str = "{level}/log-{level}-{date}.{seq}.log"
    ssh_pool: dict = field(default_factory=lambda: dict(DEFAULT_SSH_POOL))
    query_defaults: dict = field(default_factory=lambda: dict(DEFAULT_QUERY_DEFAULTS))

    # ---- 服务器查询 ----
    def get_server(self, name: str) -> Optional[ServerInfo]:
        for server in self.servers:
            if server.name == name:
                return server
        return None

    def get_default_server(self) -> ServerInfo:
        for server in self.servers:
            if server.is_default:
                return server
        return self.servers[0]

    def resolve_server(self, name: Optional[str]) -> ServerInfo:
        """按名称解析服务器；为空时取默认服务器；未知名称抛异常。"""
        if name is None:
            return self.get_default_server()
        server = self.get_server(name)
        if server is None:
            raise ValueError(f"Unknown server: {name}")
        return server

    # ---- 查询默认值 ----
    def query_default(self, key: str) -> Any:
        return self.query_defaults.get(key, DEFAULT_QUERY_DEFAULTS.get(key))

    def max_results(self) -> int:
        return int(self.query_default("maxResults"))

    def max_results_limit(self) -> int:
        return int(self.query_default("maxResultsLimit"))

    def search_timeout_ms(self) -> int:
        return int(self.query_default("searchTimeout"))

    def default_tail_lines(self) -> int:
        return int(self.query_default("defaultTailLines"))

    def default_context_lines(self) -> int:
        return int(self.query_default("contextLines"))


def _resolve_placeholders(value: str) -> str:
    """解析字符串中的 ``${VAR}`` 环境变量占位符（未定义则原样保留）。"""

    def _sub(match: re.Match) -> str:
        return os.environ.get(match.group(1), match.group(0))

    return _ENV_PLACEHOLDER.sub(_sub, value)


def _resolve_server_placeholders(server: ServerInfo) -> None:
    server.private_key_path = _resolve_placeholders(server.private_key_path)
    server.host = _resolve_placeholders(server.host)
    server.pyinfra_host = _resolve_placeholders(server.pyinfra_host)
    server.log_root_path = _resolve_placeholders(server.log_root_path)


def load_config(path: str) -> AppConfig:
    """从 JSON 文件加载配置（路径不存在时给出明确错误）。"""
    logger.info("Loading configuration from: %s", path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"配置文件不存在: {path}")

    with open(path, encoding="utf-8") as fp:
        raw = json.load(fp)

    servers_raw = raw.get("servers")
    if not servers_raw:
        raise ValueError("配置文件缺少 servers 或 servers 为空")

    config = AppConfig(
        servers=[ServerInfo.from_dict(item) for item in servers_raw],
        log_levels=raw.get("logLevels", ["info", "warn", "error", "debug"]),
        log_file_pattern=raw.get("logFilePattern", "{level}/log-{level}-{date}.{seq}.log"),
        ssh_pool={**DEFAULT_SSH_POOL, **(raw.get("sshPool") or {})},
        query_defaults={**DEFAULT_QUERY_DEFAULTS, **(raw.get("queryDefaults") or {})},
    )

    for server in config.servers:
        _resolve_server_placeholders(server)

    logger.info(
        "Configuration loaded: %d server(s): %s",
        len(config.servers),
        ", ".join(f"{s.name}({s.connector})" for s in config.servers),
    )
    return config
