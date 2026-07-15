"""cache.py must honor artifact-privacy base_path, like doctor does.

Root cause of the syncog empty-dashboard incident: cache.py hardcoded
.sweetclaude/product/ while artifact-privacy relocated the product base to
docs/product. A bridge symlink papered over the gap; deleting it blinded the
cache. Honoring base_path eliminates the divergence (and the need for the
symlink) for every relocated-base project.
"""
import sys
from pathlib import Path

import yaml

SCRIPTS_DIR = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import cache


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_scan_honors_relocated_base_path(tmp_path):
    _write(
        tmp_path / ".sweetclaude" / "artifact-privacy.yaml",
        yaml.safe_dump({"categories": {"product": {"base_path": "docs/product"}}}),
    )
    _write(tmp_path / "docs" / "product" / "backlog" / "ISSUE-001-x.md",
           "---\nid: ISSUE-001\ntitle: Relocated item\nstatus: open\n---\n")
    scanned = list(cache.scan_files(str(tmp_path)))
    assert any("ISSUE-001-x.md" in p for p in scanned), scanned


def test_scan_falls_back_to_default_base(tmp_path):
    # no artifact-privacy → default .sweetclaude/product
    _write(tmp_path / ".sweetclaude" / "product" / "backlog" / "ISSUE-002-y.md",
           "---\nid: ISSUE-002\ntitle: Default item\nstatus: open\n---\n")
    scanned = list(cache.scan_files(str(tmp_path)))
    assert any("ISSUE-002-y.md" in p for p in scanned), scanned


def test_rebuild_ingests_from_relocated_base(tmp_path):
    _write(
        tmp_path / ".sweetclaude" / "artifact-privacy.yaml",
        yaml.safe_dump({"categories": {"product": {"base_path": "docs/product"}}}),
    )
    _write(tmp_path / "docs" / "product" / "backlog" / "ISSUE-003-z.md",
           "---\nid: ISSUE-003\ntitle: Ingest me\nstatus: open\n---\n")
    result = cache.rebuild(str(tmp_path))
    assert result.get("scanned", 0) >= 1, result
