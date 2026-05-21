import os
import shlex
import subprocess
from datetime import datetime, timezone

_MAX_OUTPUT_LEN = 2048
_DEFAULT_TIMEOUT = 300

ACTIONS = {}


def register(name):
    def decorator(fn):
        ACTIONS[name] = fn
        return fn
    return decorator


def dispatch(step, state, project_dir):
    action_name = step.get("action")
    if action_name not in ACTIONS:
        raise ValueError("Action '{}' is not registered".format(action_name))
    return ACTIONS[action_name](step, state, project_dir)


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@register("verify_artifacts")
def verify_artifacts(step, state, project_dir):
    input_artifacts = step.get("input_artifacts")
    if not input_artifacts:
        return {"status": "success"}
    artifacts = state.get("artifacts", {})
    for key in input_artifacts:
        path = artifacts.get(key)
        if path is None or not os.path.exists(path):
            return {"status": "failure", "message": "Artifact '{}' is missing or not found".format(key)}
    return {"status": "success"}


@register("run_tests")
def run_tests(step, state, project_dir):
    test_command = step.get("test_command")
    if not test_command:
        return {"status": "failure", "message": "No test_command configured for step"}
    cmd = shlex.split(test_command)
    timeout = step.get("timeout", _DEFAULT_TIMEOUT)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=project_dir, timeout=timeout)
    except FileNotFoundError as e:
        return {"status": "failure", "message": str(e)}
    except subprocess.TimeoutExpired:
        return {"status": "failure", "message": "Test command timed out after {}s".format(timeout)}
    if result.returncode != 0:
        return {"status": "failure", "returncode": result.returncode,
                "stdout": result.stdout[:_MAX_OUTPUT_LEN], "stderr": result.stderr[:_MAX_OUTPUT_LEN]}
    return {"status": "success", "stdout": result.stdout[:_MAX_OUTPUT_LEN]}


@register("checkpoint_only")
def checkpoint_only(step, state, project_dir):
    message = step.get("checkpoint_message", "")
    state["checkpoint"] = message
    state["checkpoint_at"] = _now_iso()
    return {"status": "success"}
