"""本地执行通道：直接以 subprocess 执行命令（开发/测试/单机场景）。"""

from __future__ import annotations

import logging
import subprocess

from log_mcp.config import AppConfig
from log_mcp.executors.base import CommandExecutor
from log_mcp.models import CommandResult

logger = logging.getLogger(__name__)


class LocalExecutor(CommandExecutor):
    def __init__(self, config: AppConfig | None = None):
        # config 仅为与其他通道工厂签名统一；本地通道无连接配置
        self._config = config
    def execute(self, server_name: str, command: str, timeout_ms: int) -> CommandResult:
        timeout_s = max(timeout_ms / 1000.0, 0.1)
        logger.debug("Executing local command for %s: %s", server_name, command)
        try:
            proc = subprocess.run(
                ["sh", "-c", command],
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
            return CommandResult(proc.returncode, proc.stdout, proc.stderr)
        except subprocess.TimeoutExpired:
            return CommandResult(-1, "", f"Error: command timed out after {timeout_ms}ms")
        except Exception as exc:  # noqa: BLE001 - 与远端通道行为对齐，失败降级为结果
            logger.error("Error executing local command: %s", exc)
            return CommandResult(-1, "", f"Error: {exc}")
