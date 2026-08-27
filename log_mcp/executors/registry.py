"""通道注册表与路由。

- ``register_executor``: 注册通道工厂 ``name -> factory(AppConfig) -> CommandExecutor``；
- ``ExecutorRouter``: 实现同一抽象接口，按 ``server.connector`` 分发到具体通道实例；
- ``create_executors``: 依据配置中实际出现的 connector 懒构造通道并装配 Router。

新增通道（docker exec、跳板机、自研 Agent 等）只需实现 CommandExecutor
并在注册表登记，业务代码零改动。
"""

from __future__ import annotations

import logging
from typing import Callable

from log_mcp.config import AppConfig
from log_mcp.executors.base import CommandExecutor
from log_mcp.models import CommandResult

logger = logging.getLogger(__name__)

ExecutorFactory = Callable[[AppConfig], CommandExecutor]

EXECUTOR_REGISTRY: dict[str, ExecutorFactory] = {}


def register_executor(name: str, factory: ExecutorFactory) -> None:
    EXECUTOR_REGISTRY[name.lower()] = factory


class ExecutorRouter(CommandExecutor):
    """按服务器配置的 connector 将命令分发到对应通道。"""

    def __init__(self, config: AppConfig, executors: dict[str, CommandExecutor]):
        self._config = config
        self._executors = executors

    def execute(self, server_name: str, command: str, timeout_ms: int) -> CommandResult:
        server = self._config.get_server(server_name)
        if server is None:
            return CommandResult(-1, "", f"Error: Unknown server: {server_name}")
        executor = self._executors.get(server.connector)
        if executor is None:
            return CommandResult(
                -1, "", f"Error: no executor for connector '{server.connector}'"
            )
        return executor.execute(server_name, command, timeout_ms)

    def close(self) -> None:
        for executor in self._executors.values():
            executor.close()


def create_executors(config: AppConfig) -> ExecutorRouter:
    """为配置中出现的每种 connector 构造一个实例，装配路由器。"""
    from log_mcp.executors.local import LocalExecutor
    from log_mcp.executors.ssh_key import SshKeyExecutor

    register_executor("ssh", SshKeyExecutor)
    register_executor("local", LocalExecutor)

    # pyinfra 通道仅在配置使用时才导入（可选依赖）
    if any(s.connector == "pyinfra" for s in config.servers):
        from log_mcp.executors.pyinfra_exec import PyInfraExecutor

        register_executor("pyinfra", PyInfraExecutor)

    needed = {server.connector for server in config.servers}
    unknown = needed - set(EXECUTOR_REGISTRY)
    if unknown:
        raise ValueError(f"未知的 connector 类型: {', '.join(sorted(unknown))}")

    executors = {
        connector: EXECUTOR_REGISTRY[connector](config)
        for connector in sorted(needed)
    }
    logger.info("Executors ready: %s", ", ".join(f"{k}({type(v).__name__})" for k, v in executors.items()))

    router = ExecutorRouter(config, executors)
    return router
