"""统一命令构建层（全执行通道共用）。

所有日志操作在此归一为一段 POSIX shell 命令；关键词与路径一律经
security.shell 转义后再入命令，缺失文件容错由命令本身保证。
"""

from __future__ import annotations

from log_mcp.security.shell import escape_for_grep, quote


def build_search_command(
    keyword: str, use_regex: bool, context_lines: int, files: list[str]
) -> str:
    """grep 搜索命令（-i 忽略大小写，-n 行号，-F/-E 定串/正则，-A/-B 上下文）。"""
    parts = ["grep", "-i", "-n", "-E" if use_regex else "-F"]
    if context_lines > 0:
        parts += ["-A", str(context_lines), "-B", str(context_lines)]
    parts.append(escape_for_grep(keyword, use_regex))
    parts.extend(quote(file) for file in files)
    # 缺失文件容错：丢弃 stderr 且不影响后续文件
    return " ".join(parts) + " 2>/dev/null || true"


def build_tail_command(full_path: str, lines: int) -> str:
    return f"tail -n {int(lines)} {quote(full_path)}"


def build_read_command(full_path: str, start_line: int, end_line: int) -> str:
    return f"sed -n '{int(start_line)},{int(end_line)}p' {quote(full_path)}"


def build_list_files_command(level_dir: str) -> str:
    return (
        f"find {quote(level_dir)} -name '*.log' -type f "
        f"-printf '%p|%s|%TY-%Tm-%Td %TH:%TM:%TS\\n' 2>/dev/null || true"
    )
