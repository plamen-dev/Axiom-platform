"""Tests for the word-to-number conversion utility."""


from axiom_core.word_numbers import replace_word_numbers, word_to_number


class TestWordToNumber:
    """Test individual word-to-number conversions."""

    def test_ones(self):
        assert word_to_number("one") == 1
        assert word_to_number("five") == 5
        assert word_to_number("nine") == 9

    def test_teens(self):
        assert word_to_number("ten") == 10
        assert word_to_number("thirteen") == 13
        assert word_to_number("nineteen") == 19

    def test_tens(self):
        assert word_to_number("twenty") == 20
        assert word_to_number("fifty") == 50
        assert word_to_number("ninety") == 90

    def test_compound_tens(self):
        assert word_to_number("twenty-five") == 25
        assert word_to_number("thirty two") == 32
        assert word_to_number("forty-eight") == 48

    def test_hundreds(self):
        assert word_to_number("one hundred") == 100
        assert word_to_number("two hundred") == 200
        assert word_to_number("five hundred") == 500

    def test_hundreds_compound(self):
        assert word_to_number("one hundred fifty") == 150
        assert word_to_number("two hundred twenty-five") == 225
        assert word_to_number("three hundred forty two") == 342

    def test_zero(self):
        assert word_to_number("zero") == 0

    def test_case_insensitive(self):
        assert word_to_number("TWENTY") == 20
        assert word_to_number("Five") == 5
        assert word_to_number("One Hundred") == 100

    def test_not_a_number(self):
        assert word_to_number("hello") is None
        assert word_to_number("grids") is None
        assert word_to_number("") is None

    def test_whitespace(self):
        assert word_to_number("  ten  ") == 10


class TestReplaceWordNumbers:
    """Test in-place word number replacement in text."""

    def test_single_word(self):
        result = replace_word_numbers("create five grids")
        assert "5" in result
        assert "five" not in result

    def test_compound_number(self):
        result = replace_word_numbers("twenty-five feet apart")
        assert "25" in result

    def test_multiple_numbers(self):
        result = replace_word_numbers("twenty vertical and ten horizontal")
        assert "20" in result
        assert "10" in result

    def test_preserves_non_numbers(self):
        result = replace_word_numbers("create grids spaced apart")
        assert result == "create grids spaced apart"

    def test_hundred(self):
        result = replace_word_numbers("one hundred feet long")
        assert "100" in result

    def test_mixed_with_digits(self):
        result = replace_word_numbers("10 vertical and ten horizontal")
        assert "10" in result
