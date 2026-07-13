import json
from pathlib import Path

import pytest

from control_receipts import (
    hash_file,
    lint_control_artifacts,
    validate_control_receipt_context,
)
from evidence import validate_receipt, write_receipt


ROOT = Path(__file__).resolve().parents[1]
EFFORT = ROOT / ".sweetclaude" / "efforts" / "ms-007-failure-mode-controls"
CONTROLS_MAP = EFFORT / "02-design" / "controls-map.md"

# Data precondition (ISSUE-236, same pattern as test_dashboard_ui): the t024
# lint tests read live effort artifacts under gitignored .sweetclaude/ —
# absent in CI checkouts. Skip those tests visibly there; they run locally.
requires_effort_artifacts = pytest.mark.skipif(
    not CONTROLS_MAP.is_file(),
    reason="requires live effort artifacts "
           "(.sweetclaude is gitignored and absent in CI checkouts)",
)
TEST_STRATEGY = EFFORT / "04-test-strategy" / "beta-4x-control-test-strategy.md"
IMPLEMENTATION_PLAN = (
    EFFORT / "03-implementation-plan" / "beta-4x-control-implementation-plan.md"
)


def _write_receipt(path: Path, **overrides):
    data = {
        "schema_version": 2,
        "receipt_type": "evidence",
        "receipt_id": "receipt-1",
        "generated_at": "2026-05-26T12:00:00Z",
        "command_or_workflow_step": "test",
        "cwd": str(path.parent),
        "repo_root": str(path.parent),
        "branch": "beta-4.x",
        "commit": "abc123",
        "install_path": None,
        "manifest_id": "ms-007",
        "result": "pass",
        "input_artifacts": [],
    }
    data.update(overrides)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


@requires_effort_artifacts
def test_t024_active_control_artifacts_do_not_use_undefined_controls_or_ranges():
    lint_control_artifacts(
        controls_map_path=CONTROLS_MAP,
        artifact_paths=[TEST_STRATEGY, IMPLEMENTATION_PLAN],
    )


@requires_effort_artifacts
def test_t024_rejects_undefined_control_reference(tmp_path):
    artifact = tmp_path / "artifact.md"
    artifact.write_text("Controls: CTL-999\n", encoding="utf-8")

    with pytest.raises(ValueError, match="undefined control.*CTL-999"):
        lint_control_artifacts(
            controls_map_path=CONTROLS_MAP,
            artifact_paths=[artifact],
        )


@requires_effort_artifacts
def test_t024_rejects_implementation_significant_ranges(tmp_path):
    artifact = tmp_path / "artifact.md"
    bad_range = "T-001 " + "thr" + "ough T-002"
    artifact.write_text(f"Fixtures: {bad_range}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="numeric range"):
        lint_control_artifacts(
            controls_map_path=CONTROLS_MAP,
            artifact_paths=[artifact],
        )


def test_t001_rejects_stale_commit_bound_receipt(tmp_path):
    receipt = _write_receipt(tmp_path / "receipt.json", commit="old")

    with pytest.raises(ValueError, match="commit mismatch"):
        validate_control_receipt_context(receipt, expected_context={"commit": "new"})


def test_t001_rejects_stale_input_artifact_hash(tmp_path):
    artifact = tmp_path / "input.txt"
    artifact.write_text("before\n", encoding="utf-8")
    receipt = _write_receipt(
        tmp_path / "receipt.json",
        repo_root=str(tmp_path),
        input_artifacts=[{"path": "input.txt", "sha256": hash_file(artifact)}],
    )
    artifact.write_text("after\n", encoding="utf-8")

    with pytest.raises(ValueError, match="file hash mismatch"):
        validate_control_receipt_context(receipt, verify_artifact_hashes=True)


def test_t002_rejects_context_mismatch_when_fields_are_present(tmp_path):
    receipt = _write_receipt(
        tmp_path / "receipt.json",
        cwd=str(tmp_path / "checkout-a"),
        repo_root=str(tmp_path / "repo-a"),
        branch="beta-4.x",
        commit="abc123",
        install_path=str(tmp_path / "installed-a"),
        manifest_id="manifest-a",
    )

    with pytest.raises(ValueError, match="install_path mismatch"):
        validate_control_receipt_context(
            receipt,
            expected_context={
                "cwd": str(tmp_path / "checkout-a"),
                "repo_root": str(tmp_path / "repo-a"),
                "branch": "beta-4.x",
                "commit": "abc123",
                "install_path": str(tmp_path / "installed-b"),
                "manifest_id": "manifest-a",
            },
        )


def test_existing_v1_evidence_receipts_remain_valid(tmp_path):
    receipt = write_receipt(
        tmp_path,
        subject_id="ISSUE-123",
        receipt_type="completion",
        check_name="tests",
        status="pass",
        command="pytest -q",
    )

    parsed = validate_receipt(
        receipt,
        subject_id="ISSUE-123",
        receipt_type="completion",
    )

    assert parsed["schema_version"] == 1
