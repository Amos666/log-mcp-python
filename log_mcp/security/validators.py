"""参数与路径校验（防注入、防路径穿越、防资源滥用）。"""

from __future__ import annotations

import datetime as _dt
import os
import re
from typing import Optional

VALID_LEVELS = ("info", "warn", "error", "debug")

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_level(level: Optional[str]) -> None:
    if level is not None and level.lower() not in VALID_LEVELS:
        raise ValueError(f"Invalid log level: {level}")


def validate_levels(levels: Optional[list[str]]) -> None:
    if levels is not None:
        for level in levels:
            validate_level(level)


def validate_date(date: Optional[str]) -> None:
    if date is None:
        return
    if not _DATE_PATTERN.match(date):
        raise ValueError(f"Invalid date format: {date} (expected YYYY-MM-DD)")
    try:
        _dt.datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Invalid date: {date}") from None


def validate_keyword(keyword: Optional[str]) -> None:
    if keyword is None or not keyword.strip():
        raise ValueError("Keyword cannot be empty")
    if len(keyword) > 500:
        raise ValueError("Keyword too long (max 500 characters)")


def validate_max_results(max_results: int, limit: int) -> None:
    if max_results <= 0:
        raise ValueError("maxResults must be positive")
    if max_results > limit:
        raise ValueError(f"maxResults exceeds limit of {limit}")


def validate_context_lines(context_lines: int) -> None:
    if not 0 <= context_lines <= 10:
        raise ValueError("contextLines must be between 0 and 10")


def validate_file_path(file_path: Optional[str], log_root_path: str) -> None:
    """校验相对日志路径：非空、无路径穿越、必须位于 logRootPath 内、.log 结尾。"""
    if file_path is None or not file_path.strip():
        raise ValueError("File path cannot be empty")
    if ".." in file_path:
        raise ValueError("Path traversal not allowed")

    root = os.path.normpath(log_root_path)
    full = os.path.normpath(os.path.join(root, file_path))
    if not (full == root or full.startswith(root + os.sep) or full.startswith(root + "/")):
        raise ValueError("Path must be within log root directory")

    if not file_path.endswith(".log"):
        raise ValueError("Only .log files are allowed")


def build_full_path(log_root_path: str, relative_path: str) -> str:
    """校验并拼接出绝对日志路径。"""
    validate_file_path(relative_path, log_root_path)
    root = log_root_path.rstrip("/")
    return f"{root}/{relative_path.lstrip('/')}"
