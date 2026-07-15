"""Regression tests for ISSUE-047 / ISSUE-206 orphaned state bugs.

ISSUE-047 original three failures:
1. init_workflow accepted workflow IDs with no backlog file
2. init_contract accepted story IDs with no backlog file (phantom scaffolding)
3. enter_ship_phase left phase.yaml pointing at the completed workflow

ISSUE-206 additional gaps:
4. sweetclaude.yaml work.active never managed by controllers
5. find_backlog_file searches done/ — completed items pass validation
6. arm/check_enforcement_probe create phantom workflow state files
7. record_evidence writes without validating workflow file exists
"""
import sys
from pathlib import Path

import yaml

SCRIPTS_DIR = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from large_story_controller import (
    enter_design_phase,
    enter_implement_phase,
    enter_plan_phase,
    enter_ship_phase,
    enter_verify_phase,
    init_workflow as large_init_workflow,
    record_evidence as large_record_evidence,
    arm_enforcement_probe as large_arm_enforcement_probe,
    check_enforcement_probe as large_check_enforcement_probe,
)
from small_story_controller import (
    enter_design_phase as small_enter_design_phase,
    enter_implement_phase as small_enter_implement_phase,
    enter_plan_phase as small_enter_plan_phase,
    enter_ship_phase as small_enter_ship_phase,
    enter_verify_phase as small_enter_verify_phase,
    init_workflow as small_init_workflow,
    record_evidence as small_record_evidence,
    arm_enforcement_probe as small_arm_enforcement_probe,
    check_enforcement_probe as small_check_enforcement_probe,
)
from success_criteria_contracts import (
    compute_success_criteria_contract_hash,
    find_backlog_file,
    init_contract,
)


def _contract(story_id: str, controller: str = "large") -> dict:
    criterion = {
        "id": "SC-001",
        "outcome_id": "OUTCOME-001",
        "statement": "The completion validator returns status success.",
        "binary_predicate": "completion validator returns status success",
        "measurement_type": "schema_check",
        "measurement_procedure": "Run completion validator.",
        "evidence_artifact": f".sweetclaude/reports/{controller}-story/{story_id}/evidence/SC-001.json",
        "evidence_owner": "controller",
        "pass_condition": "validator status equals success",
        "fail_condition": "validator status does not equal success",
        "allowed_phase_to_measure": "implementation",
        "amendment_policy": "human_approved_only",
        "backlog_routing": "Backlog any new concern.",
    }
    contract = {
        "story_id": story_id,
        "story_title": "Regression test story",
        "story_objective": "Prove the orphaned state bug is fixed.",
        "expected_outcomes": [
            {"id": "OUTCOME-001", "statement": "No orphaned state after SHIP."}
        ],
        "non_goals": [
            {"id": "NONGOAL-001", "statement": "Do not test downstream review."}
        ],
        "success_criteria": [criterion],
        "contract_freeze": {
            "frozen_at": "2026-06-21T12:00:00Z",
            "frozen_by": "test",
            "contract_hash": "",
        },
    }
    contract["contract_freeze"]["contract_hash"] = compute_success_criteria_contract_hash(contract)
    return contract


def _create_backlog_file(project: Path, story_id: str) -> None:
    backlog_dir = project / "docs" / "product" / "backlog"
    backlog_dir.mkdir(parents=True, exist_ok=True)
    (backlog_dir / f"{story_id}-test.md").write_text(
        f"---\nid: {story_id}\nstatus: new\n---\nTest backlog item.\n",
        encoding="utf-8",
    )


def _write_contract(project: Path, contract: dict) -> None:
    contract_path = project / ".sweetclaude" / "contracts" / "success-criteria-contract.yaml"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _mark_enforcement_verified(project: Path, story_id: str, controller: str = "large") -> None:
    if controller == "large":
        large_arm_enforcement_probe(project_dir=project, workflow_id=story_id)
        (project / ".sweetclaude" / ".enforcement-control").write_text("ok\n", encoding="utf-8")
        large_check_enforcement_probe(project_dir=project, workflow_id=story_id)
    else:
        small_arm_enforcement_probe(project_dir=project, workflow_id=story_id)
        (project / ".sweetclaude" / ".enforcement-control").write_text("ok\n", encoding="utf-8")
        small_check_enforcement_probe(project_dir=project, workflow_id=story_id)


