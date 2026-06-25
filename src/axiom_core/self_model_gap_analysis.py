"""Self-Model Gap Analysis (Integration Milestone, PR #144).

Executable *negative discovery* on top of the repository self-model populated in
Integration PR #143. Given a populated capability-knowledge-graph report (the
self-model), this analyzer enumerates and classifies what is missing,
disconnected, unused, or unexplained across the repository and emits a ranked,
structured integration backlog (JSON + Markdown).

This is an **analyzer/adapter only** — like :mod:`axiom_core.self_model` it
introduces no new framework, registry, object family, engine, or evidence
system. It reads the existing self-model (plus, optionally, existing
command-registry / capability-summary metadata as extra evidence) and returns
plain ``dict`` findings. All output is deterministic: every module list is
sorted, gaps are assigned stable ids, and the backlog is sorted by a fixed
``(-score, gap_type, gap_id)`` key.

The analysis answers, from Axiom's own self-model, "where is integration
missing?" rather than the positive questions PR #143 answered ("what depends on
X?").
"""

from __future__ import annotations

from typing import Any

# Default execution chain whose stage-to-stage transitions the roadmap declares
# but which may not be supported by an actual import edge. Each stage lists the
# candidate module node-ids; the first one present in the graph is used.
DEFAULT_CHAIN_STAGES: list[tuple[str, tuple[str, ...]]] = [
    ("ExecutionPlan", ("axiom_core.execution_plan",)),
    ("ExecutionStep", ("axiom_core.execution_step",)),
    (
        "ExecutionAttempt",
        ("axiom_core.execution_attempt_v2", "axiom_core.execution_attempt"),
    ),
    ("ExecutionResult", ("axiom_core.execution_result",)),
    ("ExecutionArtifact", ("axiom_core.execution_artifact",)),
    ("ExecutionReport", ("axiom_core.execution_report",)),
]

# CLI-layer node prefixes: modules under these expose `axiom` commands.
_CLI_PREFIXES = ("axiom_cli.",)

# Minimum members for a prefix-grouped family to be considered a "framework
# family" worth flagging as disconnected.
_MIN_FAMILY_SIZE = 3

# Class-name suffixes that mark a module as an artifact/evidence producer.
_PRODUCER_SUFFIXES = ("Evidence", "Report")

# Per-gap-type base score (higher == more integration value). Reflects the
# ranking criteria: chain blockers and evidence/promotion gaps rank highest.
_BASE_SCORE: dict[str, int] = {
    "declared_but_unwired_chains": 100,
    "recommended_integration_candidates": 90,
    "artifact_or_evidence_producers_without_consumers": 80,
    "disconnected_framework_families": 70,
    "command_modules_with_low_connectivity": 60,
    "unconsumed_modules": 50,
    "isolated_modules": 50,
    "missing_purpose_or_layer_candidates": 40,
    "no_outgoing_dependency_modules": 30,
}

# Short stable id prefix per gap type.
_TYPE_CODE: dict[str, str] = {
    "isolated_modules": "ISO",
    "unconsumed_modules": "UNC",
    "no_outgoing_dependency_modules": "NOUT",
    "command_modules_with_low_connectivity": "CMD",
    "declared_but_unwired_chains": "CHAIN",
    "artifact_or_evidence_producers_without_consumers": "EVID",
    "missing_purpose_or_layer_candidates": "PURP",
    "disconnected_framework_families": "FAM",
    "recommended_integration_candidates": "REC",
}

# Number of affected modules to show inline in the Markdown before truncating.
_MD_PREVIEW = 12


def _priority(score: int) -> str:
    if score >= 70:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


def _family_of(module: str) -> str:
    """Family key for a module node-id (deterministic).

    ``axiom_core.execution_plan`` -> ``execution``; ``axiom_cli.main`` ->
    ``axiom_cli``; ``axiom_core.codebase_inventory`` -> ``codebase``.
    """
    if module.startswith("axiom_core."):
        rest = module[len("axiom_core.") :]
        head = rest.split(".", 1)[0]
        return head.split("_", 1)[0]
    return module.split(".", 1)[0]


