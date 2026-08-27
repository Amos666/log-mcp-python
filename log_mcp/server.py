"""应用组装与生命周期（对应原 Java 版 LogMcpServer）。"""

from __future__ import annotations

import logging
import signal
import sys
from typing import Optional

from log_mcp.config import AppConfig, load_config
from log_mcp.executors.base import CommandExecutor
from log_mcp.executors.registry import create_executors
from log_mcp.mcp.handler import McpRequestHandler
from log_mcp.mcp.http_server import HttpServer
from log_mcp.mcp.stdio_server import StdioServer
from log_mcp.service.log_service import LogService
from log_mcp.tools import build_tools

logger = logging.getLogger(__name__)


def build_handler(config: AppConfig) -> tuple[McpRequestHandler, CommandExecutor]:
    """配置 → 执行通道 Router → LogService → 工具 → (MCP 处理器, 执行通道)。"""
    executor = create_executors(config)
    log_service = LogService(executor, config)
    tools = build_tools(log_service)
    return McpRequestHandler(tools), executor


def run(
    config_path: str,
    transport: str = "stdio",
    port: int = 8892,
    log_level: Optional[str] = None,
) -> None:
    """启动服务。

    :param config_path: 配置文件路径
    :param transport: 传输模式 stdio / http
    :param port: HTTP 模式监听端口
    :param log_level: 日志级别（默认 INFO；stdio 模式下日志仅走 stderr）
    """
    level = getattr(logging, (log_level or "INFO").upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    logger.info("Starting LogMCP Server (python)...")
    config = load_config(config_path)
    logger.info("Configuration loaded successfully")

    handler, executor = build_handler(config)
    logger.info("Request handler initialized")

    mode = transport.lower()
    logger.info("Transport mode: %s", mode)

    def _handle_signal(signum, frame) -> None:  # noqa: ARG001
        # 以异常展开阻塞中的 select/读循环，由 finally 统一清理（避免在
        # 信号处理器内执行阻塞的 shutdown 调用造成同线程互等）
        raise KeyboardInterrupt

    for sig_name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                signal.signal(sig, _handle_signal)
            except (ValueError, OSError):  # pragma: no cover - 非主线程等场景
                pass

    try:
        if mode == "http":
            HttpServer(handler, port).start()
        else:
            StdioServer(handler).start()
    except KeyboardInterrupt:
        logger.info("LogMCP Server interrupted")
    finally:
        logger.info("Shutting down LogMCP Server...")
        executor.close()
        logger.info("LogMCP Server stopped")
