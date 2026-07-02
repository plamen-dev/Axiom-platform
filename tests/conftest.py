"""Shared test helpers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def make_symlink_or_skip(link: Path, target: str | os.PathLike[str]) -> None:
    """Create ``link`` pointing at ``target``, or skip the test.

    Windows requires a privilege (or Developer Mode) to create symlinks;
    without it (WinError 1314) a symlink-escape scenario cannot be
    constructed, so the safety test is skipped rather than failed. The
    production path-safety logic is unaffected.
    """
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
