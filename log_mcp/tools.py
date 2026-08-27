"""MCP 工具层：5 个工具的声明式定义（名称/描述/输入 Schema 与原版契约对齐）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from log_mcp.models import (
    ListLogFilesRequest,
    ReadLogFileRequest,
    SearchLogsRequest,
    TailLogsRequest,
)
from log_mcp.service.log_service import LogService

Param = dict[str, Any]


@dataclass(frozen=True)
class Tool:
    """一个 MCP 工具 = 名称 + 描述 + JSON Schema + 处理函数。"""

    name: str
    description: str
    input_schema: dict
    handler: Callable[[Param], Any]


def _str(description: str) -> dict:
    return {"type": "string", "description": description}


def _int(description: str) -> dict:
    return {"type": "integer", "description": description}


# ---------------------------------------------------------------- list_servers
_LIST_SERVERS = Tool(
    name="list_servers",
    description="List all configured servers",
    input_schema={"type": "object", "properties": {}, "required": []},
    handler=lambda params, svc: svc.list_servers(),
)

# ------------------------------------------------------------- list_log_files
_LIST_LOG_FILES = Tool(
    name="list_log_files",
    description="List available log files on the server",
    input_schema={
        "type": "object",
        "properties": {
            "level": _str("Log level filter"),
            "startDate": _str("Start date (YYYY-MM-DD)"),
            "endDate": _str("End date (YYYY-MM-DD)"),
            "server": _str("Target server"),
        },
        "required": [],
    },
    handler=lambda params, svc: svc.list_log_files(
        ListLogFilesRequest(
            server=params.get("server"),
            level=params.get("level"),
            start_date=params.get("startDate"),
            end_date=params.get("endDate"),
        )
    ),
)

# -------------------------------------------------------------- read_log_file
_READ_LOG_FILE = Tool(
    name="read_log_file",
    description="Read specific line range from a log file",
    input_schema={
        "type": "object",
        "properties": {
            "filePath": _str("Relative path to log file"),
            "server": _str("Target server"),
            "startLine": _int("Start line number"),
            "endLine": _int("End line number"),
            "maxLines": _int("Maximum lines to read"),
        },
        "required": ["filePath"],
    },
    handler=lambda params, svc: svc.read_log_file(
        ReadLogFileRequest(
            file_path=params.get("filePath", ""),
            server=params.get("server"),
            start_line=params.get("startLine"),
            end_line=params.get("endLine"),
            max_lines=params.get("maxLines"),
        )
    ),
)

# ----------------------------------------------------------------- search_logs
_SEARCH_LOGS = Tool(
    name="search_logs",
    description="Search for keywords in log files across specified date range and log levels",
    input_schema={
        "type": "object",
        "properties": {
            "keyword": _str("Search keyword"),
            "levels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Log levels to search (default: debug, info)",
            },
            "startDate": _str("Start date (YYYY-MM-DD)"),
            "endDate": _str("End date (YYYY-MM-DD)"),
            "maxResults": _int("Maximum results"),
            "contextLines": _int("Context lines"),
            "useRegex": {"type": "boolean", "description": "Use regex"},
            "server": _str("Target server"),
        },
        "required": ["keyword"],
    },
    handler=lambda params, svc: svc.search_logs(
        SearchLogsRequest(
            keyword=params.get("keyword", ""),
            levels=params.get("levels"),
            start_date=params.get("startDate"),
            end_date=params.get("endDate"),
            max_results=params.get("maxResults"),
            context_lines=params.get("contextLines"),
            use_regex=params.get("useRegex"),
            server=params.get("server"),
        )
    ),
)

# ------------------------------------------------------------------ tail_logs
_TAIL_LOGS = Tool(
    name="tail_logs",
    description="Get the latest log lines from a specific log level",
    input_schema={
        "type": "object",
        "properties": {
            "level": _str("Log level (default: info)"),
            "lines": _int("Number of lines (default: 50)"),
            "server": _str("Target server"),
        },
        "required": [],
    },
    handler=lambda params, svc: svc.tail_logs(
        TailLogsRequest(
            server=params.get("server"),
            level=params.get("level"),
            lines=params.get("lines"),
        )
    ),
)


def build_tools(log_service: LogService) -> list[Tool]:
    """构造绑定到 LogService 的工具列表（顺序即 tools/list 展示顺序）。"""
    bound = []
    for tool in (_SEARCH_LOGS, _TAIL_LOGS, _READ_LOG_FILE, _LIST_LOG_FILES, _LIST_SERVERS):
        bound.append(
            Tool(
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema,
                handler=lambda params, h=tool.handler, svc=log_service: h(params, svc),
            )
        )
    return bound
