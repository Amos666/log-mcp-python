"""pyinfra 执行通道：复用 pyinfra 的主机连接体系执行命令。

适用场景：
1. 配置里给出 host/username/privateKeyPath —— 由本通道构造 pyinfra Inventory 建连
   （连接的建立、认证、命令执行全部交给 pyinfra 的 connector 体系）；
2. 配置里给出 ``pyinfraHost``（如 ``root@192.168.5.20:22``）与可选 ``pyinfraData``
   （透传 ssh_key / ssh_user / ssh_port 等 pyinfra 主机数据）—— 直接复用已有主机资产定义。

pyinfra 为可选依赖，仅在本通道被使用时导入。
"""

from __future__ import annotations

import logging
from typing import Optional

from log_mcp.config import AppConfig, ServerInfo
from log_mcp.executors.base import CommandExecutor
from log_mcp.models import CommandResult

logger = logging.getLogger(__name__)


class PyInfraExecutor(CommandExecutor):
    def __init__(self, config: AppConfig):
        self._config = config
        self._servers = [s for s in config.servers if s.connector == "pyinfra"]
        self._hosts: dict[str, object] = {}
        self._state = None
        self._connect()

    # ---- 内部：借 pyinfra Inventory/State 建立连接 ----
    def _connect(self) -> None:
        try:
            from pyinfra.api import Config as PyInfraConfig
            from pyinfra.api import Inventory, State
            from pyinfra.api.connect import connect_all
        except ImportError as exc:
            raise RuntimeError(
                "pyinfra 通道需要安装 pyinfra：pip install 'log-mcp-python[pyinfra]'"
            ) from exc

        names = []
        for server in self._servers:
            spec = server.pyinfra_host or server.host
            if not spec:
                raise ValueError(
                    f"server {server.name} 配置了 connector=pyinfra 但缺少 host/pyinfraHost"
                )
            data = dict(server.pyinfra_data)
            # 从通用字段补齐 pyinfra ssh 数据（未在 pyinfraData 中显式给出时）
            if server.username:
                data.setdefault("ssh_user", server.username)
            if server.port:
                data.setdefault("ssh_port", server.port)
            if server.private_key_path:
                data.setdefault("ssh_key", server.private_key_path)
            names.append((spec, data))

        inventory = Inventory((names, {}))
        config = PyInfraConfig()
        state = State(inventory, config, check_for_changes=False)
        connect_all(state)

        # 建立 server.name → Host 对象映射（按 spec 索引）
        host_by_name = {host.name: host for host in inventory}
        for server in self._servers:
            spec = server.pyinfra_host or server.host
            host = host_by_name.get(spec)
            if host is None:
                raise ValueError(f"pyinfra inventory 中未找到主机: {spec}")
            self._hosts[server.name] = host
        self._state = state
        logger.info("pyinfra 通道已连接 %d 台主机", len(self._hosts))

    def execute(self, server_name: str, command: str, timeout_ms: int) -> CommandResult:
        host = self._hosts.get(server_name)
        if host is None:
            return CommandResult(-1, "", f"Error: no pyinfra host for server {server_name}")
        try:
            logger.debug("Executing command via pyinfra on %s: %s", server_name, command)
            status, output = host.run_shell_command(command, _timeout=timeout_ms / 1000.0)
            exit_code = 0 if status else 1
            return CommandResult(
                exit_code,
                output.stdout or "",
                output.stderr or "",
            )
        except Exception as exc:  # noqa: BLE001 - 失败降级为结果，与其他通道一致
            logger.error("Error executing command via pyinfra on %s: %s", server_name, exc)
            return CommandResult(-1, "", f"Error: {exc}")

    def close(self) -> None:
        if self._state is None:
            return
        try:
            from pyinfra.api.connect import disconnect_all

            logger.info("Disconnecting pyinfra hosts")
            disconnect_all(self._state)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error disconnecting pyinfra hosts: %s", exc)
        finally:
            self._state = None
            self._hosts = {}
