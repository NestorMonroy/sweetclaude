#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Read-only SweetClaude project layout characterization.

This script intentionally does not create, update, move, or delete files in the
target project. It is the first stage of the recoverability harness: understand
the project shape before any tool can claim a migration or repair is safe.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml


SCHEMA_VERSION = 1
DEFAULT_PRODUCT_BASES = (
    Path("docs/product"),
    Path(".sweetclaude/product"),
    Path(".sweetclaude/artifacts/product"),
)
WORK_ITEM_RE = re.compile(
    r"^(?P<id>(?P<prefix>STORY|BUG|DEBT|CHORE|BL|ISSUE|EP|I|RM|MS)-(?P<num>\d+))"
    r"(?:-|\.md$)"
)
OLD_TAXONOMY_PREFIXES = {"STORY", "BUG", "DEBT", "CHORE", "BL"}
V4_TAXONOMY_PREFIXES = {"ISSUE", "EP", "MS", "RM", "I"}
TYPED_BACKLOG_DIRS = ("stories", "bugs", "debt", "chores")
CANONICAL_TYPES = frozenset({
    "bug-fix", "cycle", "enhancement", "epic", "goal", "milestone",
    "net-new-feature", "pitch", "release", "roadmap_item", "spike",
    "sprint", "story", "tech-debt", "theme",
})

# Backup/derived-file detection: suffix-anchored, case-insensitive.
# Matches: *.bold-backup-*.md  *.bak  *~  *.orig  *.swp
# Must NOT match "backup" or "orig" mid-slug (e.g. STORY-041-backup-and-restore.md).
DERIVED_FILE_RE = re.compile(
    r"(?:"
    r"\.bold-backup-[^/\\]+\.md"   # *.bold-backup-*.md (suffix with .md at end)
    r"|\.bak"                       # *.bak
    r"|~"                           # *~ (tilde suffix)
    r"|\.orig"                      # *.orig
    r"|\.swp"                       # *.swp
    r")$",
    re.IGNORECASE,
)

# Epic directory name pattern: EPIC-NNN or BL-NNN
EPIC_DIR_RE = re.compile(r"^(EPIC|BL)-\d+$")

# Bespoke epic file: exactly EPIC-NNN.md (not EPIC-NNN-index.md or similar)
EPIC_FILE_RE = re.compile(r"^(EPIC-\d+)\.md$")

# Bespoke story file: US-* file inside an EPIC/BL dir
STORY_FILE_RE = re.compile(r"^US-")

# Supporting document keywords (filename-based, no frontmatter id required)
SUPPORTING_DOC_RE = re.compile(
    r"(?:FOUNDATION|prd|brief|index|personas)",
    re.IGNORECASE,
)


def is_derived_file(rel_path: str) -> bool:
    """Return True if rel_path matches a backup/derived-file pattern (suffix-anchored)."""
    return bool(DERIVED_FILE_RE.search(rel_path))


