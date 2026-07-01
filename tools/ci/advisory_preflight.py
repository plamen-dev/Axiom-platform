"""Advisory context preflight for CI (non-blocking, ALWAYS exit 0).

This is a *signpost, not a gate*. It reuses the existing
:mod:`axiom_core.context_preflight` scan plus a few lightweight diff heuristics
to surface repo-context advisories on a pull request as GitHub Actions
``::warning::`` annotations. It never fails the build — the whole point is to
prompt human judgement without introducing a blocking CI gate.

Advisories emitted:

* working-tree state warnings carried straight from ``context-preflight``;
* changes to **high-overlap "protected" components** (from the context-preflight
  system atlas) without a Context Basis in the PR body;
* new **runner / worker / evidence / attempt** concept modules under ``src/``
  added without a relationship note in the PR body;
* **provenance wording** ("legacy", "old-foundation", "pre-#NNN", "deprecated")
  *added* by the diff without an adjacent evidence link (``#123``, a URL, an
  ``artifacts/``/``docs/`` path, or a ``BUG-``/``BHV-``/``ADR-`` id);
* a PR body missing a "Context Basis" section.

Design constraints (approved): reuse existing tooling, add no new framework, and
never change exit status — see :func:`main`, which returns ``0`` unconditionally.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

# Import the existing context-preflight atlas as the source of truth for which
# components are "protected" (high overlap risk). No new component registry.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from axiom_core.context_preflight import (  # noqa: E402
    _COMPONENT_FAMILIES,
    run_preflight,
)

# Provenance wording that should be backed by evidence when introduced.
PROVENANCE_RE = re.compile(
    r"\b(legacy|old[-\s]?foundation|pre-#?\d+|deprecated)\b", re.IGNORECASE
)
# Any of these on the same added line counts as an adjacent evidence link.
EVIDENCE_RE = re.compile(
    r"(#\d+|https?://|artifacts/|docs/|BUG-\d+|BHV-\d+|ADR-\d+)", re.IGNORECASE
)
# Concept modules whose introduction warrants a relationship note.
CONCEPT_RE = re.compile(r"(runner|worker|evidence|attempt)", re.IGNORECASE)


# ── pure helpers (unit-tested) ────────────────────────────────────────────


def protected_component_files(
    families: list[dict] | None = None,
) -> dict[str, str]:
    """Map each high-overlap component file to its family name.

    "High overlap" is read from the context-preflight atlas
    (``overlap_risk`` beginning with ``high``); these are the components a
    change should not touch silently.
    """
    families = families if families is not None else _COMPONENT_FAMILIES
    protected: dict[str, str] = {}
    for family in families:
        risk = str(family.get("overlap_risk", "")).strip().lower()
        if not risk.startswith("high"):
            continue
        for rel in family.get("primary_files", []):
            protected[rel] = family.get("name", rel)
    return protected


def find_protected_changes(
    changed_files: list[str], protected: dict[str, str]
) -> list[tuple[str, str]]:
    """Return ``(file, family)`` for changed files that are protected."""
    return [(f, protected[f]) for f in changed_files if f in protected]


def find_provenance_wording(
    added_by_file: dict[str, list[str]],
) -> list[tuple[str, str]]:
    """Return ``(file, line)`` for added lines with unbacked provenance wording."""
    hits: list[tuple[str, str]] = []
    for path, lines in added_by_file.items():
        for line in lines:
            if PROVENANCE_RE.search(line) and not EVIDENCE_RE.search(line):
                hits.append((path, line.strip()))
    return hits


def find_new_concept_modules(added_files: list[str]) -> list[str]:
    """Return newly-added ``src/`` Python modules that name a core concept."""
    out: list[str] = []
    for path in added_files:
        if not path.startswith("src/") or not path.endswith(".py"):
            continue
        if path.endswith("__init__.py"):
            continue
        if CONCEPT_RE.search(Path(path).stem):
            out.append(path)
    return out


def body_has_context_basis(pr_body: str | None) -> bool:
    """Whether the PR body contains a Context Basis section."""
    return bool(pr_body) and "context basis" in pr_body.lower()


def format_warning(message: str, file: str | None = None) -> str:
    """Render a GitHub Actions ``::warning::`` annotation line."""
    if file:
        return f"::warning file={file}::{message}"
    return f"::warning::{message}"


# ── git plumbing (thin; integration-covered) ──────────────────────────────


def _git(args: list[str]) -> str:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout
    except OSError:
        return ""


def _diff_base() -> str | None:
    """Resolve the base ref to diff against (PR base, else origin/main)."""
    base_ref = os.environ.get("GITHUB_BASE_REF", "").strip()
    for candidate in (
        f"origin/{base_ref}" if base_ref else "",
        "origin/main",
        "main",
    ):
        if candidate and _git(["rev-parse", "--verify", "--quiet", candidate]):
            return candidate
    return None


def changed_files(base: str) -> list[str]:
    out = _git(["diff", "--name-only", f"{base}...HEAD"])
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def added_files(base: str) -> list[str]:
    out = _git(["diff", "--diff-filter=A", "--name-only", f"{base}...HEAD"])
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def added_lines(base: str) -> dict[str, list[str]]:
    """Parse ``git diff --unified=0`` into added lines keyed by file path."""
    out = _git(["diff", "--unified=0", f"{base}...HEAD"])
    result: dict[str, list[str]] = {}
    current: str | None = None
    for line in out.splitlines():
        if line.startswith("+++ b/"):
            current = line[len("+++ b/"):].strip()
            result.setdefault(current, [])
        elif line.startswith("+++ ") and line.endswith("/dev/null"):
            current = None
        elif current and line.startswith("+") and not line.startswith("+++"):
            result[current].append(line[1:])
    return {k: v for k, v in result.items() if v}


# ── orchestration ─────────────────────────────────────────────────────────


def collect_advisories(
    base: str | None, pr_body: str | None
) -> list[tuple[str, str | None]]:
    """Return ``(message, file)`` advisories. Never raises for advisory work."""
    advisories: list[tuple[str, str | None]] = []

    try:
        report = run_preflight(repo_root=str(_REPO_ROOT))
        for w in report.get("git_state", {}).get("warnings", []):
            advisories.append((f"context-preflight: {w}", None))
    except Exception as exc:  # advisory only — never fail the build
        advisories.append((f"context-preflight scan skipped: {exc}", None))

    if base is None:
        advisories.append(
            ("no base ref resolved; diff-based advisories skipped", None)
        )
        return advisories

    changed = changed_files(base)
    added = added_files(base)
    added_map = added_lines(base)
    has_basis = body_has_context_basis(pr_body)

    for path, family in find_protected_changes(
        changed, protected_component_files()
    ):
        if not has_basis:
            advisories.append(
                (
                    f"protected component '{family}' changed without a "
                    f"'Context Basis' section in the PR body",
                    path,
                )
            )

    for path in find_new_concept_modules(added):
        if not has_basis:
            advisories.append(
                (
                    "new runner/worker/evidence/attempt concept module added "
                    "without a relationship note (add a 'Context Basis' "
                    "section describing how it relates to existing components)",
                    path,
                )
            )

    for path, line in find_provenance_wording(added_map):
        advisories.append(
            (
                f"provenance wording without an adjacent evidence link: "
                f"{line!r}",
                path,
            )
        )

    if changed and not has_basis:
        advisories.append(
            ("PR body has no 'Context Basis' section (advisory)", None)
        )

    return advisories


def main() -> int:
    """Print advisories as annotations and ALWAYS exit 0."""
    base = _diff_base()
    pr_body = os.environ.get("PR_BODY", "")
    advisories = collect_advisories(base, pr_body)

    print("── Axiom advisory context preflight (non-blocking) ──")
    if not advisories:
        print("No advisories. (This check never fails the build.)")
        return 0

    for message, file in advisories:
        print(format_warning(message, file))
    print(f"\n{len(advisories)} advisory signpost(s). This check never fails the build.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
