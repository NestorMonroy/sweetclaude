"""Small-story terminal gate tests — per-story file protection.

Mirrors the large-story gate tests for the terminal history lockout bug:
completing one story must not prevent starting the next.
"""
import sys
from pathlib import Path

import yaml

SCRIPTS_DIR = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from small_story_controller import (
    enter_design_phase,
    enter_implement_phase,
    enter_plan_phase,
    enter_ship_phase,
    enter_verify_phase,
    gate_tool_use,
    init_workflow,
    record_evidence,
    arm_enforcement_probe,
    check_enforcement_probe,
)
from success_criteria_contracts import compute_success_criteria_contract_hash


def _contract(story_id: str = "STORY-001") -> dict:
    criterion = {
        "id": "SC-001",
        "outcome_id": "OUTCOME-001",
        "statement": "The completion validator returns status success.",
        "binary_predicate": "completion validator returns status success",
        "measurement_type": "schema_check",
        "measurement_procedure": "Run completion validator.",
        "evidence_artifact": f".sweetclaude/reports/small-story/{story_id}/evidence/SC-001.json",
        "evidence_owner": "controller",
        "pass_condition": "validator status equals success",
        "fail_condition": "validator status does not equal success",
        "allowed_phase_to_measure": "implementation",
        "amendment_policy": "human_approved_only",
        "backlog_routing": "Backlog any new concern.",
    }
    contract = {
        "story_id": story_id,
        "story_title": "Small story gate test",
        "story_objective": "Prove tool use is controller gated.",
        "expected_outcomes": [
            {"id": "OUTCOME-001", "statement": "Tool use is evidence-bound."}
        ],
        "non_goals": [
            {"id": "NONGOAL-001", "statement": "Do not test downstream review."}
        ],
        "success_criteria": [criterion],
        "contract_freeze": {
            "frozen_at": "2026-06-06T12:00:00Z",
            "frozen_by": "test",
            "contract_hash": "",
        },
    }
    contract["contract_freeze"]["contract_hash"] = compute_success_criteria_contract_hash(contract)
    return contract


def _write_contract(project: Path, contract: dict) -> Path:
    contract_path = project / ".sweetclaude" / "contracts" / "success-criteria-contract.yaml"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")
    return contract_path


def _create_backlog_file(project: Path, story_id: str) -> None:
    backlog_dir = project / "docs" / "product" / "backlog"
    backlog_dir.mkdir(parents=True, exist_ok=True)
    (backlog_dir / f"{story_id}-test.md").write_text(
        f"---\nid: {story_id}\nstatus: new\n---\nTest backlog item.\n",
        encoding="utf-8",
    )


def _init_project(tmp_path: Path, story_id: str = "STORY-001") -> Path:
    _create_backlog_file(tmp_path, story_id)
    _write_contract(tmp_path, _contract(story_id))
    result = init_workflow(project_dir=tmp_path, workflow_id=story_id)
    assert result["ok"], result
    return tmp_path


def _mark_enforcement_verified(project, story_id="STORY-001"):
    arm_enforcement_probe(project_dir=project, workflow_id=story_id)
    (project / ".sweetclaude" / ".enforcement-control").write_text("ok\n", encoding="utf-8")
    check_enforcement_probe(project_dir=project, workflow_id=story_id)


def _advance_to_implement(project: Path, story_id: str = "STORY-001") -> None:
    assert enter_design_phase(project_dir=project, workflow_id=story_id, design_summary="design")["ok"]
    assert enter_plan_phase(project_dir=project, workflow_id=story_id, plan_summary="plan")["ok"]
    _mark_enforcement_verified(project, story_id)
    assert enter_implement_phase(project_dir=project, workflow_id=story_id, implementation_summary="impl")["ok"]


def _ship_story(project, story_id="STORY-001"):
    _advance_to_implement(project, story_id)
    record_evidence(project_dir=project, tool="Write", file_path="app.py", workflow_id=story_id)
    assert enter_verify_phase(project_dir=project, workflow_id=story_id)["ok"]
    assert enter_ship_phase(project_dir=project, workflow_id=story_id)["ok"]


# --- Terminal gate: completed-story files are protected -----------------------