def _safe_load_yaml(path: Path) -> tuple[Any | None, str | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(errors="replace")
    try:
        return yaml.safe_load(text), None
    except yaml.YAMLError as exc:
        return None, str(exc)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _resolve_product_base(project_dir: Path) -> tuple[Path | None, list[str]]:
    reasons: list[str] = []

    privacy_path = project_dir / ".sweetclaude" / "artifact-privacy.yaml"
    if privacy_path.exists():
        data, error = _safe_load_yaml(privacy_path)
        if error:
            reasons.append(f"artifact-privacy parse error: {error}")
        elif isinstance(data, dict):
            product = data.get("product")
            categories = data.get("categories")
            if not isinstance(product, dict) and isinstance(categories, dict):
                product = categories.get("product")
            if isinstance(product, dict) and product.get("base_path"):
                return _resolve_owned_path(project_dir, str(product["base_path"])), reasons

    state_path = project_dir / ".sweetclaude" / "state" / "sweetclaude.yaml"
    if state_path.exists():
        data, error = _safe_load_yaml(state_path)
        if error:
            reasons.append(f"sweetclaude.yaml parse error: {error}")
        elif isinstance(data, dict):
            paths = data.get("paths")
            if isinstance(paths, dict) and paths.get("product_base"):
                return _resolve_owned_path(project_dir, str(paths["product_base"])), reasons

    for candidate in DEFAULT_PRODUCT_BASES:
        path = project_dir / candidate
        if path.exists():
            return path.resolve(), reasons

    return None, reasons


def _resolve_owned_path(project_dir: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (project_dir / candidate).resolve()
    project_resolved = project_dir.resolve()
    if not _is_relative_to(resolved, project_resolved):
        raise ValueError(f"product base escapes project root: {raw_path}")
    return resolved


def _frontmatter_status(path: Path) -> tuple[str, dict[str, Any] | None, str | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(errors="replace")
    if not text.startswith("---\n"):
        return "missing", None, None
    end = text.find("\n---", 4)
    if end == -1:
        return "parse_error", None, "frontmatter closing delimiter not found"
    raw = text[4:end]
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        return "parse_error", None, str(exc)
    if not isinstance(data, dict):
        return "parse_error", None, "frontmatter is not a mapping"
    return "present", data, None


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _nearest_epic_dir(path: Path, product_base: Path) -> str | None:
    """Walk ancestors from path up to product_base; return the first dir matching EPIC_DIR_RE."""
    try:
        rel = path.relative_to(product_base)
    except ValueError:
        return None
    parts = list(rel.parts)
    # Walk from innermost to outermost, skipping the filename itself
    for part in reversed(parts[:-1]):
        if EPIC_DIR_RE.match(part):
            return part
    return None


def _classify_and_collect(
    product_base: Path,
) -> tuple[
    list[str],          # derived_files (rel paths, sorted)
    list[str],          # supporting_docs (rel paths, sorted)
    list[dict],         # epics [{id, path}]
    list[dict],         # stories [{id, path, parent_epic, feature_file}]
]:
    """
    Walk the product base and classify every file into one of:
      - derived (backup): goes into derived_files, excluded from all counts
      - bespoke epic: EPIC-NNN.md inside an EPIC-NNN/ dir
      - bespoke story: US-* md inside an EPIC/BL dir
      - supporting doc: matches doc keywords, no work-item id in filename
      - work item: matches WORK_ITEM_RE (counted normally)
      - other: counted but not classified specially

    Returns four sorted lists.
    """
    derived_files: list[str] = []
    supporting_docs: list[str] = []
    epic_entries: list[dict] = []
    story_entries: list[dict] = []

    # Collect .feature files for pairing
    feature_paths: set[str] = set()

    all_files = [p for p in product_base.rglob("*") if p.is_file()]
    for p in all_files:
        if p.suffix.lower() == ".feature":
            feature_paths.add(_rel(p, product_base))

    for p in all_files:
        rel = _rel(p, product_base)

        # --- Derived/backup first (highest precedence) ---
        if is_derived_file(rel):
            derived_files.append(rel)
            continue

        # Only further classify .md files for epics/stories/docs
        if p.suffix.lower() != ".md":
            continue

        name = p.name
        parent_dir = p.parent

        # --- Bespoke epic: EPIC-NNN.md inside an EPIC-NNN/ dir ---
        epic_match = EPIC_FILE_RE.match(name)
        if epic_match:
            epic_id = epic_match.group(1)
            # Must be inside a dir named EPIC-NNN
            if parent_dir.name == epic_id:
                epic_entries.append({"id": epic_id, "path": rel})
                continue
            # EPIC-NNN.md not inside its own dir → fall through to other checks

        # --- Bespoke story: US-* inside an EPIC/BL dir ---
        if STORY_FILE_RE.match(name):
            parent_epic = _nearest_epic_dir(p, product_base)
            if parent_epic is not None:
                story_id = name[:-3]  # strip .md
                feature_rel = rel[:-3] + ".feature"  # same path but .feature
                feature_file = feature_rel if feature_rel in feature_paths else None
                story_entries.append({
                    "id": story_id,
                    "path": rel,
                    "parent_epic": parent_epic,
                    "feature_file": feature_file,
                })
                continue

        # --- Work-item id wins over doc keywords ---
        if WORK_ITEM_RE.match(name):
            continue  # counted in main loop; not a supporting doc

        # --- EPIC-NNN-index.md → supporting doc (not epic, not work item) ---
        # Also other known doc patterns
        if SUPPORTING_DOC_RE.search(name):
            supporting_docs.append(rel)
            continue

        # --- Loose lowercase narrative docs (e.g. epic-034-stories.md) ---
        # A file is a supporting doc if its name has no known work-item prefix
        # and starts with a lowercase letter (narrative/planning doc convention).
        if name[0].islower():
            supporting_docs.append(rel)
            continue

    return (
        sorted(derived_files),
        sorted(supporting_docs),
        sorted(epic_entries, key=lambda e: e["id"]),
        sorted(story_entries, key=lambda s: s["id"]),
    )


def characterize_project(project_dir: Path | str) -> dict[str, Any]:
    project = Path(project_dir).expanduser().resolve()
    if not project.exists():
        raise FileNotFoundError(f"project directory not found: {project}")
    if not project.is_dir():
        raise NotADirectoryError(f"project path is not a directory: {project}")

    product_base, product_base_notes = _resolve_product_base(project)
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "project_dir": str(project),
        "product_base": str(product_base) if product_base else None,
        "product_base_exists": bool(product_base and product_base.exists()),
        "notes": product_base_notes,
        "counts": {
            "product_files": 0,
            "markdown_files": 0,
            "prefixes": {},
            "top_level_dirs": {},
            "typed_backlog_dirs": {},
        },
        "frontmatter": {
            "present": 0,
            "missing": 0,
            "parse_errors": 0,
            "parse_error_files": [],
            "missing_files_sample": [],
        },
        "ids": {
            "unique_count": 0,
            "duplicate_count": 0,
            "duplicates": [],
            "derived_files": [],
        },
        "documents": {
            "supporting": [],
        },
        "items": {
            "epics": [],
            "stories": [],
        },
        "layout": {
            "has_backlog": False,
            "has_flat_backlog_items": False,
            "has_typed_backlog_dirs": False,
            "has_backlog_done_dir": False,
            "has_roadmap": False,
            "has_epics": False,
            "has_sprints": False,
            "unsupported_patterns": [],
        },
        "migration_risk": {
            "requires_manual_plan": False,
            "taxonomy_candidate_count": 0,
            "reasons": [],
        },
        "v4_compliance": {
            "old_prefix_count": 0,
            "v4_prefix_count": 0,
            "is_v4_only": False,
            "has_required_fields": True,
            "canonical_types_only": True,
            "no_duplicates": True,
            "standard_structure": False,
        },
    }

    if not product_base or not product_base.exists():
        result["migration_risk"]["requires_manual_plan"] = True
        result["migration_risk"]["reasons"].append("product-base-not-found")
        return result

    # Classify all files first (derived files excluded from counts)
    derived_files, supporting_docs, epic_entries, story_entries = _classify_and_collect(product_base)
    derived_set: set[str] = set(derived_files)

    product_files = [p for p in product_base.rglob("*") if p.is_file()]
    # markdown_files: .md files only, NOT derived
    markdown_files = [
        p for p in product_files
        if p.suffix.lower() == ".md" and _rel(p, product_base) not in derived_set
    ]
    prefix_counts: Counter[str] = Counter()
    top_level_counts: Counter[str] = Counter()
    typed_dir_counts: Counter[str] = Counter()
    id_to_files: dict[str, list[str]] = defaultdict(list)
    taxonomy_candidate_count = 0
    v4_prefix_count = 0
    flat_backlog_items = 0
    has_all_required_fields = True
    has_canonical_types_only = True
    required_fields_checked = False

    backlog_dir = product_base / "backlog"
    result["layout"]["has_backlog"] = backlog_dir.is_dir()
    result["layout"]["has_backlog_done_dir"] = (backlog_dir / "done").is_dir()
    result["layout"]["has_roadmap"] = (product_base / "roadmap").is_dir()
    result["layout"]["has_epics"] = (product_base / "epics").is_dir() or (product_base / "roadmap" / "epics").is_dir()
    result["layout"]["has_sprints"] = (product_base / "sprints").is_dir()

    supporting_set: set[str] = set(supporting_docs)

    for path in markdown_files:
        rel_path = _rel(path, product_base)
        parts = rel_path.split("/")
        if parts:
            top_level_counts[parts[0]] += 1

        match = WORK_ITEM_RE.match(path.name)
        if match:
            item_id = match.group("id")
            prefix = match.group("prefix")
            prefix_counts[prefix] += 1
            id_to_files[item_id].append(rel_path)
            if prefix in OLD_TAXONOMY_PREFIXES:
                taxonomy_candidate_count += 1
            if prefix in V4_TAXONOMY_PREFIXES:
                v4_prefix_count += 1
            if path.parent == backlog_dir:
                flat_backlog_items += 1

        if len(parts) >= 3 and parts[0] == "backlog" and parts[1] in TYPED_BACKLOG_DIRS:
            typed_dir_counts[parts[1]] += 1

        fm_status, fm_data, fm_error = _frontmatter_status(path)
        if fm_status == "present":
            result["frontmatter"]["present"] += 1
            if match and fm_data:
                required_fields_checked = True
                for req in ("id", "type", "title", "status"):
                    if fm_data.get(req) is None:
                        has_all_required_fields = False
                        break
                item_type = fm_data.get("type")
                if isinstance(item_type, str) and item_type not in CANONICAL_TYPES:
                    has_canonical_types_only = False
        elif fm_status == "missing":
            result["frontmatter"]["missing"] += 1
            if len(result["frontmatter"]["missing_files_sample"]) < 20:
                result["frontmatter"]["missing_files_sample"].append(rel_path)
        else:
            result["frontmatter"]["parse_errors"] += 1
            if len(result["frontmatter"]["parse_error_files"]) < 20:
                result["frontmatter"]["parse_error_files"].append({
                    "file": rel_path,
                    "error": fm_error or "unknown parse error",
                })

    duplicate_ids = [
        {"id": item_id, "files": sorted(files)}
        for item_id, files in sorted(id_to_files.items())
        if len(files) > 1
    ]

    # product_files count includes ALL files (derived included); markdown_files already excludes derived
    result["counts"]["product_files"] = len(product_files)
    result["counts"]["markdown_files"] = len(markdown_files)
    result["counts"]["prefixes"] = dict(sorted(prefix_counts.items()))
    result["counts"]["top_level_dirs"] = dict(sorted(top_level_counts.items()))
    result["counts"]["typed_backlog_dirs"] = dict(sorted(typed_dir_counts.items()))
    result["ids"]["unique_count"] = len(id_to_files)
    result["ids"]["duplicate_count"] = len(duplicate_ids)
    result["ids"]["duplicates"] = duplicate_ids
    result["ids"]["derived_files"] = derived_files
    result["documents"]["supporting"] = supporting_docs
    result["items"]["epics"] = epic_entries
    result["items"]["stories"] = story_entries
    result["layout"]["has_flat_backlog_items"] = flat_backlog_items > 0
    result["layout"]["has_typed_backlog_dirs"] = bool(typed_dir_counts)
    result["migration_risk"]["taxonomy_candidate_count"] = taxonomy_candidate_count

    no_duplicates = len(duplicate_ids) == 0
    is_v4_only = taxonomy_candidate_count == 0 and v4_prefix_count > 0
    standard_structure = (
        result["layout"]["has_backlog"]
        and not bool(typed_dir_counts)
        and result["frontmatter"]["parse_errors"] == 0
    )
    result["v4_compliance"] = {
        "old_prefix_count": taxonomy_candidate_count,
        "v4_prefix_count": v4_prefix_count,
        "is_v4_only": is_v4_only,
        "has_required_fields": has_all_required_fields if required_fields_checked else False,
        "canonical_types_only": has_canonical_types_only,
        "no_duplicates": no_duplicates,
        "standard_structure": standard_structure,
    }

    if typed_dir_counts:
        result["layout"]["unsupported_patterns"].append({
            "code": "typed-backlog-prefixes",
            "detail": "backlog contains typed subdirectories with legacy typed prefixes",
            "dirs": dict(sorted(typed_dir_counts.items())),
        })
        result["migration_risk"]["requires_manual_plan"] = True
        result["migration_risk"]["reasons"].append("typed-backlog-prefixes")

    if duplicate_ids:
        result["migration_risk"]["requires_manual_plan"] = True
        result["migration_risk"]["reasons"].append("duplicate-work-item-ids")

    if result["frontmatter"]["parse_errors"]:
        result["migration_risk"]["requires_manual_plan"] = True
        result["migration_risk"]["reasons"].append("frontmatter-parse-errors")

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only SweetClaude project characterization")
    parser.add_argument("--project-dir", default=".", help="Project directory to characterize")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    try:
        result = characterize_project(Path(args.project_dir))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
