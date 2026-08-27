"""Log-MCP: MCP 日志查询服务（Python 版）。

基于 caijianying/log-mcp（Java）的设计思想重构，提供完全一致的
MCP 工具接口，并支持可插拔的多执行通道（ssh / pyinfra / local）。
"""

__version__ = "1.0.0"

SERVER_NAME = "log-mcp"
PROTOCOL_VERSION = "2025-11-25"
