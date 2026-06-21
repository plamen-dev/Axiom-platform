"""Text utility functions for Axiom.

Small, deterministic, pure-function text helpers used across registries,
CLI output, and evidence generation.
"""

from __future__ import annotations

import re
import unicodedata


def safe_slug(text: str) -> str:
    """Convert arbitrary text into a filesystem-safe, URL-safe slug.

    Rules:
    - Lowercase
    - Unicode characters transliterated to ASCII via NFKD decomposition
    - Non-alphanumeric characters replaced with hyphens
    - Consecutive hyphens collapsed
    - Leading/trailing hyphens stripped
    - Empty input returns empty string
    """
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered)
    slug = slug.strip("-")
    return slug


def parse_key_value_lines(text: str) -> dict[str, str]:
    """Parse newline-delimited key=value text into a dict.

    Rules:
    - Lines formatted as key=value are parsed
    - Surrounding whitespace on keys and values is trimmed
    - Blank lines are ignored
    - Comment lines beginning with # are ignored
    - Malformed non-empty lines raise ValueError
    - Duplicate keys raise ValueError
    - Empty input returns empty dict
    """
    if not text or not text.strip():
        return {}

    result: dict[str, str] = {}
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(
                f"Malformed line {lineno}: {raw_line!r}"
            )
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError(
                f"Malformed line {lineno}: empty key in {raw_line!r}"
            )
        if key in result:
            raise ValueError(
                f"Duplicate key on line {lineno}: {key!r}"
            )
        result[key] = value
    return result