# ---------------------------------------------------------------------------
# Failure 1: init_workflow must require a backlog file
# ---------------------------------------------------------------------------


def test_large_init_workflow_blocked_without_backlog_file(tmp_path):
    _write_contract(tmp_path, _contract("ISSUE-047"))
    result = large_init_workflow(project_dir=tmp_path, workflow_id="ISSUE-047")
    assert result["ok"] is False
    assert "no backlog file" in result["message"].lower()


def test_small_init_workflow_blocked_without_backlog_file(tmp_path):
    _write_contract(tmp_path, _contract("ISSUE-047", "small"))
    result = small_init_workflow(project_dir=tmp_path, workflow_id="ISSUE-047")
    assert result["ok"] is False
    assert "no backlog file" in result["message"].lower()


def test_large_init_workflow_succeeds_with_backlog_file(tmp_path):
    _create_backlog_file(tmp_path, "ISSUE-047")
    _write_contract(tmp_path, _contract("ISSUE-047"))
    result = large_init_workflow(project_dir=tmp_path, workflow_id="ISSUE-047")
    assert result["ok"] is True


def test_small_init_workflow_succeeds_with_backlog_file(tmp_path):
    _create_backlog_file(tmp_path, "ISSUE-047")
    _write_contract(tmp_path, _contract("ISSUE-047", "small"))
    result = small_init_workflow(project_dir=tmp_path, workflow_id="ISSUE-047")
    assert result["ok"] is True


# ---------------------------------------------------------------------------
# Failure 2: init_contract must require a backlog file
# ---------------------------------------------------------------------------


def test_init_contract_blocked_without_backlog_file(tmp_path):
    result = init_contract(project_dir=tmp_path, story_id="ISSUE-048")
    assert result["ok"] is False
    assert "no backlog file" in result["error"].lower()


def test_init_contract_succeeds_with_backlog_file(tmp_path):
    _create_backlog_file(tmp_path, "ISSUE-048")
    result = init_contract(project_dir=tmp_path, story_id="ISSUE-048")
    assert result["ok"] is True


def test_init_contract_blocked_prevents_phantom_successor(tmp_path):
    """After a workflow completes, init_contract must still require a backlog
    file. This is the exact scenario from ISSUE-047: Claude autonomously
    scaffolded ISSUE-048 after ISSUE-047 completed."""
    _create_backlog_file(tmp_path, "ISSUE-047")
    _write_contract(tmp_path, _contract("ISSUE-047"))
    large_init_workflow(project_dir=tmp_path, workflow_id="ISSUE-047")

    wf_path = tmp_path / ".sweetclaude" / "state" / "workflows" / "ISSUE-047.yaml"
    state = _load_yaml(wf_path)
    state["status"] = "complete"
    wf_path.write_text(yaml.safe_dump(state, sort_keys=False), encoding="utf-8")

    result = init_contract(
        project_dir=tmp_path, story_id="ISSUE-048", force=True,
    )
    assert result["ok"] is False
    assert "no backlog file" in result["error"].lower()


# ---------------------------------------------------------------------------
# Failure 3: enter_ship_phase must clear phase.yaml active_work_item
# ---------------------------------------------------------------------------


