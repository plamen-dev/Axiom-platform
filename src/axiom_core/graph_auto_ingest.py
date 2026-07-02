"""Knowledge Graph Auto-Ingest v1.

Feeds evidence that already exists on disk into the capability knowledge
graph without manual ``capability-graph-create`` calls. Scans four
read-only artifact sources:

- ``artifacts/capability_evidence_intake/*/report.json`` — evidence
  intake reports (M2 promotion loop)
- ``artifacts/execution_chain/*/evidence.json`` — execution chain run
  evidence (M4 orchestrator)
- ``artifacts/validation_evidence/*/validation_run.json`` — CLI
  validation-evidence bundles
- ``artifacts/github_metadata_import/*/report.json`` — imported GitHub
  PR metadata (canonical PR sequence)

Each ingest run assembles one deterministic graph report via the existing
``CapabilityKnowledgeGraphEngine`` (append-only framework preserved).
Node and edge ids are derived from source ids, so re-running over the same
artifacts yields the same graph structure. Malformed artifact files are
recorded as skipped, never fatal, and nothing upstream is mutated.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from axiom_core.capability_knowledge_graph import (
    CapabilityKnowledgeGraphEngine,
)


def _node_id(node_type: str, source_id: str) -> str:
    return f"ingest:{node_type.lower()}:{source_id}"


def _edge_id(source_node_id: str, target_node_id: str, edge_type: str) -> str:
    return f"ingest:{edge_type.lower()}:{source_node_id}->{target_node_id}"


class GraphAutoIngestEngine:
    """Scan evidence artifacts and assemble a capability graph report."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._graph_engine = CapabilityKnowledgeGraphEngine(
            artifacts_root=str(artifacts_root)
        )

    # ------------------------------------------------------------------
    # Source loaders
    # ------------------------------------------------------------------

    def _load_json_files(
        self,
        subdir: str,
        filename: str,
        skipped: list[dict[str, str]],
    ) -> list[tuple[str, dict[str, Any]]]:
        root = self._artifacts_root / subdir
        if not root.is_dir():
            return []
        loaded: list[tuple[str, dict[str, Any]]] = []
        for entry in sorted(root.iterdir()):
            path = entry / filename
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                skipped.append(
                    {"file": f"{subdir}/{entry.name}/{filename}",
                     "error": str(exc)}
                )
                continue
            if isinstance(data, dict):
                loaded.append((entry.name, data))
        return loaded

    # ------------------------------------------------------------------
    # Node/edge builders per source
    # ------------------------------------------------------------------

    @staticmethod
    def _capability_node(capability_id: str) -> dict[str, Any]:
        return {
            "node_id": _node_id("CAPABILITY", capability_id),
            "node_type": "CAPABILITY",
            "source_id": capability_id,
            "label": capability_id,
            "summary": f"capability {capability_id}",
            "raw_payload": {"capability_id": capability_id},
        }

    def _ingest_intakes(
        self,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        skipped: list[dict[str, str]],
    ) -> int:
        count = 0
        for _, report in self._load_json_files(
            "capability_evidence_intake", "report.json", skipped
        ):
            intake_id = str(report.get("intake_id", "")).strip()
            capability_id = str(report.get("capability_id", "")).strip()
            if not intake_id or not capability_id:
                continue
            node_id = _node_id("VALIDATION", intake_id)
            nodes.append({
                "node_id": node_id,
                "node_type": "VALIDATION",
                "source_id": intake_id,
                "label": f"evidence intake for {capability_id}",
                "summary": (
                    f"decision={report.get('decision', '')} "
                    f"outcome={report.get('evidence_outcome', '')} "
                    f"state_changed={report.get('state_changed', False)}"
                ),
                "raw_payload": {
                    "intake_id": intake_id,
                    "capability_id": capability_id,
                    "decision": report.get("decision", ""),
                    "evidence_outcome": report.get("evidence_outcome", ""),
                    "evidence_path": report.get("evidence_path", ""),
                    "updated_state": report.get("updated_state", {}),
                },
            })
            nodes.append(self._capability_node(capability_id))
            cap_node_id = _node_id("CAPABILITY", capability_id)
            edges.append({
                "edge_id": _edge_id(node_id, cap_node_id, "VALIDATES"),
                "source_node_id": node_id,
                "target_node_id": cap_node_id,
                "edge_type": "VALIDATES",
                "summary": f"intake {intake_id} validates {capability_id}",
                "raw_payload": {"decision": report.get("decision", "")},
            })
            count += 1
        return count

    def _ingest_chain_runs(
        self,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        skipped: list[dict[str, str]],
    ) -> int:
        count = 0
        for run_dir, evidence in self._load_json_files(
            "execution_chain", "evidence.json", skipped
        ):
            evidence_id = str(evidence.get("evidence_id", "")).strip()
            if not evidence_id:
                continue
            references = evidence.get("references", {}) or {}
            capability_id = str(
                references.get("capability_id", "")
            ).strip()
            node_id = _node_id("ARTIFACT", evidence_id)
            nodes.append({
                "node_id": node_id,
                "node_type": "ARTIFACT",
                "source_id": evidence_id,
                "label": f"chain-run evidence ({run_dir})",
                "summary": str(evidence.get("summary", ""))[:200],
                "raw_payload": {
                    "evidence_id": evidence_id,
                    "chain_run": run_dir,
                    "metrics": evidence.get("metrics", {}),
                    "quality_verdict": (
                        (evidence.get("quality", {}) or {}).get(
                            "verdict", ""
                        )
                    ),
                    "references": references,
                },
            })
            if capability_id:
                nodes.append(self._capability_node(capability_id))
                cap_node_id = _node_id("CAPABILITY", capability_id)
                edges.append({
                    "edge_id": _edge_id(
                        cap_node_id, node_id, "HAS_ARTIFACT"
                    ),
                    "source_node_id": cap_node_id,
                    "target_node_id": node_id,
                    "edge_type": "HAS_ARTIFACT",
                    "summary": (
                        f"chain run {run_dir} produced evidence "
                        f"for {capability_id}"
                    ),
                    "raw_payload": {"chain_run": run_dir},
                })
            count += 1
        return count

    def _ingest_validation_runs(
        self,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        skipped: list[dict[str, str]],
    ) -> int:
        count = 0
        for run_dir, run in self._load_json_files(
            "validation_evidence", "validation_run.json", skipped
        ):
            run_id = str(run.get("run_id", "")).strip() or run_dir
            node_id = _node_id("VALIDATION", run_id)
            nodes.append({
                "node_id": node_id,
                "node_type": "VALIDATION",
                "source_id": run_id,
                "label": f"validation run {run.get('name', run_id)}",
                "summary": (
                    f"status={run.get('status', '')} "
                    f"commands={run.get('commands_passed', 0)}/"
                    f"{run.get('commands_total', 0)} passed"
                ),
                "raw_payload": {
                    "run_id": run_id,
                    "plan_id": run.get("plan_id", ""),
                    "status": run.get("status", ""),
                    "passed": run.get("passed", False),
                    "commands_total": run.get("commands_total", 0),
                    "commands_passed": run.get("commands_passed", 0),
                    "commands_failed": run.get("commands_failed", 0),
                },
            })
            count += 1
        return count

    def _ingest_github_imports(
        self,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        skipped: list[dict[str, str]],
    ) -> int:
        count = 0
        for _, report in self._load_json_files(
            "github_metadata_import", "report.json", skipped
        ):
            pr_number = report.get("repository_pr_number", 0)
            repository = str(report.get("repository", "")).strip()
            if not repository or not pr_number:
                continue
            pr_meta = (
                (report.get("metadata_import", {}) or {}).get("pr", {})
                or {}
            )
            source_id = f"{repository}#pr{pr_number}"
            node_id = _node_id("EVENT", source_id)
            nodes.append({
                "node_id": node_id,
                "node_type": "EVENT",
                "source_id": source_id,
                "label": str(pr_meta.get("title", f"PR #{pr_number}")),
                "summary": (
                    f"GitHub PR #{pr_number} canonical "
                    f"#{report.get('global_capability_number', 0)} "
                    f"status={pr_meta.get('status', '')}"
                ),
                "raw_payload": {
                    "repository": repository,
                    "repository_pr_number": pr_number,
                    "global_capability_number": report.get(
                        "global_capability_number", 0
                    ),
                    "title": pr_meta.get("title", ""),
                    "author": pr_meta.get("author", ""),
                    "status": pr_meta.get("status", ""),
                    "merged_at": pr_meta.get("merged_at", ""),
                    "import_report_id": report.get("report_id", ""),
                },
            })
            count += 1
        return count

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def ingest(self) -> dict[str, Any]:
        """Scan all artifact sources and create one graph report.

        Returns a summary with the created ``report_id``, per-source
        ingest counts, resulting node/edge counts, and any skipped
        (malformed) artifact files.
        """
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []

        source_counts = {
            "evidence_intakes": self._ingest_intakes(
                nodes, edges, skipped
            ),
            "chain_runs": self._ingest_chain_runs(nodes, edges, skipped),
            "validation_runs": self._ingest_validation_runs(
                nodes, edges, skipped
            ),
            "github_pr_imports": self._ingest_github_imports(
                nodes, edges, skipped
            ),
        }

        report = self._graph_engine.create(
            nodes=nodes,
            edges=edges,
            graph_raw_payload={
                "generator": "graph-auto-ingest",
                "source_counts": source_counts,
            },
            raw_metadata={"generator": "graph-auto-ingest"},
        )

        return {
            "report_id": report["report_id"],
            "artifacts_root": str(self._artifacts_root),
            "source_counts": source_counts,
            "node_count": report["node_count"],
            "edge_count": report["edge_count"],
            "node_type_counts": report["node_type_counts"],
            "edge_type_counts": report["edge_type_counts"],
            "duplicate_node_count": report["duplicate_node_count"],
            "duplicate_edge_count": report["duplicate_edge_count"],
            "orphan_node_count": report["orphan_node_count"],
            "skipped_count": len(skipped),
            "skipped": skipped,
        }
