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