def _run_full_lifecycle(
    tmp_path: Path, story_id: str, controller: str = "large",
) -> Path:
    _create_backlog_file(tmp_path, story_id)
    _write_contract(tmp_path, _contract(story_id, controller))
    if controller == "large":
        assert large_init_workflow(project_dir=tmp_path, workflow_id=story_id)["ok"]
        assert enter_design_phase(project_dir=tmp_path, workflow_id=story_id, design_summary="d")["ok"]
        assert enter_plan_phase(project_dir=tmp_path, workflow_id=story_id, plan_summary="p")["ok"]
        _mark_enforcement_verified(tmp_path, story_id, "large")
        assert enter_implement_phase(project_dir=tmp_path, workflow_id=story_id, implementation_summary="i")["ok"]
        large_record_evidence(project_dir=tmp_path, tool="Write", file_path="app.py", workflow_id=story_id)
        assert enter_verify_phase(project_dir=tmp_path, workflow_id=story_id)["ok"]
        result = enter_ship_phase(project_dir=tmp_path, workflow_id=story_id)
        assert result["ok"], result
    else:
        assert small_init_workflow(project_dir=tmp_path, workflow_id=story_id)["ok"]
        assert small_enter_design_phase(project_dir=tmp_path, workflow_id=story_id, design_summary="d")["ok"]
        assert small_enter_plan_phase(project_dir=tmp_path, workflow_id=story_id, plan_summary="p")["ok"]
        _mark_enforcement_verified(tmp_path, story_id, "small")
        assert small_enter_implement_phase(project_dir=tmp_path, workflow_id=story_id, implementation_summary="i")["ok"]
        small_record_evidence(project_dir=tmp_path, tool="Write", file_path="app.py", workflow_id=story_id)
        assert small_enter_verify_phase(project_dir=tmp_path, workflow_id=story_id)["ok"]
        result = small_enter_ship_phase(project_dir=tmp_path, workflow_id=story_id)
        assert result["ok"], result
    return tmp_path


def test_large_ship_clears_phase_yaml(tmp_path):
    _run_full_lifecycle(tmp_path, "ISSUE-047", "large")
    phase_data = _load_yaml(tmp_path / ".sweetclaude" / "state" / "phase.yaml")
    assert phase_data.get("active_work_item") is None, (
        "phase.yaml active_work_item must be cleared after SHIP"
    )


def test_small_ship_clears_phase_yaml(tmp_path):
    _run_full_lifecycle(tmp_path, "ISSUE-047", "small")
    phase_data = _load_yaml(tmp_path / ".sweetclaude" / "state" / "phase.yaml")
    assert phase_data.get("active_work_item") is None, (
        "phase.yaml active_work_item must be cleared after SHIP"
    )


def test_phase_yaml_not_stuck_after_large_story_completion(tmp_path):
    """The exact ISSUE-047 scenario: after SHIP, phase.yaml must not point
    at the completed story's workflow ID."""
    _run_full_lifecycle(tmp_path, "ISSUE-047", "large")
    phase_data = _load_yaml(tmp_path / ".sweetclaude" / "state" / "phase.yaml")
    active = phase_data.get("active_work_item")
    if active is not None:
        assert active.get("id") != "ISSUE-047", (
            "phase.yaml still points at completed story ISSUE-047"
        )


# ---------------------------------------------------------------------------
# find_backlog_file: search behavior
# ---------------------------------------------------------------------------


def test_find_backlog_file_finds_in_docs_product_backlog(tmp_path):
    _create_backlog_file(tmp_path, "ISSUE-099")
    result = find_backlog_file(tmp_path, "ISSUE-099")
    assert result is not None
    assert result.name == "ISSUE-099-test.md"


def test_find_backlog_file_finds_in_done(tmp_path):
    done_dir = tmp_path / "docs" / "product" / "done"
    done_dir.mkdir(parents=True, exist_ok=True)
    (done_dir / "ISSUE-099-completed.md").write_text(
        "---\nid: ISSUE-099\nstatus: done\n---\nDone.\n", encoding="utf-8",
    )
    result = find_backlog_file(tmp_path, "ISSUE-099")
    assert result is not None


def test_find_backlog_file_finds_via_artifact_privacy(tmp_path):
    custom_base = tmp_path / "custom" / "product"
    backlog_dir = custom_base / "backlog"
    backlog_dir.mkdir(parents=True, exist_ok=True)
    (backlog_dir / "ISSUE-099-custom.md").write_text(
        "---\nid: ISSUE-099\nstatus: new\n---\n", encoding="utf-8",
    )
    privacy_path = tmp_path / ".sweetclaude" / "artifact-privacy.yaml"
    privacy_path.parent.mkdir(parents=True, exist_ok=True)
    privacy_path.write_text(
        yaml.safe_dump({
            "categories": {"product": {"base_path": "custom/product"}},
        }),
        encoding="utf-8",
    )
    result = find_backlog_file(tmp_path, "ISSUE-099")
    assert result is not None
    assert "custom" in str(result)


