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
