"""Small-story Stop guard tests, driven as real subprocesses.

Mirrors the large-story stop-guard coverage. The small-story controller is a
parallel copy of the large-story controller with the identical API, and its
Stop guard shares the identical pause-across-turns logic, so the regression
coverage must exist on both.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

HOOK_PATH = f"{os.path.dirname(sys.executable)}:/usr/bin:/bin:/usr/local/bin"

REPO_ROOT = Path(__file__).parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from small_story_controller import (
    enter_design_phase,
    enter_implement_phase,
    enter_plan_phase,
    enter_verify_phase,
    init_workflow,
    record_evidence,
    arm_enforcement_probe,
    check_enforcement_probe,
)
from success_criteria_contracts import compute_success_criteria_contract_hash

STOP_HOOK = REPO_ROOT / "hooks" / "small-story-stop-guard.sh"


def _contract(story_id: str = "STORY-001") -> dict:
    contract = {
        "story_id": story_id,
        "story_title": "Hook enforcement test",
        "story_objective": "Prove hooks enforce the controller gate.",
        "expected_outcomes": [
            {"id": "OUTCOME-001", "statement": "Tool use is harness-gated."}
        ],
        "non_goals": [{"id": "NONGOAL-001", "statement": "No terminal review."}],
        "success_criteria": [
            {
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
        ],
        "contract_freeze": {
            "frozen_at": "2026-06-06T12:00:00Z",
            "frozen_by": "test",
            "contract_hash": "",
        },
    }
    contract["contract_freeze"]["contract_hash"] = compute_success_criteria_contract_hash(contract)
    return contract


def _project_with_workflow(tmp_path: Path, story_id: str = "STORY-001") -> Path:
    contract_path = tmp_path / ".sweetclaude" / "contracts" / "success-criteria-contract.yaml"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(yaml.safe_dump(_contract(story_id), sort_keys=False), encoding="utf-8")
    assert init_workflow(project_dir=tmp_path, workflow_id=story_id)["ok"]
    return tmp_path


def _mark_enforcement_verified(project: Path, story_id: str = "STORY-001") -> None:
    arm_enforcement_probe(project_dir=project, workflow_id=story_id)
    (project / ".sweetclaude" / ".enforcement-control").write_text("ok\n", encoding="utf-8")
    check_enforcement_probe(project_dir=project, workflow_id=story_id)


def _advance_to_implement(project: Path, story_id: str = "STORY-001") -> None:
    assert enter_design_phase(project_dir=project, workflow_id=story_id, design_summary="d")["ok"]
    assert enter_plan_phase(project_dir=project, workflow_id=story_id, plan_summary="p")["ok"]
    _mark_enforcement_verified(project, story_id)
    assert enter_implement_phase(project_dir=project, workflow_id=story_id, implementation_summary="i")["ok"]


def _run_hook(hook: Path, project: Path, payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        env={
            "PATH": HOOK_PATH,
            "CLAUDE_PROJECT_DIR": str(project),
            "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
            "HOME": str(project),
        },
        cwd=str(project),
    )


def _stop_payload(project: Path, stop_hook_active: bool = False) -> dict:
    return {
        "session_id": "test-session",
        "transcript_path": str(project / "transcript.jsonl"),
        "cwd": str(project),
        "permission_mode": "default",
        "hook_event_name": "Stop",
        "stop_hook_active": stop_hook_active,
    }


def test_stop_hook_silent_without_workflow(tmp_path):
    result = _run_hook(STOP_HOOK, tmp_path, _stop_payload(tmp_path))
    assert result.returncode == 0
    assert not result.stdout.strip()


def test_stop_hook_blocks_nonterminal_workflow(tmp_path):
    project = _project_with_workflow(tmp_path)
    _advance_to_implement(project)
    result = _run_hook(STOP_HOOK, project, _stop_payload(project))
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["decision"] == "block"
    assert "STORY-001" in data["reason"]


def test_stop_hook_respects_stop_hook_active(tmp_path):
    project = _project_with_workflow(tmp_path)
    _advance_to_implement(project)
    result = _run_hook(STOP_HOOK, project, _stop_payload(project, stop_hook_active=True))
    assert result.returncode == 0
    assert not result.stdout.strip()


def test_stop_hook_honors_pause_across_turns(tmp_path):
    """Regression: a deliberately paused story must not re-fire the block on
    every subsequent turn."""
    project = _project_with_workflow(tmp_path)
    _advance_to_implement(project)

    first = _run_hook(STOP_HOOK, project, _stop_payload(project, stop_hook_active=False))
    assert json.loads(first.stdout)["decision"] == "block"

    second = _run_hook(STOP_HOOK, project, _stop_payload(project, stop_hook_active=True))
    assert not second.stdout.strip()

    for _ in range(3):
        later = _run_hook(STOP_HOOK, project, _stop_payload(project, stop_hook_active=False))
        assert not later.stdout.strip(), "paused small-story re-fired the stop block on a new turn"


def test_stop_hook_rearms_after_state_change(tmp_path):
    project = _project_with_workflow(tmp_path)
    _advance_to_implement(project)
    _run_hook(STOP_HOOK, project, _stop_payload(project, stop_hook_active=False))
    _run_hook(STOP_HOOK, project, _stop_payload(project, stop_hook_active=True))
    assert not _run_hook(STOP_HOOK, project, _stop_payload(project)).stdout.strip()

    record_evidence(project_dir=project, tool="Write", file_path="app.py", workflow_id="STORY-001")
    assert enter_verify_phase(project_dir=project, workflow_id="STORY-001")["ok"]

    result = _run_hook(STOP_HOOK, project, _stop_payload(project, stop_hook_active=False))
    assert json.loads(result.stdout)["decision"] == "block"


def test_stop_block_message_is_a_summary_not_a_verbatim_dump(tmp_path):
    project = _project_with_workflow(tmp_path)
    _advance_to_implement(project)
    result = _run_hook(STOP_HOOK, project, _stop_payload(project, stop_hook_active=False))
    reason = json.loads(result.stdout)["reason"]
    assert "verbatim" not in reason.lower()
    assert "render-status" not in reason
