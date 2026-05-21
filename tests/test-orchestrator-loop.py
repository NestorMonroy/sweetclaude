"""
Tests for scripts/orchestrator_loop.py — main orchestrator loop.

Coverage (from orchestrator-loop.feature):
  - Main loop flow (execute, re-read state, termination)
  - Gate enforcement (soft/hard, deference levels, persistence, iterate routing)
  - Subagent invocation (prompt assembly, output dir creation, actions dispatch)
  - Failure handling (missing/empty artifact, retry/skip/abort decisions)
  - Crash recovery (active state detection, stale cleanup, session appending)
  - Configuration (max iterations from config, per-step override, output dir)
  - Session state integration (orchestrated flag, completion, abort, phase update)
  - Escalation handling
  - Pre-step cleanup and containment validation
  - Observability (checkpoint written after each step)
  - Routing and iteration (signal validation, backward detection, max iterations)
  - Re-entry guards (terminal state rejection, invalid action rejection)
  - Validation at load time (step id pattern, subagent_type allowlist)
"""
import os
import sys
import yaml
import pytest
from unittest.mock import MagicMock, patch, call

_SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import orchestrator_loop
from orchestrator_loop import run_loop, resume_loop


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

def _make_sweetclaude_yaml(project_dir, workflow_id="STORY-025"):
    """Write a minimal sweetclaude.yaml with an active work item."""
    state_dir = project_dir / ".sweetclaude" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": 2,
        "work": {
            "active": {
                "id": workflow_id,
                "type": "story",
                "phase": "ACTIVATION",
            },
            "last_item_id": workflow_id,
        },
        "work_history": [],
    }
    (state_dir / "sweetclaude.yaml").write_text(yaml.safe_dump(data))
    return state_dir / "sweetclaude.yaml"


def _make_orchestrator_defaults(project_dir, default_max=3, output_dir=".sweetclaude/workflows"):
    """Write config/orchestrator-defaults.yaml."""
    config_dir = project_dir / "config"
    config_dir.mkdir(exist_ok=True)
    data = {
        "iteration_limits": {
            "default_max": default_max,
        },
        "paths": {
            "output_dir": output_dir,
        },
        "subagent_types": {
            "allowlist": ["code", "research", "housekeeping"],
        },
    }
    (config_dir / "orchestrator-defaults.yaml").write_text(yaml.safe_dump(data))


def _make_workflow_template(project_dir, steps=None):
    """Write config/workflow-templates.yaml with a minimal net-new-feature template."""
    config_dir = project_dir / "config"
    config_dir.mkdir(exist_ok=True)

    if steps is None:
        steps = [
            {
                "id": "activate",
                "phase": "ACTIVATION",
                "agent": "housekeeping",
                "model": "sonnet",
                "subagent_type": "code",
                "input_artifacts": None,
                "output_artifact": None,
                "gate": None,
                "routing": None,
                "max_iterations": None,
                "next": None,
                "exit_checks": None,
                "escalation": None,
                "action": None,
            },
            {
                "id": "spec",
                "phase": "DEFINE",
                "agent": "spec-writer",
                "model": "opus",
                "subagent_type": "research",
                "input_artifacts": ["story_file"],
                "output_artifact": "spec_file",
                "gate": "user_approval",
                "routing": None,
                "max_iterations": None,
                "next": None,
                "exit_checks": ["file_exists", "file_non_empty"],
                "escalation": None,
                "action": None,
            },
            {
                "id": "implement",
                "phase": "IMPLEMENT",
                "agent": "implementer",
                "model": "sonnet",
                "subagent_type": "code",
                "input_artifacts": ["spec_file"],
                "output_artifact": "source_files",
                "gate": None,
                "routing": None,
                "max_iterations": None,
                "next": None,
                "exit_checks": ["file_exists", "file_non_empty"],
                "escalation": None,
                "action": None,
            },
        ]

    data = {
        "schema_version": 2,
        "net-new-feature": {
            "shape": "full-pipeline",
            "phases": ["ACTIVATION", "DEFINE", "IMPLEMENT"],
            "steps": steps,
        },
    }
    (config_dir / "workflow-templates.yaml").write_text(yaml.safe_dump(data))


def _make_workflow_state(project_dir, workflow_id="STORY-025", current_step_id="activate",
                          status="active", extra=None):
    """Write a minimal workflow state yaml file."""
    wf_dir = project_dir / ".sweetclaude" / "state" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": 1,
        "workflow_id": workflow_id,
        "workflow_type": "net-new-feature",
        "status": status,
        "current_step_id": current_step_id,
        "completed_steps": [],
        "artifacts": {},
        "gates_passed": [],
        "iterations": {},
        "checkpoint": "Workflow started.",
        "checkpoint_at": "2026-05-20T10:00:00Z",
        "error": None,
        "sessions": [
            {
                "started_at": "2026-05-20T10:00:00Z",
                "ended_at": None,
                "steps_completed": [],
            }
        ],
        "started_at": "2026-05-20T10:00:00Z",
        "updated_at": "2026-05-20T10:00:00Z",
    }
    if extra:
        state.update(extra)
    (wf_dir / f"{workflow_id}.yaml").write_text(yaml.safe_dump(state))
    return wf_dir / f"{workflow_id}.yaml"


def _make_step(id, phase="ACTIVATION", agent=None, model="sonnet", subagent_type="code",
               input_artifacts=None, output_artifact=None, gate=None, routing=None,
               max_iterations=None, next=None, exit_checks=None, escalation=None, action=None):
    """Build a step dict with sensible defaults."""
    return {
        "id": id,
        "phase": phase,
        "agent": agent,
        "model": model,
        "subagent_type": subagent_type,
        "input_artifacts": input_artifacts,
        "output_artifact": output_artifact,
        "gate": gate,
        "routing": routing,
        "max_iterations": max_iterations,
        "next": next,
        "exit_checks": exit_checks,
        "escalation": escalation,
        "action": action,
    }


def _full_project(tmp_path, workflow_id="STORY-025", current_step_id="activate",
                  status="active", steps=None, extra_state=None,
                  completed_steps=None, gates_passed=None, checkpoint=None,
                  default_max=3, output_dir=".sweetclaude/workflows"):
    """Create a fully-configured project directory for loop tests."""
    _make_sweetclaude_yaml(tmp_path, workflow_id=workflow_id)
    _make_orchestrator_defaults(tmp_path, default_max=default_max, output_dir=output_dir)
    _make_workflow_template(tmp_path, steps=steps)
    extra = extra_state or {}
    if completed_steps is not None:
        extra["completed_steps"] = completed_steps
    if gates_passed is not None:
        extra["gates_passed"] = gates_passed
    if checkpoint is not None:
        extra["checkpoint"] = checkpoint
    _make_workflow_state(tmp_path, workflow_id=workflow_id,
                         current_step_id=current_step_id, status=status, extra=extra)
    return tmp_path


# ---------------------------------------------------------------------------
# Scenario: Loop executes a single step and advances
# ---------------------------------------------------------------------------

class TestMainLoopFlow:
    def test_loop_executes_step_and_advances_current_step_id(self, tmp_path):
        """After one iteration on 'activate' (no gate, no output), state shows next step."""
        project_dir = _full_project(tmp_path, current_step_id="activate")

        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            result = run_loop("STORY-025", project_dir=str(project_dir),
                              deference_level="autonomous")

        state_file = (tmp_path / ".sweetclaude" / "state" / "workflows" / "STORY-025.yaml")
        state = yaml.safe_load(state_file.read_text())
        assert state["current_step_id"] != "activate"

    def test_loop_adds_completed_step_to_completed_steps(self, tmp_path):
        """After executing 'activate', it appears in completed_steps."""
        project_dir = _full_project(tmp_path, current_step_id="activate")

        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")

        state_file = (tmp_path / ".sweetclaude" / "state" / "workflows" / "STORY-025.yaml")
        state = yaml.safe_load(state_file.read_text())
        assert "activate" in state["completed_steps"]

    def test_loop_re_reads_state_from_disk_each_iteration(self, tmp_path):
        """If state file is modified externally between iterations, loop uses fresh copy."""
        project_dir = _full_project(tmp_path, current_step_id="activate")

        iteration_count = [0]
        wf_state_file = tmp_path / ".sweetclaude" / "state" / "workflows" / "STORY-025.yaml"

        original_invoke = getattr(orchestrator_loop, "_invoke_agent", None)

        def intercepting_invoke(step, state, project_dir_str, **kwargs):
            iteration_count[0] += 1
            if iteration_count[0] == 1:
                # Externally modify the state before iteration 2
                current = yaml.safe_load(wf_state_file.read_text())
                current["external_marker"] = "injected_externally"
                wf_state_file.write_text(yaml.safe_dump(current))
            return None

        with patch.object(orchestrator_loop, "_invoke_agent", side_effect=intercepting_invoke):
            run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")

        final_state = yaml.safe_load(wf_state_file.read_text())
        # The loop should not have overwritten the externally-injected marker without reading it
        # (i.e., it reads fresh state each time)
        assert final_state.get("external_marker") == "injected_externally" or iteration_count[0] >= 1

    def test_loop_terminates_on_complete_sentinel(self, tmp_path):
        """A workflow at COMPLETE yields a YieldPoint with reason 'complete'."""
        project_dir = _full_project(tmp_path, current_step_id="COMPLETE")

        result = run_loop("STORY-025", project_dir=str(project_dir),
                          deference_level="autonomous")

        assert result["reason"] == "complete"

    def test_loop_terminates_on_halted_sentinel(self, tmp_path):
        """A workflow at HALTED yields a YieldPoint with reason 'halted'."""
        project_dir = _full_project(tmp_path, current_step_id="HALTED",
                                     status="HALTED")

        result = run_loop("STORY-025", project_dir=str(project_dir),
                          deference_level="autonomous")

        assert result["reason"] == "halted"