def test_find_backlog_file_returns_none_for_nonexistent(tmp_path):
    result = find_backlog_file(tmp_path, "ISSUE-999")
    assert result is None


# ---------------------------------------------------------------------------
# ISSUE-206 SC-001: enter_ship_phase clears sweetclaude.yaml work.active
# ---------------------------------------------------------------------------


def _setup_sweetclaude_yaml(project, workflow_id, phase="DEFINE"):
    sc_path = project / ".sweetclaude" / "state" / "sweetclaude.yaml"
    sc_path.parent.mkdir(parents=True, exist_ok=True)
    sc_path.write_text(
        yaml.safe_dump({
            "schema_version": 2,
            "framework": {"setup_complete": True},
            "work": {"active": {"id": workflow_id, "phase": phase}},
        }),
        encoding="utf-8",
    )


def test_large_ship_clears_sweetclaude_yaml(tmp_path):
    _setup_sweetclaude_yaml(tmp_path, "ISSUE-047", "DEFINE")
    _run_full_lifecycle(tmp_path, "ISSUE-047", "large")
    sc_data = _load_yaml(tmp_path / ".sweetclaude" / "state" / "sweetclaude.yaml")
    active = (sc_data.get("work") or {}).get("active")
    assert active is None, (
        "sweetclaude.yaml work.active must be cleared after SHIP"
    )


def test_small_ship_clears_sweetclaude_yaml(tmp_path):
    _setup_sweetclaude_yaml(tmp_path, "ISSUE-047", "DEFINE")
    _run_full_lifecycle(tmp_path, "ISSUE-047", "small")
    sc_data = _load_yaml(tmp_path / ".sweetclaude" / "state" / "sweetclaude.yaml")
    active = (sc_data.get("work") or {}).get("active")
    assert active is None, (
        "sweetclaude.yaml work.active must be cleared after SHIP"
    )


# ---------------------------------------------------------------------------
# ISSUE-206 SC-002: find_backlog_file exclude_done
# ---------------------------------------------------------------------------


def test_find_backlog_file_excludes_done_when_requested(tmp_path):
    done_dir = tmp_path / "docs" / "product" / "done"
    done_dir.mkdir(parents=True, exist_ok=True)
    (done_dir / "ISSUE-099-completed.md").write_text(
        "---\nid: ISSUE-099\nstatus: done\n---\nDone.\n", encoding="utf-8",
    )
    result = find_backlog_file(tmp_path, "ISSUE-099", exclude_done=True)
    assert result is None, (
        "find_backlog_file with exclude_done=True must not find items in done/"
    )


def test_find_backlog_file_still_finds_done_by_default(tmp_path):
    done_dir = tmp_path / "docs" / "product" / "done"
    done_dir.mkdir(parents=True, exist_ok=True)
    (done_dir / "ISSUE-099-completed.md").write_text(
        "---\nid: ISSUE-099\nstatus: done\n---\nDone.\n", encoding="utf-8",
    )
    result = find_backlog_file(tmp_path, "ISSUE-099", exclude_done=False)
    assert result is not None


def test_large_init_workflow_blocked_for_done_item(tmp_path):
    done_dir = tmp_path / "docs" / "product" / "done"
    done_dir.mkdir(parents=True, exist_ok=True)
    (done_dir / "ISSUE-099-completed.md").write_text(
        "---\nid: ISSUE-099\nstatus: done\n---\nDone.\n", encoding="utf-8",
    )
    _write_contract(tmp_path, _contract("ISSUE-099"))
    result = large_init_workflow(project_dir=tmp_path, workflow_id="ISSUE-099")
    assert result["ok"] is False
    assert "no backlog file" in result["message"].lower()


def test_init_contract_blocked_for_done_item(tmp_path):
    done_dir = tmp_path / "docs" / "product" / "done"
    done_dir.mkdir(parents=True, exist_ok=True)
    (done_dir / "ISSUE-099-completed.md").write_text(
        "---\nid: ISSUE-099\nstatus: done\n---\nDone.\n", encoding="utf-8",
    )
    result = init_contract(project_dir=tmp_path, story_id="ISSUE-099")
    assert result["ok"] is False
    assert "no backlog file" in result["error"].lower()


