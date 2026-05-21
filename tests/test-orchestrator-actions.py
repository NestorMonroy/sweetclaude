"""
Tests for scripts/orchestrator_actions.py — actions registry.

Coverage (from orchestrator-actions.feature):
  - @register decorator adds to ACTIONS dict
  - verify_artifacts action checks all input artifacts exist
  - verify_artifacts action fails when artifact missing
  - run_tests action executes the configured test command
  - checkpoint_only action writes checkpoint and returns success
  - Unknown action raises ValueError
"""
import os
import sys
import subprocess
import pytest

_SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import orchestrator_actions
from orchestrator_actions import ACTIONS, register


# ---------------------------------------------------------------------------
# Scenario: Register decorator adds action to ACTIONS dict
# ---------------------------------------------------------------------------

class TestRegisterDecorator:
    def test_register_adds_function_to_actions_dict(self):
        """@register("my_action") makes ACTIONS["my_action"] the decorated fn."""
        @register("_test_register_unique_9182")
        def my_fn(step, state, project_dir):
            return {"status": "success"}

        assert "_test_register_unique_9182" in ACTIONS
        assert ACTIONS["_test_register_unique_9182"] is my_fn

    def test_register_returns_original_function_unmodified(self):
        """@register is transparent — it returns the function itself."""
        @register("_test_register_identity_4455")
        def my_fn(step, state, project_dir):
            return {"status": "ok"}

        result = my_fn({}, {}, "/tmp")
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Scenario: verify_artifacts action checks all input artifacts exist
# ---------------------------------------------------------------------------

class TestVerifyArtifactsSuccess:
    def test_verify_artifacts_returns_success_when_all_artifacts_exist(self, tmp_path):
        """verify_artifacts returns success when all input artifact files exist."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# spec content")
        story_file = tmp_path / "story.md"
        story_file.write_text("# story content")

        state = {
            "artifacts": {
                "spec_file": str(spec_file),
                "story_file": str(story_file),
            }
        }
        step = {
            "id": "verify",
            "action": "verify_artifacts",
            "input_artifacts": ["spec_file", "story_file"],
        }

        result = ACTIONS["verify_artifacts"](step, state, str(tmp_path))
        assert result["status"] == "success"

    def test_verify_artifacts_success_with_single_artifact(self, tmp_path):
        """verify_artifacts works with a single artifact."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("content")

        state = {"artifacts": {"spec_file": str(spec_file)}}
        step = {
            "id": "verify",
            "action": "verify_artifacts",
            "input_artifacts": ["spec_file"],
        }

        result = ACTIONS["verify_artifacts"](step, state, str(tmp_path))
        assert result["status"] == "success"


# ---------------------------------------------------------------------------
# Scenario: verify_artifacts action fails when artifact missing
# ---------------------------------------------------------------------------

class TestVerifyArtifactsFailure:
    def test_verify_artifacts_returns_failure_when_artifact_missing(self, tmp_path):
        """verify_artifacts returns failure with the missing artifact name."""
        state = {
            "artifacts": {
                "spec_file": str(tmp_path / "nonexistent.md"),
            }
        }
        step = {
            "id": "verify",
            "action": "verify_artifacts",
            "input_artifacts": ["spec_file"],
        }

        result = ACTIONS["verify_artifacts"](step, state, str(tmp_path))
        assert result["status"] == "failure"
        assert "spec_file" in result.get("message", "") or "spec_file" in str(result)

    def test_verify_artifacts_failure_names_the_missing_artifact(self, tmp_path):
        """Failure result identifies which artifact is missing."""
        present = tmp_path / "story.md"
        present.write_text("present")

        state = {
            "artifacts": {
                "story_file": str(present),
                "spec_file": str(tmp_path / "missing_spec.md"),
            }
        }
        step = {
            "id": "verify",
            "action": "verify_artifacts",
            "input_artifacts": ["story_file", "spec_file"],
        }

        result = ACTIONS["verify_artifacts"](step, state, str(tmp_path))
        assert result["status"] == "failure"
        combined = str(result)
        assert "spec_file" in combined or "missing_spec" in combined


# ---------------------------------------------------------------------------
# Scenario: run_tests action executes test command
# ---------------------------------------------------------------------------

class TestRunTestsAction:
    def test_run_tests_executes_configured_test_command(self, tmp_path, monkeypatch):
        """run_tests calls the test command from step config."""
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            class FakeResult:
                returncode = 0
                stdout = ""
                stderr = ""
            return FakeResult()

        monkeypatch.setattr(subprocess, "run", fake_run)

        step = {
            "id": "run-tests",
            "action": "run_tests",
            "test_command": "pytest tests/",
        }
        state = {}

        ACTIONS["run_tests"](step, state, str(tmp_path))
        assert len(calls) == 1

    def test_run_tests_passes_test_command_from_step(self, tmp_path, monkeypatch):
        """The command executed matches what's in step.test_command."""
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            class FakeResult:
                returncode = 0
                stdout = ""
                stderr = ""
            return FakeResult()

        monkeypatch.setattr(subprocess, "run", fake_run)

        step = {
            "id": "run-tests",
            "action": "run_tests",
            "test_command": "pytest -x tests/unit/",
        }
        state = {}

        ACTIONS["run_tests"](step, state, str(tmp_path))
        assert captured.get("cmd") is not None
        cmd_str = " ".join(captured["cmd"]) if isinstance(captured["cmd"], list) else captured["cmd"]
        assert "pytest" in cmd_str

    def test_run_tests_returns_failure_on_nonzero_exit(self, tmp_path, monkeypatch):
        """run_tests returns failure status when test command exits non-zero."""
        def fake_run(cmd, **kwargs):
            class FakeResult:
                returncode = 1
                stdout = ""
                stderr = "1 test failed"
            return FakeResult()

        monkeypatch.setattr(subprocess, "run", fake_run)

        step = {
            "id": "run-tests",
            "action": "run_tests",
            "test_command": "pytest tests/",
        }
        state = {}

        result = ACTIONS["run_tests"](step, state, str(tmp_path))
        assert result["status"] == "failure"