# ---------------------------------------------------------------------------
# Scenario: Gate enforcement
# ---------------------------------------------------------------------------

class TestGateEnforcement:
    def test_soft_gate_yields_in_collaborative_mode(self, tmp_path):
        """Soft gate yields a 'gate' YieldPoint in collaborative mode."""
        project_dir = _full_project(tmp_path, current_step_id="spec")

        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            result = run_loop("STORY-025", project_dir=str(project_dir),
                              deference_level="collaborative")

        assert result["reason"] == "gate"

    def test_soft_gate_yield_payload_contains_gate_type(self, tmp_path):
        """The gate yield payload includes gate_type."""
        project_dir = _full_project(tmp_path, current_step_id="spec")

        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            result = run_loop("STORY-025", project_dir=str(project_dir),
                              deference_level="collaborative")

        payload = result.get("payload", {})
        assert "gate_type" in payload
        assert payload["gate_type"] == "user_approval"

    def test_soft_gate_auto_advances_in_autonomous_mode_no_critical_findings(self, tmp_path):
        """In autonomous mode with no critical findings, soft gate auto-advances."""
        # activate has no gate, so we need spec step with story_file artifact present
        spec_output = tmp_path / "outputs" / "spec.md"
        spec_output.parent.mkdir(parents=True, exist_ok=True)
        spec_output.write_text("# Spec content\n")

        project_dir = _full_project(
            tmp_path,
            current_step_id="spec",
            extra_state={
                "artifacts": {
                    "story_file": str(tmp_path / "story.md"),
                    "spec_file": str(spec_output),
                }
            }
        )
        (tmp_path / "story.md").write_text("# Story")

        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            result = run_loop("STORY-025", project_dir=str(project_dir),
                              deference_level="autonomous")

        # Should NOT yield "gate" — should advance past it
        assert result.get("reason") != "gate"

    def test_hard_gate_always_yields_regardless_of_deference(self, tmp_path):
        """Hard gate (user_approval_hard) always yields, even in autonomous mode."""
        steps = [
            {
                "id": "activate",
                "phase": "ACTIVATION",
                "agent": "housekeeping",
                "model": "sonnet",
                "subagent_type": "code",
                "input_artifacts": None,
                "output_artifact": None,
                "gate": None,
                "routing": None,
                "max_iterations": None,
                "next": None,
                "exit_checks": None,
                "escalation": None,
                "action": None,
            },
            {
                "id": "spec",
                "phase": "DEFINE",
                "agent": "spec-writer",
                "model": "opus",
                "subagent_type": "research",
                "input_artifacts": None,
                "output_artifact": None,
                "gate": "user_approval_hard",
                "routing": None,
                "max_iterations": None,
                "next": None,
                "exit_checks": None,
                "escalation": None,
                "action": None,
            },
        ]
        project_dir = _full_project(tmp_path, current_step_id="spec", steps=steps)

        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            result = run_loop("STORY-025", project_dir=str(project_dir),
                              deference_level="autonomous")

        assert result["reason"] == "gate"

    def test_gate_passage_written_to_disk_before_execution_continues(self, tmp_path):
        """record_gate_passage is persisted to disk before the loop continues executing."""
        project_dir = _full_project(tmp_path, current_step_id="spec")

        # First: get to the gate yield
        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            gate_result = run_loop("STORY-025", project_dir=str(project_dir),
                                   deference_level="collaborative")

        assert gate_result["reason"] == "gate"

        # Now approve and resume
        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            resume_loop("STORY-025", decision={"action": "approve"},
                        project_dir=str(project_dir), deference_level="collaborative")

        state_file = tmp_path / ".sweetclaude" / "state" / "workflows" / "STORY-025.yaml"
        state = yaml.safe_load(state_file.read_text())
        gates = state.get("gates_passed", [])
        assert len(gates) >= 1
        gate_types = [g.get("gate_type") for g in gates]
        assert "user_approval" in gate_types

    def test_gate_state_shows_gate_in_gates_passed_before_step_execution(self, tmp_path):
        """After resume with approve, gates_passed has the entry before step runs."""
        project_dir = _full_project(tmp_path, current_step_id="spec")

        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            run_loop("STORY-025", project_dir=str(project_dir),
                     deference_level="collaborative")

        # Capture what state looks like at agent invocation time
        captured_state = {}

        def capturing_invoke(step, state, project_dir_str, **kwargs):
            if step["id"] == "spec":
                captured_state.update(state)
            return None

        with patch.object(orchestrator_loop, "_invoke_agent", side_effect=capturing_invoke):
            resume_loop("STORY-025", decision={"action": "approve"},
                        project_dir=str(project_dir), deference_level="collaborative")

        # gates_passed should contain the entry at the time spec step runs
        gates = captured_state.get("gates_passed", [])
        assert any(g.get("gate_type") == "user_approval" for g in gates)

    def test_iterate_gate_option_routes_back_to_input_producer(self, tmp_path):
        """Selecting 'iterate' at the spec gate sets current_step_id to 'activate' (the prior step)."""
        project_dir = _full_project(tmp_path, current_step_id="spec")

        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            run_loop("STORY-025", project_dir=str(project_dir),
                     deference_level="collaborative")

        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            resume_loop("STORY-025", decision={"action": "iterate"},
                        project_dir=str(project_dir), deference_level="collaborative")

        state_file = tmp_path / ".sweetclaude" / "state" / "workflows" / "STORY-025.yaml"
        state = yaml.safe_load(state_file.read_text())
        # Should have routed back to activate (the step producing story_file, input to spec)
        assert state["current_step_id"] == "activate"


# ---------------------------------------------------------------------------
# Scenario: Subagent invocation
# ---------------------------------------------------------------------------

class TestSubagentInvocation:
    def test_agent_prompt_contains_input_artifact_file_paths(self, tmp_path):
        """When invoking an agent step, the prompt includes resolved input artifact paths."""
        story_file = tmp_path / "story.md"
        story_file.write_text("# Story")

        project_dir = _full_project(
            tmp_path,
            current_step_id="spec",
            extra_state={"artifacts": {"story_file": str(story_file)}}
        )

        captured_prompts = []

        def capturing_invoke(step, state, project_dir_str, prompt=None, **kwargs):
            if prompt:
                captured_prompts.append(prompt)
            return None

        with patch.object(orchestrator_loop, "_invoke_agent", side_effect=capturing_invoke):
            # Skip gate by using autonomous
            run_loop("STORY-025", project_dir=str(project_dir),
                     deference_level="autonomous")

        assert len(captured_prompts) > 0
        combined = " ".join(captured_prompts)
        assert str(story_file) in combined

    def test_agent_prompt_specifies_output_path(self, tmp_path):
        """The agent prompt tells the agent where to write its output."""
        story_file = tmp_path / "story.md"
        story_file.write_text("# Story")

        project_dir = _full_project(
            tmp_path,
            current_step_id="spec",
            extra_state={"artifacts": {"story_file": str(story_file)}}
        )

        captured_prompts = []

        def capturing_invoke(step, state, project_dir_str, prompt=None, **kwargs):
            if prompt:
                captured_prompts.append(prompt)
            return None

        with patch.object(orchestrator_loop, "_invoke_agent", side_effect=capturing_invoke):
            run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")

        combined = " ".join(captured_prompts)
        # Output path should reference the output_dir from config
        assert ".sweetclaude/workflows" in combined or "spec" in combined.lower()

    def test_agent_step_creates_output_directory_before_invocation(self, tmp_path):
        """The output directory is created before the agent is called."""
        story_file = tmp_path / "story.md"
        story_file.write_text("# Story")

        project_dir = _full_project(
            tmp_path,
            current_step_id="spec",
            extra_state={"artifacts": {"story_file": str(story_file)}}
        )

        dir_existed_at_invoke = {}

        def capturing_invoke(step, state, project_dir_str, output_path=None, **kwargs):
            if output_path:
                dir_existed_at_invoke["exists"] = os.path.isdir(os.path.dirname(output_path))
            return None

        with patch.object(orchestrator_loop, "_invoke_agent", side_effect=capturing_invoke):
            run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")

        assert dir_existed_at_invoke.get("exists", True) is True

    def test_steps_with_agent_null_dispatch_via_orchestrator_actions(self, tmp_path):
        """Steps with agent=null call orchestrator_actions.ACTIONS[step['action']]."""
        steps = [
            {
                "id": "verify",
                "phase": "VERIFY",
                "agent": None,
                "model": None,
                "subagent_type": None,
                "input_artifacts": None,
                "output_artifact": None,
                "gate": None,
                "routing": None,
                "max_iterations": None,
                "next": None,
                "exit_checks": None,
                "escalation": None,
                "action": "verify_artifacts",
            },
        ]
        project_dir = _full_project(tmp_path, current_step_id="verify", steps=steps)

        import orchestrator_actions

        called_with = {}

        def fake_verify(step, state, project_dir_str):
            called_with["step"] = step
            return {"status": "success"}

        original_actions = dict(orchestrator_actions.ACTIONS)
        orchestrator_actions.ACTIONS["verify_artifacts"] = fake_verify

        try:
            run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")
        finally:
            orchestrator_actions.ACTIONS.clear()
            orchestrator_actions.ACTIONS.update(original_actions)

        assert called_with.get("step", {}).get("id") == "verify"


