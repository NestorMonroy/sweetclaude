"""re_adopt: the universal no-data-loss terminal fallback doctor's totality
classifier promises. Archives SweetClaude state aside (reversible) so a project
can be re-onboarded, without touching source or relocated artifacts.
"""
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from recovery import re_adopt


def _project(tmp_path):
    p = tmp_path / "proj"
    (p / ".sweetclaude" / "state").mkdir(parents=True)
    (p / ".sweetclaude" / "state" / "phase.yaml").write_text("schema_version: 2\n")
    (p / ".sweetclaude" / "artifact-privacy.yaml").write_text(
        "categories:\n  product:\n    base_path: docs/product\n")
    (p / "docs" / "product" / "backlog").mkdir(parents=True)
    (p / "docs" / "product" / "backlog" / "ISSUE-001.md").write_text("---\nid: ISSUE-001\n---\n")
    (p / "src").mkdir()
    (p / "src" / "app.py").write_text("print('hi')\n")
    return p


def test_plan_is_read_only_and_reports_what_will_move(tmp_path):
    p = _project(tmp_path)
    plan = re_adopt.plan_re_adopt(p)
    assert plan["ok"]
    assert plan["archives"] == [".sweetclaude"]
    assert plan["no_data_loss"] is True
    assert plan["reversible"] is True
    # planning touches nothing
    assert (p / ".sweetclaude").is_dir()
    assert not list(p.glob(".sweetclaude.legacy*"))


def test_execute_archives_state_preserving_every_file(tmp_path):
    p = _project(tmp_path)
    before = {str(f.relative_to(p / ".sweetclaude"))
              for f in (p / ".sweetclaude").rglob("*") if f.is_file()}
    result = re_adopt.execute_re_adopt(p)
    assert result["ok"]
    legacy = Path(result["legacy_path"])
    assert legacy.exists()
    # .sweetclaude cleared from root (fresh slate for re-onboarding)
    assert not (p / ".sweetclaude").exists()
    # every original file preserved in the archive — no data loss
    after = {str(f.relative_to(legacy / ".sweetclaude"))
             for f in (legacy / ".sweetclaude").rglob("*") if f.is_file()}
    assert after == before


def test_execute_leaves_source_and_relocated_artifacts_untouched(tmp_path):
    p = _project(tmp_path)
    re_adopt.execute_re_adopt(p)
    assert (p / "src" / "app.py").read_text() == "print('hi')\n"
    assert (p / "docs" / "product" / "backlog" / "ISSUE-001.md").exists()


def test_reverse_restores_state(tmp_path):
    p = _project(tmp_path)
    result = re_adopt.execute_re_adopt(p)
    re_adopt.reverse_re_adopt(p, result["legacy_path"])
    assert (p / ".sweetclaude" / "state" / "phase.yaml").exists()
    assert not (p / ".sweetclaude").is_symlink()


def test_execute_refuses_if_no_sweetclaude(tmp_path):
    p = tmp_path / "empty"
    p.mkdir()
    result = re_adopt.execute_re_adopt(p)
    assert result["ok"] is False
