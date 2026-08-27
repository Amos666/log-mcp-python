"""CLI 入口：python -m log_mcp 或安装后的 log-mcp 命令。

启动方式与原 Java 版对应关系：
- 配置路径: ``--config`` / ``LOG_CONFIG`` 环境变量（默认 config.json）
- 传输模式: ``--transport`` / ``TRANSPORT_MODE`` 环境变量（默认 stdio）
- HTTP 端口: ``--port`` / ``SERVER_PORT`` 环境变量（默认 8892）
"""

from __future__ import annotations

import argparse
import os

from log_mcp import __version__
from log_mcp.server import run


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="log-mcp", description="Log-MCP: MCP 日志查询服务（Python 版）"
    )
    parser.add_argument("--config", default=None, help="配置文件路径 (默认: $LOG_CONFIG 或 config.json)")
    parser.add_argument(
        "--transport",
        default=None,
        choices=("stdio", "http"),
        help="MCP 传输模式 (默认: $TRANSPORT_MODE 或 stdio)",
    )
    parser.add_argument("--port", type=int, default=None, help="HTTP 模式监听端口 (默认: $SERVER_PORT 或 8892)")
    parser.add_argument("--log-level", default=None, help="日志级别 (默认 INFO)")
    parser.add_argument("--version", action="version", version=f"log-mcp-python {__version__}")
    args = parser.parse_args(argv)

    config_path = args.config or os.environ.get("LOG_CONFIG", "config.json")
    transport = args.transport or os.environ.get("TRANSPORT_MODE", "stdio")
    port = args.port or int(os.environ.get("SERVER_PORT", "8892"))

    run(config_path=config_path, transport=transport, port=port, log_level=args.log_level)


if __name__ == "__main__":
    main()
