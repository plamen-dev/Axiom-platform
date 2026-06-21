"""Tests for text_utils — safe_slug and parse_key_value_lines."""

from __future__ import annotations

import pytest
from axiom_core.text_utils import parse_key_value_lines, safe_slug


class TestSafeSlug:
    def test_basic(self) -> None:
        assert safe_slug("Hello World") == "hello-world"

    def test_empty(self) -> None:
        assert safe_slug("") == ""

    def test_whitespace_only(self) -> None:
        assert safe_slug("   ") == ""

    def test_special_characters(self) -> None:
        assert safe_slug("foo@bar!baz") == "foo-bar-baz"

    def test_consecutive_specials(self) -> None:
        assert safe_slug("a---b___c") == "a-b-c"

    def test_leading_trailing(self) -> None:
        assert safe_slug("--hello--") == "hello"

    def test_unicode(self) -> None:
        assert safe_slug("café résumé") == "cafe-resume"

    def test_numbers(self) -> None:
        assert safe_slug("PR #83 Trial") == "pr-83-trial"

    def test_mixed_case(self) -> None:
        assert safe_slug("CamelCase") == "camelcase"

    def test_already_slug(self) -> None:
        assert safe_slug("already-a-slug") == "already-a-slug"

    def test_path_like(self) -> None:
        assert safe_slug("src/axiom_core/main.py") == "src-axiom-core-main-py"

    def test_deterministic(self) -> None:
        for _ in range(100):
            assert safe_slug("Deterministic Test!") == "deterministic-test"


class TestParseKeyValueLines:
    def test_normal(self) -> None:
        result = parse_key_value_lines("name=Alice\nage=30")
        assert result == {"name": "Alice", "age": "30"}

    def test_whitespace_trimmed(self) -> None:
        result = parse_key_value_lines("  key  =  value  ")
        assert result == {"key": "value"}

    def test_blank_lines_ignored(self) -> None:
        result = parse_key_value_lines("a=1\n\n\nb=2")
        assert result == {"a": "1", "b": "2"}

    def test_comment_lines_ignored(self) -> None:
        result = parse_key_value_lines("# comment\nfoo=bar\n# another")
        assert result == {"foo": "bar"}

    def test_malformed_line_raises(self) -> None:
        with pytest.raises(ValueError, match="Malformed line"):
            parse_key_value_lines("good=ok\nbad line")

    def test_duplicate_key_raises(self) -> None:
        with pytest.raises(ValueError, match="Duplicate key"):
            parse_key_value_lines("x=1\nx=2")

    def test_empty_input(self) -> None:
        assert parse_key_value_lines("") == {}

    def test_whitespace_only_input(self) -> None:
        assert parse_key_value_lines("   \n  \n  ") == {}

    def test_value_with_equals(self) -> None:
        result = parse_key_value_lines("url=http://example.com?a=b")
        assert result == {"url": "http://example.com?a=b"}

    def test_empty_value(self) -> None:
        result = parse_key_value_lines("key=")
        assert result == {"key": ""}

    def test_deterministic(self) -> None:
        text = "b=2\na=1\nc=3"
        for _ in range(100):
            result = parse_key_value_lines(text)
            assert result == {"b": "2", "a": "1", "c": "3"}

    def test_empty_key_raises(self) -> None:
        with pytest.raises(ValueError, match="empty key"):
            parse_key_value_lines("=value")
