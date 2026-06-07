"""TASK-C2/C3/C4 tests: large-story enforcement hooks driven as real subprocesses.

Each test feeds the hook script genuine Claude Code hook stdin JSON and asserts
on the verified protocol from
.sweetclaude/efforts/large-story-implementation/process-control-redesign/13-hook-protocol-reference.md:
- PreToolUse deny = exit 0 + hookSpecificOutput.permissionDecision "deny"
- Stop block = exit 0 + top-level {"decision": "block"}
- PostToolUse evidence hook never blocks
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

from large_story_controller import (
    enter_design_phase,
    enter_implement_phase,
    enter_plan_phase,
    enter_ship_phase,
    enter_verify_phase,
    init_workflow,
    record_evidence,
)
from success_criteria_contracts import compute_success_criteria_contract_hash

GATE_HOOK = REPO_ROOT / "hooks" / "large-story-gate.sh"
EVIDENCE_HOOK = REPO_ROOT / "hooks" / "large-story-evidence.sh"
STOP_HOOK = REPO_ROOT / "hooks" / "large-story-stop-guard.sh"


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
                "evidence_artifact": f".sweetclaude/reports/large-story/{story_id}/evidence/SC-001.json",
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


def _advance_to_implement(project: Path, story_id: str = "STORY-001") -> None:
    assert enter_design_phase(project_dir=project, workflow_id=story_id, design_summary="d")["ok"]
    assert enter_plan_phase(project_dir=project, workflow_id=story_id, plan_summary="p")["ok"]
    assert enter_implement_phase(project_dir=project, workflow_id=story_id, implementation_summary="i")["ok"]


def _ship(project: Path, story_id: str = "STORY-001") -> None:
    record_evidence(project_dir=project, tool="Write", file_path="app.py", workflow_id=story_id)
    assert enter_verify_phase(project_dir=project, workflow_id=story_id)["ok"]
    assert enter_ship_phase(project_dir=project, workflow_id=story_id)["ok"]


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


def _pretool_payload(project: Path, tool: str, **tool_input) -> dict:
    return {
        "session_id": "test-session",
        "transcript_path": str(project / "transcript.jsonl"),
        "cwd": str(project),
        "permission_mode": "default",
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": tool_input,
    }


def _posttool_payload(project: Path, tool: str, **tool_input) -> dict:
    payload = _pretool_payload(project, tool, **tool_input)
    payload["hook_event_name"] = "PostToolUse"
    payload["tool_response"] = {"success": True}
    return payload


def _stop_payload(project: Path, stop_hook_active: bool = False) -> dict:
    return {
        "session_id": "test-session",
        "transcript_path": str(project / "transcript.jsonl"),
        "cwd": str(project),
        "permission_mode": "default",
        "hook_event_name": "Stop",
        "stop_hook_active": stop_hook_active,
    }


def _deny_decision(result: subprocess.CompletedProcess) -> dict | None:
    if not result.stdout.strip():
        return None
    data = json.loads(result.stdout)
    return data.get("hookSpecificOutput")


# --- TASK-C2: PreToolUse gate hook --------------------------------------------


def test_gate_hook_silent_without_workflow(tmp_path):
    result = _run_hook(GATE_HOOK, tmp_path, _pretool_payload(tmp_path, "Write", file_path="app.py", content="x"))
    assert result.returncode == 0
    assert _deny_decision(result) is None


def test_gate_hook_denies_app_write_in_define(tmp_path):
    project = _project_with_workflow(tmp_path)
    result = _run_hook(GATE_HOOK, project, _pretool_payload(project, "Write", file_path="app.py", content="x"))
    assert result.returncode == 0
    decision = _deny_decision(result)
    assert decision is not None
    assert decision["hookEventName"] == "PreToolUse"
    assert decision["permissionDecision"] == "deny"
    assert "IMPLEMENT" in decision["permissionDecisionReason"]


def test_gate_hook_allows_app_write_in_implement(tmp_path):
    project = _project_with_workflow(tmp_path)
    _advance_to_implement(project)
    result = _run_hook(GATE_HOOK, project, _pretool_payload(project, "Write", file_path="app.py", content="x"))
    assert result.returncode == 0
    assert _deny_decision(result) is None


def test_gate_hook_denies_state_write_in_implement(tmp_path):
    project = _project_with_workflow(tmp_path)
    _advance_to_implement(project)
    result = _run_hook(
        GATE_HOOK,
        project,
        _pretool_payload(
            project, "Edit",
            file_path=str(project / ".sweetclaude" / "state" / "workflows" / "STORY-001.yaml"),
            old_string="a", new_string="b",
        ),
    )
    decision = _deny_decision(result)
    assert decision is not None
    assert decision["permissionDecision"] == "deny"


def test_gate_hook_denies_bash_ledger_tampering(tmp_path):
    project = _project_with_workflow(tmp_path)
    _advance_to_implement(project)
    result = _run_hook(
        GATE_HOOK,
        project,
        _pretool_payload(
            project, "Bash",
            command="echo '{}' > .sweetclaude/reports/success-criteria-ledger.json",
        ),
    )
    decision = _deny_decision(result)
    assert decision is not None
    assert decision["permissionDecision"] == "deny"


def test_gate_hook_allows_benign_bash(tmp_path):
    project = _project_with_workflow(tmp_path)
    _advance_to_implement(project)
    result = _run_hook(GATE_HOOK, project, _pretool_payload(project, "Bash", command="python3 app.py"))
    assert result.returncode == 0
    assert _deny_decision(result) is None


def test_gate_hook_fails_closed_on_malformed_input_with_workflow(tmp_path):
    project = _project_with_workflow(tmp_path)
    result = subprocess.run(
        ["bash", str(GATE_HOOK)],
        input="this is not json",
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
    decision = _deny_decision(result)
    assert decision is not None
    assert decision["permissionDecision"] == "deny"


def test_gate_hook_fails_open_on_malformed_input_without_workflow(tmp_path):
    result = subprocess.run(
        ["bash", str(GATE_HOOK)],
        input="this is not json",
        capture_output=True,
        text=True,
        timeout=30,
        env={
            "PATH": HOOK_PATH,
            "CLAUDE_PROJECT_DIR": str(tmp_path),
            "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
            "HOME": str(tmp_path),
        },
        cwd=str(tmp_path),
    )
    assert result.returncode == 0
    assert not result.stdout.strip()


# --- TASK-C3: PostToolUse evidence hook ----------------------------------------


def _evidence_entries(project: Path, story_id: str = "STORY-001") -> list[dict]:
    log = (
        project / ".sweetclaude" / "reports" / "large-story" / story_id
        / "implementation" / "evidence.jsonl"
    )
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_evidence_hook_records_write_during_implement(tmp_path):
    project = _project_with_workflow(tmp_path)
    _advance_to_implement(project)
    result = _run_hook(EVIDENCE_HOOK, project, _posttool_payload(project, "Write", file_path="app.py", content="x"))
    assert result.returncode == 0
    entries = _evidence_entries(project)
    assert any(entry.get("file_path") == "app.py" and entry.get("tool") == "Write" for entry in entries)


def test_evidence_hook_records_bash_command_during_implement(tmp_path):
    project = _project_with_workflow(tmp_path)
    _advance_to_implement(project)
    _run_hook(EVIDENCE_HOOK, project, _posttool_payload(project, "Bash", command="pip install flask"))
    entries = _evidence_entries(project)
    assert any(entry.get("command") == "pip install flask" for entry in entries)


def test_evidence_hook_skips_outside_implement(tmp_path):
    project = _project_with_workflow(tmp_path)
    _run_hook(EVIDENCE_HOOK, project, _posttool_payload(project, "Write", file_path="app.py", content="x"))
    assert _evidence_entries(project) == []


def test_evidence_hook_skips_controller_invocations(tmp_path):
    project = _project_with_workflow(tmp_path)
    _advance_to_implement(project)
    _run_hook(
        EVIDENCE_HOOK,
        project,
        _posttool_payload(project, "Bash", command="python3 scripts/large_story_controller.py render-status"),
    )
    assert _evidence_entries(project) == []


def test_evidence_hook_skips_sweetclaude_files(tmp_path):
    project = _project_with_workflow(tmp_path)
    _advance_to_implement(project)
    _run_hook(
        EVIDENCE_HOOK,
        project,
        _posttool_payload(project, "Write", file_path=".sweetclaude/contracts/note.md", content="x"),
    )
    assert _evidence_entries(project) == []


def test_evidence_hook_silent_without_workflow(tmp_path):
    result = _run_hook(EVIDENCE_HOOK, tmp_path, _posttool_payload(tmp_path, "Write", file_path="app.py", content="x"))
    assert result.returncode == 0
    assert _evidence_entries(tmp_path) == []


# --- TASK-C4: Stop guard hook ---------------------------------------------------


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
    assert "complete" in data["reason"].lower()


def test_stop_hook_respects_stop_hook_active(tmp_path):
    project = _project_with_workflow(tmp_path)
    _advance_to_implement(project)
    result = _run_hook(STOP_HOOK, project, _stop_payload(project, stop_hook_active=True))
    assert result.returncode == 0
    assert not result.stdout.strip()


def test_stop_hook_allows_after_terminal_closeout(tmp_path):
    project = _project_with_workflow(tmp_path)
    _advance_to_implement(project)
    _ship(project)
    result = _run_hook(STOP_HOOK, project, _stop_payload(project))
    assert result.returncode == 0
    assert not result.stdout.strip()


def test_evidence_hook_survives_oversized_command(tmp_path):
    project = _project_with_workflow(tmp_path)
    _advance_to_implement(project)
    huge = "pip install flask # " + "A" * 400_000
    result = _run_hook(EVIDENCE_HOOK, project, _posttool_payload(project, "Bash", command=huge))
    assert result.returncode == 0
    entries = _evidence_entries(project)
    assert any(entry.get("command", "").startswith("pip install flask") for entry in entries)


def test_gate_hook_survives_oversized_content(tmp_path):
    project = _project_with_workflow(tmp_path)
    payload = _pretool_payload(project, "Write", file_path="app.py", content="A" * 400_000)
    result = _run_hook(GATE_HOOK, project, payload)
    decision = _deny_decision(result)
    assert decision is not None
    assert decision["permissionDecision"] == "deny"


def test_gate_hook_asks_for_contract_amendment_in_default_mode(tmp_path):
    project = _project_with_workflow(tmp_path)
    payload = _pretool_payload(
        project, "Write",
        file_path=".sweetclaude/contracts/success-criteria-contract.yaml",
        content="amended",
    )
    result = _run_hook(GATE_HOOK, project, payload)
    assert result.returncode == 0
    decision = json.loads(result.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "ask"
    assert "amendment" in decision["permissionDecisionReason"].lower()


def test_gate_hook_asks_for_contract_amendment_in_every_mode(tmp_path):
    """Hook 'ask' escalates to a real user dialog in all permission modes
    (official docs) — the hook must never downgrade it to deny by mode."""
    project = _project_with_workflow(tmp_path)
    for mode in ("default", "plan", "bypassPermissions", "dontAsk", "acceptEdits", "auto"):
        payload = _pretool_payload(
            project, "Write",
            file_path=".sweetclaude/contracts/success-criteria-contract.yaml",
            content="amended",
        )
        payload["permission_mode"] = mode
        result = _run_hook(GATE_HOOK, project, payload)
        decision = json.loads(result.stdout)["hookSpecificOutput"]
        assert decision["permissionDecision"] == "ask", mode