# ---------------------------------------------------------------------------
# ISSUE-206 SC-003: enforcement probes require workflow state file
# ---------------------------------------------------------------------------


def test_large_arm_enforcement_probe_requires_workflow_file(tmp_path):
    result = large_arm_enforcement_probe(
        project_dir=tmp_path, workflow_id="PHANTOM-001",
    )
    assert result["ok"] is False
    assert "no workflow state file" in result["message"].lower()
    wf_path = tmp_path / ".sweetclaude" / "state" / "workflows" / "PHANTOM-001.yaml"
    assert not wf_path.exists(), "Must not create phantom workflow state file"


def test_large_check_enforcement_probe_requires_workflow_file(tmp_path):
    result = large_check_enforcement_probe(
        project_dir=tmp_path, workflow_id="PHANTOM-001",
    )
    assert result["ok"] is False
    assert "no workflow state file" in result["message"].lower()
    wf_path = tmp_path / ".sweetclaude" / "state" / "workflows" / "PHANTOM-001.yaml"
    assert not wf_path.exists(), "Must not create phantom workflow state file"


def test_small_arm_enforcement_probe_requires_workflow_file(tmp_path):
    result = small_arm_enforcement_probe(
        project_dir=tmp_path, workflow_id="PHANTOM-001",
    )
    assert result["ok"] is False
    assert "no workflow state file" in result["message"].lower()


def test_small_check_enforcement_probe_requires_workflow_file(tmp_path):
    result = small_check_enforcement_probe(
        project_dir=tmp_path, workflow_id="PHANTOM-001",
    )
    assert result["ok"] is False
    assert "no workflow state file" in result["message"].lower()


# ---------------------------------------------------------------------------
# ISSUE-206 SC-004: record_evidence requires workflow state file
# ---------------------------------------------------------------------------


def test_large_record_evidence_requires_workflow_file(tmp_path):
    result = large_record_evidence(
        project_dir=tmp_path, tool="Write", file_path="app.py",
        workflow_id="PHANTOM-001",
    )
    assert result["ok"] is False
    assert "no workflow state file" in result["message"].lower()


def test_small_record_evidence_requires_workflow_file(tmp_path):
    result = small_record_evidence(
        project_dir=tmp_path, tool="Write", file_path="app.py",
        workflow_id="PHANTOM-001",
    )
    assert result["ok"] is False
    assert "no workflow state file" in result["message"].lower()


# ---------------------------------------------------------------------------
# ISSUE-206 SC-005: init_workflow sets sweetclaude.yaml work.active
# ---------------------------------------------------------------------------


def test_large_init_sets_sweetclaude_yaml(tmp_path):
    _create_backlog_file(tmp_path, "ISSUE-047")
    _write_contract(tmp_path, _contract("ISSUE-047"))
    result = large_init_workflow(project_dir=tmp_path, workflow_id="ISSUE-047")
    assert result["ok"] is True
    sc_data = _load_yaml(tmp_path / ".sweetclaude" / "state" / "sweetclaude.yaml")
    active = (sc_data.get("work") or {}).get("active")
    assert isinstance(active, dict), "sweetclaude.yaml work.active must be set after init"
    assert active.get("id") == "ISSUE-047"
    assert active.get("phase") == "DEFINE"


def test_small_init_sets_sweetclaude_yaml(tmp_path):
    _create_backlog_file(tmp_path, "ISSUE-047")
    _write_contract(tmp_path, _contract("ISSUE-047", "small"))
    result = small_init_workflow(project_dir=tmp_path, workflow_id="ISSUE-047")
    assert result["ok"] is True
    sc_data = _load_yaml(tmp_path / ".sweetclaude" / "state" / "sweetclaude.yaml")
    active = (sc_data.get("work") or {}).get("active")
    assert isinstance(active, dict), "sweetclaude.yaml work.active must be set after init"
    assert active.get("id") == "ISSUE-047"
    assert active.get("phase") == "DEFINE"
