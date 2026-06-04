"""Tests for the Capability Validation Registry (PR #23).

Covers the governance schema, the seed catalog, named-type contracts
(retry/promotion/evidence), SQLite persistence, unknown-capability denial, and
the ``axiom validation-registry`` CLI paths. Governance only — nothing here
executes a validation.
"""

import json

from axiom_cli.main import cli
from axiom_core.database import create_db_engine, init_db, make_session_factory
from axiom_core.models import ValidationProcedureRow
from axiom_core.validation import (
    DEFAULT_REGISTRY,
    CapabilityType,
    CapabilityValidationRegistry,
    EnvironmentRequirement,
    EvidenceItem,
    EvidenceKind,
    FailureCondition,
    PassCondition,
    PromotionEligibility,
    RetryPolicy,
    ValidationEvidence,
    ValidationProcedure,
    ValidationResult,
    ValidationStatus,
    get_procedure,
    is_known,
    list_procedures,
    persist_default_registry,
    procedure_names,
    procedures_by_capability_type,
    upsert_procedures,
    validate_registry,
)
from click.testing import CliRunner

SEED_CAPABILITIES = {
    "InventoryModel",
    "DiscoveryHarness",
    "SetParameterValue",
    "BridgeExecute",
}


# ---------------------------------------------------------------------------
# Catalog integrity
# ---------------------------------------------------------------------------


def test_default_registry_validates():
    validate_registry()  # raises on structural problems
    DEFAULT_REGISTRY.validate()


def test_seed_capabilities_present():
    assert set(procedure_names()) == SEED_CAPABILITIES


def test_every_procedure_has_full_contract():
    for proc in list_procedures():
        assert proc.capability_name
        assert isinstance(proc.capability_type, CapabilityType)
        assert proc.adapter and proc.version
        assert proc.validation_procedure_id
        assert proc.steps, f"{proc.capability_name} has no steps"
        assert proc.pass_conditions, f"{proc.capability_name} has no pass conditions"
        assert proc.failure_conditions, f"{proc.capability_name} has no failure conditions"
        assert proc.evidence.required_items(), f"{proc.capability_name} has no evidence"


def test_validation_procedure_ids_are_unique():
    ids = [p.validation_procedure_id for p in list_procedures()]
    assert len(ids) == len(set(ids))


def test_validate_rejects_key_mismatch():
    proc = get_procedure("InventoryModel")
    bad = CapabilityValidationRegistry({"WrongKey": proc})
    try:
        bad.validate()
    except ValueError as exc:
        assert "WrongKey" in str(exc)
    else:
        raise AssertionError("expected ValueError for key/name mismatch")


def test_validate_rejects_retry_condition_not_in_failures():
    proc = ValidationProcedure(
        capability_name="X",
        capability_type=CapabilityType.DISCOVERY,
        adapter="revit",
        version="v0",
        validation_procedure_id="x.proc",
        validation_name="X",
        validation_description="x",
        steps=("a",),
        environment_requirements=(),
        evidence=ValidationEvidence(required_artifacts=("a.json",)),
        pass_conditions=(PassCondition.ARTIFACTS_EXIST,),
        failure_conditions=(FailureCondition.EXCEPTION,),
        retry_policy=RetryPolicy(max_retries=1, retry_conditions=(FailureCondition.TIMEOUT,)),
    )
    reg = CapabilityValidationRegistry({"X": proc})
    try:
        reg.validate()
    except ValueError as exc:
        assert "retry condition" in str(exc)
    else:
        raise AssertionError("expected ValueError for dangling retry condition")


# ---------------------------------------------------------------------------
# Classification expectations
# ---------------------------------------------------------------------------


def test_set_parameter_value_is_mutation_definition_only():
    proc = get_procedure("SetParameterValue")
    assert proc.capability_type is CapabilityType.MUTATION
    assert proc.is_mutation
    assert proc.requires_revit
    assert proc.requires_model_open
    assert proc.requires_test_model  # must validate on a disposable/sample model
    assert "DEFINITION ONLY" in proc.notes


def test_discovery_harness_does_not_require_revit():
    proc = get_procedure("DiscoveryHarness")
    assert proc.capability_type is CapabilityType.DISCOVERY
    assert not proc.requires_revit  # read-only over an export
    assert EnvironmentRequirement.REQUIRES_INVENTORY_EXPORT in proc.environment_requirements
    for cond in (
        PassCondition.CATEGORIES_DISCOVERED,
        PassCondition.PARAMETERS_DISCOVERED,
        PassCondition.CANDIDATES_GENERATED,
        PassCondition.DISCOVERY_COMPLETE,
    ):
        assert cond in proc.pass_conditions


def test_bridge_execute_requires_runner_and_revit():
    proc = get_procedure("BridgeExecute")
    assert proc.capability_type is CapabilityType.BRIDGE
    assert proc.requires_revit
    assert proc.requires_runner


def test_by_capability_type_filter():
    mutations = procedures_by_capability_type(CapabilityType.MUTATION)
    assert [p.capability_name for p in mutations] == ["SetParameterValue"]


# ---------------------------------------------------------------------------
# Named-type contracts
# ---------------------------------------------------------------------------


def test_unknown_capability_denied_by_default():
    assert is_known("InventoryModel")
    assert not is_known("fake-capability")
    assert get_procedure("fake-capability") is None


def test_retry_policy_should_retry():
    policy = RetryPolicy(max_retries=2, retry_conditions=(FailureCondition.PIPE_UNAVAILABLE,))
    assert policy.should_retry(FailureCondition.PIPE_UNAVAILABLE)
    assert not policy.should_retry(FailureCondition.EXCEPTION)
    # No retries allowed when max_retries == 0 even if condition is listed.
    no_retry = RetryPolicy(max_retries=0, retry_conditions=(FailureCondition.TIMEOUT,))
    assert not no_retry.should_retry(FailureCondition.TIMEOUT)


