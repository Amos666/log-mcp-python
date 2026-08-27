"""日志业务编排：参数校验 → 文件推导 → 命令构建 → 通道执行 → 结果解析。"""

from __future__ import annotations

import logging
import time

from log_mcp.config import AppConfig, ServerInfo
from log_mcp.executors.base import CommandExecutor
from log_mcp.models import (
    ListLogFilesRequest,
    ReadLogFileRequest,
    SearchLogsRequest,
    TailLogsRequest,
)
from log_mcp.security.validators import (
    build_full_path,
    validate_context_lines,
    validate_date,
    validate_keyword,
    validate_level,
    validate_levels,
    validate_max_results,
)
from log_mcp.service import commands
from log_mcp.service.parser import parse_find_output, parse_grep_output, parse_lines
from log_mcp.util import FilePatternResolver, today

logger = logging.getLogger(__name__)

_READ_TIMEOUT_MS = 10000
_DEFAULT_READ_SPAN = 100  # 无 endLine/maxLines 时默认读取 100 行（与原版一致）


class LogService:
    """面向工具层的日志服务，只依赖 CommandExecutor 抽象通道。"""

    def __init__(self, executor: CommandExecutor, config: AppConfig):
        self._executor = executor
        self._config = config
        self._file_resolver = FilePatternResolver(config.log_file_pattern)

    # ------------------------------------------------------------------ search
    def search_logs(self, request: SearchLogsRequest) -> dict:
        validate_keyword(request.keyword)
        validate_levels(request.levels)
        validate_date(request.start_date)
        validate_date(request.end_date)

        max_results = (
            request.max_results
            if request.max_results is not None
            else self._config.max_results()
        )
        validate_max_results(max_results, self._config.max_results_limit())

        context_lines = (
            request.context_lines
            if request.context_lines is not None
            else self._config.default_context_lines()
        )
        validate_context_lines(context_lines)

        server = self._config.resolve_server(request.server)
        use_regex = bool(request.use_regex)

        levels = request.levels or ["debug", "info"]
        start_date = request.start_date or today()
        end_date = request.end_date or today()

        log_files = self._file_resolver.resolve_files(
            server.log_root_path, levels, start_date, end_date
        )
        command = commands.build_search_command(
            request.keyword, use_regex, context_lines, log_files
        )

        started = time.monotonic()
        result = self._executor.execute(
            server.name, command, self._config.search_timeout_ms()
        )
        duration_ms = int((time.monotonic() - started) * 1000)

        entries = parse_grep_output(
            result, server.name, "multiple", context_lines, max_results,
            known_files=log_files,
        )

        return {
            "results": [entry.to_dict() for entry in entries],
            "summary": {
                "totalMatches": len(entries),
                "serversQueried": [server.name],
                "serversFailed": [],
                "searchTime": f"{duration_ms}ms",
            },
        }

    # -------------------------------------------------------------------- tail
    def tail_logs(self, request: TailLogsRequest) -> dict:
        validate_level(request.level)

        server = self._config.resolve_server(request.server)
        lines = request.lines if request.lines is not None else self._config.default_tail_lines()
        level = (request.level or "info").lower()

        file_name = self._file_resolver.build_file(level, today(), 0)
        full_path = f"{server.log_root_path.rstrip('/')}/{file_name}"
        command = commands.build_tail_command(full_path, lines)

        result = self._executor.execute(server.name, command, _READ_TIMEOUT_MS)
        log_lines = parse_lines(result)

        return {
            "server": server.name,
            "file": file_name,
            "lines": log_lines,
            "totalLines": len(log_lines),
        }

    # -------------------------------------------------------------------- read
    def read_log_file(self, request: ReadLogFileRequest) -> dict:
        server = self._config.resolve_server(request.server)
        full_path = build_full_path(server.log_root_path, request.file_path)

        start_line = request.start_line if request.start_line is not None else 1
        if request.end_line is not None:
            end_line = request.end_line
        elif request.max_lines is not None:
            end_line = start_line + request.max_lines - 1
        else:
            end_line = start_line + _DEFAULT_READ_SPAN - 1

        command = commands.build_read_command(full_path, start_line, end_line)
        result = self._executor.execute(server.name, command, _READ_TIMEOUT_MS)
        log_lines = parse_lines(result)

        return {
            "server": server.name,
            "file": request.file_path,
            "lines": log_lines,
            "totalLines": len(log_lines),
        }

    # ------------------------------------------------------------ list files
    def list_log_files(self, request: ListLogFilesRequest) -> dict:
        server = self._config.resolve_server(request.server)
        level = (request.level or "info").lower()

        level_dir = f"{server.log_root_path.rstrip('/')}/{level}"
        command = commands.build_list_files_command(level_dir)

        result = self._executor.execute(server.name, command, _READ_TIMEOUT_MS)
        files = parse_find_output(result, server.log_root_path, level)

        return {
            "server": server.name,
            "files": files,
            "totalFiles": len(files),
        }

    # ------------------------------------------------------------- list servers
    def list_servers(self) -> dict:
        servers = [
            {
                "name": server.name,
                "host": server.host,
                "description": server.description,
                "isDefault": server.is_default,
                "connector": server.connector,
                "status": "unknown",
            }
            for server in self._config.servers
        ]
        return {"servers": servers}
