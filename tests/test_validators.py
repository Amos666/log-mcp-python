import pytest

from log_mcp.security.validators import (
    build_full_path,
    validate_context_lines,
    validate_date,
    validate_file_path,
    validate_keyword,
    validate_level,
    validate_levels,
    validate_max_results,
)


class TestLevel:
    def test_valid_levels(self):
        for level in ("info", "INFO", "warn", "error", "debug"):
            validate_level(level)

    def test_none_allowed(self):
        validate_level(None)

    def test_invalid_level(self):
        with pytest.raises(ValueError, match="Invalid log level"):
            validate_level("trace")

    def test_invalid_level_list(self):
        with pytest.raises(ValueError):
            validate_levels(["info", "fatal"])


class TestDate:
    def test_valid(self):
        validate_date("2026-08-27")

    def test_none_allowed(self):
        validate_date(None)

    @pytest.mark.parametrize("bad", ["2026/08/27", "2026-8-27", "20260827", "2026-02-30"])
    def test_invalid(self, bad):
        with pytest.raises(ValueError):
            validate_date(bad)


class TestKeyword:
    def test_valid(self):
        validate_keyword("NullPointerException")

    def test_empty(self):
        with pytest.raises(ValueError, match="Keyword cannot be empty"):
            validate_keyword("   ")

    def test_too_long(self):
        with pytest.raises(ValueError, match="too long"):
            validate_keyword("x" * 501)


class TestLimits:
    def test_max_results(self):
        validate_max_results(100, 1000)
        with pytest.raises(ValueError, match="positive"):
            validate_max_results(0, 1000)
        with pytest.raises(ValueError, match="exceeds"):
            validate_max_results(1001, 1000)

    def test_context_lines(self):
        validate_context_lines(0)
        validate_context_lines(10)
        with pytest.raises(ValueError):
            validate_context_lines(11)
        with pytest.raises(ValueError):
            validate_context_lines(-1)


class TestFilePath:
    ROOT = "/var/logs/app"

    def test_valid_relative(self):
        validate_file_path("error/log-error-2026-05-04.0.log", self.ROOT)

    def test_empty(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_file_path("", self.ROOT)

    def test_traversal(self):
        with pytest.raises(ValueError, match="traversal"):
            validate_file_path("../etc/passwd.log", self.ROOT)

    def test_escape_root(self):
        with pytest.raises(ValueError, match="within log root"):
            validate_file_path("/etc/other.log", self.ROOT)

    def test_extension(self):
        with pytest.raises(ValueError, match=r"\.log"):
            validate_file_path("error/log-error-2026-05-04.0.txt", self.ROOT)

    def test_build_full_path(self):
        assert (
            build_full_path("/var/logs/app/", "error/x.log")
            == "/var/logs/app/error/x.log"
        )
