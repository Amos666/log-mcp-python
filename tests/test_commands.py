from log_mcp.service.commands import (
    build_list_files_command,
    build_read_command,
    build_search_command,
    build_tail_command,
)


class TestSearchCommand:
    def test_fixed_keyword_basic(self):
        cmd = build_search_command("ERROR", False, 0, ["/logs/info/log-info-x.0.log"])
        assert cmd == "grep -i -n -F 'ERROR' '/logs/info/log-info-x.0.log' 2>/dev/null || true"

    def test_regex_keyword(self):
        cmd = build_search_command("err(or)?", True, 0, ["/f.log"])
        assert cmd.startswith("grep -i -n -E 'err(or)?'")

    def test_context_lines(self):
        cmd = build_search_command("E", False, 3, ["/f.log"])
        assert " -A 3 -B 3 'E'" in cmd

    def test_no_context(self):
        cmd = build_search_command("E", False, 0, ["/f.log"])
        assert " -A " not in cmd and " -B " not in cmd

    def test_multiple_files(self):
        cmd = build_search_command("E", False, 0, ["/a.log", "/b.log"])
        assert "'/a.log' '/b.log'" in cmd

    def test_keyword_with_space_and_quote(self):
        cmd = build_search_command("two words'q", False, 0, [])
        assert "'two words'\\''q'" in cmd


def test_tail_command():
    assert build_tail_command("/logs/info/x.log", 50) == "tail -n 50 '/logs/info/x.log'"


def test_read_command():
    assert build_read_command("/logs/info/x.log", 3, 10) == "sed -n '3,10p' '/logs/info/x.log'"


def test_list_files_command():
    cmd = build_list_files_command("/logs/error")
    assert cmd.startswith("find '/logs/error' -name '*.log' -type f")
    assert r"-printf '%p|%s|%TY-%Tm-%Td %TH:%TM:%TS\n'" in cmd
    assert cmd.endswith("2>/dev/null || true")
