"""Evidence quality / substance verdict (Finding 2).

A *thin*, shared helper that judges whether an execution-chain evidence bundle
is semantically substantive or empty. It is deliberately **not** a new evidence
framework, a promotion doctrine, or a new object family: it is one pure function
plus a small per-capability required-metrics table, used by two existing places:

* the **producer** (``execution_chain_orchestrator._write_evidence``) stamps the
  verdict onto the bundle so it travels with the evidence (the bundle is the
  future navigable record);
* the **consumer** (``evidence_promotion.EvidencePromotionLoop.apply``) enforces
  it, defensively **recomputing** the verdict from the bundle's ``metrics`` when
  the field is absent or malformed so older / hand-authored bundles cannot
  bypass the gate.

Design contract (approved, Finding 2 option A):

* The execution-chain ``status`` (id-flow / plumbing verdict) is **unchanged**;
  this verdict is orthogonal and lives under a separate ``quality`` field.
* ``self-model-build`` requires ``module_count > 0``. ``import_edge_count`` and
  ``isolated_module_count`` are reported in the diagnostic ``reason`` but are
  **not** required (a small or disconnected repo can legitimately have modules
  with no import edges).
* Capabilities without a configured rule are ``NOT_EVALUATED`` and preserve
  current behavior (they are not blocked by this gate).
* Zero metrics are not globally invalid — only the configured required metrics
  for a capability are enforced.
"""

from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "1.0"

# Approved verdict values.
SUBSTANTIVE = "SUBSTANTIVE"
EMPTY = "EMPTY"
NOT_EVALUATED = "NOT_EVALUATED"

# Per-capability required metrics. A capability is EMPTY when every configured
# required metric is missing or zero. Capabilities absent from this table are
# NOT_EVALUATED (current behavior preserved). Deliberately small: this is a
# rule table, not a framework.
_REQUIRED_METRICS: dict[str, tuple[str, ...]] = {
    "self-model-build": ("module_count",),
}

# Metrics included in the diagnostic reason for context, without being required.
_DIAGNOSTIC_METRICS: dict[str, tuple[str, ...]] = {
    "self-model-build": ("import_edge_count", "isolated_module_count"),
}


def required_metrics_for(capability_id: str) -> tuple[str, ...]:
    """Return the configured required metric names for a capability (or ``()``)."""
    return _REQUIRED_METRICS.get((capability_id or "").strip(), ())


def _metric_value(metrics: dict[str, Any], name: str) -> int | None:
    """Coerce a metric to an int, or ``None`` if missing / not a number."""
    if not isinstance(metrics, dict) or name not in metrics:
        return None
    raw = metrics[name]
    if isinstance(raw, bool):  # bool is an int subclass; treat as absent.
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    return None


def evaluate_quality(capability_id: str, metrics: dict[str, Any]) -> dict[str, Any]:
    """Return the ``quality`` verdict for one capability's metrics.

    The verdict is a plain dict (JSON-serializable) with the approved shape::

        {
            "schema_version": ...,
            "verdict": SUBSTANTIVE | EMPTY | NOT_EVALUATED,
            "required_metrics": [...],   # configured for this capability
            "zero_metrics": [...],       # required metrics missing or == 0
            "reason": "...",
        }

    ``NOT_EVALUATED`` is returned for capabilities with no configured rule, so
    the promotion gate leaves their current behavior untouched.
    """
    capability = (capability_id or "").strip()
    required = _REQUIRED_METRICS.get(capability, ())
    metrics = metrics if isinstance(metrics, dict) else {}

    if not required:
        return {
            "schema_version": SCHEMA_VERSION,
            "verdict": NOT_EVALUATED,
            "required_metrics": [],
            "zero_metrics": [],
            "reason": (
                f"no evidence-quality rule configured for capability "
                f"{capability or '<unknown>'!r}; verdict not evaluated"
            ),
        }

    zero_metrics = [
        name for name in required if (_metric_value(metrics, name) or 0) <= 0
    ]

    diagnostics = _DIAGNOSTIC_METRICS.get(capability, ())
    diag_pairs = [
        f"{name}={_metric_value(metrics, name)}"
        for name in (*required, *diagnostics)
    ]
    diag_str = ", ".join(diag_pairs)

    if zero_metrics:
        verdict = EMPTY
        reason = (
            f"semantically empty evidence for {capability}: required metric(s) "
            f"{zero_metrics} missing or zero ({diag_str})"
        )
    else:
        verdict = SUBSTANTIVE
        reason = (
            f"substantive evidence for {capability}: required metric(s) "
            f"{list(required)} present and non-zero ({diag_str})"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": verdict,
        "required_metrics": list(required),
        "zero_metrics": zero_metrics,
        "reason": reason,
    }


def resolve_quality(
    capability_id: str, bundle: dict[str, Any]
) -> tuple[dict[str, Any], bool]:
    """Return ``(quality, recomputed)`` for an evidence bundle.

    Uses the bundle's own ``quality`` field when it is present and well-formed
    (a dict carrying a recognized ``verdict``); otherwise **defensively
    recomputes** the verdict from the bundle's ``metrics`` so older or malformed
    bundles cannot bypass the gate. ``recomputed`` reports which path was taken
    (for auditability in the intake record).
    """
    stamped = bundle.get("quality") if isinstance(bundle, dict) else None
    if (
        isinstance(stamped, dict)
        and stamped.get("verdict") in (SUBSTANTIVE, EMPTY, NOT_EVALUATED)
    ):
        return stamped, False
    metrics = bundle.get("metrics") if isinstance(bundle, dict) else {}
    return evaluate_quality(capability_id, metrics or {}), True