def test_gate_denies_history_writes_after_terminal_closeout(tmp_path):
    project = _init_project(tmp_path)
    _ship_story(project)
    for path in (
        ".sweetclaude/reports/success-criteria-ledger.json",
        ".sweetclaude/reports/small-story/STORY-001/ship/closeout.json",
        ".sweetclaude/state/workflows/archived/STORY-001.yaml",
    ):
        result = gate_tool_use(project_dir=project, tool="Write", file_path=path)
        assert result["allow"] is False, path
        assert result["decision"] == "deny"


def test_gate_allows_app_and_phase_writes_after_terminal_closeout(tmp_path):
    project = _init_project(tmp_path)
    _ship_story(project)
    assert gate_tool_use(project_dir=project, tool="Write", file_path="app.py")["allow"] is True
    assert gate_tool_use(
        project_dir=project, tool="Edit", file_path=".sweetclaude/state/phase.yaml"
    )["allow"] is True


# --- Terminal gate: new stories are allowed -----------------------------------


def test_gate_allows_contract_reuse_after_terminal_closeout(tmp_path):
    """Contract at the default path is a reusable draft, not permanent evidence."""
    project = _init_project(tmp_path)
    _ship_story(project)
    result = gate_tool_use(
        project_dir=project,
        tool="Write",
        file_path=".sweetclaude/contracts/success-criteria-contract.yaml",
    )
    assert result["allow"] is True


def test_gate_allows_new_story_contract_after_first_completes(tmp_path):
    """Regression: completing one story must not lock out authoring the next."""
    project = _init_project(tmp_path)
    _ship_story(project)
    new_contract = ".sweetclaude/contracts/success-criteria-contract.yaml"
    (project / new_contract).parent.mkdir(parents=True, exist_ok=True)
    (project / new_contract).write_text("story_id: STORY-002\n", encoding="utf-8")
    result = gate_tool_use(project_dir=project, tool="Write", file_path=new_contract)
    assert result["allow"] is True, f"New story contract should be writable: {result['reason']}"
    result = gate_tool_use(project_dir=project, tool="Edit", file_path=new_contract)
    assert result["allow"] is True, f"New story contract should be editable: {result['reason']}"


def test_gate_allows_new_story_reports_after_first_completes(tmp_path):
    """New story reports dir must be writable even with completed stories."""
    project = _init_project(tmp_path)
    _ship_story(project)
    new_report = ".sweetclaude/reports/small-story/STORY-002/design/notes.md"
    result = gate_tool_use(project_dir=project, tool="Write", file_path=new_report)
    assert result["allow"] is True, f"New story report should be writable: {result['reason']}"


def test_gate_allows_new_workflow_yaml_after_first_completes(tmp_path):
    """New workflow state file must be writable after completion."""
    project = _init_project(tmp_path)
    _ship_story(project)
    new_workflow = ".sweetclaude/state/workflows/STORY-002.yaml"
    result = gate_tool_use(project_dir=project, tool="Write", file_path=new_workflow)
    assert result["allow"] is True, f"New workflow YAML should be writable: {result['reason']}"


# --- Terminal gate: Bash commands ---------------------------------------------


def test_gate_allows_readonly_bash_after_terminal_closeout(tmp_path):
    """Read-only commands mentioning protected paths must not be denied."""
    project = _init_project(tmp_path)
    _ship_story(project)
    for cmd in (
        "ls .sweetclaude/reports/small-story/STORY-001/",
        "cat .sweetclaude/state/workflows/STORY-001.yaml",
        "grep -r contract .sweetclaude/contracts/",
    ):
        result = gate_tool_use(project_dir=project, tool="Bash", command=cmd)
        assert result["allow"] is True, f"Read-only Bash should be allowed: {cmd}"


def test_gate_denies_bash_write_to_completed_story_files(tmp_path):
    """Write commands targeting completed-story files must be denied."""
    project = _init_project(tmp_path)
    _ship_story(project)
    result = gate_tool_use(
        project_dir=project,
        tool="Bash",
        command="echo '{}' > .sweetclaude/reports/success-criteria-ledger.json",
    )
    assert result["allow"] is False


def test_gate_denies_bash_history_tampering_after_terminal_closeout(tmp_path):
    project = _init_project(tmp_path)
    _ship_story(project)
    result = gate_tool_use(
        project_dir=project,
        tool="Bash",
        command="echo '{}' > .sweetclaude/reports/success-criteria-ledger.json",
    )
    assert result["allow"] is False
