#!/usr/bin/env python3
"""Shared artifact file parser — handles both YAML frontmatter and Bold Key-Value formats."""
from __future__ import annotations

import re
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

NONE_SENTINELS = frozenset({
    "(none)", "(sp-nnn when scheduled)", "(date when achieved)",
    "(rm-nnn when promoted)", "none", "",
})

BOLD_TO_YAML_FIELD_MAP = {
    "epic_id": "epic",
    "epic": "epic",
    "sprint_id": "sprint",
    "sprint": "sprint",
    "theme_id": "theme",
    "theme": "theme",
    "roadmap_item_id": "roadmap_item",
    "roadmap_item": "roadmap_item",
    "milestone_id": "milestone",
    "milestone": "milestone",
    "release_id": "release",
    "release": "release",
    "completed_at": "closed_date",
    "mode_introduced": "mode_introduced",
}

PREFIX_TO_TYPE = {
    "ISSUE": "net-new-feature",
    "I": "net-new-feature",
    "EP": "epic",
    "MS": "milestone",
    "SP": "sprint",
    "TH": "theme",
    "RM": "roadmap_item",
    "REL": "release",
    "PITCH": "pitch",
    "CYC": "cycle",
}


def _key_to_field(key: str) -> str:
    return key.lower().replace(" ", "_").replace("-", "_")


def _normalize_value(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if stripped.lower() in NONE_SENTINELS:
        return None
    return stripped


def _remap_field(key: str) -> str:
    return BOLD_TO_YAML_FIELD_MAP.get(key, key)


def parse_bold_metadata(content: str) -> dict | None:
    """Parse a Bold Key-Value format file (# Title / **Key:** Value)."""
    result: dict = {}

    heading_match = re.match(r"^#\s+(\S+-\d+):\s+(.+)", content)
    if heading_match:
        result["id"] = heading_match.group(1)
        result["title"] = heading_match.group(2).strip()
        prefix = result["id"].split("-")[0]
        if prefix in PREFIX_TO_TYPE and "type" not in result:
            result["type"] = PREFIX_TO_TYPE[prefix]
    else:
        title_match = re.match(r"^#\s+(.+)", content)
        if title_match:
            result["title"] = title_match.group(1).strip()

    found_any = False
    for line in content.splitlines():
        m = re.match(r"^\*\*([^*]+):\*\*\s*(.*)", line)
        if m:
            found_any = True
            raw_key = _key_to_field(m.group(1).strip())
            key = _remap_field(raw_key)
            result[key] = _normalize_value(m.group(2))

    if "type" in result and result["type"] in PREFIX_TO_TYPE.values():
        bold_type = result.get("type")
        if bold_type and bold_type not in PREFIX_TO_TYPE.values():
            pass

    if not found_any and "id" not in result:
        return None
    return result


def parse_yaml_frontmatter(content: str) -> dict | None:
    """Parse a YAML frontmatter file (--- ... ---)."""
    if yaml is None:
        return None
    normalized = content.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    parts = normalized.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        fm = yaml.safe_load(parts[1])
        return fm if isinstance(fm, dict) else None
    except Exception:
        return None


def detect_format(content: str) -> str:
    """Return 'yaml', 'bold', or 'unknown'."""
    stripped = content.lstrip("﻿").replace("\r\n", "\n")
    if stripped.startswith("---\n") or stripped.startswith("---\r"):
        parts = stripped.split("---", 2)
        if len(parts) >= 3:
            return "yaml"
    if re.search(r"^\*\*[^*]+:\*\*\s", content, re.MULTILINE):
        return "bold"
    return "unknown"


def parse_artifact(content: str) -> dict | None:
    """Parse an artifact file in either format. Returns dict or None."""
    fmt = detect_format(content)
    if fmt == "yaml":
        return parse_yaml_frontmatter(content)
    if fmt == "bold":
        return parse_bold_metadata(content)
    return None


def parse_artifact_file(path: str | Path) -> dict | None:
    """Read and parse an artifact file from disk."""
    try:
        content = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return parse_artifact(content)