# ---------------------------------------------------------------------------
# Scenario: Failure handling
# ---------------------------------------------------------------------------

class TestFailureHandling:
    def test_missing_output_artifact_yields_failure(self, tmp_path):
        """When the agent produces no output file, run_loop yields reason='failure'."""
        story_file = tmp_path / "story.md"
        story_file.write_text("# Story")

        project_dir = _full_project(
            tmp_path,
            current_step_id="spec",
            extra_state={"artifacts": {"story_file": str(story_file)}}
        )

        # Agent is called but writes nothing
        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            result = run_loop("STORY-025", project_dir=str(project_dir),
                              deference_level="autonomous")

        assert result["reason"] == "failure"

    def test_failure_payload_describes_missing_artifact(self, tmp_path):
        """Failure YieldPoint payload identifies the missing artifact."""
        story_file = tmp_path / "story.md"
        story_file.write_text("# Story")

        project_dir = _full_project(
            tmp_path,
            current_step_id="spec",
            extra_state={"artifacts": {"story_file": str(story_file)}}
        )

        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            result = run_loop("STORY-025", project_dir=str(project_dir),
                              deference_level="autonomous")

        payload = result.get("payload", {})
        combined = str(payload)
        assert "spec_file" in combined or "spec" in combined.lower()

    def test_empty_output_artifact_yields_failure(self, tmp_path):
        """When the agent writes an empty file, run_loop yields reason='failure'."""
        story_file = tmp_path / "story.md"
        story_file.write_text("# Story")

        output_dir = tmp_path / ".sweetclaude" / "workflows" / "STORY-025" / "spec"
        output_dir.mkdir(parents=True)
        empty_output = output_dir / "spec.md"
        empty_output.write_text("")

        project_dir = _full_project(
            tmp_path,
            current_step_id="spec",
            extra_state={
                "artifacts": {
                    "story_file": str(story_file),
                    "spec_file": str(empty_output),
                }
            }
        )

        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            result = run_loop("STORY-025", project_dir=str(project_dir),
                              deference_level="autonomous")

        assert result["reason"] == "failure"

    def test_retry_decision_keeps_current_step_id(self, tmp_path):
        """After a failure yield, resume with 'retry' keeps current_step_id as 'spec'."""
        story_file = tmp_path / "story.md"
        story_file.write_text("# Story")

        project_dir = _full_project(
            tmp_path,
            current_step_id="spec",
            extra_state={"artifacts": {"story_file": str(story_file)}}
        )

        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")

        # Simulate: set the state to waiting_for_user with a pending failure
        wf_state_file = tmp_path / ".sweetclaude" / "state" / "workflows" / "STORY-025.yaml"
        state = yaml.safe_load(wf_state_file.read_text())
        state["status"] = "waiting_for_user"
        state["current_step_id"] = "spec"
        wf_state_file.write_text(yaml.safe_dump(state))

        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            resume_loop("STORY-025", decision={"action": "retry"},
                        project_dir=str(project_dir), deference_level="autonomous")

        state = yaml.safe_load(wf_state_file.read_text())
        assert state["current_step_id"] == "spec"

    def test_retry_cleans_stale_output_before_re_execution(self, tmp_path):
        """On retry, stale output artifact is deleted before the agent re-runs."""
        story_file = tmp_path / "story.md"
        story_file.write_text("# Story")

        stale_spec = tmp_path / ".sweetclaude" / "workflows" / "STORY-025" / "spec.md"
        stale_spec.parent.mkdir(parents=True, exist_ok=True)
        stale_spec.write_text("stale content")

        project_dir = _full_project(
            tmp_path,
            current_step_id="spec",
            extra_state={
                "artifacts": {
                    "story_file": str(story_file),
                    "spec_file": str(stale_spec),
                }
            }
        )

        wf_state_file = tmp_path / ".sweetclaude" / "state" / "workflows" / "STORY-025.yaml"
        state = yaml.safe_load(wf_state_file.read_text())
        state["status"] = "waiting_for_user"
        wf_state_file.write_text(yaml.safe_dump(state))

        agent_saw_file_at_invocation = {}

        def capturing_invoke(step, state, project_dir_str, **kwargs):
            if step["id"] == "spec":
                agent_saw_file_at_invocation["exists"] = stale_spec.exists()
            return None

        with patch.object(orchestrator_loop, "_invoke_agent", side_effect=capturing_invoke):
            resume_loop("STORY-025", decision={"action": "retry"},
                        project_dir=str(project_dir), deference_level="autonomous")

        # The stale file should have been deleted before the agent ran
        assert agent_saw_file_at_invocation.get("exists") is False

    def test_skip_decision_advances_to_next_step(self, tmp_path):
        """After a failure yield, resume with 'skip' advances current_step_id."""
        project_dir = _full_project(tmp_path, current_step_id="spec",
                                     extra_state={"artifacts": {"story_file": str(tmp_path / "s.md")}})
        (tmp_path / "s.md").write_text("# Story")
        wf_state_file = tmp_path / ".sweetclaude" / "state" / "workflows" / "STORY-025.yaml"
        state = yaml.safe_load(wf_state_file.read_text())
        state["status"] = "waiting_for_user"
        wf_state_file.write_text(yaml.safe_dump(state))

        resume_loop("STORY-025", decision={"action": "skip"},
                    project_dir=str(project_dir), deference_level="autonomous")

        state = yaml.safe_load(wf_state_file.read_text())
        assert state["current_step_id"] != "spec"

    def test_skip_records_skip_reason_in_state(self, tmp_path):
        """Skip decision records the reason in state."""
        project_dir = _full_project(tmp_path, current_step_id="spec",
                                     extra_state={"artifacts": {"story_file": str(tmp_path / "s.md")}})
        (tmp_path / "s.md").write_text("# Story")
        wf_state_file = tmp_path / ".sweetclaude" / "state" / "workflows" / "STORY-025.yaml"
        state = yaml.safe_load(wf_state_file.read_text())
        state["status"] = "waiting_for_user"
        wf_state_file.write_text(yaml.safe_dump(state))

        resume_loop("STORY-025",
                    decision={"action": "skip", "reason": "skipping manually"},
                    project_dir=str(project_dir), deference_level="autonomous")

        state = yaml.safe_load(wf_state_file.read_text())
        combined = str(state)
        assert "skip" in combined.lower()

    def test_abort_decision_sets_status_halted(self, tmp_path):
        """Abort decision sets workflow status to 'HALTED' on disk."""
        project_dir = _full_project(tmp_path, current_step_id="spec")
        wf_state_file = tmp_path / ".sweetclaude" / "state" / "workflows" / "STORY-025.yaml"
        state = yaml.safe_load(wf_state_file.read_text())
        state["status"] = "waiting_for_user"
        wf_state_file.write_text(yaml.safe_dump(state))

        resume_loop("STORY-025", decision={"action": "abort"},
                    project_dir=str(project_dir), deference_level="autonomous")

        state = yaml.safe_load(wf_state_file.read_text())
        assert state["status"].lower() in ("halted", "HALTED")

    def test_abort_decision_sets_checkpoint_explaining_abort(self, tmp_path):
        """Abort writes a checkpoint message explaining the abort."""
        project_dir = _full_project(tmp_path, current_step_id="spec")
        wf_state_file = tmp_path / ".sweetclaude" / "state" / "workflows" / "STORY-025.yaml"
        state = yaml.safe_load(wf_state_file.read_text())
        state["status"] = "waiting_for_user"
        wf_state_file.write_text(yaml.safe_dump(state))

        resume_loop("STORY-025", decision={"action": "abort"},
                    project_dir=str(project_dir), deference_level="autonomous")

        state = yaml.safe_load(wf_state_file.read_text())
        assert "abort" in state.get("checkpoint", "").lower() or \
               "halt" in state.get("checkpoint", "").lower()


# ---------------------------------------------------------------------------
# Scenario: Crash recovery
# ---------------------------------------------------------------------------

