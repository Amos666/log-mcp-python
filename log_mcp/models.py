"""数据模型：命令执行结果、日志条目、各工具请求。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CommandResult:
    """一次远端命令执行的统一结果（所有执行通道共用）。"""

    exit_code: int
    stdout: str = ""
    stderr: str = ""

    @property
    def is_success(self) -> bool:
        return self.exit_code == 0


@dataclass
class LogEntry:
    """grep 命中的一条日志（含上下文）。"""

    server: str = ""
    file: str = ""
    line_number: int = 0
    content: str = ""
    context_before: list[str] = field(default_factory=list)
    context_after: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "server": self.server,
            "file": self.file,
            "lineNumber": self.line_number,
            "content": self.content,
            "contextBefore": self.context_before,
            "contextAfter": self.context_after,
        }


@dataclass
class SearchLogsRequest:
    keyword: str = ""
    levels: Optional[list[str]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    max_results: Optional[int] = None
    context_lines: Optional[int] = None
    use_regex: Optional[bool] = None
    server: Optional[str] = None


@dataclass
class TailLogsRequest:
    server: Optional[str] = None
    level: Optional[str] = None
    lines: Optional[int] = None


@dataclass
class ReadLogFileRequest:
    file_path: str = ""
    server: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    max_lines: Optional[int] = None


@dataclass
class ListLogFilesRequest:
    server: Optional[str] = None
    level: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
