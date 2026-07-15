"""Regression lock: the orphan scan must not flag correctly-placed
current-taxonomy ISSUE-*.md files as orphans.

Before the fix, scan_orphans whitelisted only legacy BL-*.md in backlog/, so a
fully-migrated project reported its entire ISSUE backlog as "stray-file"
orphans — inflating orphan_count and firing a spurious "recovery disabled / no
files changed" prompt on every sweetclaude:update.
"""
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "migrate" / "migrate-v3-to-v4.py"


def _scan(project_dir):
    out = subprocess.run(
        ["python3", str(SCRIPT), "scan-orphans", "--project-dir", str(project_dir)],
        capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _item(path, item_id, status="new"):
    path.write_text(f"---\nid: {item_id}\ntitle: {item_id}\nstatus: {status}\n---\n\nbody\n")


def _migrated_project(tmp_path):
    backlog = tmp_path / ".sweetclaude" / "product" / "backlog"
    (backlog / "done").mkdir(parents=True)
    _item(backlog / "ISSUE-001-active.md", "ISSUE-001")
    _item(backlog / "ISSUE-002-active.md", "ISSUE-002")
    _item(backlog / "done" / "ISSUE-003-done.md", "ISSUE-003", status="done")
    return tmp_path


def test_migrated_backlog_reports_zero_orphans(tmp_path):
    result = _scan(_migrated_project(tmp_path))
    assert result["orphan_count"] == 0, result["findings"]


def test_genuinely_stray_file_still_flagged_without_false_positives(tmp_path):
    project = _migrated_project(tmp_path)
    _item(project / ".sweetclaude" / "product" / "BL-009-old-draft.md", "BL-009")
    result = _scan(project)
    ids = {f["id"] for f in result["findings"]}
    assert "BL-009" in ids, "a real stray file must still be flagged"
    assert {"ISSUE-001", "ISSUE-002", "ISSUE-003"}.isdisjoint(ids), (
        "correctly-placed ISSUE files must not be flagged"
    )