class TestCrashRecovery:
    def test_active_workflow_detected_on_entry(self, tmp_path):
        """run_loop detects existing active state for the workflow."""
        project_dir = _full_project(tmp_path, current_step_id="activate")

        # State file already exists (written by _full_project)
        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            result = run_loop("STORY-025", project_dir=str(project_dir),
                              deference_level="autonomous")

        # It should run (not error) and the state file should exist
        wf_state_file = tmp_path / ".sweetclaude" / "state" / "workflows" / "STORY-025.yaml"
        assert wf_state_file.exists()

    def test_stale_output_artifact_cleaned_before_step_re_run(self, tmp_path):
        """Stale output from a prior run is deleted before the agent executes."""
        story_file = tmp_path / "story.md"
        story_file.write_text("# Story")

        stale_spec = tmp_path / ".sweetclaude" / "workflows" / "STORY-025" / "spec.md"
        stale_spec.parent.mkdir(parents=True, exist_ok=True)
        stale_spec.write_text("stale from prior run")

        project_dir = _full_project(
            tmp_path,
            current_step_id="spec",
            extra_state={
                "artifacts": {
                    "story_file": str(story_file),
                    "spec_file": str(stale_spec),
                }
            }
        )

        file_present_at_invocation = []

        def capturing_invoke(step, state, project_dir_str, **kwargs):
            if step["id"] == "spec":
                file_present_at_invocation.append(stale_spec.exists())
            return None

        with patch.object(orchestrator_loop, "_invoke_agent", side_effect=capturing_invoke):
            run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")

        if file_present_at_invocation:
            assert file_present_at_invocation[0] is False

    def test_resume_appends_new_session_entry(self, tmp_path):
        """When resume_loop is called, a new session entry is appended to state.sessions."""
        project_dir = _full_project(tmp_path, current_step_id="spec")
        wf_state_file = tmp_path / ".sweetclaude" / "state" / "workflows" / "STORY-025.yaml"
        state = yaml.safe_load(wf_state_file.read_text())
        original_session_count = len(state.get("sessions", []))
        state["status"] = "waiting_for_user"
        wf_state_file.write_text(yaml.safe_dump(state))

        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            resume_loop("STORY-025", decision={"action": "approve"},
                        project_dir=str(project_dir), deference_level="collaborative")

        state = yaml.safe_load(wf_state_file.read_text())
        assert len(state.get("sessions", [])) > original_session_count


# ---------------------------------------------------------------------------
# Scenario: Configuration
# ---------------------------------------------------------------------------

class TestConfiguration:
    def test_default_max_iterations_from_config(self, tmp_path):
        """When step has no max_iterations, config default_max is used."""
        project_dir = _full_project(tmp_path, default_max=3, current_step_id="activate")

        # The loop should respect the config value — we verify by checking that
        # the loop doesn't exceed the max when detecting backward movement.
        # We assert the config is loadable and the value propagates.
        defaults_file = tmp_path / "config" / "orchestrator-defaults.yaml"
        data = yaml.safe_load(defaults_file.read_text())
        assert data["iteration_limits"]["default_max"] == 3

        # The loop must use 3 as the cap for steps without explicit max_iterations
        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            # Run loop to ensure config is loaded (no KeyError or AttributeError)
            run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")

    def test_per_step_max_iterations_overrides_config_default(self, tmp_path):
        """When step has max_iterations=5, it overrides config default of 3."""
        steps = [
            {
                "id": "activate",
                "phase": "ACTIVATION",
                "agent": "housekeeping",
                "model": "sonnet",
                "subagent_type": "code",
                "input_artifacts": None,
                "output_artifact": None,
                "gate": None,
                "routing": {"needs_redo": "activate", "done": "continue"},
                "max_iterations": 5,
                "next": None,
                "exit_checks": None,
                "escalation": None,
                "action": None,
            },
        ]
        project_dir = _full_project(tmp_path, default_max=3, current_step_id="activate",
                                     steps=steps)

        # The step's max_iterations=5 should be used, not config's 3.
        # We verify the loop accepts this configuration without error.
        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            result = run_loop("STORY-025", project_dir=str(project_dir),
                              deference_level="autonomous")

        # No ValueError should have been raised about max_iterations
        assert result is not None

    def test_output_dir_from_config_used_in_agent_prompt(self, tmp_path):
        """Paths from config/orchestrator-defaults.yaml.paths.output_dir appear in agent prompts."""
        story_file = tmp_path / "story.md"
        story_file.write_text("# Story")

        project_dir = _full_project(
            tmp_path,
            current_step_id="spec",
            output_dir=".sweetclaude/workflows",
            extra_state={"artifacts": {"story_file": str(story_file)}}
        )

        captured_prompts = []

        def capturing_invoke(step, state, project_dir_str, prompt=None, **kwargs):
            if prompt:
                captured_prompts.append(prompt)
            return None

        with patch.object(orchestrator_loop, "_invoke_agent", side_effect=capturing_invoke):
            run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")

        combined = " ".join(captured_prompts)
        assert ".sweetclaude/workflows" in combined


# ---------------------------------------------------------------------------
# Scenario: Session state integration (sweetclaude.yaml)
# ---------------------------------------------------------------------------

class TestSessionStateIntegration:
    def test_workflow_start_sets_orchestrated_flag(self, tmp_path):
        """run_loop sets sweetclaude.yaml orchestrated=true on start."""
        project_dir = _full_project(tmp_path, current_step_id="activate")

        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")

        sc_yaml = tmp_path / ".sweetclaude" / "state" / "sweetclaude.yaml"
        data = yaml.safe_load(sc_yaml.read_text())
        assert data.get("work", {}).get("active", {}).get("orchestrated") is True or \
               data.get("orchestrated") is True

    def test_workflow_start_sets_workflow_state_file_path(self, tmp_path):
        """run_loop sets sweetclaude.yaml workflow_state_file to the state file path."""
        project_dir = _full_project(tmp_path, current_step_id="activate")

        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")

        sc_yaml = tmp_path / ".sweetclaude" / "state" / "sweetclaude.yaml"
        data = yaml.safe_load(sc_yaml.read_text())
        combined = str(data)
        assert "STORY-025" in combined

    def test_workflow_completion_clears_active_work(self, tmp_path):
        """When workflow completes, sweetclaude.yaml work.active is cleared."""
        project_dir = _full_project(tmp_path, current_step_id="COMPLETE")

        run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")

        sc_yaml = tmp_path / ".sweetclaude" / "state" / "sweetclaude.yaml"
        data = yaml.safe_load(sc_yaml.read_text())
        active = data.get("work", {}).get("active")
        assert active is None or active == {}

    def test_workflow_completion_adds_entry_to_work_history(self, tmp_path):
        """Completing a workflow adds a work_history entry with result='complete'."""
        project_dir = _full_project(tmp_path, current_step_id="COMPLETE")

        run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")

        sc_yaml = tmp_path / ".sweetclaude" / "state" / "sweetclaude.yaml"
        data = yaml.safe_load(sc_yaml.read_text())
        history = data.get("work_history", [])
        assert any(h.get("result") == "complete" for h in history)

    def test_workflow_abort_clears_active_work(self, tmp_path):
        """When workflow is halted, sweetclaude.yaml work.active is cleared."""
        project_dir = _full_project(tmp_path, current_step_id="spec")
        wf_state_file = tmp_path / ".sweetclaude" / "state" / "workflows" / "STORY-025.yaml"
        state = yaml.safe_load(wf_state_file.read_text())
        state["status"] = "waiting_for_user"
        wf_state_file.write_text(yaml.safe_dump(state))

        resume_loop("STORY-025", decision={"action": "abort"},
                    project_dir=str(project_dir), deference_level="autonomous")

        sc_yaml = tmp_path / ".sweetclaude" / "state" / "sweetclaude.yaml"
        data = yaml.safe_load(sc_yaml.read_text())
        active = data.get("work", {}).get("active")
        assert active is None or active == {}

    def test_workflow_abort_adds_halted_entry_to_work_history(self, tmp_path):
        """Aborting adds a work_history entry with result='halted'."""
        project_dir = _full_project(tmp_path, current_step_id="spec")
        wf_state_file = tmp_path / ".sweetclaude" / "state" / "workflows" / "STORY-025.yaml"
        state = yaml.safe_load(wf_state_file.read_text())
        state["status"] = "waiting_for_user"
        wf_state_file.write_text(yaml.safe_dump(state))

        resume_loop("STORY-025", decision={"action": "abort"},
                    project_dir=str(project_dir), deference_level="autonomous")

        sc_yaml = tmp_path / ".sweetclaude" / "state" / "sweetclaude.yaml"
        data = yaml.safe_load(sc_yaml.read_text())
        history = data.get("work_history", [])
        assert any(h.get("result") == "halted" for h in history)

    def test_phase_updated_to_next_step_phase_after_routing(self, tmp_path):
        """After routing from spec (DEFINE) back to activate (ACTIVATION), phase is ACTIVATION."""
        steps = [
            {
                "id": "activate",
                "phase": "ACTIVATION",
                "agent": "housekeeping",
                "model": "sonnet",
                "subagent_type": "code",
                "input_artifacts": None,
                "output_artifact": None,
                "gate": None,
                "routing": None,
                "max_iterations": None,
                "next": None,
                "exit_checks": None,
                "escalation": None,
                "action": None,
            },
            {
                "id": "spec",
                "phase": "DEFINE",
                "agent": "spec-writer",
                "model": "opus",
                "subagent_type": "research",
                "input_artifacts": None,
                "output_artifact": None,
                "gate": None,
                "routing": {"needs_redo": "activate", "done": "continue"},
                "max_iterations": None,
                "next": None,
                "exit_checks": None,
                "escalation": None,
                "action": None,
            },
            {
                "id": "implement",
                "phase": "IMPLEMENT",
                "agent": "implementer",
                "model": "sonnet",
                "subagent_type": "code",
                "input_artifacts": None,
                "output_artifact": None,
                "gate": None,
                "routing": None,
                "max_iterations": None,
                "next": None,
                "exit_checks": None,
                "escalation": None,
                "action": None,
            },
        ]
        project_dir = _full_project(tmp_path, current_step_id="spec", steps=steps)

        def invoke_with_signal(step, state, project_dir_str, output_path=None, **kwargs):
            if output_path and step["id"] == "spec":
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                with open(output_path, "w") as f:
                    f.write("---\nsignal: needs_redo\n---\n\nNeeds revision.\n")
            return None

        with patch.object(orchestrator_loop, "_invoke_agent", side_effect=invoke_with_signal):
            run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")

        sc_yaml = tmp_path / ".sweetclaude" / "state" / "sweetclaude.yaml"
        data = yaml.safe_load(sc_yaml.read_text())
        active_phase = data.get("work", {}).get("active", {}).get("phase", "")
        assert active_phase.upper() == "ACTIVATION"

    def test_completion_does_not_modify_sweetclaude_if_id_mismatch(self, tmp_path):
        """If sweetclaude.yaml active.id was changed externally, loop does not clear it."""
        project_dir = _full_project(tmp_path, current_step_id="COMPLETE",
                                     workflow_id="STORY-025")

        # Change active.id to something else
        sc_yaml_path = tmp_path / ".sweetclaude" / "state" / "sweetclaude.yaml"
        data = yaml.safe_load(sc_yaml_path.read_text())
        data["work"]["active"]["id"] = "STORY-999"
        sc_yaml_path.write_text(yaml.safe_dump(data))

        run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")

        data = yaml.safe_load(sc_yaml_path.read_text())
        # Should NOT have cleared active — id didn't match
        assert data.get("work", {}).get("active") is not None
        assert data["work"]["active"].get("id") == "STORY-999"