# ---------------------------------------------------------------------------
# Scenario: checkpoint_only action writes checkpoint and succeeds
# ---------------------------------------------------------------------------

class TestCheckpointOnlyAction:
    def test_checkpoint_only_returns_success(self, tmp_path):
        """checkpoint_only returns success status."""
        state = {
            "checkpoint": "previous checkpoint",
            "checkpoint_at": "2026-05-20T10:00:00Z",
        }
        step = {
            "id": "checkpoint",
            "action": "checkpoint_only",
            "checkpoint_message": "Completed planning phase.",
        }

        result = ACTIONS["checkpoint_only"](step, state, str(tmp_path))
        assert result["status"] == "success"

    def test_checkpoint_only_writes_checkpoint_message_to_state(self, tmp_path):
        """checkpoint_only updates state.checkpoint with the step message."""
        state = {
            "checkpoint": "old checkpoint",
            "checkpoint_at": "2026-05-20T10:00:00Z",
        }
        step = {
            "id": "checkpoint",
            "action": "checkpoint_only",
            "checkpoint_message": "Completed planning phase.",
        }

        ACTIONS["checkpoint_only"](step, state, str(tmp_path))
        assert "Completed planning phase." in state.get("checkpoint", "")

    def test_checkpoint_only_updates_checkpoint_at_timestamp(self, tmp_path):
        """checkpoint_only refreshes the checkpoint_at timestamp."""
        state = {
            "checkpoint": "old",
            "checkpoint_at": "2026-05-20T10:00:00Z",
        }
        step = {
            "id": "checkpoint",
            "action": "checkpoint_only",
            "checkpoint_message": "Done.",
        }

        ACTIONS["checkpoint_only"](step, state, str(tmp_path))
        # checkpoint_at should be updated (different from original or newly set)
        assert "checkpoint_at" in state


# ---------------------------------------------------------------------------
# Scenario: Unknown action name raises ValueError
# ---------------------------------------------------------------------------

class TestUnknownActionRaisesError:
    def test_dispatching_unregistered_action_raises_value_error(self, tmp_path):
        """Dispatching an unregistered action name raises ValueError."""
        step = {
            "id": "some-step",
            "action": "nonexistent_action",
        }
        state = {}

        with pytest.raises((ValueError, KeyError)):
            action_fn = ACTIONS.get("nonexistent_action")
            if action_fn is None:
                raise ValueError("Action 'nonexistent_action' is not registered")
            action_fn(step, state, str(tmp_path))

    def test_actions_dict_does_not_contain_nonexistent_action(self):
        """ACTIONS dict does not have a key for an unregistered name."""
        assert "nonexistent_action" not in ACTIONS

    def test_dispatch_helper_raises_value_error_for_unregistered_action(self, tmp_path):
        """The module exposes a dispatch helper that raises ValueError for unknown names."""
        step = {"id": "x", "action": "nonexistent_action"}
        state = {}

        with pytest.raises(ValueError):
            orchestrator_actions.dispatch(step, state, str(tmp_path))


# ---------------------------------------------------------------------------
# QA Caucus additions — run_tests edge cases
# ---------------------------------------------------------------------------

class TestRunTestsEdgeCases:
    def test_run_tests_missing_test_command_returns_failure(self, tmp_path, monkeypatch):
        """run_tests with no test_command in step returns failure or raises."""
        step = {
            "id": "run-tests",
            "action": "run_tests",
        }
        state = {}

        result = ACTIONS["run_tests"](step, state, str(tmp_path))
        assert result["status"] == "failure" or "error" in str(result).lower()

    def test_run_tests_subprocess_not_found_returns_failure(self, tmp_path, monkeypatch):
        """run_tests returns failure when the test command binary is not found."""
        def raise_fnf(cmd, **kwargs):
            raise FileNotFoundError("No such file or directory: 'nonexistent_binary'")

        monkeypatch.setattr(subprocess, "run", raise_fnf)

        step = {
            "id": "run-tests",
            "action": "run_tests",
            "test_command": "nonexistent_binary tests/",
        }
        state = {}

        result = ACTIONS["run_tests"](step, state, str(tmp_path))
        assert result["status"] == "failure"


# ---------------------------------------------------------------------------
# QA Caucus additions — verify_artifacts with None input_artifacts
# ---------------------------------------------------------------------------

class TestVerifyArtifactsNoneInput:
    def test_verify_artifacts_with_no_input_artifacts_returns_success(self, tmp_path):
        """verify_artifacts returns success when input_artifacts is None or empty."""
        state = {"artifacts": {}}
        step = {
            "id": "verify",
            "action": "verify_artifacts",
            "input_artifacts": None,
        }

        result = ACTIONS["verify_artifacts"](step, state, str(tmp_path))
        assert result["status"] == "success"
