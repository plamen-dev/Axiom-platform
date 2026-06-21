"""Tests for text_utils — safe_slug function."""

from __future__ import annotations

from axiom_core.text_utils import safe_slug


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