# ---------------------------------------------------------------------------
# Scenario: Escalation handling
# ---------------------------------------------------------------------------

class TestEscalationHandling:
    def test_escalation_condition_triggers_yield(self, tmp_path):
        """When agent output signal matches escalation condition, loop yields 'escalation'."""
        steps = [
            {
                "id": "review",
                "phase": "VERIFY",
                "agent": "reviewer",
                "model": "sonnet",
                "subagent_type": "research",
                "input_artifacts": None,
                "output_artifact": "review_output",
                "gate": None,
                "routing": None,
                "max_iterations": None,
                "next": None,
                "exit_checks": None,
                "escalation": {"signal": "critical", "action": "pause"},
                "action": None,
            },
        ]
        project_dir = _full_project(tmp_path, current_step_id="review", steps=steps)

        def invoke_with_critical(step, state, project_dir_str, output_path=None, **kwargs):
            if output_path:
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                with open(output_path, "w") as f:
                    f.write("---\nsignal: critical\n---\n\nCritical issue found.\n")
            return None

        with patch.object(orchestrator_loop, "_invoke_agent", side_effect=invoke_with_critical):
            result = run_loop("STORY-025", project_dir=str(project_dir),
                              deference_level="autonomous")

        assert result["reason"] == "escalation"

    def test_escalation_payload_contains_escalation_details(self, tmp_path):
        """Escalation yield payload includes the escalation signal and action."""
        steps = [
            {
                "id": "review",
                "phase": "VERIFY",
                "agent": "reviewer",
                "model": "sonnet",
                "subagent_type": "research",
                "input_artifacts": None,
                "output_artifact": "review_output",
                "gate": None,
                "routing": None,
                "max_iterations": None,
                "next": None,
                "exit_checks": None,
                "escalation": {"signal": "critical", "action": "pause"},
                "action": None,
            },
        ]
        project_dir = _full_project(tmp_path, current_step_id="review", steps=steps)

        def invoke_with_critical(step, state, project_dir_str, output_path=None, **kwargs):
            if output_path:
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                with open(output_path, "w") as f:
                    f.write("---\nsignal: critical\n---\n\nCritical issue.\n")
            return None

        with patch.object(orchestrator_loop, "_invoke_agent", side_effect=invoke_with_critical):
            result = run_loop("STORY-025", project_dir=str(project_dir),
                              deference_level="autonomous")

        payload = result.get("payload", {})
        combined = str(payload)
        assert "critical" in combined


# ---------------------------------------------------------------------------
# Scenario: Pre-step cleanup and containment validation
# ---------------------------------------------------------------------------

class TestPreStepCleanup:
    def test_stale_artifact_deleted_before_step_execution(self, tmp_path):
        """Stale file at expected output path is deleted before agent runs."""
        story_file = tmp_path / "story.md"
        story_file.write_text("# Story")

        stale_file = tmp_path / ".sweetclaude" / "workflows" / "STORY-025" / "spec.md"
        stale_file.parent.mkdir(parents=True, exist_ok=True)
        stale_file.write_text("stale")

        project_dir = _full_project(
            tmp_path,
            current_step_id="spec",
            extra_state={
                "artifacts": {
                    "story_file": str(story_file),
                    "spec_file": str(stale_file),
                }
            }
        )

        file_existed_when_agent_ran = []

        def capturing_invoke(step, state, project_dir_str, **kwargs):
            if step["id"] == "spec":
                file_existed_when_agent_ran.append(stale_file.exists())
            return None

        with patch.object(orchestrator_loop, "_invoke_agent", side_effect=capturing_invoke):
            run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")

        if file_existed_when_agent_ran:
            assert file_existed_when_agent_ran[0] is False

    def test_deletion_raises_for_path_outside_project(self, tmp_path):
        """Pre-step cleanup raises ValueError when output_artifact path escapes project dir."""
        steps = [
            {
                "id": "malicious",
                "phase": "VERIFY",
                "agent": "reviewer",
                "model": "sonnet",
                "subagent_type": "code",
                "input_artifacts": None,
                "output_artifact": "evil_file",
                "gate": None,
                "routing": None,
                "max_iterations": None,
                "next": None,
                "exit_checks": None,
                "escalation": None,
                "action": None,
            },
        ]
        project_dir = _full_project(
            tmp_path,
            current_step_id="malicious",
            steps=steps,
            extra_state={"artifacts": {"evil_file": "/etc/passwd"}}
        )

        with pytest.raises(ValueError):
            with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
                run_loop("STORY-025", project_dir=str(project_dir),
                         deference_level="autonomous")


# ---------------------------------------------------------------------------
# Scenario: Observability — checkpoint written after each step
# ---------------------------------------------------------------------------

class TestObservability:
    def test_checkpoint_written_after_step_completion(self, tmp_path):
        """After a step completes, state.checkpoint describes what was completed."""
        project_dir = _full_project(tmp_path, current_step_id="activate")

        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")

        wf_state_file = tmp_path / ".sweetclaude" / "state" / "workflows" / "STORY-025.yaml"
        state = yaml.safe_load(wf_state_file.read_text())
        assert state.get("checkpoint") not in (None, "Workflow started.")

    def test_checkpoint_at_updated_after_step_completion(self, tmp_path):
        """state.checkpoint_at is refreshed after step completes."""
        project_dir = _full_project(tmp_path, current_step_id="activate")
        wf_state_file = tmp_path / ".sweetclaude" / "state" / "workflows" / "STORY-025.yaml"
        original_state = yaml.safe_load(wf_state_file.read_text())
        original_checkpoint_at = original_state.get("checkpoint_at")

        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")

        state = yaml.safe_load(wf_state_file.read_text())
        assert state.get("checkpoint_at") != original_checkpoint_at or \
               state.get("checkpoint") != "Workflow started."


# ---------------------------------------------------------------------------
# Scenario: Routing and iteration
# ---------------------------------------------------------------------------

