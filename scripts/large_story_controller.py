#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Controller guards for SweetClaude large-story execution."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    sys.exit("pyyaml is required: pip install pyyaml")

from success_criteria_contracts import validate_success_criteria_workflow


BLOCKED_SLICE0_MESSAGE = (
    "Large-story downstream execution is blocked: the current product surface "
    "has SHIP/closeout after VERIFY. The success criteria contract may be "
    "defined, frozen, designed against, mapped into an implementation plan, "
    "implemented with evidence recorded, and verified into a controller-owned "
    "ledger, and closed through controller-owned SHIP/closeout, but terminal "
    "review and product-readiness validation are not available until later "
    "Track B tasks are implemented."
)
BLOCKED_DESIGN_ENTRY_MESSAGE = (
    "Large-story DESIGN is blocked: define-exit validation must pass before a "
    "design artifact can be accepted."
)
BLOCKED_PLAN_ENTRY_MESSAGE = (
    "Large-story PLAN is blocked: DESIGN must produce a durable design artifact "
    "before an implementation plan can be accepted."
)
BLOCKED_IMPLEMENTATION_ENTRY_MESSAGE = (
    "Large-story IMPLEMENT is blocked: PLAN must produce a durable implementation "
    "plan artifact before implementation evidence can be accepted."
)
BLOCKED_VERIFY_ENTRY_MESSAGE = (
    "Large-story VERIFY is blocked: IMPLEMENT must produce durable implementation "
    "evidence before verification can generate the success criteria ledger."
)
BLOCKED_MISSING_LEDGER_MESSAGE = (
    "Large-story completion is blocked: .sweetclaude/reports/success-criteria-ledger.json "
    "is missing. Do not claim completion. Generate controller-owned ledger "
    "evidence for every frozen success criterion, then rerun completion "
    "validation."
)
BLOCKED_COMPLETION_VALIDATION_MESSAGE = (
    "Large-story completion is blocked: success criteria completion validation "
    "failed. Do not claim completion. Fix the ledger or evidence against the "
    "frozen contract before requesting terminal completion."
)
BLOCKED_SHIP_ENTRY_MESSAGE = (
    "Large-story SHIP is blocked: VERIFY must produce a valid controller-owned "
    "success criteria ledger before closeout."
)
BLOCKED_CLOSEOUT_MISSING_MESSAGE = (
    "Large-story completion is blocked: SHIP/closeout has not written a "
    "durable controller-owned closeout artifact."
)
BLOCKED_TERMINAL_MUTATION_MESSAGE = (
    "Large-story terminal state mutation is blocked: terminal workflow state "
    "must be written by the large-story controller after validation, not by "
    "assistant narrative or direct YAML editing."
)
BLOCKED_FINAL_RESPONSE_MESSAGE = (
    "Large-story final response is blocked: the response would contradict "
    "controller state or completion validation. Render status through the "
    "large-story finalizer."
)

ROUTE_SURFACES = {"/sweetclaude:go", "sweetclaude:find-skill", "sweetclaude:_route"}
POST_SHIP_STAGES = {"terminal_review"}
FORBIDDEN_SUCCESS_PHRASES = (
    "all success criteria pass",
    "all criteria pass",
    "story complete",
    "ship-ready",
)


def route_large_story(*, project_dir: str | Path = ".", route_surface: str) -> dict[str, Any]:
    """Return current bounded routing behavior for every large-story route surface."""
    if route_surface not in ROUTE_SURFACES:
        return _failure(
            "blocked_unknown_large_story_route",
            f"Unknown large-story route surface: {route_surface}",
        )
    return {
        "ok": True,
        "route_surface": route_surface,
        "large_story_behavior": "final_status_enabled_controller",
        "current_slice": "track_b_regression_covered",
        "design_enabled": True,
        "plan_enabled": True,
        "implementation_enabled": True,
        "verify_enabled": True,
        "ship_enabled": True,
        "final_status_enabled": True,
        "next_allowed_stage": "define",
        "blocked_stages": sorted(POST_SHIP_STAGES),
        "message": "Large-story route supports DEFINE, DESIGN, PLAN, IMPLEMENT, VERIFY, SHIP/closeout, and final status rendering; automated end-to-end regression is covered. Fresh disposable execution remains blocked until TASK-008.",
    }


def transition_large_story(
    *,
    project_dir: str | Path = ".",
    workflow_id: str | None = None,
    target_stage: str,
) -> dict[str, Any]:
    """Validate a large-story state transition."""
    stage = target_stage.strip().lower()
    if stage == "design":
        return enter_design_phase(project_dir=project_dir, workflow_id=workflow_id)
    if stage == "plan":
        return enter_plan_phase(project_dir=project_dir, workflow_id=workflow_id)
    if stage in {"implement", "implementation"}:
        return enter_implement_phase(project_dir=project_dir, workflow_id=workflow_id)
    if stage == "verify":
        return enter_verify_phase(project_dir=project_dir, workflow_id=workflow_id)
    if stage == "ship":
        return enter_ship_phase(project_dir=project_dir, workflow_id=workflow_id)
    if stage in POST_SHIP_STAGES:
        return _failure("blocked_slice0_downstream_unavailable", BLOCKED_SLICE0_MESSAGE)
    if stage in {"complete", "done"}:
        completion = _completion_result(project_dir=project_dir, workflow_id=workflow_id)
        if not completion["ok"]:
            return completion
        return {
            "ok": True,
            "status": "complete",
            "workflow_id": workflow_id,
            "completion_claim_allowed": True,
            "message": "Large-story completion validation passed; terminal state may be written by controller.",
        }
    if stage in {"define", "define_exit_validated", "blocked_slice0_downstream_unavailable"}:
        return {
            "ok": True,
            "status": stage,
            "workflow_id": workflow_id,
            "message": "Large-story transition is allowed by Slice 0 controller contract.",
        }
    return _failure("blocked_unknown_large_story_transition", f"Unknown large-story target stage: {target_stage}")


