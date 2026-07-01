"""Unit tests for the evidence-quality / substance verdict (Finding 2).

These test the shared rule helper in isolation from the producer/consumer so
the metric rule, the per-capability table, and the defensive-recompute path are
each proven directly.
"""

from __future__ import annotations

from axiom_core.evidence_quality import (
    EMPTY,
    NOT_EVALUATED,
    SUBSTANTIVE,
    evaluate_quality,
    required_metrics_for,
    resolve_quality,
)


class TestEvaluateQuality:
    def test_self_model_build_with_modules_is_substantive(self) -> None:
        q = evaluate_quality("self-model-build", {"module_count": 12})
        assert q["verdict"] == SUBSTANTIVE
        assert q["zero_metrics"] == []
        assert q["required_metrics"] == ["module_count"]

    def test_self_model_build_zero_modules_is_empty(self) -> None:
        q = evaluate_quality(
            "self-model-build",
            {"module_count": 0, "import_edge_count": 0, "isolated_module_count": 0},
        )
        assert q["verdict"] == EMPTY
        assert "module_count" in q["zero_metrics"]

    def test_missing_module_count_is_empty(self) -> None:
        q = evaluate_quality("self-model-build", {"import_edge_count": 3})
        assert q["verdict"] == EMPTY
        assert "module_count" in q["zero_metrics"]

    def test_import_edge_count_not_required(self) -> None:
        """A small/disconnected repo (modules, no edges) is still SUBSTANTIVE."""
        q = evaluate_quality(
            "self-model-build", {"module_count": 4, "import_edge_count": 0}
        )
        assert q["verdict"] == SUBSTANTIVE

    def test_unknown_capability_not_evaluated(self) -> None:
        q = evaluate_quality("some-capability", {"module_count": 0})
        assert q["verdict"] == NOT_EVALUATED
        assert q["required_metrics"] == []
        assert q["zero_metrics"] == []

    def test_zero_metrics_not_globally_invalid(self) -> None:
        """All-zero metrics for a no-rule capability do NOT become EMPTY."""
        q = evaluate_quality("mystery", {"a": 0, "b": 0})
        assert q["verdict"] == NOT_EVALUATED

    def test_non_dict_metrics_are_handled(self) -> None:
        q = evaluate_quality("self-model-build", None)  # type: ignore[arg-type]
        assert q["verdict"] == EMPTY

    def test_bool_module_count_treated_as_absent(self) -> None:
        q = evaluate_quality("self-model-build", {"module_count": True})
        assert q["verdict"] == EMPTY


class TestRequiredMetricsFor:
    def test_known(self) -> None:
        assert required_metrics_for("self-model-build") == ("module_count",)

    def test_unknown(self) -> None:
        assert required_metrics_for("nope") == ()


class TestResolveQuality:
    def test_uses_wellformed_stamped_verdict(self) -> None:
        bundle = {
            "metrics": {"module_count": 0},
            "quality": {"verdict": SUBSTANTIVE},
        }
        quality, recomputed = resolve_quality("self-model-build", bundle)
        assert quality["verdict"] == SUBSTANTIVE
        assert recomputed is False

    def test_recomputes_when_field_absent(self) -> None:
        bundle = {"metrics": {"module_count": 0}}
        quality, recomputed = resolve_quality("self-model-build", bundle)
        assert quality["verdict"] == EMPTY
        assert recomputed is True

    def test_recomputes_when_field_malformed(self) -> None:
        bundle = {"metrics": {"module_count": 0}, "quality": {"verdict": "BOGUS"}}
        quality, recomputed = resolve_quality("self-model-build", bundle)
        assert quality["verdict"] == EMPTY
        assert recomputed is True

    def test_recomputes_when_quality_not_a_dict(self) -> None:
        bundle = {"metrics": {"module_count": 5}, "quality": "nope"}
        quality, recomputed = resolve_quality("self-model-build", bundle)
        assert quality["verdict"] == SUBSTANTIVE
        assert recomputed is True