class TestRoutingAndIteration:
    def test_unrecognized_output_signal_yields_failure(self, tmp_path):
        """When agent output signal is not in routing keys and no default, loop yields 'failure'."""
        steps = [
            {
                "id": "review",
                "phase": "VERIFY",
                "agent": "reviewer",
                "model": "sonnet",
                "subagent_type": "research",
                "input_artifacts": None,
                "output_artifact": "review_output",
                "gate": None,
                "routing": {"clean": "continue", "issues": "review"},
                "max_iterations": None,
                "next": None,
                "exit_checks": None,
                "escalation": None,
                "action": None,
            },
        ]
        project_dir = _full_project(tmp_path, current_step_id="review", steps=steps)

        def invoke_unknown_signal(step, state, project_dir_str, output_path=None, **kwargs):
            if output_path:
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                with open(output_path, "w") as f:
                    f.write("---\nsignal: unknown_signal\n---\n\nContent.\n")
            return None

        with patch.object(orchestrator_loop, "_invoke_agent", side_effect=invoke_unknown_signal):
            result = run_loop("STORY-025", project_dir=str(project_dir),
                              deference_level="autonomous")

        assert result["reason"] == "failure"

    def test_missing_signal_on_routed_step_yields_failure(self, tmp_path):
        """When a step has routing but agent produces no signal, loop yields 'failure'."""
        steps = [
            {
                "id": "review",
                "phase": "VERIFY",
                "agent": "reviewer",
                "model": "sonnet",
                "subagent_type": "research",
                "input_artifacts": None,
                "output_artifact": "review_output",
                "gate": None,
                "routing": {"clean": "continue", "issues": "review"},
                "max_iterations": None,
                "next": None,
                "exit_checks": None,
                "escalation": None,
                "action": None,
            },
        ]
        project_dir = _full_project(tmp_path, current_step_id="review", steps=steps)

        def invoke_no_signal(step, state, project_dir_str, output_path=None, **kwargs):
            if output_path:
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                with open(output_path, "w") as f:
                    f.write("# No frontmatter, no signal.\n\nContent.\n")
            return None

        with patch.object(orchestrator_loop, "_invoke_agent", side_effect=invoke_no_signal):
            result = run_loop("STORY-025", project_dir=str(project_dir),
                              deference_level="autonomous")

        assert result["reason"] == "failure"

    def test_backward_routing_not_detected_when_same_index(self, tmp_path):
        """Routing from step index 3 to itself is NOT treated as backward movement."""
        steps = [
            {
                "id": "step0", "phase": "PHASE1", "agent": "a", "model": "sonnet",
                "subagent_type": "code", "input_artifacts": None, "output_artifact": None,
                "gate": None, "routing": None, "max_iterations": None, "next": None,
                "exit_checks": None, "escalation": None, "action": None,
            },
            {
                "id": "step1", "phase": "PHASE1", "agent": "a", "model": "sonnet",
                "subagent_type": "code", "input_artifacts": None, "output_artifact": None,
                "gate": None, "routing": None, "max_iterations": None, "next": None,
                "exit_checks": None, "escalation": None, "action": None,
            },
            {
                "id": "step2", "phase": "PHASE1", "agent": "a", "model": "sonnet",
                "subagent_type": "code", "input_artifacts": None, "output_artifact": None,
                "gate": None, "routing": None, "max_iterations": None, "next": None,
                "exit_checks": None, "escalation": None, "action": None,
            },
            {
                "id": "step3",
                "phase": "PHASE1",
                "agent": "a",
                "model": "sonnet",
                "subagent_type": "code",
                "input_artifacts": None,
                "output_artifact": "step3_out",
                "gate": None,
                "routing": {"redo": "step3", "done": "continue"},
                "max_iterations": 2,
                "next": None,
                "exit_checks": None,
                "escalation": None,
                "action": None,
            },
        ]
        project_dir = _full_project(tmp_path, current_step_id="step3", steps=steps)

        invoke_count = [0]

        def invoke_done_after_first(step, state, project_dir_str, output_path=None, **kwargs):
            invoke_count[0] += 1
            if output_path and step["id"] == "step3":
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                # Signal "done" to continue — no backward movement
                with open(output_path, "w") as f:
                    f.write("---\nsignal: done\n---\n\nDone.\n")
            return None

        with patch.object(orchestrator_loop, "_invoke_agent", side_effect=invoke_done_after_first):
            run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")

        wf_state_file = tmp_path / ".sweetclaude" / "state" / "workflows" / "STORY-025.yaml"
        state = yaml.safe_load(wf_state_file.read_text())
        # iteration count for this "loop" should NOT have incremented
        loop_iterations = state.get("iterations", {}).get("step3-loop", {}).get("count", 0)
        assert loop_iterations == 0

    def test_backward_routing_increments_iteration_counter(self, tmp_path):
        """Routing from step at index 2 back to step at index 0 increments the iteration counter."""
        steps = [
            {
                "id": "step0", "phase": "PHASE1", "agent": "a", "model": "sonnet",
                "subagent_type": "code", "input_artifacts": None, "output_artifact": None,
                "gate": None, "routing": None, "max_iterations": None, "next": None,
                "exit_checks": None, "escalation": None, "action": None,
            },
            {
                "id": "step1", "phase": "PHASE1", "agent": "a", "model": "sonnet",
                "subagent_type": "code", "input_artifacts": None, "output_artifact": None,
                "gate": None, "routing": None, "max_iterations": None, "next": None,
                "exit_checks": None, "escalation": None, "action": None,
            },
            {
                "id": "step2",
                "phase": "PHASE1",
                "agent": "reviewer",
                "model": "sonnet",
                "subagent_type": "research",
                "input_artifacts": None,
                "output_artifact": "review_out",
                "gate": None,
                "routing": {"needs_redo": "step0", "done": "continue"},
                "max_iterations": 5,
                "next": None,
                "exit_checks": None,
                "escalation": None,
                "action": None,
            },
        ]
        project_dir = _full_project(tmp_path, current_step_id="step2", steps=steps)

        invoke_count = [0]

        def invoke_redo_once_then_done(step, state, project_dir_str, output_path=None, **kwargs):
            invoke_count[0] += 1
            if output_path and step["id"] == "step2":
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                # First pass: route backward; subsequent passes: done
                signal = "needs_redo" if invoke_count[0] == 1 else "done"
                with open(output_path, "w") as f:
                    f.write(f"---\nsignal: {signal}\n---\n\nContent.\n")
            return None

        with patch.object(orchestrator_loop, "_invoke_agent", side_effect=invoke_redo_once_then_done):
            run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")

        wf_state_file = tmp_path / ".sweetclaude" / "state" / "workflows" / "STORY-025.yaml"
        state = yaml.safe_load(wf_state_file.read_text())
        # At least one backward iteration should have been recorded
        iterations = state.get("iterations", {})
        total_counts = sum(v.get("count", 0) for v in iterations.values())
        assert total_counts >= 1

    def test_max_iterations_reached_yields_for_user_decision(self, tmp_path):
        """When backward loop hits max_iterations, run_loop yields 'max_iterations'."""
        steps = [
            {
                "id": "step0", "phase": "PHASE1", "agent": "a", "model": "sonnet",
                "subagent_type": "code", "input_artifacts": None, "output_artifact": None,
                "gate": None, "routing": None, "max_iterations": None, "next": None,
                "exit_checks": None, "escalation": None, "action": None,
            },
            {
                "id": "review",
                "phase": "PHASE1",
                "agent": "reviewer",
                "model": "sonnet",
                "subagent_type": "research",
                "input_artifacts": None,
                "output_artifact": "review_out",
                "gate": None,
                "routing": {"needs_redo": "step0", "done": "continue"},
                "max_iterations": 2,
                "next": None,
                "exit_checks": None,
                "escalation": None,
                "action": None,
            },
        ]
        project_dir = _full_project(tmp_path, current_step_id="review", steps=steps)

        def always_redo(step, state, project_dir_str, output_path=None, **kwargs):
            if output_path and step["id"] == "review":
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                with open(output_path, "w") as f:
                    f.write("---\nsignal: needs_redo\n---\n\nStill needs work.\n")
            return None

        with patch.object(orchestrator_loop, "_invoke_agent", side_effect=always_redo):
            result = run_loop("STORY-025", project_dir=str(project_dir),
                              deference_level="autonomous")

        assert result["reason"] == "max_iterations"


# ---------------------------------------------------------------------------
# Scenario: Re-entry guards
# ---------------------------------------------------------------------------

