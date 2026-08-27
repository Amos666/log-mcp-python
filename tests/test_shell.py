import shlex

import pytest

from log_mcp.security.shell import contains_dangerous_chars, escape_for_grep, quote


class TestQuote:
    def test_plain_always_quoted(self):
        # 与原 Java 版 ShellEscaper 一致：恒单引号包裹
        assert quote("hello") == "'hello'"

    def test_specials_wrapped(self):
        assert quote("a b;c") == "'a b;c'"

    def test_single_quote_escaped(self):
        # 单引号内的单引号通过 '\'' 转义（与原 Java 版一致）
        assert quote("it's") == "'it'\\''s'"

    def test_empty(self):
        assert quote("") == "''"

    def test_none(self):
        assert quote(None) == "''"

    @pytest.mark.parametrize(
        "value", ["hello", "it's", "a b;c", "中文字符", "$(rm -rf /)", "a\nb"]
    )
    def test_quote_is_shell_safe(self, value):
        # 反向验证：转义结果经 shell 解析后必须还原为单个原值
        assert shlex.split(quote(value)) == [value]


class TestEscapeForGrep:
    def test_plain_fixed(self):
        assert escape_for_grep("ERROR", False) == "'ERROR'"

    @pytest.mark.parametrize(
        "keyword",
        ["a;b", "a|b", "a`b", "a$b", "a(b)", "a{b}", "a[b]", "a<b>", "a\nb", "a&b"],
    )
    def test_dangerous_fixed_mode_rejected(self, keyword):
        with pytest.raises(ValueError, match="dangerous characters"):
            escape_for_grep(keyword, False)

    def test_dangerous_allowed_in_regex_mode(self):
        assert escape_for_grep("err(or)?", True) == "'err(or)?'"

    def test_none(self):
        assert escape_for_grep(None, False) == "''"


def test_contains_dangerous_chars():
    assert contains_dangerous_chars("a;b")
    assert contains_dangerous_chars("a\nb")
    assert contains_dangerous_chars("err(or)?")  # 括号属于危险字符
    assert not contains_dangerous_chars("plain-text_1.2")
    assert not contains_dangerous_chars("NullPointer at com.example.Service")
