"""可插拔执行通道（Executor SPI）。

业务层只面向 :class:`CommandExecutor` 抽象：输入 ``(server, command, timeout_ms)``
（命令文本由 service/commands.py 统一生成，全通道唯一），输出统一的
``CommandResult(exit_code, stdout, stderr)``。通道自身管理连接生命周期。
"""

from log_mcp.executors.base import CommandExecutor
from log_mcp.executors.registry import (
    EXECUTOR_REGISTRY,
    ExecutorRouter,
    create_executors,
    register_executor,
)

__all__ = [
    "CommandExecutor",
    "ExecutorRouter",
    "create_executors",
    "register_executor",
    "EXECUTOR_REGISTRY",
]
