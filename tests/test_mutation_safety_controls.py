from pathlib import Path

import pytest

from mutation_safety import (
    hash_payload,
    should_stop_repair_loop,
    validate_approval_scope,
    validate_postconditions,
    validate_restore_proof,
    validate_snapshot_scope,
    validate_write_set,
)


def test_t003_rejects_mutation_outside_approved_write_set(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    approved = ["A.md", "B.yaml"]
    actual = ["A.md", "B.yaml", "hooks/pre-commit"]

    with pytest.raises(ValueError, match="outside approved write set.*hooks/pre-commit"):
        validate_write_set(project, approved_write_set=approved, actual_changed_paths=actual)


def test_t003_accepts_actual_diff_inside_approved_write_set(tmp_path):
    project = tmp_path / "project"
    project.mkdir()

    result = validate_write_set(
        project,
        approved_write_set=["A.md", "B.yaml"],
        actual_changed_paths=["A.md"],
    )

    assert result["status"] == "pass"
    assert result["unexpected_paths"] == []


def test_t004_rejects_approval_laundering_after_plan_change():
    approval = {
        "plan_hash": hash_payload({"plan": "P1"}),
        "write_set_hash": hash_payload(["A.md"]),
        "snapshot_hash": "snapshot-1",
        "context": {"repo_root": "/repo", "branch": "beta-4.x", "commit": "abc123"},
    }

    with pytest.raises(ValueError, match="plan_hash mismatch"):
        validate_approval_scope(
            approval,
            plan_hash=hash_payload({"plan": "P2"}),
            write_set_hash=hash_payload(["A.md"]),
            snapshot_hash="snapshot-1",
            context={"repo_root": "/repo", "branch": "beta-4.x", "commit": "abc123"},
        )


def test_t004_accepts_current_bound_approval():
    approval = {
        "plan_hash": "plan-1",
        "write_set_hash": "write-set-1",
        "snapshot_hash": "snapshot-1",
        "context": {"repo_root": "/repo", "branch": "beta-4.x", "commit": "abc123"},
    }

    result = validate_approval_scope(
        approval,
        plan_hash="plan-1",
        write_set_hash="write-set-1",
        snapshot_hash="snapshot-1",
        context={"repo_root": "/repo", "branch": "beta-4.x", "commit": "abc123"},
    )

    assert result["status"] == "pass"


def test_t005_rejects_snapshot_that_omits_declared_blast_radius():
    with pytest.raises(ValueError, match="snapshot scope missing.*\\.sweetclaude/state"):
        validate_snapshot_scope(
            declared_blast_radius=["docs/product", ".sweetclaude/state"],
            snapshot_paths=["docs/product/backlog/ISSUE-001.md"],
        )


def test_t005_accepts_snapshot_covering_declared_blast_radius():
    result = validate_snapshot_scope(
        declared_blast_radius=["docs/product", ".sweetclaude/state"],
        snapshot_paths=[
            "docs/product/backlog/ISSUE-001.md",
            ".sweetclaude/state/sweetclaude.yaml",
        ],
    )

    assert result["status"] == "pass"
    assert result["missing_scopes"] == []


def test_t006_rejects_performative_restore_proof():
    with pytest.raises(ValueError, match="restore proof requires executable evidence"):
        validate_restore_proof({
            "snapshot_path": "/tmp/snapshot.tar.gz",
            "snapshot_exists": True,
            "rollback_support": {"supported": True},
        })


def test_t006_accepts_validated_restore_command():
    result = validate_restore_proof({
        "method": "dry_run",
        "status": "pass",
        "command": "python3 scripts/migrations/run_rollback.py --dry-run",
        "evidence": "dry-run completed",
    })

    assert result["status"] == "pass"


def test_t007_rejects_successful_exit_without_postconditions():
    with pytest.raises(ValueError, match="postcondition.*migration-map.*failed"):
        validate_postconditions(
            exit_code=0,
            postconditions=[
                {"id": "migration-map", "status": "fail"},
            ],
        )


def test_t007_accepts_successful_exit_with_passing_postconditions():
    result = validate_postconditions(
        exit_code=0,
        postconditions=[
            {"id": "migration-map", "status": "pass"},
            {"id": "issue-files", "status": "passed"},
        ],
    )

    assert result["status"] == "pass"


def test_t008_stops_repair_loop_when_budget_is_exhausted():
    result = should_stop_repair_loop(
        attempts=3,
        max_attempts=3,
        previous_postcondition_hash="same",
        current_postcondition_hash="same",
        new_regressions=[],
    )

    assert result["stop"] is True
    assert result["reason"] == "attempt-budget-exhausted"
    assert result["route"] == "backlog-or-escalation"


def test_t008_stops_repair_loop_on_new_regressions_before_budget():
    result = should_stop_repair_loop(
        attempts=1,
        max_attempts=3,
        previous_postcondition_hash="before",
        current_postcondition_hash="after",
        new_regressions=["release-gate-broke"],
    )

    assert result["stop"] is True
    assert result["reason"] == "new-regressions"


def test_t008_allows_repair_loop_when_progress_remains():
    result = should_stop_repair_loop(
        attempts=1,
        max_attempts=3,
        previous_postcondition_hash="before",
        current_postcondition_hash="after",
        new_regressions=[],
    )

    assert result["stop"] is False
