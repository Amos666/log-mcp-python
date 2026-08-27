from log_mcp.models import CommandResult
from log_mcp.service.parser import (
    parse_find_output,
    parse_grep_output,
    parse_lines,
)


def _result(stdout: str, exit_code: int = 0, stderr: str = "") -> CommandResult:
    return CommandResult(exit_code, stdout, stderr)


class TestParseGrepSingleFile:
    def test_basic_match(self):
        out = parse_grep_output(_result("12:ERROR boom"), "srv", "f.log", 3, 100)
        assert len(out) == 1
        assert out[0].file == "f.log"
        assert out[0].line_number == 12
        assert out[0].content == "ERROR boom"

    def test_context_before_after(self):
        output = "1-pre1\n2-pre2\n3:MATCH\n4-post1\n5-post2\n6-post3\n7-post4"
        out = parse_grep_output(_result(output), "srv", "f.log", 2, 100)
        assert len(out) == 1
        # before 缓冲保留最近 2 行（行号前缀被剥离）
        assert out[0].context_before == ["pre1", "pre2"]
        # after 只取 2 行，其后的上下文行转为下一命中点的 before 缓冲
        assert out[0].context_after == ["post1", "post2"]

    def test_context_marker_resets(self):
        output = "1:FIRST\n--\n2-x\n3:SECOND"
        out = parse_grep_output(_result(output), "srv", "f.log", 3, 100)
        assert len(out) == 2
        assert out[1].context_before == ["x"]

    def test_max_results_truncates(self):
        output = "1:a\n2:b\n3:c\n4:d\n5:e"
        out = parse_grep_output(_result(output), "srv", "f.log", 0, 3)
        assert len(out) == 3

    def test_failed_command_returns_empty(self):
        assert parse_grep_output(_result("", -1), "srv", "f.log", 3, 10) == []

    def test_empty_output(self):
        assert parse_grep_output(_result(""), "srv", "f.log", 3, 10) == []


class TestParseGrepMultiFile:
    def test_multi_file_match_and_context(self):
        output = (
            "/logs/error/log-error-x.0.log:5:boom\n"
            "/logs/error/log-error-x.0.log-4-before\n"
            "/logs/error/log-error-x.0.log:6:boom2"
        )
        out = parse_grep_output(_result(output), "srv", "multiple", 3, 100)
        assert len(out) == 2
        assert out[0].file == "/logs/error/log-error-x.0.log"
        assert out[0].line_number == 5
        # 输出顺序上紧跟命中的上下文行进入上一命中的 after（与原版算法一致）
        assert out[0].context_after == ["before"]
        assert out[1].line_number == 6
        assert out[1].content == "boom2"


class TestParseGrepKnownFiles:
    """已知文件列表的确定性解析：日志内容含时间戳（冒号/连字符）时不误判。"""

    FILES = ["/logs/error/log-error-x.0.log", "/logs/error/log-error-x.1.log"]

    def test_timestamps_do_not_confuse(self):
        output = (
            "/logs/error/log-error-x.0.log:1:2026-05-04 04:22:28.774 ERROR NullPointerException at Service\n"
            "/logs/error/log-error-x.0.log-2-2026-05-04 04:22:29.100 ERROR follow-up line\n"
        )
        out = parse_grep_output(
            _result(output), "srv", "multiple", 3, 100, known_files=self.FILES
        )
        assert len(out) == 1
        assert out[0].file == "/logs/error/log-error-x.0.log"
        assert out[0].line_number == 1
        assert out[0].content == "2026-05-04 04:22:28.774 ERROR NullPointerException at Service"
        # 上下文行不会被误判为命中行
        assert out[0].context_after == ["2026-05-04 04:22:29.100 ERROR follow-up line"]

    def test_prefix_files_ordered_by_length(self):
        # 互为前缀的文件路径：更长者优先匹配
        files = ["/logs/a.log", "/logs/a.log-2026.0.log"]
        output = "/logs/a.log-2026.0.log:3:hit\n"
        out = parse_grep_output(_result(output), "srv", "multiple", 3, 100, known_files=files)
        assert len(out) == 1
        assert out[0].file == "/logs/a.log-2026.0.log"
        assert out[0].line_number == 3

    def test_unknown_lines_fall_back_to_heuristic(self):
        out = parse_grep_output(_result("9:plain"), "srv", "f.log", 3, 100, known_files=self.FILES)
        assert out[0].file == "f.log"
        assert out[0].line_number == 9


class TestParseLines:
    def test_basic(self):
        lines = parse_lines(_result("l1\nl2\nl3\n"))
        assert lines == ["l1", "l2", "l3"]

    def test_failed(self):
        assert parse_lines(_result("x", -1)) == []

    def test_empty(self):
        assert parse_lines(_result("")) == []


class TestParseFindOutput:
    def test_basic(self):
        output = "/logs/error/log-error-x.0.log|4400|2026-05-04 04:22:28\n"
        files = parse_find_output(_result(output), "/logs/error", "error")
        assert files == [
            {
                "path": "log-error-x.0.log",
                "size": "4.3KB",
                "lastModified": "2026-05-04 04:22:28",
                "level": "error",
            }
        ]

    def test_root_trailing_slash(self):
        output = "/logs/error/a.log|100|2026-05-04 04:22:28\n"
        files = parse_find_output(_result(output), "/logs/error/", "error")
        assert files[0]["path"] == "a.log"

    def test_malformed_lines_skipped(self):
        output = "badline\n/ok/a.log|10|2026-05-04 04:22:28\n/size-bad|x|t\n"
        files = parse_find_output(_result(output), "/ok", "info")
        assert len(files) == 1

    def test_failed(self):
        assert parse_find_output(_result("x", -1), "/logs", "info") == []


class TestSizeFormat:
    def test_bytes(self):
        assert parse_find_output(_result("/a/a.log|999|t\n"), "/a", "i")[0]["size"] == "999B"

    def test_mb(self):
        assert parse_find_output(_result("/a/a.log|2097152|t\n"), "/a", "i")[0]["size"] == "2.0MB"