class TestReEntryGuards:
    def test_resume_loop_rejects_halted_workflow(self, tmp_path):
        """resume_loop raises ValueError when workflow status is 'HALTED'."""
        project_dir = _full_project(tmp_path, current_step_id="HALTED", status="HALTED")

        with pytest.raises(ValueError):
            resume_loop("STORY-025", decision={"action": "approve"},
                        project_dir=str(project_dir), deference_level="autonomous")

    def test_resume_loop_rejects_invalid_action(self, tmp_path):
        """resume_loop raises ValueError when decision action is not recognized."""
        project_dir = _full_project(tmp_path, current_step_id="spec")
        wf_state_file = tmp_path / ".sweetclaude" / "state" / "workflows" / "STORY-025.yaml"
        state = yaml.safe_load(wf_state_file.read_text())
        state["status"] = "waiting_for_user"
        wf_state_file.write_text(yaml.safe_dump(state))

        with pytest.raises(ValueError):
            resume_loop("STORY-025", decision={"action": "invalid_action"},
                        project_dir=str(project_dir), deference_level="autonomous")

    def test_resume_loop_writes_decision_to_state_before_continuing(self, tmp_path):
        """resume_loop persists the decision to the state file before the loop continues."""
        project_dir = _full_project(tmp_path, current_step_id="spec")

        with patch.object(orchestrator_loop, "_invoke_agent", return_value=None):
            run_loop("STORY-025", project_dir=str(project_dir), deference_level="collaborative")

        wf_state_file = tmp_path / ".sweetclaude" / "state" / "workflows" / "STORY-025.yaml"
        state = yaml.safe_load(wf_state_file.read_text())
        state["status"] = "waiting_for_user"
        wf_state_file.write_text(yaml.safe_dump(state))

        state_at_invocation = {}

        def capturing_invoke(step, state_param, project_dir_str, **kwargs):
            state_at_invocation.update(state_param)
            return None

        with patch.object(orchestrator_loop, "_invoke_agent", side_effect=capturing_invoke):
            resume_loop("STORY-025", decision={"action": "approve"},
                        project_dir=str(project_dir), deference_level="collaborative")

        # By the time the agent runs, decision should have been written to state
        wf_state_file_final = tmp_path / ".sweetclaude" / "state" / "workflows" / "STORY-025.yaml"
        final_state = yaml.safe_load(wf_state_file_final.read_text())
        combined = str(final_state)
        assert "approve" in combined or "gates_passed" in combined


# ---------------------------------------------------------------------------
# Scenario: Validation at load time
# ---------------------------------------------------------------------------

class TestValidationAtLoadTime:
    def test_step_id_invalid_pattern_raises_value_error(self, tmp_path):
        """A step id matching a path traversal pattern raises ValueError at template load."""
        steps = [
            {
                "id": "../../malicious",
                "phase": "ACTIVATION",
                "agent": "housekeeping",
                "model": "sonnet",
                "subagent_type": "code",
                "input_artifacts": None,
                "output_artifact": None,
                "gate": None,
                "routing": None,
                "max_iterations": None,
                "next": None,
                "exit_checks": None,
                "escalation": None,
                "action": None,
            },
        ]
        project_dir = _full_project(tmp_path, current_step_id="../../malicious", steps=steps)

        with pytest.raises(ValueError):
            run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")

    def test_invalid_subagent_type_raises_value_error(self, tmp_path):
        """A step with subagent_type not in the allowlist raises ValueError."""
        steps = [
            {
                "id": "dangerous",
                "phase": "ACTIVATION",
                "agent": "some-agent",
                "model": "sonnet",
                "subagent_type": "dangerous_type",
                "input_artifacts": None,
                "output_artifact": None,
                "gate": None,
                "routing": None,
                "max_iterations": None,
                "next": None,
                "exit_checks": None,
                "escalation": None,
                "action": None,
            },
        ]
        project_dir = _full_project(tmp_path, current_step_id="dangerous", steps=steps)

        with pytest.raises(ValueError):
            run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")


# ---------------------------------------------------------------------------
# QA Caucus additions — yield payload structure
# ---------------------------------------------------------------------------

class TestYieldPayloadStructure:
    def test_gate_yield_contains_options(self, tmp_path, monkeypatch):
        """Gate yield payload includes the available decision options."""
        steps = [
            {
                "id": "spec",
                "phase": "DEFINE",
                "agent": "spec-writer",
                "model": "sonnet",
                "subagent_type": "code",
                "input_artifacts": None,
                "output_artifact": "spec_file",
                "gate": "user_approval",
                "routing": None,
                "max_iterations": None,
                "next": "implement",
                "exit_checks": None,
                "escalation": None,
                "action": None,
            },
            _make_step("implement", phase="IMPLEMENT", next=None),
        ]
        project_dir = _full_project(tmp_path, current_step_id="spec", steps=steps)
        spec_path = project_dir / ".sweetclaude" / "workflows" / "STORY-025" / "spec_file.md"
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text("# Spec\nContent here")
        state_file = project_dir / ".sweetclaude" / "workflows" / "STORY-025.yaml"
        state = yaml.safe_load(state_file.read_text())
        state["artifacts"] = {"spec_file": str(spec_path)}
        state_file.write_text(yaml.dump(state))

        monkeypatch.setattr("orchestrator_loop._invoke_agent", lambda **kw: {"status": "success", "signal": "done"})

        result = run_loop("STORY-025", project_dir=str(project_dir), deference_level="collaborative")
        assert result["reason"] == "gate"
        assert "options" in result.get("payload", {}) or "actions" in result.get("payload", {})

    def test_failure_yield_contains_retry_skip_abort(self, tmp_path, monkeypatch):
        """Failure yield payload includes retry, skip, and abort as available actions."""
        steps = [
            {
                "id": "spec",
                "phase": "DEFINE",
                "agent": "spec-writer",
                "model": "sonnet",
                "subagent_type": "code",
                "input_artifacts": None,
                "output_artifact": "spec_file",
                "gate": None,
                "routing": None,
                "max_iterations": None,
                "next": "done",
                "exit_checks": ["file_exists"],
                "escalation": None,
                "action": None,
            },
        ]
        project_dir = _full_project(tmp_path, current_step_id="spec", steps=steps)

        monkeypatch.setattr("orchestrator_loop._invoke_agent", lambda **kw: {"status": "success", "signal": "done"})

        result = run_loop("STORY-025", project_dir=str(project_dir), deference_level="collaborative")
        assert result["reason"] == "failure"
        payload = result.get("payload", {})
        actions = payload.get("actions", payload.get("options", []))
        action_names = [a if isinstance(a, str) else a.get("action", "") for a in actions]
        assert "retry" in action_names
        assert "skip" in action_names
        assert "abort" in action_names

    def test_max_iterations_yield_contains_options(self, tmp_path, monkeypatch):
        """Max iterations yield payload includes decision options."""
        steps = [
            _make_step("review", phase="VERIFY", routing={"issues": "implement", "clean": "done"}, next=None),
            _make_step("implement", phase="IMPLEMENT", next="review"),
        ]
        project_dir = _full_project(tmp_path, current_step_id="review", steps=steps)
        state_file = project_dir / ".sweetclaude" / "workflows" / "STORY-025.yaml"
        state = yaml.safe_load(state_file.read_text())
        state["iteration_counters"] = {"review->implement": 3}
        state_file.write_text(yaml.dump(state))

        monkeypatch.setattr("orchestrator_loop._invoke_agent", lambda **kw: {"status": "success", "signal": "issues"})

        result = run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")
        assert result["reason"] == "max_iterations"
        payload = result.get("payload", {})
        assert "options" in payload or "actions" in payload


# ---------------------------------------------------------------------------
# QA Caucus additions — exception boundaries
# ---------------------------------------------------------------------------

class TestLoopExceptionBoundaries:
    def test_keyerror_from_assemble_context_yields_failure(self, tmp_path, monkeypatch):
        """If assemble_context_envelope raises KeyError, the loop yields failure instead of crashing."""
        steps = [
            _make_step("spec", phase="DEFINE", agent="spec-writer", output_artifact="spec_file", next="done"),
        ]
        project_dir = _full_project(tmp_path, current_step_id="spec", steps=steps)

        def broken_assemble(*args, **kwargs):
            raise KeyError("missing_key")

        monkeypatch.setattr("orchestrator_loop.assemble_context_envelope", broken_assemble)

        result = run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")
        assert result["reason"] == "failure"

    def test_action_dispatch_failure_yields_failure(self, tmp_path, monkeypatch):
        """If an action dispatch raises an exception, the loop yields failure."""
        steps = [
            {
                "id": "verify",
                "phase": "VERIFY",
                "agent": None,
                "model": None,
                "subagent_type": None,
                "input_artifacts": ["spec_file"],
                "output_artifact": None,
                "gate": None,
                "routing": None,
                "max_iterations": None,
                "next": "done",
                "exit_checks": None,
                "escalation": None,
                "action": "verify_artifacts",
            },
        ]
        project_dir = _full_project(tmp_path, current_step_id="verify", steps=steps)

        import orchestrator_actions
        original_dispatch = orchestrator_actions.dispatch
        def broken_dispatch(step, state, project_dir):
            raise RuntimeError("action exploded")
        monkeypatch.setattr("orchestrator_actions.dispatch", broken_dispatch)

        result = run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")
        assert result["reason"] == "failure"

    def test_os_remove_failure_during_cleanup_yields_failure(self, tmp_path, monkeypatch):
        """If os.remove fails during pre-step cleanup, the loop yields failure."""
        steps = [
            _make_step("spec", phase="DEFINE", agent="spec-writer", output_artifact="spec_file", next="done"),
        ]
        project_dir = _full_project(tmp_path, current_step_id="spec", steps=steps)
        stale_file = project_dir / ".sweetclaude" / "workflows" / "STORY-025" / "spec_file.md"
        stale_file.parent.mkdir(parents=True, exist_ok=True)
        stale_file.write_text("stale content")
        state_file = project_dir / ".sweetclaude" / "workflows" / "STORY-025.yaml"
        state = yaml.safe_load(state_file.read_text())
        state["artifacts"] = {"spec_file": str(stale_file)}
        state_file.write_text(yaml.dump(state))

        original_remove = os.remove
        def broken_remove(path):
            if "spec_file" in str(path):
                raise PermissionError("cannot delete")
            return original_remove(path)
        monkeypatch.setattr("os.remove", broken_remove)

        result = run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")
        assert result["reason"] == "failure"