class SelfModelGapAnalyzer:
    """Derives a ranked integration backlog from a populated self-model graph.

    Primary input is the persisted capability-knowledge-graph ``report`` (nodes,
    edges, ``orphan_node_ids``). Optional evidence enriches specific categories
    without changing the deterministic core:

    * ``module_classes``: ``{module: [class_name, ...]}`` from ``code-inventory``
      symbols, used to detect artifact/evidence producers.
    * ``documented_modules``: module ids that already have a capability summary,
      used to flag modules with no purpose/layer linkage.
    * ``chain_stages``: ordered ``(label, candidate_module_ids)`` for the
      declared execution chain (defaults to the roadmap's six stages).
    """

    def __init__(
        self,
        report: dict[str, Any],
        *,
        module_classes: dict[str, list[str]] | None = None,
        documented_modules: set[str] | None = None,
        chain_stages: list[tuple[str, tuple[str, ...]]] | None = None,
    ) -> None:
        self.report = report
        self.module_classes = module_classes
        self.documented_modules = documented_modules
        self.chain_stages = chain_stages or DEFAULT_CHAIN_STAGES

        self.modules: list[str] = sorted(
            n.get("source_id", "") for n in report.get("nodes", [])
        )
        self._module_set = set(self.modules)
        self.edges: list[tuple[str, str]] = sorted(
            (e.get("source_node_id", ""), e.get("target_node_id", ""))
            for e in report.get("edges", [])
        )
        self.isolated: list[str] = sorted(report.get("orphan_node_ids", []))

        self._out: dict[str, set[str]] = {m: set() for m in self.modules}
        self._in: dict[str, set[str]] = {m: set() for m in self.modules}
        for src, dst in self.edges:
            if src in self._out:
                self._out[src].add(dst)
            if dst in self._in:
                self._in[dst].add(src)

    # ------------------------------------------------------------------
    # Degree helpers
    # ------------------------------------------------------------------

    def _is_cli(self, module: str) -> bool:
        return any(module.startswith(p) for p in _CLI_PREFIXES)

    def _non_cli_degree(self, module: str) -> int:
        outs = {m for m in self._out.get(module, ()) if not self._is_cli(m)}
        ins = {m for m in self._in.get(module, ()) if not self._is_cli(m)}
        return len(outs) + len(ins)

    # ------------------------------------------------------------------
    # Individual gap detectors (each returns a list of gap dicts)
    # ------------------------------------------------------------------

    def _gap_isolated(self) -> list[dict[str, Any]]:
        if not self.isolated:
            return []
        return [
            self._make_gap(
                "isolated_modules",
                self.isolated,
                evidence=(
                    f"{len(self.isolated)} module(s) have zero import edges "
                    "(graph orphan_node_ids)."
                ),
                why=(
                    "Isolated modules neither consume nor are consumed by any "
                    "other module; they cannot participate in any end-to-end "
                    "behavior and are invisible to dependency queries."
                ),
                reuse=[
                    "capability_knowledge_graph",
                    "capability_relationship",
                    "code-inventory import edges",
                ],
                fix=(
                    "Wire each module to its real producer/consumer (add the "
                    "missing import or route its output through an existing "
                    "engine) so it gains at least one edge."
                ),
                behavior=(
                    "Each module becomes reachable in a dependency query "
                    "instead of an orphan."
                ),
                validation=(
                    "Re-run self-model-build; assert the module no longer "
                    "appears in orphan_node_ids."
                ),
            )
        ]

    def _gap_unconsumed(self) -> list[dict[str, Any]]:
        affected = sorted(
            m
            for m in self.modules
            if m not in set(self.isolated)
            and not self._in.get(m)
            and self._out.get(m)
        )
        if not affected:
            return []
        return [
            self._make_gap(
                "unconsumed_modules",
                affected,
                evidence=(
                    f"{len(affected)} module(s) have outgoing imports but zero "
                    "incoming consumers (no module imports them)."
                ),
                why=(
                    "An unconsumed module does work nothing else relies on; its "
                    "capability is not reused, so effort is stranded."
                ),
                reuse=["capability_relationship", "code-inventory import edges"],
                fix=(
                    "Identify the intended consumer and add the import/call, or "
                    "expose the module through an existing engine that callers "
                    "already use."
                ),
                behavior=(
                    "The module's capability becomes reachable from at least "
                    "one downstream consumer."
                ),
                validation=(
                    "Assert the module gains >=1 incoming edge after wiring."
                ),
            )
        ]

    def _gap_no_outgoing(self) -> list[dict[str, Any]]:
        affected = sorted(
            m
            for m in self.modules
            if m not in set(self.isolated)
            and not self._out.get(m)
            and self._in.get(m)
        )
        if not affected:
            return []
        return [
            self._make_gap(
                "no_outgoing_dependency_modules",
                affected,
                evidence=(
                    f"{len(affected)} module(s) are imported by others but "
                    "import no internal module themselves (leaf modules)."
                ),
                why=(
                    "Leaf modules are often genuine primitives, but some are "
                    "leaves only because they re-implement shared plumbing "
                    "instead of depending on it."
                ),
                reuse=["code-inventory import edges", "patch_impact_analyzer"],
                fix=(
                    "Confirm each is a true primitive; where it duplicates "
                    "shared logic, depend on the shared module instead."
                ),
                behavior=(
                    "Genuine duplication collapses onto shared dependencies; "
                    "true primitives are confirmed as such."
                ),
                validation=(
                    "Spot-check leaves for duplicated helpers; assert no "
                    "regression in import edges for confirmed primitives."
                ),
            )
        ]

    def _gap_command_low_connectivity(self) -> list[dict[str, Any]]:
        cli_modules = {m for m in self.modules if self._is_cli(m)}
        if not cli_modules:
            return []
        command_reachable = set()
        for cli in cli_modules:
            command_reachable |= {
                m for m in self._out.get(cli, ()) if m in self._module_set
            }
        affected = sorted(
            m
            for m in command_reachable
            if not self._is_cli(m) and self._non_cli_degree(m) == 0
        )
        if not affected:
            return []
        return [
            self._make_gap(
                "command_modules_with_low_connectivity",
                affected,
                evidence=(
                    f"{len(affected)} module(s) are imported by the CLI layer "
                    f"({sorted(cli_modules)}) but have zero non-CLI import "
                    "edges — exposed by a command yet structurally isolated."
                ),
                why=(
                    "A module reachable only from the CLI is operable by a "
                    "human command but cannot be composed by other capabilities "
                    "autonomously."
                ),
                reuse=[
                    "runner command_registry",
                    "capability_relationship",
                ],
                fix=(
                    "Connect the module to the capabilities that should consume "
                    "it programmatically, not only via the CLI entrypoint."
                ),
                behavior=(
                    "Command-exposed capabilities become reusable by other "
                    "modules, not just by a person typing a command."
                ),
                validation=(
                    "Assert each module gains a non-CLI edge after wiring."
                ),
            )
        ]

    def _gap_unwired_chains(self) -> list[dict[str, Any]]:
        # Resolve each declared stage to a present node (first candidate found).
        resolved: list[tuple[str, str | None]] = []
        for label, candidates in self.chain_stages:
            node = next((c for c in candidates if c in self._module_set), None)
            resolved.append((label, node))

        gaps: list[dict[str, Any]] = []
        for (a_label, a_mod), (b_label, b_mod) in zip(resolved, resolved[1:]):
            if a_mod is None or b_mod is None:
                missing = a_label if a_mod is None else b_label
                gaps.append(
                    self._make_gap(
                        "declared_but_unwired_chains",
                        [m for m in (a_mod, b_mod) if m],
                        title=f"{a_label} -> {b_label}",
                        evidence=(
                            f"Declared transition {a_label} -> {b_label} cannot "
                            f"be verified: stage module for {missing} is not "
                            "present as a node in the self-model."
                        ),
                        why=(
                            "A declared execution stage with no module in the "
                            "self-model cannot carry id flow; the chain cannot "
                            "execute end-to-end through it."
                        ),
                        reuse=[a_mod or "", b_mod or ""],
                        fix=(
                            "Confirm the stage module name and ensure it is "
                            "scanned, or remove the declared stage."
                        ),
                        behavior=(
                            "The chain's stage inventory matches reality."
                        ),
                        validation=(
                            "Assert each declared stage resolves to a graph "
                            "node."
                        ),
                    )
                )
                continue
            wired = (a_mod, b_mod) in set(self.edges) or (
                b_mod,
                a_mod,
            ) in set(self.edges)
            if not wired:
                gaps.append(
                    self._make_gap(
                        "declared_but_unwired_chains",
                        [a_mod, b_mod],
                        title=f"{a_label} -> {b_label}",
                        evidence=(
                            f"No import edge exists between {a_mod} and {b_mod} "
                            f"in either direction, yet {a_label} -> {b_label} is "
                            "declared as a consume-upstream transition."
                        ),
                        why=(
                            "The transition is satisfied only by documentation; "
                            "no executable dependency or id flow connects the "
                            "two stages, so the chain never executes as a chain."
                        ),
                        reuse=[a_mod, b_mod],
                        fix=(
                            f"Have {b_mod} consume {a_mod}'s output id (add the "
                            "import / pass the upstream id), establishing one "
                            "real edge for this transition."
                        ),
                        behavior=(
                            f"{b_label} can reconstruct its {a_label} via a real "
                            "reference instead of a docstring."
                        ),
                        validation=(
                            f"Assert an import edge {b_mod} -> {a_mod} exists "
                            "after wiring; assert an id flows between stages."
                        ),
                    )
                )
        return gaps

    def _gap_evidence_producers(self) -> list[dict[str, Any]]:
        if self.module_classes is None:
            return []
        producers = sorted(
            m
            for m, classes in self.module_classes.items()
            if m in self._module_set
            and any(
                c.endswith(_PRODUCER_SUFFIXES) for c in classes
            )
        )
        affected = sorted(
            m for m in producers if not self._in.get(m)
        )
        if not affected:
            return []
        return [
            self._make_gap(
                "artifact_or_evidence_producers_without_consumers",
                affected,
                evidence=(
                    f"{len(affected)} module(s) define *Evidence/*Report "
                    "producer classes yet have zero incoming consumers in the "
                    "self-model."
                ),
                why=(
                    "Evidence and reports written to disk that nothing consumes "
                    "cannot feed a trust/promotion loop — the verification "
                    "factory's evidence path stays open."
                ),
                reuse=[
                    "global_capability_registry",
                    "capability-state",
                    "capability_relationship",
                ],
                fix=(
                    "Route each producer's report id into a consumer (e.g. the "
                    "promotion registry) so evidence updates trust state."
                ),
                behavior=(
                    "Evidence from a run reaches a consumer instead of being "
                    "abandoned as an isolated artifact."
                ),
                validation=(
                    "Assert each producer gains an incoming consumer edge."
                ),
            )
        ]

    def _gap_missing_purpose(self) -> list[dict[str, Any]]:
        if self.documented_modules is None:
            documented: set[str] = set()
            detail = (
                "no capability_summary metadata was available, so no module "
                "has a detectable purpose/layer linkage"
            )
        else:
            documented = self.documented_modules
            detail = (
                f"{len(documented)} module(s) have a capability summary; the "
                "rest have no detectable purpose/layer linkage"
            )
        affected = sorted(m for m in self.modules if m not in documented)
        if not affected:
            return []
        return [
            self._make_gap(
                "missing_purpose_or_layer_candidates",
                affected,
                evidence=(
                    f"{len(affected)} module(s) have no capability summary "
                    f"linking purpose/layer ({detail})."
                ),
                why=(
                    "Without purpose/layer linkage Axiom cannot explain why a "
                    "module exists or which architectural layer it belongs to."
                ),
                reuse=["capability_summary", "code-inventory docstrings"],
                fix=(
                    "Populate capability_summary from module docstrings and add "
                    "a layer tag (the M3 direction), starting with the highest-"
                    "connectivity modules."
                ),
                behavior=(
                    "Axiom can answer 'why does X exist / which layer' from its "
                    "own summaries."
                ),
                validation=(
                    "Assert a capability_summary node exists per documented "
                    "module."
                ),
            )
        ]

    def _gap_disconnected_families(self) -> list[dict[str, Any]]:
        families: dict[str, list[str]] = {}
        for m in self.modules:
            families.setdefault(_family_of(m), []).append(m)

        gaps: list[dict[str, Any]] = []
        for family, members in sorted(families.items()):
            members = sorted(members)
            if len(members) < _MIN_FAMILY_SIZE:
                continue
            connected = [m for m in members if self._non_cli_degree(m) > 0]
            if connected:
                continue
            gaps.append(
                self._make_gap(
                    "disconnected_framework_families",
                    members,
                    title=f"{family}_* family",
                    evidence=(
                        f"All {len(members)} module(s) in the '{family}_*' "
                        "family have zero non-CLI import edges — the entire "
                        "family is structurally disconnected."
                    ),
                    why=(
                        "A whole framework family that connects to nothing "
                        "represents vocabulary added without integration; none "
                        "of its capabilities participates in an executable "
                        "path."
                    ),
                    reuse=[
                        "capability_relationship",
                        "capability_knowledge_graph",
                    ],
                    fix=(
                        "Wire one representative member of the family to its "
                        "real producer/consumer to begin integrating the "
                        "family (smallest viable edge first)."
                    ),
                    behavior=(
                        "The family stops being an island; at least one of its "
                        "capabilities becomes reachable."
                    ),
                    validation=(
                        "Assert >=1 family member gains a non-CLI edge."
                    ),
                )
            )
        return gaps

    # ------------------------------------------------------------------
    # Synthesis: recommended integration candidates (ranked roll-up)
    # ------------------------------------------------------------------

    def _gap_recommendations(
        self, prior: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        by_type: dict[str, list[dict[str, Any]]] = {}
        for g in prior:
            by_type.setdefault(g["gap_type"], []).append(g)

        recs: list[dict[str, Any]] = []

        chain = by_type.get("declared_but_unwired_chains", [])
        if chain:
            mods = sorted({m for g in chain for m in g["affected_modules"]})
            recs.append(
                self._make_gap(
                    "recommended_integration_candidates",
                    mods,
                    title="Wire one capability through the execution chain",
                    evidence=(
                        f"{len(chain)} declared chain transition(s) have no "
                        "supporting import edge."
                    ),
                    why=(
                        "Closing one full chain is the first complete end-to-"
                        "end engineering behavior the platform can demonstrate."
                    ),
                    reuse=["execution_* engines", "capability_relationship"],
                    fix=(
                        "Implement a thin orchestrator that passes each stage's "
                        "id to the next for a single capability."
                    ),
                    behavior=(
                        "Run one capability and get a single linked execution "
                        "trace from plan to report."
                    ),
                    validation=(
                        "Assert each stage record carries the upstream id and "
                        "the final report references resolve."
                    ),
                    refs=[g["gap_id"] for g in chain],
                )
            )

        evid = by_type.get(
            "artifact_or_evidence_producers_without_consumers", []
        )
        if evid:
            mods = sorted({m for g in evid for m in g["affected_modules"]})
            recs.append(
                self._make_gap(
                    "recommended_integration_candidates",
                    mods,
                    title="Route evidence producers into the promotion loop",
                    evidence=(
                        f"{len(mods)} evidence/report producer(s) have no "
                        "consumer."
                    ),
                    why=(
                        "Connecting evidence to promotion turns run output into "
                        "trust state automatically."
                    ),
                    reuse=["global_capability_registry", "capability-state"],
                    fix=(
                        "Feed producer report ids into the promotion registry."
                    ),
                    behavior=(
                        "Evidence from a run changes a capability's trust level "
                        "without human transcription."
                    ),
                    validation=(
                        "Assert promotion counters increment after a run."
                    ),
                    refs=[g["gap_id"] for g in evid],
                )
            )

        fam = by_type.get("disconnected_framework_families", [])
        if fam:
            biggest = max(fam, key=lambda g: len(g["affected_modules"]))
            recs.append(
                self._make_gap(
                    "recommended_integration_candidates",
                    biggest["affected_modules"],
                    title=f"Integrate the largest disconnected family "
                    f"({biggest.get('title', '')})",
                    evidence=(
                        f"{len(fam)} fully-disconnected family/families; "
                        f"largest has {len(biggest['affected_modules'])} "
                        "modules."
                    ),
                    why=(
                        "The largest island family yields the most coherence "
                        "per wiring edge."
                    ),
                    reuse=["capability_relationship", "code-inventory"],
                    fix=(
                        "Wire one representative member to its real "
                        "producer/consumer."
                    ),
                    behavior=(
                        "The biggest island family begins participating in the "
                        "dependency graph."
                    ),
                    validation=(
                        "Assert a member gains a non-CLI edge."
                    ),
                    refs=[biggest["gap_id"]],
                )
            )
        return recs

    # ------------------------------------------------------------------
    # Gap construction + scoring
    # ------------------------------------------------------------------

    def _make_gap(
        self,
        gap_type: str,
        affected_modules: list[str],
        *,
        evidence: str,
        why: str,
        reuse: list[str],
        fix: str,
        behavior: str,
        validation: str,
        title: str | None = None,
        refs: list[str] | None = None,
    ) -> dict[str, Any]:
        affected = sorted(m for m in affected_modules if m)
        score = _BASE_SCORE.get(gap_type, 0) + len(affected)
        gap: dict[str, Any] = {
            "gap_id": "",  # assigned later (stable, post-sort within type)
            "gap_type": gap_type,
            "title": title or gap_type.replace("_", " "),
            "affected_modules": affected,
            "affected_module_count": len(affected),
            "evidence": evidence,
            "why_it_matters": why,
            "existing_capabilities_to_reuse": sorted(set(r for r in reuse if r)),
            "proposed_smallest_fix": fix,
            "expected_new_behavior": behavior,
            "validation_strategy": validation,
            "score": score,
            "priority": _priority(score),
        }
        if refs:
            gap["related_gap_ids"] = sorted(set(refs))
        return gap

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self) -> dict[str, Any]:
        """Run every detector and return the full, ranked backlog dict."""
        gaps: list[dict[str, Any]] = []
        gaps += self._gap_isolated()
        gaps += self._gap_unconsumed()
        gaps += self._gap_no_outgoing()
        gaps += self._gap_command_low_connectivity()
        gaps += self._gap_unwired_chains()
        gaps += self._gap_evidence_producers()
        gaps += self._gap_missing_purpose()
        gaps += self._gap_disconnected_families()

        # Assign stable ids per type (sorted by affected count desc, then title).
        self._assign_ids(gaps)

        # Recommendations reference the ids just assigned.
        recs = self._gap_recommendations(gaps)
        self._assign_ids(recs, existing=gaps)
        gaps += recs

        gaps.sort(
            key=lambda g: (-g["score"], g["gap_type"], g["gap_id"])
        )

        counts: dict[str, int] = {}
        for g in gaps:
            counts[g["gap_type"]] = counts.get(g["gap_type"], 0) + 1

        return {
            "graph_report_id": self.report.get("report_id", ""),
            "generated_from": "self-model (capability_knowledge_graph)",
            "module_count": len(self.modules),
            "edge_count": len(self.edges),
            "isolated_module_count": len(self.isolated),
            "gap_count": len(gaps),
            "gap_counts_by_type": dict(sorted(counts.items())),
            "gaps": gaps,
        }

    def _assign_ids(
        self,
        gaps: list[dict[str, Any]],
        existing: list[dict[str, Any]] | None = None,
    ) -> None:
        used: dict[str, int] = {}
        for g in existing or []:
            code = _TYPE_CODE.get(g["gap_type"], "GAP")
            used[code] = used.get(code, 0)
        by_type: dict[str, list[dict[str, Any]]] = {}
        for g in gaps:
            by_type.setdefault(g["gap_type"], []).append(g)
        for gap_type, group in by_type.items():
            code = _TYPE_CODE.get(gap_type, "GAP")
            group.sort(
                key=lambda g: (-g["affected_module_count"], g["title"])
            )
            start = used.get(code, 0)
            for i, g in enumerate(group, start=start + 1):
                g["gap_id"] = f"{code}-{i:03d}"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def to_markdown(result: dict[str, Any]) -> str:
    """Render the backlog as a deterministic Markdown document."""
    lines: list[str] = []
    lines.append("# Self-Model Gap Analysis — Integration Backlog")
    lines.append("")
    lines.append(
        f"Generated from {result['generated_from']} "
        f"(graph `{result.get('graph_report_id', '')}`)."
    )
    lines.append("")
    lines.append(
        f"- Modules: {result['module_count']}  |  "
        f"Import edges: {result['edge_count']}  |  "
        f"Isolated: {result['isolated_module_count']}"
    )
    lines.append(f"- Total gaps: {result['gap_count']}")
    lines.append("")
    lines.append("## Gap counts by type")
    lines.append("")
    lines.append("| Gap type | Count |")
    lines.append("|---|---|")
    for gap_type, count in result["gap_counts_by_type"].items():
        lines.append(f"| {gap_type} | {count} |")
    lines.append("")
    lines.append("## Ranked integration backlog")
    lines.append("")
    for g in result["gaps"]:
        affected = g["affected_modules"]
        preview = ", ".join(affected[:_MD_PREVIEW])
        if len(affected) > _MD_PREVIEW:
            preview += f", … (+{len(affected) - _MD_PREVIEW} more)"
        lines.append(
            f"### {g['gap_id']} — {g['title']} "
            f"[{g['priority'].upper()}]"
        )
        lines.append("")
        lines.append(f"- **Gap type:** {g['gap_type']}")
        lines.append(
            f"- **Affected modules ({g['affected_module_count']}):** "
            f"{preview or '(none)'}"
        )
        lines.append(f"- **Evidence:** {g['evidence']}")
        lines.append(f"- **Why it matters:** {g['why_it_matters']}")
        lines.append(
            "- **Existing capabilities to reuse:** "
            + ", ".join(g["existing_capabilities_to_reuse"])
        )
        lines.append(f"- **Proposed smallest fix:** {g['proposed_smallest_fix']}")
        lines.append(f"- **Expected new behavior:** {g['expected_new_behavior']}")
        lines.append(f"- **Validation strategy:** {g['validation_strategy']}")
        if g.get("related_gap_ids"):
            lines.append(
                "- **Related gaps:** " + ", ".join(g["related_gap_ids"])
            )
        lines.append(f"- **Score:** {g['score']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
