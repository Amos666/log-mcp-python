"""通用工具：日期、日志文件名模式解析、尺寸格式化。"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

DATE_FORMAT = "%Y-%m-%d"


def today() -> str:
    return _dt.date.today().strftime(DATE_FORMAT)


def date_range(start_date: str, end_date: str) -> list[str]:
    """展开 [start, end] 闭区间内的所有日期（YYYY-MM-DD）。"""
    start = _dt.datetime.strptime(start_date, DATE_FORMAT).date()
    end = _dt.datetime.strptime(end_date, DATE_FORMAT).date()
    if end < start:
        return []
    days = (end - start).days + 1
    return [(start + _dt.timedelta(days=i)).strftime(DATE_FORMAT) for i in range(days)]


def format_size(num_bytes: int) -> str:
    """字节数人性化显示（B/KB/MB，与原版一致）。"""
    if num_bytes < 1024:
        return f"{num_bytes}B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f}KB"
    return f"{num_bytes / (1024 * 1024):.1f}MB"


@dataclass(frozen=True)
class FilePatternResolver:
    """按 ``logFilePattern``（如 ``{level}/log-{level}-{date}.{seq}.log``）推导日志文件路径。"""

    pattern: str

    def build_file(self, level: str, date: str, seq: int) -> str:
        return (
            self.pattern.replace("{level}", level)
            .replace("{date}", date)
            .replace("{seq}", str(seq))
        )

    def resolve_files(
        self, log_root_path: str, levels: list[str], start_date: str, end_date: str
    ) -> list[str]:
        """level × date × seq(0-9) 全组合展开为绝对路径列表（与原版一致，缺失文件由命令层容错）。"""
        files: list[str] = []
        for level in levels:
            for date in date_range(start_date, end_date):
                for seq in range(10):
                    files.append(f"{log_root_path.rstrip('/')}/{self.build_file(level, date, seq)}")
        return files
