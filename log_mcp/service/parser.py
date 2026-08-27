"""远端命令输出解析：grep（含上下文）、tail/sed 行列表、find 文件列表。

grep 行格式识别策略（在原 Java 版基础上改进）：

- **已知文件列表优先（确定性匹配）**：命令由本服务统一构建，grep 收到的
  文件列表是已知的。多文件模式下 grep 输出 ``file:N:content``（命中）与
  ``file-N-content``（上下文），按已知文件前缀逐个匹配即可无歧义解析，
  不受日志内容中的时间戳（如 ``04:22:28`` 含冒号/连字符）干扰。
- **启发式回退**：无文件列表时使用与原版一致的贪婪正则
  （``^(.+):(\\d+):(.*)$`` 等）与单文件格式 ``N:content`` / ``N-content``。
- ``--`` 为 grep 的分组分隔符，重置上下文状态。
"""

from __future__ import annotations

import re
from typing import Optional, Sequence

from log_mcp.models import CommandResult, LogEntry
from log_mcp.util import format_size

_MULTI_FILE_MATCH = re.compile(r"^(.+):(\d+):(.*)$")
_MULTI_FILE_CONTEXT = re.compile(r"^(.+)-(\d+)-(.*)$")
_SINGLE_FILE_MATCH = re.compile(r"^(\d+):(.*)$")
_SINGLE_FILE_CONTEXT = re.compile(r"^(\d+)-(.*)$")


def parse_grep_output(
    result: CommandResult,
    server_name: str,
    default_file_name: str,
    context_lines: int,
    max_results: int,
    known_files: Sequence[str] = (),
) -> list[LogEntry]:
    """解析 grep -n -A -B 输出为结构化日志条目。

    上下文算法与原版一致：维护前置缓冲（context_before，超出 context_lines
    淘汰最旧）与命中后的后置计数（context_after，达 context_lines 停止追加）。

    :param known_files: 传给 grep 的文件列表（推荐提供，用于确定性解析）
    :param default_file_name: 单文件格式的缺省文件名（如 "multiple"）
    """
    if not result.is_success or not result.stdout.strip():
        return []

    # 已知文件按路径长度降序匹配，避免互为前缀的路径误配
    matchers = sorted(known_files, key=len, reverse=True)

    entries: list[LogEntry] = []
    context_before: list[str] = []
    current: Optional[LogEntry] = None
    after_count = 0

    for line in result.stdout.split("\n"):
        if line == "--":
            context_before.clear()
            current = None
            after_count = 0
            continue

        parsed = _parse_with_known_files(line, matchers)
        if parsed is None:
            parsed = _parse_heuristic(line, default_file_name)
        if parsed is None:
            # 与已知格式均不匹配：计入前置上下文缓冲
            context_before.append(line)
            if len(context_before) > context_lines:
                context_before.pop(0)
            continue

        file_name, line_number, content, is_match = parsed

        if not is_match:
            if current is not None and after_count < context_lines:
                current.context_after.append(content)
                after_count += 1
            else:
                context_before.append(content)
                if len(context_before) > context_lines:
                    context_before.pop(0)
            continue

        current = LogEntry(
            server=server_name,
            file=file_name,
            line_number=line_number,
            content=content,
            context_before=list(context_before),
        )
        entries.append(current)
        if len(entries) >= max_results:
            break
        after_count = 0
        context_before.clear()

    return entries


def _parse_with_known_files(line: str, matchers: Sequence[str]):
    """按已知文件前缀解析：``file:N:content``（命中）/ ``file-N-content``（上下文）。"""
    for file in matchers:
        prefix = file + ":"
        if line.startswith(prefix):
            m = _SINGLE_FILE_MATCH.match(line[len(prefix):])
            if m:
                return file, int(m.group(1)), m.group(2), True
            continue
        prefix = file + "-"
        if line.startswith(prefix):
            m = _SINGLE_FILE_CONTEXT.match(line[len(prefix):])
            if m:
                return file, int(m.group(1)), m.group(2), False
    return None


def _parse_heuristic(line: str, default_file_name: str):
    """无已知文件列表时的回退解析（与原 Java 版行为一致）。"""
    m = _MULTI_FILE_MATCH.match(line)
    if m:
        return m.group(1), int(m.group(2)), m.group(3), True

    m = _MULTI_FILE_CONTEXT.match(line)
    if m:
        return m.group(1), int(m.group(2)), m.group(3), False

    m = _SINGLE_FILE_MATCH.match(line)
    if m:
        return default_file_name, int(m.group(1)), m.group(2), True

    m = _SINGLE_FILE_CONTEXT.match(line)
    if m:
        return default_file_name, int(m.group(1)), m.group(2), False

    return None


def parse_lines(result: CommandResult) -> list[str]:
    """tail / sed 输出按行拆分。"""
    if not result.is_success or not result.stdout:
        return []
    output = result.stdout.rstrip("\n")
    if not output:
        return []
    return output.split("\n")


def parse_find_output(
    result: CommandResult, log_root_path: str, level: str
) -> list[dict]:
    """find -printf 'path|size|mtime' 输出解析为文件信息列表。"""
    files: list[dict] = []
    if not result.is_success:
        return files

    root_prefix = log_root_path.rstrip("/") + "/"
    for line in result.stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) != 3:
            continue
        path, size_str, last_modified = parts
        try:
            size = int(size_str)
        except ValueError:
            continue
        relative = path.removeprefix(root_prefix) if path.startswith(root_prefix) else path
        files.append(
            {
                "path": relative,
                "size": format_size(size),
                "lastModified": last_modified,
                "level": level,
            }
        )
    return files
