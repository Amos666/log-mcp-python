"""Shell 命令转义（防止命令注入）。

对应原 Java 版 ShellEscaper：
- ``quote``: 单引号包裹，内部单引号替换为 ``'\\''``（与原版转义风格一致，
  保证跨版本生成的命令文本统一）；
- ``escape_for_grep``: 非 regex 模式下拒绝 shell 元字符（提示改用 regex），regex 模式单引号包裹。
"""

from __future__ import annotations

import re
from typing import Optional

_DANGEROUS_CHARS = re.compile(r"[;&|`$(){}\[\]<>\n\r]")


def quote(value: Optional[str]) -> str:
    """单引号包裹并转义内部单引号（None → 空引号）。"""
    if value is None:
        return "''"
    return "'" + value.replace("'", "'\\''") + "'"


def contains_dangerous_chars(value: str) -> bool:
    return bool(_DANGEROUS_CHARS.search(value))


def escape_for_grep(keyword: Optional[str], use_regex: bool) -> str:
    """转义 grep 关键词。

    :param keyword: 搜索关键词
    :param use_regex: 是否为正则表达式模式
    :raises ValueError: 非 regex 模式下包含危险 shell 元字符
    """
    if keyword is None:
        return "''"
    if not use_regex and contains_dangerous_chars(keyword):
        raise ValueError(
            "Keyword contains dangerous characters. Use regex mode or remove special characters."
        )
    return quote(keyword)
