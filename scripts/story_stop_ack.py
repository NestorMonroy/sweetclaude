#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Durable pause-acknowledgment for the large/small-story Stop guards.

The Stop guards block session end while a story workflow is non-terminal, to
stop the assistant walking away implying the work is done. Claude Code only
sets ``stop_hook_active`` true for *consecutive* stops within a single turn, so
that flag alone cannot record that the user deliberately paused — the next turn
resets it and the guard re-fires forever.

This module persists the pause acknowledgment to disk, fingerprinted to the
workflow's material state (phase + controller status code). Once the user
confirms a pause (the deliberate second stop), the guard stays silent on later
turns until the workflow's state changes (re-arming one reminder) or it goes
terminal. The ack file is a dotfile so it is never matched by ``*.yaml`` globs.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def pause_ack_path(project: Path, workflow_id: str) -> Path:
    return project / ".sweetclaude" / "state" / "workflows" / f".stop-ack-{workflow_id}.json"


def compute_fingerprint(phase: str, status: dict[str, Any]) -> str:
    """Stable fingerprint of the workflow's material state.

    Keyed on phase and the controller status code so an acknowledged pause is
    honored until the story actually progresses (phase or status-class change)
    or closes out.
    """
    material = f"{phase}|{status.get('status')}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def read_ack_fingerprint(project: Path, workflow_id: str) -> str | None:
    path = pause_ack_path(project, workflow_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    fingerprint = data.get("fingerprint")
    return fingerprint if isinstance(fingerprint, str) else None


def write_ack(project: Path, workflow_id: str, fingerprint: str) -> None:
    path = pause_ack_path(project, workflow_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"workflow_id": workflow_id, "fingerprint": fingerprint})
    with tempfile.NamedTemporaryFile(
        "w", dir=str(path.parent), prefix=".stop-ack-", suffix=".tmp", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(payload)
        tmp_name = handle.name
    os.replace(tmp_name, path)
