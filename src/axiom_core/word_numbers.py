"""System-level word-to-number conversion utility.

Converts written-out numbers (e.g. "twenty", "one hundred") to their
numeric equivalents. Used across the platform wherever user input may
contain word numbers instead of digits — prompts, documents, Excel
imports, parameter descriptions.

Handles:
- Cardinal numbers: zero through nine hundred ninety-nine
- Compound forms: "twenty-five", "twenty five"
- Common construction quantities (up to 999)
"""

import re
from typing import Optional

_ONES = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}

_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}

_MAGNITUDE = {
    "hundred": 100,
}


def word_to_number(text: str) -> Optional[int]:
    """Convert a word-number string to an integer.

    Returns None if the text is not a recognized number word.

    Examples:
        word_to_number("five") -> 5
        word_to_number("twenty") -> 20
        word_to_number("twenty-five") -> 25
        word_to_number("one hundred") -> 100
        word_to_number("two hundred fifty") -> 250
        word_to_number("hello") -> None
    """
    text = text.lower().strip().replace("-", " ")
    tokens = text.split()

    if not tokens:
        return None

    # Single word lookup
    if len(tokens) == 1:
        word = tokens[0]
        if word in _ONES:
            return _ONES[word]
        if word in _TENS:
            return _TENS[word]
        return None

    # Multi-word: parse hundreds + tens + ones
    result = 0
    i = 0

    while i < len(tokens):
        word = tokens[i]

        if word in _ONES:
            val = _ONES[word]
            # Check if next token is "hundred"
            if i + 1 < len(tokens) and tokens[i + 1] == "hundred":
                result += val * 100
                i += 2
                continue
            result += val
            i += 1
        elif word in _TENS:
            val = _TENS[word]
            # Check if next token is a ones word (e.g. "twenty five")
            if i + 1 < len(tokens) and tokens[i + 1] in _ONES:
                result += val + _ONES[tokens[i + 1]]
                i += 2
                continue
            result += val
            i += 1
        elif word == "hundred":
            # "hundred" without a preceding number = 100
            if result == 0:
                result = 100
            i += 1
        else:
            return None

    return result if result > 0 or text.strip() == "zero" else None


def replace_word_numbers(text: str) -> str:
    """Replace word numbers in text with their digit equivalents.

    Scans for known number words and replaces them in-place.
    Preserves surrounding text. Handles compound forms.

    Examples:
        replace_word_numbers("twenty vertical grids") -> "20 vertical grids"
        replace_word_numbers("create five grids") -> "create 5 grids"
        replace_word_numbers("one hundred feet") -> "100 feet"
    """
    # Build pattern that matches multi-word numbers first, then single words
    # Order: hundreds compounds > tens-ones compounds > tens > ones
    all_words = set()
    all_words.update(_ONES.keys())
    all_words.update(_TENS.keys())
    all_words.add("hundred")

    # Match sequences of number words (greedy, longest first)
    # Structure: word (then optionally separator + word)*
    # This avoids consuming trailing whitespace after the last word.
    word_pattern = "|".join(sorted(all_words, key=len, reverse=True))
    pattern = re.compile(
        rf"\b((?:{word_pattern})(?:(?:\s+|-)(?:{word_pattern}))*)\b",
        re.IGNORECASE,
    )

    def _replace_match(match: re.Match) -> str:
        matched = match.group(0)
        result = word_to_number(matched)
        if result is None:
            return matched
        # Don't replace "one" used as a determiner (e.g. "one direction",
        # "one way"). Only replace "one" if followed by a number word
        # (e.g. "one hundred") or at end of string/before punctuation.
        if result == 1 and matched.strip().lower() == "one":
            after = text[match.end() :].lstrip()
            first_word = after.split()[0].lower() if after.split() else ""
            if first_word and first_word not in all_words:
                return matched
        return str(result)

    return pattern.sub(_replace_match, text)
