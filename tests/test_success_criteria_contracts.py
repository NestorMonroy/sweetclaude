import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from success_criteria_contracts import (
    SuccessCriteriaValidationError,
    compute_success_criteria_contract_hash,
    validate_success_criteria_contract,
    validate_success_criteria_ledger,
    validate_success_criteria_workflow,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "success_criteria_contracts.py"


def _valid_contract() -> dict:
    return {
        "story_id": "STORY-123",
        "story_title": "Runtime success criteria validation",
        "story_objective": "Reject incomplete completion evidence deterministically.",
        "expected_outcomes": [
            {
                "id": "OUTCOME-001",
                "statement": "Completion is based on accepted evidence.",
            }
        ],
        "non_goals": [
            {
                "id": "NONGOAL-001",
                "statement": "Do not use open-ended review as completion authority.",
            }
        ],
        "success_criteria": [
            {
                "id": "SC-001",
                "outcome_id": "OUTCOME-001",
                "statement": "The validator rejects failed criteria.",
                "binary_predicate": "JSON field all_success_criteria_passed equals true",
                "measurement_type": "schema_check",
                "measurement_procedure": "Run success_criteria_contracts.py validate-ledger",
                "evidence_artifact": ".sweetclaude/reports/success-criteria-ledger.json",
                "evidence_owner": "controller",
                "pass_condition": "all_success_criteria_passed equals true",
                "fail_condition": "all_success_criteria_passed is missing or false",
                "allowed_phase_to_measure": "implementation",
                "amendment_policy": "human_approved_only",
                "backlog_routing": "Create a follow-up backlog item.",
            },
            {
                "id": "SC-002",
                "outcome_id": "OUTCOME-001",
                "statement": "Every criterion has fresh evidence.",
                "binary_predicate": "Every ledger criterion entry has evidence_fresh equals true",
                "measurement_type": "schema_check",
                "measurement_procedure": "Run success_criteria_contracts.py validate-ledger",
                "evidence_artifact": ".sweetclaude/reports/success-criteria-ledger.json",
                "evidence_owner": "controller",
                "pass_condition": "Every ledger criterion entry has evidence_fresh equals true",
                "fail_condition": "Any ledger criterion entry lacks evidence_fresh true",
                "allowed_phase_to_measure": "implementation",
                "amendment_policy": "human_approved_only",
                "backlog_routing": "Create a follow-up backlog item.",
            },
        ],
        "contract_freeze": {
            "frozen_at": "2026-05-31T12:00:00Z",
            "frozen_by": "test",
            "contract_hash": "",
        },
    }


def _freeze(contract: dict) -> dict:
    contract["contract_freeze"]["contract_hash"] = compute_success_criteria_contract_hash(contract)
    return contract


def _write_contract(path: Path, contract: dict | None = None) -> Path:
    contract = _freeze(contract or _valid_contract())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")
    return path


def _valid_ledger(contract: dict) -> dict:
    contract_hash = compute_success_criteria_contract_hash(contract)
    return {
        "story_id": contract["story_id"],
        "success_criteria_contract_hash": contract_hash,
        "all_success_criteria_passed": True,
        "criteria": [
            {
                "id": criterion["id"],
                "status": "pass",
                "success_criteria_contract_hash": contract_hash,
                "evidence_artifact": criterion["evidence_artifact"],
                "evidence_owner": criterion["evidence_owner"],
                "evidence_fresh": True,
            }
            for criterion in contract["success_criteria"]
        ],
    }


def _write_ledger(path: Path, ledger: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    return path


def test_contract_validation_accepts_frozen_binary_contract(tmp_path):
    contract = _valid_contract()
    contract_path = _write_contract(tmp_path / "success-criteria-contract.yaml", contract)

    result = validate_success_criteria_contract(contract_path)

    assert result["ok"] is True
    assert result["criterion_ids"] == ["SC-001", "SC-002"]


def test_contract_validation_rejects_stale_hash(tmp_path):
    contract = _freeze(_valid_contract())
    contract["story_title"] = "Changed after freeze"
    contract_path = tmp_path / "success-criteria-contract.yaml"
    contract_path.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")

    with pytest.raises(SuccessCriteriaValidationError, match="contract_hash mismatch"):
        validate_success_criteria_contract(contract_path)


def test_contract_validation_rejects_vague_non_binary_criteria(tmp_path):
    contract = _valid_contract()
    contract["success_criteria"][0]["statement"] = "The implementation is SOTA"
    contract["success_criteria"][0]["binary_predicate"] = "Reviewer approved"
    contract["success_criteria"][0]["pass_condition"] = "Reviewer approved"
    contract["success_criteria"][0]["fail_condition"] = "Reviewer did not approve"
    contract["success_criteria"][0]["measurement_procedure"] = "Ask reviewer"
    contract_path = _write_contract(tmp_path / "success-criteria-contract.yaml", contract)

    with pytest.raises(SuccessCriteriaValidationError, match="not objectively measurable"):
        validate_success_criteria_contract(contract_path)


def test_contract_validation_rejects_missing_fail_condition(tmp_path):
    contract = _valid_contract()
    contract["success_criteria"][0]["fail_condition"] = ""
    contract_path = _write_contract(tmp_path / "success-criteria-contract.yaml", contract)

    with pytest.raises(SuccessCriteriaValidationError, match="missing fail_condition"):
        validate_success_criteria_contract(contract_path)


def test_ledger_validation_accepts_complete_fresh_evidence(tmp_path):
    contract = _freeze(_valid_contract())
    contract_path = _write_contract(tmp_path / "success-criteria-contract.yaml", contract)
    ledger_path = _write_ledger(tmp_path / "success-criteria-ledger.json", _valid_ledger(contract))

    result = validate_success_criteria_ledger(
        contract_path=contract_path,
        ledger_path=ledger_path,
    )

    assert result["ok"] is True
    assert result["all_success_criteria_passed"] is True


def test_ledger_validation_rejects_stale_contract_hash(tmp_path):
    contract = _freeze(_valid_contract())
    contract_path = _write_contract(tmp_path / "success-criteria-contract.yaml", contract)
    ledger = _valid_ledger(contract)
    ledger["success_criteria_contract_hash"] = "sha256:" + "0" * 64
    ledger_path = _write_ledger(tmp_path / "success-criteria-ledger.json", ledger)

    with pytest.raises(SuccessCriteriaValidationError, match="success_criteria_contract_hash mismatch"):
        validate_success_criteria_ledger(contract_path=contract_path, ledger_path=ledger_path)


def test_ledger_validation_rejects_missing_criterion(tmp_path):
    contract = _freeze(_valid_contract())
    contract_path = _write_contract(tmp_path / "success-criteria-contract.yaml", contract)
    ledger = _valid_ledger(contract)
    ledger["criteria"] = ledger["criteria"][:1]
    ledger_path = _write_ledger(tmp_path / "success-criteria-ledger.json", ledger)

    with pytest.raises(SuccessCriteriaValidationError, match="criterion ids do not match"):
        validate_success_criteria_ledger(contract_path=contract_path, ledger_path=ledger_path)


def test_ledger_validation_rejects_failed_criterion(tmp_path):
    contract = _freeze(_valid_contract())
    contract_path = _write_contract(tmp_path / "success-criteria-contract.yaml", contract)
    ledger = _valid_ledger(contract)
    ledger["criteria"][0]["status"] = "fail"
    ledger_path = _write_ledger(tmp_path / "success-criteria-ledger.json", ledger)

    with pytest.raises(SuccessCriteriaValidationError, match="failed criteria"):
        validate_success_criteria_ledger(contract_path=contract_path, ledger_path=ledger_path)


def test_ledger_validation_rejects_stale_evidence(tmp_path):
    contract = _freeze(_valid_contract())
    contract_path = _write_contract(tmp_path / "success-criteria-contract.yaml", contract)
    ledger = _valid_ledger(contract)
    ledger["criteria"][0]["evidence_fresh"] = False
    ledger_path = _write_ledger(tmp_path / "success-criteria-ledger.json", ledger)

    with pytest.raises(SuccessCriteriaValidationError, match="evidence is stale"):
        validate_success_criteria_ledger(contract_path=contract_path, ledger_path=ledger_path)


def test_cli_validate_ledger_returns_json_success(tmp_path):
    contract = _freeze(_valid_contract())
    contract_path = _write_contract(tmp_path / "success-criteria-contract.yaml", contract)
    ledger_path = _write_ledger(tmp_path / "success-criteria-ledger.json", _valid_ledger(contract))

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "validate-ledger",
            "--contract",
            str(contract_path),
            "--ledger",
            str(ledger_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["ok"] is True


def test_validate_workflow_define_exit_resolves_john_wick_contract(tmp_path):
    contract = _freeze(_valid_contract())
    contract_path = _write_contract(
        tmp_path / ".sweetclaude" / "contracts" / "success-criteria-contract.yaml",
        contract,
    )
    state_dir = tmp_path / ".sweetclaude" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "john-wick.yaml").write_text(
        yaml.safe_dump(
            {
                "feature_name": "validator",
                "success_criteria_contract": {
                    "path": ".sweetclaude/contracts/success-criteria-contract.yaml",
                    "success_criteria_contract_hash": compute_success_criteria_contract_hash(contract),
                    "criterion_ids": ["SC-001", "SC-002"],
                },
            }
        ),
        encoding="utf-8",
    )

    result = validate_success_criteria_workflow(
        project_dir=tmp_path,
        stage="define-exit",
    )

    assert result["ok"] is True
    assert result["contract_path"] == str(contract_path.resolve(strict=False))
    assert result["criterion_ids"] == ["SC-001", "SC-002"]


def test_validate_workflow_completion_resolves_workflow_state_artifacts(tmp_path):
    contract = _freeze(_valid_contract())
    contract_path = _write_contract(
        tmp_path / ".sweetclaude" / "contracts" / "success-criteria-contract.yaml",
        contract,
    )
    ledger_path = _write_ledger(
        tmp_path / ".sweetclaude" / "reports" / "success-criteria-ledger.json",
        _valid_ledger(contract),
    )
    workflow_dir = tmp_path / ".sweetclaude" / "state" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "STORY-123.yaml").write_text(
        yaml.safe_dump(
            {
                "workflow_id": "STORY-123",
                "success_criteria_contract": {
                    "path": ".sweetclaude/contracts/success-criteria-contract.yaml",
                },
                "success_criteria_ledger": {
                    "path": ".sweetclaude/reports/success-criteria-ledger.json",
                },
            }
        ),
        encoding="utf-8",
    )

    result = validate_success_criteria_workflow(
        project_dir=tmp_path,
        workflow_id="STORY-123",
        stage="completion",
    )

    assert result["ok"] is True
    assert result["workflow_id"] == "STORY-123"
    assert result["contract_path"] == str(contract_path.resolve(strict=False))
    assert result["ledger_path"] == str(ledger_path.resolve(strict=False))
    assert result["all_success_criteria_passed"] is True


def test_validate_workflow_define_exit_missing_contract_blocks(tmp_path):
    result = validate_success_criteria_workflow(
        project_dir=tmp_path,
        workflow_id="STORY-123",
        stage="define-exit",
    )

    assert result["ok"] is False
    assert result["blocking"] is True
    assert result["blocking_failures"]
    assert "Do not leave Define" in result["recovery_hint"]


def test_validate_workflow_completion_missing_ledger_blocks(tmp_path):
    contract = _freeze(_valid_contract())
    _write_contract(
        tmp_path / ".sweetclaude" / "contracts" / "success-criteria-contract.yaml",
        contract,
    )

    result = validate_success_criteria_workflow(
        project_dir=tmp_path,
        workflow_id="STORY-123",
        stage="completion",
    )

    assert result["ok"] is False
    assert result["blocking"] is True
    assert "ledger" in result["error"].lower()
    assert "Do not claim completion" in result["recovery_hint"]


def test_cli_validate_workflow_draft_reports_invalid_without_blocking(tmp_path):
    contract = _freeze(_valid_contract())
    contract["success_criteria"][0]["fail_condition"] = ""
    contract_path = tmp_path / "success-criteria-contract.yaml"
    contract_path.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "validate-workflow",
            "--stage",
            "draft",
            "--contract",
            str(contract_path),
            "--project-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 0
    assert payload["ok"] is False
    assert payload["blocking"] is False
    assert payload["blocking_failures"] == []
    assert "Draft validation failed" in payload["recovery_hint"]


def test_cli_validate_workflow_completion_returns_json_failure(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "validate-workflow",
            "--stage",
            "completion",
            "--workflow-id",
            "STORY-123",
            "--project-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["ok"] is False
    assert payload["workflow_id"] == "STORY-123"
    assert payload["blocking"] is True
    assert payload["blocking_failures"]


def test_validate_contract_reports_all_compound_criteria_at_once(tmp_path):
    contract = _valid_contract()
    contract["success_criteria"][0]["statement"] = "The root page loads."
    contract["success_criteria"][0]["binary_predicate"] = "GET / returns 200 and body has a title"
    contract["success_criteria"][1]["statement"] = "The seed populates rows."
    contract["success_criteria"][1]["binary_predicate"] = "seed runs and rows exist"
    contract["contract_freeze"]["contract_hash"] = compute_success_criteria_contract_hash(contract)
    cp = tmp_path / "c.yaml"
    cp.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")
    with pytest.raises(SuccessCriteriaValidationError) as exc:
        validate_success_criteria_contract(cp)
    msg = str(exc.value)
    assert "SC-001" in msg and "SC-002" in msg


def test_verify_cli_accepts_list_of_criterion_results(tmp_path):
    from large_story_controller import enter_verify_phase
    # reuse the controller test's project builder via a minimal inline setup
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts"))
    from large_story_controller import (
        arm_enforcement_probe, check_enforcement_probe,
        enter_design_phase, enter_plan_phase, enter_implement_phase, init_workflow,
        record_evidence,
    )
    contract = _valid_contract()
    contract["success_criteria"] = [contract["success_criteria"][0]]
    contract["contract_freeze"]["contract_hash"] = compute_success_criteria_contract_hash(contract)
    cp = tmp_path / ".sweetclaude" / "contracts" / "success-criteria-contract.yaml"
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")
    assert init_workflow(project_dir=tmp_path, workflow_id="STORY-123")["ok"]
    enter_design_phase(project_dir=tmp_path, workflow_id="STORY-123", design_summary="d")
    enter_plan_phase(project_dir=tmp_path, workflow_id="STORY-123", plan_summary="p")
    arm_enforcement_probe(project_dir=tmp_path, workflow_id="STORY-123")
    (tmp_path / ".sweetclaude" / ".enforcement-control").write_text("ok\n", encoding="utf-8")
    check_enforcement_probe(project_dir=tmp_path, workflow_id="STORY-123")
    enter_implement_phase(project_dir=tmp_path, workflow_id="STORY-123", implementation_summary="i")
    record_evidence(project_dir=tmp_path, tool="Write", file_path="app.py", workflow_id="STORY-123")
    # CLI with a LIST payload (the recurring stumble) must not crash
    result = subprocess.run(
        [sys.executable, str(SCRIPT.parent / "large_story_controller.py"),
         "--project-dir", str(tmp_path), "verify", "--workflow-id", "STORY-123",
         "--criterion-result-json", json.dumps([{"criterion_id": "SC-001", "status": "pass"}])],
        capture_output=True, text=True, cwd=str(SCRIPT.parent),
    )
    # the recurring defect was a traceback/crash on a list payload; assert it
    # is parsed into structured JSON with no traceback.
    assert result.returncode in (0, 1), result.stderr
    payload = json.loads(result.stdout)
    assert "Traceback" not in result.stderr
    assert isinstance(payload, dict) and "ok" in payload