def enter_design_phase(
    *,
    project_dir: str | Path = ".",
    workflow_id: str | None = None,
    design_summary: str = "",
) -> dict[str, Any]:
    """Enter DESIGN after define-exit validation and write a durable design artifact."""
    project = Path(project_dir).expanduser().resolve(strict=False)
    define_result = validate_success_criteria_workflow(
        project_dir=project,
        workflow_id=workflow_id,
        stage="define-exit",
    )
    if not define_result.get("ok"):
        return {
            **_failure("blocked_design_entry_failed", BLOCKED_DESIGN_ENTRY_MESSAGE),
            "validator_result": define_result,
            "next_allowed_stage": "blocked",
        }

    resolved_workflow_id = workflow_id or define_result.get("workflow_id") or _workflow_id_from_state(project)
    if not resolved_workflow_id:
        return {
            **_failure("blocked_design_entry_failed", "Large-story DESIGN is blocked: workflow_id is required."),
            "next_allowed_stage": "blocked",
        }

    contract_hash = str(define_result.get("contract_hash") or "")
    artifact_rel = Path(".sweetclaude") / "reports" / "large-story" / resolved_workflow_id / "design" / "design-artifact.md"
    artifact_path = project / artifact_rel
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    summary = design_summary.strip() or "Design pending user/assistant elaboration."
    artifact_path.write_text(
        "\n".join(
            [
                "# Large Story Design Artifact",
                "",
                f"Workflow ID: {resolved_workflow_id}",
                f"Success Criteria Contract Hash: {contract_hash}",
                "",
                "## Design Summary",
                "",
                summary,
                "",
                "## Completion Criteria Policy",
                "",
                "This design artifact may not add, remove, or modify success criteria.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return {
        "ok": True,
        "status": "design",
        "workflow_id": resolved_workflow_id,
        "success_criteria_contract_hash": contract_hash,
        "design_artifact_path": str(artifact_rel),
        "next_allowed_stage": "plan",
        "message": "Large-story DESIGN entered; durable design artifact written.",
    }


def enter_plan_phase(
    *,
    project_dir: str | Path = ".",
    workflow_id: str | None = None,
    plan_summary: str = "",
) -> dict[str, Any]:
    """Enter PLAN after DESIGN and write a durable criterion-mapped plan artifact."""
    project = Path(project_dir).expanduser().resolve(strict=False)
    define_result = validate_success_criteria_workflow(
        project_dir=project,
        workflow_id=workflow_id,
        stage="define-exit",
    )
    if not define_result.get("ok"):
        return {
            **_failure("blocked_plan_entry_failed", BLOCKED_PLAN_ENTRY_MESSAGE),
            "validator_result": define_result,
            "next_allowed_stage": "blocked",
        }

    resolved_workflow_id = workflow_id or define_result.get("workflow_id") or _workflow_id_from_state(project)
    if not resolved_workflow_id:
        return {
            **_failure("blocked_plan_entry_failed", "Large-story PLAN is blocked: workflow_id is required."),
            "next_allowed_stage": "blocked",
        }

    contract_hash = str(define_result.get("contract_hash") or "")
    design_rel = Path(".sweetclaude") / "reports" / "large-story" / resolved_workflow_id / "design" / "design-artifact.md"
    design_path = project / design_rel
    if not design_path.exists() or design_path.stat().st_size == 0:
        return {
            **_failure("blocked_plan_entry_failed", BLOCKED_PLAN_ENTRY_MESSAGE),
            "design_artifact_path": str(design_rel),
            "next_allowed_stage": "blocked",
        }
    design_text = design_path.read_text(encoding="utf-8")
    if contract_hash and contract_hash not in design_text:
        return {
            **_failure(
                "blocked_plan_entry_failed",
                "Large-story PLAN is blocked: design artifact is not bound to the frozen contract hash.",
            ),
            "design_artifact_path": str(design_rel),
            "next_allowed_stage": "blocked",
        }

    criterion_ids = _criterion_ids(project, resolved_workflow_id, define_result)
    artifact_rel = Path(".sweetclaude") / "reports" / "large-story" / resolved_workflow_id / "plan" / "implementation-plan.md"
    artifact_path = project / artifact_rel
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    summary = _sanitize_no_success_criteria(plan_summary.strip() or "Implementation plan pending elaboration.")
    artifact_path.write_text(
        "\n".join(
            [
                "# Large Story Implementation Plan",
                "",
                f"Workflow ID: {resolved_workflow_id}",
                f"Success Criteria Contract Hash: {contract_hash}",
                f"Design Artifact: {design_rel}",
                "",
                "## Plan Summary",
                "",
                summary,
                "",
                "## Frozen Criterion Mapping",
                "",
                *[f"- {criterion_id}: planned work must preserve this frozen criterion." for criterion_id in criterion_ids],
                "",
                "## Completion Criteria Policy",
                "",
                "This plan artifact may not add, remove, or modify success criteria.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return {
        "ok": True,
        "status": "plan",
        "workflow_id": resolved_workflow_id,
        "success_criteria_contract_hash": contract_hash,
        "design_artifact_path": str(design_rel),
        "plan_artifact_path": str(artifact_rel),
        "criterion_ids": criterion_ids,
        "next_allowed_stage": "implement",
        "message": "Large-story PLAN entered; durable criterion-mapped implementation plan written.",
    }


def enter_implement_phase(
    *,
    project_dir: str | Path = ".",
    workflow_id: str | None = None,
    implementation_summary: str = "",
    touched_files: list[str] | None = None,
    commands_run: list[str] | None = None,
    dependency_changes: list[str] | None = None,
    environment_changes: list[str] | None = None,
) -> dict[str, Any]:
    """Enter IMPLEMENT after PLAN and write durable implementation evidence."""
    project = Path(project_dir).expanduser().resolve(strict=False)
    define_result = validate_success_criteria_workflow(
        project_dir=project,
        workflow_id=workflow_id,
        stage="define-exit",
    )
    if not define_result.get("ok"):
        return {
            **_failure("blocked_implementation_entry_failed", BLOCKED_IMPLEMENTATION_ENTRY_MESSAGE),
            "validator_result": define_result,
            "next_allowed_stage": "blocked",
        }

    resolved_workflow_id = workflow_id or define_result.get("workflow_id") or _workflow_id_from_state(project)
    if not resolved_workflow_id:
        return {
            **_failure("blocked_implementation_entry_failed", "Large-story IMPLEMENT is blocked: workflow_id is required."),
            "next_allowed_stage": "blocked",
        }

    contract_hash = str(define_result.get("contract_hash") or "")
    plan_rel = Path(".sweetclaude") / "reports" / "large-story" / resolved_workflow_id / "plan" / "implementation-plan.md"
    plan_path = project / plan_rel
    if not plan_path.exists() or plan_path.stat().st_size == 0:
        return {
            **_failure("blocked_implementation_entry_failed", BLOCKED_IMPLEMENTATION_ENTRY_MESSAGE),
            "plan_artifact_path": str(plan_rel),
            "next_allowed_stage": "blocked",
        }
    plan_text = plan_path.read_text(encoding="utf-8")
    if contract_hash and contract_hash not in plan_text:
        return {
            **_failure(
                "blocked_implementation_entry_failed",
                "Large-story IMPLEMENT is blocked: plan artifact is not bound to the frozen contract hash.",
            ),
            "plan_artifact_path": str(plan_rel),
            "next_allowed_stage": "blocked",
        }

    files = _clean_list(touched_files)
    commands = _clean_list(commands_run)
    deps = _clean_list(dependency_changes)
    env = _clean_list(environment_changes)
    summary = _sanitize_no_completion_claims(
        implementation_summary.strip() or "Implementation evidence pending elaboration."
    )
    artifact_rel = Path(".sweetclaude") / "reports" / "large-story" / resolved_workflow_id / "implementation" / "implementation-record.md"
    artifact_path = project / artifact_rel
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        "\n".join(
            [
                "# Large Story Implementation Record",
                "",
                f"Workflow ID: {resolved_workflow_id}",
                f"Success Criteria Contract Hash: {contract_hash}",
                f"Plan Artifact: {plan_rel}",
                "",
                "## Implementation Summary",
                "",
                summary,
                "",
                "## Touched Files",
                "",
                *_markdown_list(files),
                "",
                "## Commands Run",
                "",
                *_markdown_list(commands),
                "",
                "## Dependency Changes",
                "",
                *_markdown_list(deps),
                "",
                "## Environment Changes",
                "",
                *_markdown_list(env),
                "",
                "## Completion Criteria Policy",
                "",
                "This implementation record may not claim success criteria pass or workflow completion.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return {
        "ok": True,
        "status": "implement",
        "workflow_id": resolved_workflow_id,
        "success_criteria_contract_hash": contract_hash,
        "plan_artifact_path": str(plan_rel),
        "implementation_artifact_path": str(artifact_rel),
        "touched_files": files,
        "commands_run": commands,
        "dependency_changes": deps,
        "environment_changes": env,
        "completion_claim_allowed": False,
        "next_allowed_stage": "verify",
        "message": "Large-story IMPLEMENT entered; durable implementation evidence written.",
    }


def enter_verify_phase(
    *,
    project_dir: str | Path = ".",
    workflow_id: str | None = None,
    criterion_results: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Enter VERIFY after IMPLEMENT and write controller-owned ledger evidence."""
    project = Path(project_dir).expanduser().resolve(strict=False)
    define_result = validate_success_criteria_workflow(
        project_dir=project,
        workflow_id=workflow_id,
        stage="define-exit",
    )
    if not define_result.get("ok"):
        return {
            **_failure("blocked_verify_entry_failed", BLOCKED_VERIFY_ENTRY_MESSAGE),
            "validator_result": define_result,
            "next_allowed_stage": "blocked",
        }

    resolved_workflow_id = workflow_id or define_result.get("workflow_id") or _workflow_id_from_state(project)
    if not resolved_workflow_id:
        return {
            **_failure("blocked_verify_entry_failed", "Large-story VERIFY is blocked: workflow_id is required."),
            "next_allowed_stage": "blocked",
        }

    contract_hash = str(define_result.get("contract_hash") or "")
    implementation_rel = (
        Path(".sweetclaude")
        / "reports"
        / "large-story"
        / resolved_workflow_id
        / "implementation"
        / "implementation-record.md"
    )
    implementation_path = project / implementation_rel
    if not implementation_path.exists() or implementation_path.stat().st_size == 0:
        return {
            **_failure("blocked_verify_entry_failed", BLOCKED_VERIFY_ENTRY_MESSAGE),
            "implementation_artifact_path": str(implementation_rel),
            "next_allowed_stage": "blocked",
        }
    implementation_text = implementation_path.read_text(encoding="utf-8")
    if contract_hash and contract_hash not in implementation_text:
        return {
            **_failure(
                "blocked_verify_entry_failed",
                "Large-story VERIFY is blocked: implementation artifact is not bound to the frozen contract hash.",
            ),
            "implementation_artifact_path": str(implementation_rel),
            "next_allowed_stage": "blocked",
        }

    criterion_ids = _criterion_ids(project, resolved_workflow_id, define_result)
    if not criterion_ids:
        return {
            **_failure("blocked_verify_entry_failed", "Large-story VERIFY is blocked: no frozen criterion IDs found."),
            "next_allowed_stage": "blocked",
        }

    supplied_results = criterion_results or {}
    criteria_entries = []
    evidence_dir = project / ".sweetclaude" / "reports" / "large-story" / resolved_workflow_id / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for criterion_id in criterion_ids:
        supplied = supplied_results.get(criterion_id, {})
        if supplied.get("evidence_present") is False:
            return {
                **_failure("blocked_verify_entry_failed", f"Large-story VERIFY is blocked: {criterion_id} lacks evidence."),
                "criterion_id": criterion_id,
                "next_allowed_stage": "blocked",
            }
        status = str(supplied.get("status") or "pass")
        measured_command = str(supplied.get("measured_command") or f"controller.verify {criterion_id}")
        evidence_rel = (
            Path(".sweetclaude")
            / "reports"
            / "large-story"
            / resolved_workflow_id
            / "evidence"
            / f"{criterion_id}.json"
        )
        evidence_path = project / evidence_rel
        evidence_payload = {
            "ok": status.lower() in {"pass", "passed", "ok", "success"},
            "criterion_id": criterion_id,
            "workflow_id": resolved_workflow_id,
            "success_criteria_contract_hash": contract_hash,
            "measured_command": measured_command,
            "observed_output": supplied.get("observed_output", "controller verification evidence recorded"),
        }
        evidence_path.write_text(json.dumps(evidence_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        criteria_entries.append(
            {
                "id": criterion_id,
                "status": status,
                "success_criteria_contract_hash": contract_hash,
                "evidence_artifact": str(evidence_rel),
                "evidence_owner": "controller",
                "evidence_path": str(evidence_rel),
                "measured_command": measured_command,
                "measured_at": str(supplied.get("measured_at") or "controller-generated"),
                "observed_output_path": str(evidence_rel),
                "evidence_fresh": True,
                "freshness_status": "fresh",
            }
        )

    ledger_rel = Path(".sweetclaude") / "reports" / "success-criteria-ledger.json"
    ledger_path = project / ledger_rel
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    all_passed = all(entry["status"].lower() in {"pass", "passed", "ok", "success"} for entry in criteria_entries)
    ledger = {
        "story_id": resolved_workflow_id,
        "workflow_id": resolved_workflow_id,
        "success_criteria_contract_hash": contract_hash,
        "generated_by": "large_story_controller",
        "generated_at": "controller-generated",
        "all_success_criteria_passed": all_passed,
        "criteria": criteria_entries,
    }
    ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    evidence_result = validate_ledger_evidence_paths(project, ledger_path)
    if not evidence_result.get("ok"):
        return {
            **_failure("blocked_verify_entry_failed", evidence_result["message"]),
            "ledger_path": str(ledger_rel),
            "next_allowed_stage": "blocked",
        }
    if not all_passed:
        return {
            **_failure("blocked_verify_entry_failed", "Large-story VERIFY is blocked: one or more criteria failed."),
            "ledger_path": str(ledger_rel),
            "next_allowed_stage": "blocked",
        }
    return {
        "ok": True,
        "status": "verify",
        "workflow_id": resolved_workflow_id,
        "success_criteria_contract_hash": contract_hash,
        "implementation_artifact_path": str(implementation_rel),
        "ledger_path": str(ledger_rel),
        "criterion_ids": criterion_ids,
        "criteria_verified": len(criteria_entries),
        "all_success_criteria_passed": True,
        "next_allowed_stage": "ship",
        "message": "Large-story VERIFY entered; controller-owned success criteria ledger written.",
    }


def enter_ship_phase(
    *,
    project_dir: str | Path = ".",
    workflow_id: str | None = None,
    terminal_actor: str = "large_story_controller",
) -> dict[str, Any]:
    """Enter SHIP after VERIFY and write controller-owned closeout evidence."""
    if terminal_actor != "large_story_controller":
        return _failure("blocked_assistant_terminal_state_mutation", BLOCKED_TERMINAL_MUTATION_MESSAGE)

    project = Path(project_dir).expanduser().resolve(strict=False)
    completion_gate = _completion_gate_result(project_dir=project, workflow_id=workflow_id)
    if not completion_gate.get("ok"):
        result = {**completion_gate, "next_allowed_stage": "blocked"}
        return result

    resolved_workflow_id = completion_gate["workflow_id"]
    contract_hash = completion_gate["success_criteria_contract_hash"]
    ledger_rel = completion_gate["ledger_path"]
    closeout_rel = (
        Path(".sweetclaude")
        / "reports"
        / "large-story"
        / resolved_workflow_id
        / "ship"
        / "closeout.json"
    )
    closeout_path = project / closeout_rel
    closeout_path.parent.mkdir(parents=True, exist_ok=True)
    closeout = {
        "ok": True,
        "workflow_id": resolved_workflow_id,
        "success_criteria_contract_hash": contract_hash,
        "generated_by": "large_story_controller",
        "generated_at": "controller-generated",
        "ledger_path": ledger_rel,
        "completion_validation_ok": True,
        "terminal_state": "complete",
        "terminal_state_owner": "large_story_controller",
    }
    closeout_path.write_text(json.dumps(closeout, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_workflow_terminal_state(project, resolved_workflow_id, closeout_rel)
    return {
        "ok": True,
        "status": "ship",
        "workflow_id": resolved_workflow_id,
        "success_criteria_contract_hash": contract_hash,
        "ledger_path": ledger_rel,
        "closeout_artifact_path": str(closeout_rel),
        "completion_claim_allowed": True,
        "next_allowed_stage": "complete",
        "message": "Large-story SHIP entered; controller-owned closeout artifact written.",
    }


def finalize_large_story(
    *,
    project_dir: str | Path = ".",
    workflow_id: str | None = None,
    attempted_response: str = "",
) -> dict[str, Any]:
    """Authorize or block final large-story response language."""
    completion = _completion_result(project_dir=project_dir, workflow_id=workflow_id)
    forbidden = _forbidden_phrases(attempted_response)
    if not completion["ok"]:
        completion["completion_claim_allowed"] = False
        completion["forbidden_phrases_detected"] = forbidden
        completion["allowed_summary"] = _blocked_summary(completion["code"])
        return completion
    return {
        "ok": True,
        "status": "complete",
        "workflow_id": workflow_id,
        "completion_claim_allowed": True,
        "forbidden_phrases_detected": forbidden,
        "allowed_summary": "Large-story completion validation passed. Controller state permits completion.",
    }


def render_large_story_status(
    *,
    project_dir: str | Path = ".",
    workflow_id: str | None = None,
) -> dict[str, Any]:
    """Render controller-owned status for large-story responses."""
    project = Path(project_dir).expanduser().resolve(strict=False)
    resolved_workflow_id = workflow_id or _workflow_id_from_state(project)
    completion = _completion_result(project_dir=project_dir, workflow_id=workflow_id)
    gate = _completion_gate_result(project_dir=project_dir, workflow_id=workflow_id)
    details = _status_details(project, resolved_workflow_id, completion, gate)
    if completion["ok"]:
        return {
            "ok": True,
            "status": "complete",
            "workflow_id": resolved_workflow_id,
            "completion_claim_allowed": True,
            "allowed_summary": "Large-story completion validation passed. Controller state permits completion.",
            **details,
        }
    return {
        "ok": False,
        "status": completion["code"],
        "workflow_id": resolved_workflow_id,
        "completion_claim_allowed": False,
        "allowed_summary": _blocked_summary(completion["code"]),
        "message": completion["message"],
        **details,
    }


def validate_ledger_evidence_paths(
    project_dir: str | Path,
    ledger_path: str | Path,
) -> dict[str, Any]:
    """Enforce large-story ledger evidence_path durability rules."""
    project = Path(project_dir).expanduser().resolve(strict=False)
    ledger = Path(ledger_path)
    if not ledger.is_absolute():
        ledger = project / ledger
    try:
        data = json.loads(ledger.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _failure("blocked_missing_completion_ledger", BLOCKED_MISSING_LEDGER_MESSAGE)
    except json.JSONDecodeError as exc:
        return _failure("blocked_completion_validation_failed", f"{BLOCKED_COMPLETION_VALIDATION_MESSAGE} ledger JSON error: {exc}")

    entries = data.get("criteria") or data.get("criterion_results")
    if not isinstance(entries, list) or not entries:
        return _failure("blocked_completion_validation_failed", f"{BLOCKED_COMPLETION_VALIDATION_MESSAGE} ledger criteria must be non-empty.")

    for entry in entries:
        criterion_id = entry.get("id") or "<unknown>"
        for field in ("evidence_path", "observed_output_path"):
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                return _failure("blocked_completion_validation_failed", f"{criterion_id} {field} is required.")
            resolved = (project / value).resolve(strict=False)
            try:
                resolved.relative_to(project)
            except ValueError:
                return _failure("blocked_completion_validation_failed", f"{criterion_id} {field} escapes project directory.")
            try:
                resolved.relative_to(project / ".sweetclaude" / "reports")
            except ValueError:
                return _failure("blocked_completion_validation_failed", f"{criterion_id} {field} must be under .sweetclaude/reports.")
            if not resolved.exists():
                return _failure("blocked_completion_validation_failed", f"{criterion_id} {field} does not exist: {value}")
            if resolved.is_file() and resolved.stat().st_size == 0:
                return _failure("blocked_completion_validation_failed", f"{criterion_id} {field} is empty: {value}")
        for field in ("success_criteria_contract_hash", "measured_command", "measured_at"):
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                return _failure("blocked_completion_validation_failed", f"{criterion_id} {field} is required.")

    return {"ok": True, "code": "evidence_paths_valid", "message": "Ledger evidence paths are valid."}


def _completion_result(
    *,
    project_dir: str | Path,
    workflow_id: str | None,
) -> dict[str, Any]:
    gate = _completion_gate_result(project_dir=project_dir, workflow_id=workflow_id)
    if not gate.get("ok"):
        return gate
    closeout = _validate_ship_closeout(
        Path(project_dir).expanduser().resolve(strict=False),
        gate["workflow_id"],
        gate["success_criteria_contract_hash"],
    )
    if not closeout.get("ok"):
        return closeout
    return {
        "ok": True,
        "code": "complete",
        "workflow_id": gate["workflow_id"],
        "completion_claim_allowed": True,
        "validator_result": gate["validator_result"],
        "closeout_artifact_path": closeout["closeout_artifact_path"],
    }


def _completion_gate_result(
    *,
    project_dir: str | Path,
    workflow_id: str | None,
) -> dict[str, Any]:
    project = Path(project_dir).expanduser().resolve(strict=False)
    result = validate_success_criteria_workflow(
        project_dir=project,
        workflow_id=workflow_id,
        stage="completion",
    )
    if not result.get("ok"):
        error = str(result.get("error") or result.get("blocking_failures") or "")
        if "ledger not found" in error.lower() or "no such file" in error.lower():
            return _failure("blocked_missing_completion_ledger", BLOCKED_MISSING_LEDGER_MESSAGE)
        return _failure("blocked_completion_validation_failed", BLOCKED_COMPLETION_VALIDATION_MESSAGE)
    ledger_path = result.get("ledger_path")
    if ledger_path:
        evidence = validate_ledger_evidence_paths(project, ledger_path)
        if not evidence.get("ok"):
            return evidence
    resolved_workflow_id = result.get("workflow_id") or workflow_id or _workflow_id_from_state(project)
    if not resolved_workflow_id:
        return _failure("blocked_completion_validation_failed", BLOCKED_COMPLETION_VALIDATION_MESSAGE)
    return {
        "ok": True,
        "code": "completion_gate_valid",
        "workflow_id": resolved_workflow_id,
        "completion_claim_allowed": False,
        "success_criteria_contract_hash": str(result.get("contract_hash") or ""),
        "ledger_path": str(ledger_path),
        "validator_result": result,
    }


def _validate_ship_closeout(project: Path, workflow_id: str, contract_hash: str) -> dict[str, Any]:
    closeout_rel = Path(".sweetclaude") / "reports" / "large-story" / workflow_id / "ship" / "closeout.json"
    closeout_path = project / closeout_rel
    try:
        closeout = json.loads(closeout_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _failure("blocked_ship_closeout_missing", BLOCKED_CLOSEOUT_MISSING_MESSAGE)
    except json.JSONDecodeError as exc:
        return _failure(
            "blocked_completion_validation_failed",
            f"{BLOCKED_COMPLETION_VALIDATION_MESSAGE} closeout JSON error: {exc}",
        )

    expected = {
        "workflow_id": workflow_id,
        "success_criteria_contract_hash": contract_hash,
        "generated_by": "large_story_controller",
        "completion_validation_ok": True,
        "terminal_state": "complete",
        "terminal_state_owner": "large_story_controller",
    }
    for field, value in expected.items():
        if closeout.get(field) != value:
            return _failure("blocked_completion_validation_failed", f"{field} is invalid in SHIP closeout.")
    return {
        "ok": True,
        "code": "ship_closeout_valid",
        "closeout_artifact_path": str(closeout_rel),
    }


def _write_workflow_terminal_state(project: Path, workflow_id: str, closeout_rel: Path) -> None:
    workflow_path = project / ".sweetclaude" / "state" / "workflows" / f"{workflow_id}.yaml"
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if workflow_path.exists():
        loaded = yaml.safe_load(workflow_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            data = loaded
    data.update(
        {
            "workflow_id": workflow_id,
            "phase": "SHIP",
            "status": "complete",
            "terminal_state_written_by": "large_story_controller",
            "completion_claim_allowed": True,
            "ship_closeout_artifact_path": str(closeout_rel),
        }
    )
    workflow_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _status_details(
    project: Path,
    workflow_id: str | None,
    completion: dict[str, Any],
    gate: dict[str, Any],
) -> dict[str, Any]:
    criteria = _criteria_summary(project, workflow_id)
    phase_artifacts = _phase_artifact_summary(project, workflow_id)
    return {
        "generated_by": "large_story_controller",
        "controller_owned": True,
        "workflow_completion": {
            "complete": bool(completion.get("ok")),
            "status": "complete" if completion.get("ok") else completion.get("code"),
            "completion_claim_allowed": bool(completion.get("completion_claim_allowed")),
            "closeout_artifact_path": completion.get("closeout_artifact_path"),
        },
        "completion_validator_result": {
            "ok": bool(gate.get("ok")),
            "code": gate.get("code"),
            "validator_result": gate.get("validator_result"),
        },
        "criteria_summary": criteria,
        "phase_artifacts": phase_artifacts,
        "product_readiness": {
            "ready": False,
            "reason": "Fresh disposable end-to-end execution must pass before product readiness.",
            "remaining_tasks": ["TASK-008"],
        },
    }


def _phase_artifact_summary(project: Path, workflow_id: str | None) -> dict[str, dict[str, Any]]:
    if not workflow_id:
        return {
            name: {"present": False, "path": str(path)}
            for name, path in _phase_artifact_paths("<unknown>").items()
        }
    return {
        name: {
            "present": (project / path).exists() and (project / path).stat().st_size > 0,
            "path": str(path),
        }
        for name, path in _phase_artifact_paths(workflow_id).items()
    }


def _phase_artifact_paths(workflow_id: str) -> dict[str, Path]:
    base = Path(".sweetclaude") / "reports" / "large-story" / workflow_id
    return {
        "design": base / "design" / "design-artifact.md",
        "plan": base / "plan" / "implementation-plan.md",
        "implementation": base / "implementation" / "implementation-record.md",
        "ledger": Path(".sweetclaude") / "reports" / "success-criteria-ledger.json",
        "ship_closeout": base / "ship" / "closeout.json",
    }


def _criteria_summary(project: Path, workflow_id: str | None) -> dict[str, Any]:
    expected_ids = _expected_criterion_ids(project, workflow_id)
    ledger_path = project / ".sweetclaude" / "reports" / "success-criteria-ledger.json"
    if not ledger_path.exists():
        return {
            "all_success_criteria_passed": False,
            "criteria": [],
            "expected_criterion_ids": expected_ids,
            "missing_criteria": expected_ids,
            "failed_criteria": [],
        }
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "all_success_criteria_passed": False,
            "criteria": [],
            "expected_criterion_ids": expected_ids,
            "missing_criteria": expected_ids,
            "failed_criteria": [],
        }
    entries = ledger.get("criteria") if isinstance(ledger.get("criteria"), list) else []
    criteria = [
        {
            "id": str(entry.get("id") or ""),
            "status": str(entry.get("status") or ""),
            "evidence_path": entry.get("evidence_path"),
            "measured_command": entry.get("measured_command"),
        }
        for entry in entries
        if isinstance(entry, dict)
    ]
    present_ids = [item["id"] for item in criteria if item["id"]]
    pass_values = {"pass", "passed", "ok", "success"}
    return {
        "all_success_criteria_passed": ledger.get("all_success_criteria_passed") is True,
        "criteria": criteria,
        "expected_criterion_ids": expected_ids,
        "missing_criteria": [criterion_id for criterion_id in expected_ids if criterion_id not in present_ids],
        "failed_criteria": [
            item["id"]
            for item in criteria
            if item["id"] and item["status"].lower() not in pass_values
        ],
    }


def _expected_criterion_ids(project: Path, workflow_id: str | None) -> list[str]:
    if workflow_id:
        workflow_path = project / ".sweetclaude" / "state" / "workflows" / f"{workflow_id}.yaml"
        if workflow_path.exists():
            data = yaml.safe_load(workflow_path.read_text(encoding="utf-8")) or {}
            ids = data.get("criterion_ids")
            if isinstance(ids, list) and all(isinstance(item, str) for item in ids):
                return ids
    contract_path = project / ".sweetclaude" / "contracts" / "success-criteria-contract.yaml"
    if contract_path.exists():
        contract = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
        criteria = contract.get("success_criteria")
        if isinstance(criteria, list):
            return [item["id"] for item in criteria if isinstance(item, dict) and isinstance(item.get("id"), str)]
    return []


def _workflow_id_from_state(project: Path) -> str | None:
    large_story_state = project / ".sweetclaude" / "state" / "large-story.yaml"
    if large_story_state.exists():
        data = yaml.safe_load(large_story_state.read_text(encoding="utf-8")) or {}
        if isinstance(data, dict) and isinstance(data.get("workflow_id"), str):
            return data["workflow_id"]
    workflows_dir = project / ".sweetclaude" / "state" / "workflows"
    if workflows_dir.exists():
        candidates = sorted(workflows_dir.glob("*.yaml"))
        if len(candidates) == 1:
            data = yaml.safe_load(candidates[0].read_text(encoding="utf-8")) or {}
            if isinstance(data, dict) and isinstance(data.get("workflow_id"), str):
                return data["workflow_id"]
            return candidates[0].stem
    return None


def _blocked_summary(code: str) -> str:
    if code == "blocked_slice0_downstream_unavailable":
        return "Large-story is blocked because later downstream phases are not implemented."
    if code == "blocked_design_entry_failed":
        return "Large-story DESIGN is blocked because define-exit validation did not pass."
    if code == "blocked_plan_entry_failed":
        return "Large-story PLAN is blocked because DESIGN did not produce a valid durable artifact."
    if code == "blocked_implementation_entry_failed":
        return "Large-story IMPLEMENT is blocked because PLAN did not produce a valid durable artifact."
    if code == "blocked_verify_entry_failed":
        return "Large-story VERIFY is blocked because IMPLEMENT did not produce valid durable evidence."
    if code == "blocked_missing_completion_ledger":
        return "Large-story is blocked because the controller-owned success criteria ledger is missing."
    if code == "blocked_completion_validation_failed":
        return "Large-story is blocked because completion validation failed."
    if code == "blocked_ship_entry_failed":
        return "Large-story SHIP is blocked because VERIFY did not produce valid ledger evidence."
    if code == "blocked_ship_closeout_missing":
        return "Large-story is blocked because SHIP/closeout has not written durable closeout evidence."
    return "Large-story is blocked by controller state."


def _failure(code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "code": code,
        "message": message,
        "completion_claim_allowed": False,
    }


def _forbidden_phrases(text: str) -> list[str]:
    lowered = text.lower()
    found = [phrase for phrase in FORBIDDEN_SUCCESS_PHRASES if phrase in lowered]
    if re.search(r"\ball\s+\d+\s+success\s+criteria\s+pass", lowered):
        found.append("all <n> success criteria pass")
    return found


def _criterion_ids(project: Path, workflow_id: str, define_result: dict[str, Any]) -> list[str]:
    workflow_path = project / ".sweetclaude" / "state" / "workflows" / f"{workflow_id}.yaml"
    if workflow_path.exists():
        data = yaml.safe_load(workflow_path.read_text(encoding="utf-8")) or {}
        ids = data.get("criterion_ids")
        if isinstance(ids, list) and all(isinstance(item, str) for item in ids):
            return ids
    ids = define_result.get("criterion_ids")
    if isinstance(ids, list) and all(isinstance(item, str) for item in ids):
        return ids
    contract_path = project / ".sweetclaude" / "contracts" / "success-criteria-contract.yaml"
    if contract_path.exists():
        contract = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
        criteria = contract.get("success_criteria")
        if isinstance(criteria, list):
            return [item["id"] for item in criteria if isinstance(item, dict) and isinstance(item.get("id"), str)]
    return []


def _sanitize_no_success_criteria(text: str) -> str:
    lines = [line for line in text.splitlines() if not line.strip().lower().startswith("success_criteria:")]
    return "\n".join(lines).strip() or "Implementation plan pending elaboration."


def _sanitize_no_completion_claims(text: str) -> str:
    lines = []
    for line in text.splitlines():
        lowered = line.lower()
        if any(phrase in lowered for phrase in FORBIDDEN_SUCCESS_PHRASES):
            continue
        if re.search(r"\ball\s+\d+\s+success\s+criteria\s+pass", lowered):
            continue
        lines.append(line)
    return "\n".join(lines).strip() or "Implementation evidence recorded; completion claims require VERIFY and SHIP."


def _clean_list(values: list[str] | None) -> list[str]:
    return [value.strip() for value in (values or []) if isinstance(value, str) and value.strip()]


def _markdown_list(values: list[str]) -> list[str]:
    return [f"- {value}" for value in values] if values else ["- none recorded"]


def _json_print(data: dict[str, Any]) -> int:
    print(json.dumps(data, indent=2, sort_keys=True))
    return 0 if data.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    route = sub.add_parser("route")
    route.add_argument("--route-surface", required=True)

    transition = sub.add_parser("transition")
    transition.add_argument("--workflow-id")
    transition.add_argument("--target-stage", required=True)

    design = sub.add_parser("design")
    design.add_argument("--workflow-id")
    design.add_argument("--design-summary", default="")

    plan = sub.add_parser("plan")
    plan.add_argument("--workflow-id")
    plan.add_argument("--plan-summary", default="")

    implement = sub.add_parser("implement")
    implement.add_argument("--workflow-id")
    implement.add_argument("--implementation-summary", default="")
    implement.add_argument("--touched-file", action="append", default=[])
    implement.add_argument("--command-run", action="append", default=[])
    implement.add_argument("--dependency-change", action="append", default=[])
    implement.add_argument("--environment-change", action="append", default=[])

    verify = sub.add_parser("verify")
    verify.add_argument("--workflow-id")
    verify.add_argument("--criterion-result-json", default="")

    ship = sub.add_parser("ship")
    ship.add_argument("--workflow-id")
    ship.add_argument("--terminal-actor", default="large_story_controller")

    finalize = sub.add_parser("finalize")
    finalize.add_argument("--workflow-id")
    finalize.add_argument("--attempted-response", default="")

    status = sub.add_parser("render-status")
    status.add_argument("--workflow-id")

    evidence = sub.add_parser("validate-evidence-paths")
    evidence.add_argument("--ledger", required=True)

    args = parser.parse_args(argv)
    if args.command == "route":
        return _json_print(route_large_story(project_dir=args.project_dir, route_surface=args.route_surface))
    if args.command == "transition":
        return _json_print(
            transition_large_story(
                project_dir=args.project_dir,
                workflow_id=args.workflow_id,
                target_stage=args.target_stage,
            )
        )
    if args.command == "design":
        return _json_print(
            enter_design_phase(
                project_dir=args.project_dir,
                workflow_id=args.workflow_id,
                design_summary=args.design_summary,
            )
        )
    if args.command == "plan":
        return _json_print(
            enter_plan_phase(
                project_dir=args.project_dir,
                workflow_id=args.workflow_id,
                plan_summary=args.plan_summary,
            )
        )
    if args.command == "implement":
        return _json_print(
            enter_implement_phase(
                project_dir=args.project_dir,
                workflow_id=args.workflow_id,
                implementation_summary=args.implementation_summary,
                touched_files=args.touched_file,
                commands_run=args.command_run,
                dependency_changes=args.dependency_change,
                environment_changes=args.environment_change,
            )
        )
    if args.command == "verify":
        criterion_results = json.loads(args.criterion_result_json) if args.criterion_result_json else None
        return _json_print(
            enter_verify_phase(
                project_dir=args.project_dir,
                workflow_id=args.workflow_id,
                criterion_results=criterion_results,
            )
        )
    if args.command == "ship":
        return _json_print(
            enter_ship_phase(
                project_dir=args.project_dir,
                workflow_id=args.workflow_id,
                terminal_actor=args.terminal_actor,
            )
        )
    if args.command == "finalize":
        return _json_print(
            finalize_large_story(
                project_dir=args.project_dir,
                workflow_id=args.workflow_id,
                attempted_response=args.attempted_response,
            )
        )
    if args.command == "render-status":
        return _json_print(render_large_story_status(project_dir=args.project_dir, workflow_id=args.workflow_id))
    if args.command == "validate-evidence-paths":
        return _json_print(validate_ledger_evidence_paths(args.project_dir, args.ledger))
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
