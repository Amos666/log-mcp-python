"""执行通道抽象接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from log_mcp.models import CommandResult


class CommandExecutor(ABC):
    """命令执行通道：把一段 shell 命令送到目标机器执行并拿回统一结果。

    约定（与原 Java 版 CommandExecutor 语义一致）：
    - 执行失败（连接失败/超时）不抛异常，返回 exit_code=-1、错误信息置于 stderr；
    - 通道负责连接的创建、复用与健康检查。
    """

    @abstractmethod
    def execute(self, server_name: str, command: str, timeout_ms: int) -> CommandResult:
        """在指定服务器上执行命令。"""

    def close(self) -> None:  # pragma: no cover - 默认无资源
        """释放通道持有的全部连接资源。"""
        return None
