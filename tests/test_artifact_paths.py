"""Cross-platform regression tests for ``is_within_sandbox``.

These cover the Windows failure mode reported by the Program 5 Windows Local
Runner Compatibility Probe: ``execution-chain-run`` / ``capability-evidence-apply``
failing with ``Resolved path escapes artifacts root`` on Windows. The previous
POSIX-only check ``str(target).startswith(str(sandbox) + "/")`` false-failed
because resolved Windows paths use ``\\`` separators.

Windows behaviour is simulated with ``PureWindowsPath`` so it is exercised on
Devin's Ubuntu host; true on-Windows execution is re-run by the operator.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest
from axiom_core.artifact_paths import is_within_sandbox


class TestWindowsRegression:
    """The exact shapes the engines produce on Windows."""

    def test_uuid_segment_under_windows_root_is_within(self):
        sandbox = PureWindowsPath(r"C:\Dev\Axiom\artifacts\capability_confidence")
        target = sandbox / "11111111-2222-3333-4444-555555555555"
        # Old check (startswith "/") would wrongly reject this.
        assert is_within_sandbox(target, sandbox) is True

    def test_actions_runner_root_is_within(self):
        sandbox = PureWindowsPath(
            r"C:\actions-runner-axiom\actions-runner\_work\Axiom-platform"
            r"\Axiom-platform\artifacts\execution_reports"
        )
        target = sandbox / "abcdef00-0000-0000-0000-000000000000"
        assert is_within_sandbox(target, sandbox) is True

    def test_sandbox_itself_is_within(self):
        sandbox = PureWindowsPath(r"C:\Dev\Axiom\artifacts\x")
        assert is_within_sandbox(sandbox, sandbox) is True

    def test_windows_case_insensitive_match(self):
        sandbox = PureWindowsPath(r"C:\Dev\Axiom\Artifacts")
        target = PureWindowsPath(r"c:\dev\axiom\artifacts\report-id")
        assert is_within_sandbox(target, sandbox) is True


class TestWindowsTraversalRejected:
    def test_parent_escape_rejected(self):
        sandbox = PureWindowsPath(r"C:\Dev\Axiom\artifacts\x")
        target = PureWindowsPath(r"C:\Dev\Axiom\outside")
        assert is_within_sandbox(target, sandbox) is False

    def test_different_drive_rejected_without_error(self):
        sandbox = PureWindowsPath(r"C:\Dev\Axiom\artifacts\x")
        target = PureWindowsPath(r"D:\evil\report-id")
        # commonpath would raise across drives; relative_to returns cleanly.
        assert is_within_sandbox(target, sandbox) is False

    def test_unc_path_rejected(self):
        sandbox = PureWindowsPath(r"C:\Dev\Axiom\artifacts\x")
        target = PureWindowsPath(r"\\server\share\report-id")
        assert is_within_sandbox(target, sandbox) is False

    def test_sibling_prefix_not_treated_as_within(self):
        # "artifacts_evil" shares a string prefix with "artifacts" but is not nested.
        sandbox = PureWindowsPath(r"C:\Dev\Axiom\artifacts")
        target = PureWindowsPath(r"C:\Dev\Axiom\artifacts_evil\report-id")
        assert is_within_sandbox(target, sandbox) is False


class TestPosixUnchanged:
    def test_uuid_segment_within(self):
        sandbox = PurePosixPath("/home/ci/repo/artifacts/evidence_promotion")
        target = sandbox / "11111111-2222-3333-4444-555555555555"
        assert is_within_sandbox(target, sandbox) is True

    def test_sandbox_itself_within(self):
        sandbox = PurePosixPath("/home/ci/repo/artifacts/x")
        assert is_within_sandbox(sandbox, sandbox) is True

    def test_parent_escape_rejected(self):
        sandbox = PurePosixPath("/home/ci/repo/artifacts/x")
        target = PurePosixPath("/home/ci/repo/outside")
        assert is_within_sandbox(target, sandbox) is False

    def test_sibling_prefix_rejected(self):
        sandbox = PurePosixPath("/home/ci/repo/artifacts")
        target = PurePosixPath("/home/ci/repo/artifacts_evil/report-id")
        assert is_within_sandbox(target, sandbox) is False


class TestRealResolvedPaths:
    """Exercises the concrete ``Path.resolve()`` flow used by the engines."""

    def test_resolved_child_within(self, tmp_path: Path):
        sandbox = (tmp_path / "artifacts").resolve()
        sandbox.mkdir()
        target = (sandbox / "report-uuid").resolve()
        assert is_within_sandbox(target, sandbox) is True

    def test_resolved_traversal_id_rejected(self, tmp_path: Path):
        sandbox = (tmp_path / "artifacts").resolve()
        sandbox.mkdir()
        target = (sandbox / ".." / "escape").resolve()
        assert is_within_sandbox(target, sandbox) is False

    @pytest.mark.parametrize("evil_id", ["../escape", "../../etc", "a/b"])
    def test_resolved_relative_escapes_rejected(self, tmp_path: Path, evil_id: str):
        sandbox = (tmp_path / "artifacts").resolve()
        sandbox.mkdir()
        target = (sandbox / evil_id).resolve()
        if target == sandbox or sandbox in target.parents:
            assert is_within_sandbox(target, sandbox) is True
        else:
            assert is_within_sandbox(target, sandbox) is False
