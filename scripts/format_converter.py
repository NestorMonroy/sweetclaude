#!/usr/bin/env python3
"""Convert Bold Key-Value format artifact files to YAML frontmatter."""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required", file=sys.stderr)
    sys.exit(1)

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from parse_utils import detect_format, parse_bold_metadata


_BODY_SECTION_PATTERN = re.compile(r"^## ", re.MULTILINE)


def _extract_body(content: str) -> str:
    m = _BODY_SECTION_PATTERN.search(content)
    if not m:
        return ""
    return content[m.start():]


def convert_content(content: str) -> str | None:
    if detect_format(content) != "bold":
        return None

    fm = parse_bold_metadata(content)
    if not fm:
        return None

    body = _extract_body(content)

    fm_text = yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False)
    parts = [f"---\n{fm_text}---\n"]
    if body:
        parts.append(f"\n{body}")
    return "".join(parts)


def convert_file(path: Path, *, dry_run: bool = False, backup: bool = True) -> dict:
    result = {"file": str(path), "action": "skip", "reason": ""}

    if not path.exists():
        result["reason"] = "file not found"
        return result

    content = path.read_text(encoding="utf-8")
    fmt = detect_format(content)

    if fmt != "bold":
        result["reason"] = f"format is {fmt}, not bold"
        return result

    converted = convert_content(content)
    if not converted:
        result["reason"] = "conversion failed"
        return result

    if dry_run:
        result["action"] = "would_convert"
        result["preview"] = converted[:500]
        return result

    if backup:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = path.with_suffix(f".bold-backup-{ts}.md")
        shutil.copy2(path, backup_path)
        result["backup"] = str(backup_path)

    path.write_text(converted, encoding="utf-8")
    result["action"] = "converted"
    return result


def convert_project(project_dir: Path, *, dry_run: bool = False, backup: bool = True) -> list[dict]:
    results = []

    privacy_path = project_dir / ".sweetclaude" / "artifact-privacy.yaml"
    product_base = project_dir / ".sweetclaude" / "product"
    if privacy_path.exists():
        try:
            d = yaml.safe_load(privacy_path.read_text()) or {}
            bp = d.get("categories", {}).get("product", {}).get("base_path", "")
            if bp:
                product_base = project_dir / bp
        except Exception:
            pass

    scan_dirs = [
        product_base / "backlog",
        product_base / "roadmap",
        product_base / "epics",
        product_base / "sprints",
        product_base / "themes",
        product_base / "milestones",
        product_base / "pitches",
        product_base / "cycles",
    ]

    seen: set[str] = set()
    for scan_dir in scan_dirs:
        if not scan_dir.is_dir():
            continue
        for p in scan_dir.rglob("*.md"):
            real = str(p.resolve())
            if real in seen:
                continue
            seen.add(real)
            if p.name in ("INDEX.md", "MIGRATION-MAP.md") or p.name.endswith("-INDEX.md"):
                continue
            result = convert_file(p, dry_run=dry_run, backup=backup)
            if result["action"] != "skip":
                results.append(result)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert Bold-format artifacts to YAML frontmatter")
    parser.add_argument("--file", type=Path, help="Convert a single file")
    parser.add_argument("--project-dir", type=Path, help="Convert all Bold-format files in a project")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be converted without writing")
    parser.add_argument("--backup", action="store_true", default=True, help="Create backup before converting (default: true)")
    parser.add_argument("--no-backup", action="store_true", help="Skip backup creation")
    args = parser.parse_args()

    backup = not args.no_backup

    if args.file:
        result = convert_file(args.file, dry_run=args.dry_run, backup=backup)
        print(f"{result['action']}: {result['file']}")
        if result.get("backup"):
            print(f"  backup: {result['backup']}")
        if result.get("reason"):
            print(f"  reason: {result['reason']}")
    elif args.project_dir:
        results = convert_project(args.project_dir, dry_run=args.dry_run, backup=backup)
        if not results:
            print("No Bold-format files found.")
        for r in results:
            print(f"{r['action']}: {r['file']}")
            if r.get("backup"):
                print(f"  backup: {r['backup']}")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