def test_promotion_eligibility_is_pure_predicate():
    pe = PromotionEligibility(minimum_successes=3, minimum_evidence_sets=3, required_confidence=0.8)
    assert pe.is_eligible(successes=3, evidence_sets=3, confidence=0.8)
    assert not pe.is_eligible(successes=2, evidence_sets=3, confidence=0.9)
    assert not pe.is_eligible(successes=5, evidence_sets=1, confidence=0.9)
    assert not pe.is_eligible(successes=5, evidence_sets=5, confidence=0.5)


def test_evidence_coercion_and_kinds():
    ev = ValidationEvidence(
        required_artifacts=("request.json",),
        required_logs=("transcript",),
        required_checkpoints=(EvidenceItem(EvidenceKind.STATE, "before_state"),),
    )
    assert ev.required_artifacts[0].kind is EvidenceKind.ARTIFACT
    assert ev.required_logs[0].kind is EvidenceKind.LOG
    assert ev.required_checkpoints[0].kind is EvidenceKind.STATE
    assert len(ev.all_items()) == 3


def test_validation_result_defaults_untested():
    result = ValidationResult(
        capability_name="InventoryModel",
        validation_procedure_id="inventory_model.export_and_verify",
    )
    assert result.status is ValidationStatus.UNTESTED
    assert not result.passed
    assert result.to_dict()["status"] == "untested"


def test_to_dict_is_json_serializable():
    for proc in list_procedures():
        blob = json.dumps(proc.to_dict())  # must not raise
        restored = json.loads(blob)
        assert restored["capability_name"] == proc.capability_name
        assert "retry_policy" in restored
        assert "promotion_eligibility" in restored
        assert "evidence" in restored


# ---------------------------------------------------------------------------
# Persistence (reuses PR #1 SQLite patterns)
# ---------------------------------------------------------------------------


def _session_factory(tmp_path):
    engine = create_db_engine(str(tmp_path / "validation.db"))
    init_db(engine)
    return make_session_factory(engine)


def test_persist_default_registry_inserts_rows(tmp_path):
    sf = _session_factory(tmp_path)
    counts = persist_default_registry(sf)
    assert counts["inserted"] == len(SEED_CAPABILITIES)
    assert counts["updated"] == 0
    with sf() as session:
        assert session.query(ValidationProcedureRow).count() == len(SEED_CAPABILITIES)


def test_persist_is_idempotent_upsert(tmp_path):
    sf = _session_factory(tmp_path)
    persist_default_registry(sf)
    counts = persist_default_registry(sf)  # second pass updates, no new rows
    assert counts["inserted"] == 0
    assert counts["updated"] == len(SEED_CAPABILITIES)
    with sf() as session:
        assert session.query(ValidationProcedureRow).count() == len(SEED_CAPABILITIES)


def test_persisted_row_round_trips_json_fields(tmp_path):
    sf = _session_factory(tmp_path)
    upsert_procedures(sf, [get_procedure("SetParameterValue")])
    with sf() as session:
        row = (
            session.query(ValidationProcedureRow)
            .filter_by(capability_name="SetParameterValue")
            .one()
        )
        assert row.capability_type == "mutation"
        assert json.loads(row.pass_conditions_json) == ["parameter_value_matches"]
        retry = json.loads(row.retry_policy_json)
        assert retry["max_retries"] == 1
        promo = json.loads(row.promotion_eligibility_json)
        assert promo["minimum_successes"] == 5


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_list_shows_all_capabilities():
    result = CliRunner().invoke(
        cli, ["validation-registry"], env={"COLUMNS": "200"})
    assert result.exit_code == 0
    for name in SEED_CAPABILITIES:
        assert name in result.output


def test_cli_filter_by_type():
    result = CliRunner().invoke(
        cli, ["validation-registry", "--type", "mutation"], env={"COLUMNS": "200"})
    assert result.exit_code == 0
    assert "SetParameterValue" in result.output
    assert "DiscoveryHarness" not in result.output


def test_cli_invalid_type_exits_2():
    result = CliRunner().invoke(cli, ["validation-registry", "--type", "nonsense"])
    assert result.exit_code == 2


def test_cli_inspect_named_capability():
    result = CliRunner().invoke(cli, ["validation-registry", "--name", "DiscoveryHarness"])
    assert result.exit_code == 0
    assert "discovery_harness.run_and_verify" in result.output
    assert "Procedure steps" in result.output


def test_cli_unknown_capability_denied_exit_2():
    result = CliRunner().invoke(cli, ["validation-registry", "--name", "fake-capability"])
    assert result.exit_code == 2
    assert "denied by default" in result.output


def test_cli_json_output_is_valid():
    result = CliRunner().invoke(cli, ["validation-registry", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert {d["capability_name"] for d in data} == SEED_CAPABILITIES
    for entry in data:
        assert "retry_policy" in entry
        assert "promotion_eligibility" in entry
        assert "pass_conditions" in entry


def test_cli_json_unknown_capability_denied():
    result = CliRunner().invoke(
        cli, ["validation-registry", "--name", "nope", "--json"])
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["known"] is False


def test_cli_persist_writes_rows(tmp_path):
    db_path = str(tmp_path / "cli_validation.db")
    result = CliRunner().invoke(
        cli, ["validation-registry", "--persist", "--db-path", db_path])
    assert result.exit_code == 0
    assert "Persisted validation definitions" in result.output
    sf = make_session_factory(create_db_engine(db_path))
    with sf() as session:
        assert session.query(ValidationProcedureRow).count() == len(SEED_CAPABILITIES)
