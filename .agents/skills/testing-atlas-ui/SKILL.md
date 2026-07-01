---
name: testing-atlas-ui
description: Verify the Axiom Atlas visual map UI (axiom atlas) — the module bubble graph, capability/evidence panels, static-snapshot serve behavior, and read-only guarantees. Use when testing or changing the Atlas viewer, or when a task needs browser-based verification with recording.
---

# Testing the Atlas UI

## Domain

`axiom atlas` renders a local-first, read-only visual map of the platform: self-model modules as bubbles with import edges, capability confidence/readiness, and captured evidence summaries. Source: `src/axiom_core/atlas.py`, CLI in `src/axiom_cli/main.py`. It is the only axiom command with a browser UI — test it in Chrome with a recording, not just shell output.

## Commands

- `axiom atlas [--repo-root <p>] [--serve] [--port <n>] [--json-output]` (default port 8763)

## Registry pointers

- Cataloged in `src/axiom_core/runner/command_registry.py` as READ_ONLY/SAFE.
- Reads: newest `artifacts/execution_chain/<run>/self_model.json`, latest per-capability `artifacts/capability_evidence_intake/` reports, `artifacts/validation_runs/*/evidence_summary.json`.
- Writes ONLY `artifacts/atlas/atlas.html` + `atlas_data.json` (gitignored).

## Verification checklists

- Serve with `poetry run axiom atlas --serve --port <p>` (run in background), then open `http://127.0.0.1:<p>/atlas.html`.
- Header must show the real self-model counts (`N modules · M import edges`) and the source run id; assert against `axiom atlas --json-output` counts, not hardcoded numbers.
- Hover a large bubble: tooltip shows module name + import-edge count, and its edges highlight.
- Right panels: capability pills (confidence/readiness) from intake reports; captured summaries with quality-verdict + decision pills and relative paths.
- Read-only assertions (shell): no tracked files modified, `artifacts/atlas/` gitignored, capability-confidence reports byte-identical before/after.
- Self-contained page: no CDN assets, no external calls, server binds 127.0.0.1 only; module names HTML-escaped.

## Tests

Targeted: `tests/test_atlas.py` (data collection, empty-workspace grace, no absolute paths, XSS escaping, read-only, registry governance). Full pytest only at PR checkpoints.

## Notes / gotchas

- The served page is a **static snapshot generated at server start** — artifacts created while serving (e.g. a new `emit_evidence_summary`) only appear after restarting the server or re-running `axiom atlas`. Don't mistake a stale page for a rendering bug; restart first. The server prints this at startup.
- If evidence panels are empty on a rebased branch, tracked summaries may live on an unmerged branch — emit a fresh one via the runner `emit_evidence_summary` action instead of merging.
