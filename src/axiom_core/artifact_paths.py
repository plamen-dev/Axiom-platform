"""Cross-platform artifact-sandbox path containment helper.

Shared by every engine that persists artifacts under a sandbox root. This
replaces the previous POSIX-only containment check::

    str(target).startswith(str(sandbox) + "/")

which false-failed on Windows because resolved paths use ``\\`` separators, so
a perfectly valid ``<sandbox>\\<uuid>`` never matched the hard-coded ``/`` and
was wrongly rejected with ``Resolved path escapes artifacts root``.

The replacement uses :meth:`pathlib.Path.relative_to`, which applies pathlib's
own (separator-aware and, on Windows, case-insensitive) semantics and therefore
behaves correctly on both POSIX and Windows without any hard-coded ``/`` or
``\\``. Path-traversal protection is preserved: a ``target`` that resolves
outside ``sandbox`` (``..`` escapes, absolute/drive-root injection, separators
inside an id) is not relative to ``sandbox`` and is rejected.
"""

from __future__ import annotations

from pathlib import Path


def is_within_sandbox(target: Path, sandbox: Path) -> bool:
    """Return ``True`` if ``target`` is ``sandbox`` itself or nested under it.

    Both arguments are expected to be already resolved (``Path.resolve()``).
    The check is lexical over the resolved paths, so it is cross-platform and
    raises nothing for inputs on different drives (Windows) — those simply
    return ``False``.
    """
    if target == sandbox:
        return True
    try:
        target.relative_to(sandbox)
        return True
    except ValueError:
        return False