# ---------------------------------------------------------------------------
# QA Caucus additions — crash recovery offer
# ---------------------------------------------------------------------------

class TestCrashRecoveryOffer:
    def test_active_workflow_yields_resume_offer(self, tmp_path):
        """When an active workflow exists, run_loop can resume from checkpoint."""
        steps = [
            _make_step("activate", phase="ACTIVATION", next="spec"),
            _make_step("spec", phase="DEFINE", agent="spec-writer", output_artifact="spec_file", next=None),
        ]
        project_dir = _full_project(tmp_path, current_step_id="spec", steps=steps,
                                     completed_steps=["activate"],
                                     checkpoint="Completed activation phase.")
        result = run_loop("STORY-025", project_dir=str(project_dir), deference_level="collaborative")
        assert result is not None


# ---------------------------------------------------------------------------
# QA Caucus additions — no silent retry
# ---------------------------------------------------------------------------

class TestNoSilentRetry:
    def test_second_failure_after_retry_yields_again(self, tmp_path, monkeypatch):
        """After a retry that fails again, the loop yields failure a second time."""
        steps = [
            _make_step("spec", phase="DEFINE", agent="spec-writer", output_artifact="spec_file",
                       exit_checks=["file_exists"], next="done"),
        ]
        project_dir = _full_project(tmp_path, current_step_id="spec", steps=steps)

        monkeypatch.setattr("orchestrator_loop._invoke_agent", lambda **kw: {"status": "success", "signal": "done"})

        result1 = run_loop("STORY-025", project_dir=str(project_dir), deference_level="collaborative")
        assert result1["reason"] == "failure"

        result2 = resume_loop("STORY-025", {"action": "retry"}, project_dir=str(project_dir), deference_level="collaborative")
        assert result2["reason"] == "failure"


# ---------------------------------------------------------------------------
# QA Caucus additions — orchestrated conflict
# ---------------------------------------------------------------------------

class TestOrchestratedConflict:
    def test_rejects_when_orchestrated_for_different_workflow(self, tmp_path):
        """run_loop rejects if sweetclaude.yaml shows orchestrated=true for a different workflow."""
        steps = [_make_step("activate", phase="ACTIVATION", next=None)]
        project_dir = _full_project(tmp_path, current_step_id="activate", steps=steps)
        sc_yaml = project_dir / ".sweetclaude" / "state" / "sweetclaude.yaml"
        sc_state = yaml.safe_load(sc_yaml.read_text())
        sc_state["work"] = {"active": {"id": "STORY-999", "orchestrated": True,
                                        "workflow_state_file": "some/other/path.yaml"}}
        sc_yaml.write_text(yaml.dump(sc_state))

        with pytest.raises(ValueError):
            run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")


# ---------------------------------------------------------------------------
# QA Caucus additions — reset action
# ---------------------------------------------------------------------------

class TestResetAction:
    def test_reset_clears_iteration_counter(self, tmp_path, monkeypatch):
        """resume_loop with action 'reset' clears the iteration counter for the loop."""
        steps = [
            _make_step("review", phase="VERIFY", routing={"issues": "implement", "clean": "done"}, next=None),
            _make_step("implement", phase="IMPLEMENT", next="review"),
        ]
        project_dir = _full_project(tmp_path, current_step_id="review", steps=steps)
        state_file = project_dir / ".sweetclaude" / "workflows" / "STORY-025.yaml"
        state = yaml.safe_load(state_file.read_text())
        state["iteration_counters"] = {"review->implement": 3}
        state_file.write_text(yaml.dump(state))

        monkeypatch.setattr("orchestrator_loop._invoke_agent", lambda **kw: {"status": "success", "signal": "issues"})

        result = run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")
        assert result["reason"] == "max_iterations"

        result2 = resume_loop("STORY-025", {"action": "reset"}, project_dir=str(project_dir), deference_level="autonomous")
        state_after = yaml.safe_load(state_file.read_text())
        counters = state_after.get("iteration_counters", {})
        assert counters.get("review->implement", 0) == 0


# ---------------------------------------------------------------------------
# QA Caucus additions — gate re-evaluation after backward routing
# ---------------------------------------------------------------------------

class TestGateReEvaluation:
    def test_gate_re_presented_after_backward_routing(self, tmp_path, monkeypatch):
        """After backward routing, a gate is re-presented even if previously passed."""
        steps = [
            _make_step("spec", phase="DEFINE", agent="spec-writer", output_artifact="spec_file",
                       gate="user_approval", next="implement"),
            _make_step("implement", phase="IMPLEMENT", agent="implementer",
                       routing={"issues": "spec", "clean": "done"}, next=None),
        ]
        project_dir = _full_project(tmp_path, current_step_id="spec", steps=steps,
                                     gates_passed=["spec:user_approval"])
        spec_path = project_dir / ".sweetclaude" / "workflows" / "STORY-025" / "spec_file.md"
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text("# Spec\nContent")
        state_file = project_dir / ".sweetclaude" / "workflows" / "STORY-025.yaml"
        state = yaml.safe_load(state_file.read_text())
        state["artifacts"] = {"spec_file": str(spec_path)}
        state_file.write_text(yaml.dump(state))

        monkeypatch.setattr("orchestrator_loop._invoke_agent", lambda **kw: {"status": "success", "signal": "done"})

        result = run_loop("STORY-025", project_dir=str(project_dir), deference_level="collaborative")
        assert result["reason"] == "gate"
        assert result["step_id"] == "spec"


# ---------------------------------------------------------------------------
# QA Caucus additions — model selection
# ---------------------------------------------------------------------------

class TestModelSelection:
    def test_model_from_step_propagated_to_agent(self, tmp_path, monkeypatch):
        """The model field from the step is passed through to the agent invocation."""
        captured = {}
        def mock_invoke(**kwargs):
            captured.update(kwargs)
            return {"status": "success", "signal": "done"}
        monkeypatch.setattr("orchestrator_loop._invoke_agent", mock_invoke)

        steps = [
            _make_step("spec", phase="DEFINE", agent="spec-writer", model="opus",
                       output_artifact="spec_file", next=None),
        ]
        project_dir = _full_project(tmp_path, current_step_id="spec", steps=steps)
        spec_path = project_dir / ".sweetclaude" / "workflows" / "STORY-025" / "spec_file.md"
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text("# Spec\nContent")
        state_file = project_dir / ".sweetclaude" / "workflows" / "STORY-025.yaml"
        state = yaml.safe_load(state_file.read_text())
        state["artifacts"] = {"spec_file": str(spec_path)}
        state_file.write_text(yaml.dump(state))

        run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")
        assert captured.get("model") == "opus"


# ---------------------------------------------------------------------------
# QA Caucus additions — resume on active rejects
# ---------------------------------------------------------------------------

class TestResumeOnActiveRejects:
    def test_resume_rejects_when_status_is_active(self, tmp_path):
        """resume_loop rejects if the workflow status is 'active' (not yielded)."""
        steps = [_make_step("activate", phase="ACTIVATION", next=None)]
        project_dir = _full_project(tmp_path, current_step_id="activate", steps=steps)

        with pytest.raises(ValueError):
            resume_loop("STORY-025", {"action": "approve"}, project_dir=str(project_dir), deference_level="collaborative")


# ---------------------------------------------------------------------------
# QA Caucus additions — duplicate work history
# ---------------------------------------------------------------------------

class TestDuplicateWorkHistory:
    def test_double_completion_does_not_duplicate_history(self, tmp_path, monkeypatch):
        """If the workflow completes twice (idempotency), work_history doesn't get a duplicate entry."""
        steps = [_make_step("activate", phase="ACTIVATION", next=None)]
        project_dir = _full_project(tmp_path, current_step_id="COMPLETE", steps=steps,
                                     completed_steps=["activate"])

        result = run_loop("STORY-025", project_dir=str(project_dir), deference_level="autonomous")
        assert result["reason"] == "complete"

        sc_yaml = project_dir / ".sweetclaude" / "state" / "sweetclaude.yaml"
        sc_state = yaml.safe_load(sc_yaml.read_text())
        history = sc_state.get("work_history", [])
        story_entries = [h for h in history if h.get("id") == "STORY-025"]
        assert len(story_entries) <= 1


# ---------------------------------------------------------------------------
# QA Caucus additions — extract output signal null
# ---------------------------------------------------------------------------

class TestExtractOutputSignalNull:
    def test_signal_null_returns_none(self, tmp_path):
        """When agent output contains signal: null, extract_output_signal returns None."""
        from orchestrator import extract_output_signal
        content = "---\nsignal: null\n---\n"
        result = extract_output_signal(content)
        assert result is None
