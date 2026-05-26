#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared mutation lifecycle validators for SweetClaude maintenance commands."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PASS_STATUSES = {"pass", "passed", "ok", "success"}
RESTORE_METHODS = {"command", "dry_run", "round_trip", "fixture"}


def hash_payload(payload: Any) -> str:
    """Return a stable sha256 digest for a JSON-compatible payload."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_relative_path(project_dir: Path, value: str | Path) -> str:
    project = project_dir.resolve(strict=False)
    path = Path(value)
    if path.is_absolute():
        resolved = path.resolve(strict=False)
    else:
        resolved = (project / path).resolve(strict=False)
    try:
        relative = resolved.relative_to(project)
    except ValueError:
        raise ValueError(f"path escapes project root: {value}") from None
    return relative.as_posix()


def validate_write_set(
    project_dir: str | Path,
    *,
    approved_write_set: list[str | Path],
    actual_changed_paths: list[str | Path],
) -> dict[str, Any]:
    """Validate actual writes are inside the approved write set."""
    project = Path(project_dir)
    approved = {
        _normalize_relative_path(project, path).rstrip("/")
        for path in approved_write_set
    }
    approved_prefixes = {
        _normalize_relative_path(project, path)
        for path in approved_write_set
        if str(path).endswith("/")
    }
    unexpected: list[str] = []
    for actual_path in actual_changed_paths:
        normalized = _normalize_relative_path(project, actual_path).rstrip("/")
        if normalized not in approved and not any(
            normalized == prefix.rstrip("/") or normalized.startswith(prefix.rstrip("/") + "/")
            for prefix in approved_prefixes
        ):
            unexpected.append(normalized)

    if unexpected:
        raise ValueError(
            "mutation outside approved write set: " + ", ".join(sorted(unexpected))
        )

    return {
        "status": "pass",
        "approved_write_set": sorted(approved),
        "actual_changed_paths": sorted(
            _normalize_relative_path(project, path).rstrip("/")
            for path in actual_changed_paths
        ),
        "unexpected_paths": [],
    }


def validate_approval_scope(
    approval: dict[str, Any],
    *,
    plan_hash: str,
    write_set_hash: str,
    snapshot_hash: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Validate approval is bound to the current plan, write set, snapshot, and context."""
    expected = {
        "plan_hash": plan_hash,
        "write_set_hash": write_set_hash,
        "snapshot_hash": snapshot_hash,
    }
    for key, expected_value in expected.items():
        actual = approval.get(key)
        if actual != expected_value:
            raise ValueError(f"{key} mismatch: expected {expected_value!r}, got {actual!r}")

    approval_context = approval.get("context")
    if not isinstance(approval_context, dict):
        raise ValueError("approval context is required")
    for key, expected_value in context.items():
        actual = approval_context.get(key)
        if actual != expected_value:
            raise ValueError(
                f"context.{key} mismatch: expected {expected_value!r}, got {actual!r}"
            )

    return {"status": "pass"}


def _covers_scope(snapshot_path: str, declared_scope: str) -> bool:
    snapshot = snapshot_path.strip("/").rstrip("/")
    scope = declared_scope.strip("/").rstrip("/")
    return snapshot == scope or snapshot.startswith(scope + "/")


def validate_snapshot_scope(
    *,
    declared_blast_radius: list[str],
    snapshot_paths: list[str],
) -> dict[str, Any]:
    """Validate snapshot paths cover every declared blast-radius scope."""
    missing = [
        scope
        for scope in declared_blast_radius
        if not any(_covers_scope(path, scope) for path in snapshot_paths)
    ]
    if missing:
        raise ValueError("snapshot scope missing: " + ", ".join(missing))
    return {
        "status": "pass",
        "declared_blast_radius": list(declared_blast_radius),
        "missing_scopes": [],
    }


def validate_restore_proof(proof: dict[str, Any]) -> dict[str, Any]:
    """Validate restore proof contains executable evidence, not backup metadata alone."""
    method = proof.get("method")
    status = str(proof.get("status", "")).lower()
    command = str(proof.get("command", "")).strip()
    evidence = str(proof.get("evidence", "")).strip()

    if method not in RESTORE_METHODS or status not in PASS_STATUSES:
        raise ValueError(
            "restore proof requires executable evidence with passing status"
        )
    if method in {"command", "dry_run", "round_trip"} and not command:
        raise ValueError("restore proof requires command evidence")
    if not evidence:
        raise ValueError("restore proof requires evidence")

    return {"status": "pass", "method": method}


def validate_postconditions(
    *,
    exit_code: int,
    postconditions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate mutation success using postconditions, not exit code alone."""
    if exit_code != 0:
        raise ValueError(f"mutation command failed with exit code {exit_code}")
    if not postconditions:
        raise ValueError("postconditions are required before marking mutation successful")

    failed: list[str] = []
    for index, postcondition in enumerate(postconditions, start=1):
        check_id = str(postcondition.get("id", f"postcondition-{index}"))
        status = str(postcondition.get("status", "")).lower()
        if status not in PASS_STATUSES:
            failed.append(f"{check_id} failed")

    if failed:
        raise ValueError("postcondition failure: " + ", ".join(failed))

    return {"status": "pass", "postcondition_count": len(postconditions)}


def should_stop_repair_loop(
    *,
    attempts: int,
    max_attempts: int,
    previous_postcondition_hash: str | None,
    current_postcondition_hash: str | None,
    new_regressions: list[str],
) -> dict[str, Any]:
    """Return repair-loop stop decision and escalation route."""
    if attempts >= max_attempts:
        return {
            "stop": True,
            "reason": "attempt-budget-exhausted",
            "route": "backlog-or-escalation",
        }
    if new_regressions:
        return {
            "stop": True,
            "reason": "new-regressions",
            "route": "backlog-or-escalation",
            "new_regressions": list(new_regressions),
        }
    if (
        attempts > 0
        and previous_postcondition_hash
        and previous_postcondition_hash == current_postcondition_hash
    ):
        return {
            "stop": True,
            "reason": "unchanged-postconditions",
            "route": "backlog-or-escalation",
        }
    return {"stop": False, "reason": "progress-or-budget-remains"}
