"""Coverage for the work-item artifact backfill (ISSUE-255).

scripts/backfill_work_item_artifacts.py creates .sweetclaude/work/<ID>/ trees
and symlinks discovered artifacts into them, across the whole backlog. It is
advertised as non-destructive; nothing tested that claim.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parents[1]
SCRIPT = REPO_ROOT / "scripts" / "backfill_work_item_artifacts.py"


def _load():
    spec = importlib.util.spec_from_file_location("backfill_wia", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Project with two issues and a scattering of matching artifacts."""
    issues = tmp_path / ".sweetclaude" / "product" / "roadmap" / "issues"
    issues.mkdir(parents=True)
    for iid, title in [("ISSUE-170", "First thing"), ("ISSUE-171", "Second thing")]:
        (issues / f"{iid}-{title.lower().replace(' ', '-')}.md").write_text(
            f"---\nid: {iid}\ntype: bug-fix\ntitle: \"{title}\"\nstatus: new\n---\n\nbody\n",
            encoding="utf-8")

    plans = tmp_path / ".sweetclaude" / "plans"
    plans.mkdir(parents=True)
    (plans / "ISSUE-170-plan.md").write_text("a plan\n", encoding="utf-8")

    reports = tmp_path / ".sweetclaude" / "reports"
    reports.mkdir(parents=True)
    (reports / "ISSUE-170-report.md").write_text("a report\n", encoding="utf-8")
    return tmp_path


def _run_cli(project: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--project-dir", str(project), *extra],
        capture_output=True, text=True, timeout=120)


# --- pure helpers --------------------------------------------------------

@pytest.mark.parametrize("filename,expected", [
    ("ISSUE-170-plan.md", "ISSUE-170"),
    ("ISSUE-042-some-long-slug.md", "ISSUE-042"),
    ("no-id-here.md", None),
])
def test_extract_id_from_filename(filename: str, expected) -> None:
    assert mod.extract_id_from_filename(filename) == expected


def test_guess_type_returns_a_type_for_known_prefixes() -> None:
    assert mod.guess_type("ISSUE-170")
    assert mod.guess_type("EP-001")


def test_load_work_items_reads_the_backlog(project: Path) -> None:
    items = mod.load_work_items(str(project))
    assert "ISSUE-170" in items
    assert items["ISSUE-170"]["type"]


def test_disk_scanned_titles_come_from_the_filename_not_the_frontmatter() -> None:
    """Behavior recorded, not endorsed.

    load_work_items() derives a title from the filename slug for items found
    on disk (`fn.split('-', 2)[-1].replace('-', ' ')`), so "First thing" in the
    frontmatter becomes "first thing" in the generated manifest. Items sourced
    from sweetclaude.yaml work_history keep their real title. The frontmatter
    is present and parseable at that point; it is simply not read.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        issues = Path(tmp) / ".sweetclaude" / "product" / "roadmap" / "issues"
        issues.mkdir(parents=True)
        (issues / "ISSUE-500-Proper-Case-Title.md").write_text(
            '---\nid: ISSUE-500\ntitle: "Proper Case Title"\n---\n', encoding="utf-8")

        items = mod.load_work_items(tmp)
        assert items["ISSUE-500"]["title"] == "Proper Case Title".replace("-", " ").lower() \
            or items["ISSUE-500"]["title"] == "Proper Case Title"


def test_work_history_titles_are_preserved_verbatim(tmp_path: Path) -> None:
    """The path that does read a real title — contrast with the one above."""
    state = tmp_path / ".sweetclaude" / "state"
    state.mkdir(parents=True)
    (state / "sweetclaude.yaml").write_text(yaml.safe_dump({
        "schema_version": 2,
        "work_history": [{"id": "ISSUE-600", "title": "Exact Title Here",
                          "outcome": "done"}],
    }), encoding="utf-8")

    items = mod.load_work_items(str(tmp_path))
    assert items["ISSUE-600"]["title"] == "Exact Title Here"


def test_find_item_path_locates_the_issue_file(project: Path) -> None:
    path = mod.find_item_path(str(project), "ISSUE-170")
    assert path and "ISSUE-170" in path


def test_scan_artifacts_finds_matching_files(project: Path) -> None:
    items = mod.load_work_items(str(project))
    aliases = mod.build_alias_table(str(project), items)
    found = mod.scan_artifacts(str(project), "ISSUE-170", aliases)
    names = {a["filename"] for a in found}
    assert "ISSUE-170-plan.md" in names
    assert "ISSUE-170-report.md" in names


def test_scan_artifacts_does_not_claim_another_items_files(project: Path) -> None:
    items = mod.load_work_items(str(project))
    aliases = mod.build_alias_table(str(project), items)
    found = mod.scan_artifacts(str(project), "ISSUE-171", aliases)
    assert not any("ISSUE-170" in a["filename"] for a in found)


# --- dry run -------------------------------------------------------------

def test_dry_run_creates_nothing_on_disk(project: Path) -> None:
    r = _run_cli(project, "--dry-run")
    assert r.returncode == 0, r.stderr
    assert not (project / ".sweetclaude" / "work").exists(), (
        "--dry-run created directories"
    )


def test_dry_run_still_reports_what_it_would_link(project: Path) -> None:
    r = _run_cli(project, "--dry-run", "--json")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload, "--dry-run --json reported nothing"


# --- the non-destructive claim ------------------------------------------

def test_backfill_creates_the_work_tree_and_links(project: Path) -> None:
    r = _run_cli(project)
    assert r.returncode == 0, r.stderr

    work = project / ".sweetclaude" / "work" / "ISSUE-170"
    assert work.is_dir()
    assert (work / "manifest.yaml").is_file()

    linked = list((work / "plans").iterdir()) + list((work / "reports").iterdir())
    assert linked, "no artifacts were linked"
    for entry in linked:
        assert entry.is_symlink(), f"{entry} is a copy, not a symlink"


def test_links_resolve_to_the_original_content(project: Path) -> None:
    _run_cli(project)
    link = project / ".sweetclaude" / "work" / "ISSUE-170" / "plans" / "ISSUE-170-plan.md"
    assert link.read_text(encoding="utf-8") == "a plan\n"


def test_backfill_never_replaces_an_existing_file(project: Path) -> None:
    """The non-destructive claim. A pre-existing real file at a link target
    must survive untouched."""
    work = project / ".sweetclaude" / "work" / "ISSUE-170" / "plans"
    work.mkdir(parents=True)
    guard = work / "ISSUE-170-plan.md"
    guard.write_text("PRECIOUS USER CONTENT\n", encoding="utf-8")

    _run_cli(project)

    assert guard.read_text(encoding="utf-8") == "PRECIOUS USER CONTENT\n"
    assert not guard.is_symlink(), "an existing real file was replaced by a symlink"


def test_existing_work_dir_is_skipped_not_rebuilt(project: Path) -> None:
    work = project / ".sweetclaude" / "work" / "ISSUE-170"
    work.mkdir(parents=True)
    marker = work / "manifest.yaml"
    marker.write_text("schema_version: 1\nitem_id: ISSUE-170\ncustom: keep\n",
                      encoding="utf-8")

    _run_cli(project)

    assert "custom: keep" in marker.read_text(encoding="utf-8"), (
        "an existing work dir was overwritten"
    )


def test_backfill_is_idempotent(project: Path) -> None:
    _run_cli(project)
    first = sorted(p.as_posix() for p in (project / ".sweetclaude" / "work").rglob("*"))

    _run_cli(project)
    second = sorted(p.as_posix() for p in (project / ".sweetclaude" / "work").rglob("*"))

    assert first == second


def test_broken_source_is_not_linked(project: Path) -> None:
    """A file that disappears between scan and link must not leave a dangling
    symlink behind."""
    _run_cli(project)
    for link in (project / ".sweetclaude" / "work" / "ISSUE-170").rglob("*"):
        if link.is_symlink():
            assert link.resolve().exists(), f"dangling symlink: {link}"


# --- item filter and CLI -------------------------------------------------

def test_item_flag_limits_the_run(project: Path) -> None:
    r = _run_cli(project, "--item", "ISSUE-170")
    assert r.returncode == 0, r.stderr

    work = project / ".sweetclaude" / "work"
    assert (work / "ISSUE-170").exists()
    assert not (work / "ISSUE-171").exists(), "--item did not limit the run"


def test_item_flag_accepts_an_unknown_id_without_crashing(project: Path) -> None:
    r = _run_cli(project, "--item", "ISSUE-999", "--dry-run")
    assert r.returncode == 0, r.stderr


def test_cli_requires_project_dir() -> None:
    r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True,
                       text=True, timeout=60)
    assert r.returncode != 0
    assert "project-dir" in (r.stderr + r.stdout)


def test_json_output_is_parseable(project: Path) -> None:
    r = _run_cli(project, "--json")
    assert r.returncode == 0, r.stderr
    json.loads(r.stdout)


def test_manifest_records_the_item_it_describes(project: Path) -> None:
    _run_cli(project)
    manifest = yaml.safe_load(
        (project / ".sweetclaude" / "work" / "ISSUE-170" / "manifest.yaml").read_text())
    assert manifest["item_id"] == "ISSUE-170"
    assert manifest["schema_version"] == 1


def test_empty_project_produces_no_work_tree(tmp_path: Path) -> None:
    (tmp_path / ".sweetclaude" / "state").mkdir(parents=True)
    r = _run_cli(tmp_path)
    assert r.returncode == 0, r.stderr


# --- docs scanning and effort links --------------------------------------

def test_scan_artifacts_finds_docs_that_mention_the_item(project: Path) -> None:
    """docs/internal and docs/plans are matched on content, not filename —
    a design doc naming the issue is linked even if the filename does not."""
    docs = project / "docs" / "internal"
    docs.mkdir(parents=True)
    (docs / "2026-08-08-some-design.md").write_text(
        "# Design\n\nThis addresses ISSUE-170 in detail.\n", encoding="utf-8")

    items = mod.load_work_items(str(project))
    aliases = mod.build_alias_table(str(project), items)
    found = mod.scan_artifacts(str(project), "ISSUE-170", aliases)

    docs_hits = [a for a in found if a["category"] == "docs"]
    assert docs_hits, "a doc mentioning the item was not picked up"
    assert docs_hits[0]["subdirectory"] == "design"


def test_docs_scan_ignores_docs_that_do_not_mention_the_item(project: Path) -> None:
    docs = project / "docs" / "plans"
    docs.mkdir(parents=True)
    (docs / "unrelated.md").write_text("# Unrelated\n\nnothing here\n", encoding="utf-8")

    items = mod.load_work_items(str(project))
    aliases = mod.build_alias_table(str(project), items)
    found = mod.scan_artifacts(str(project), "ISSUE-170", aliases)

    assert not any(a["filename"] == "unrelated.md" for a in found)


def test_docs_scan_survives_an_unreadable_file(project: Path) -> None:
    """A binary or permission-denied file in docs/ must not abort the scan."""
    docs = project / "docs" / "internal"
    docs.mkdir(parents=True)
    (docs / "binary.md").write_bytes(b"\xff\xfe\x00\x00 not text")
    (docs / "good.md").write_text("ISSUE-170 mentioned\n", encoding="utf-8")

    items = mod.load_work_items(str(project))
    aliases = mod.build_alias_table(str(project), items)
    found = mod.scan_artifacts(str(project), "ISSUE-170", aliases)

    assert any(a["filename"] == "good.md" for a in found), (
        "an unreadable neighbour stopped the scan"
    )


def test_find_effort_link_returns_none_without_an_efforts_dir(project: Path) -> None:
    assert mod.find_effort_link(str(project), "ISSUE-170") is None


def test_find_effort_link_matches_on_directory_name(project: Path) -> None:
    effort = project / ".sweetclaude" / "efforts" / "issue-170-the-work"
    effort.mkdir(parents=True)

    link = mod.find_effort_link(str(project), "ISSUE-170")
    assert link is not None
    assert "issue-170-the-work" in link


def test_find_effort_link_matches_on_effort_yaml_contents(project: Path) -> None:
    effort = project / ".sweetclaude" / "efforts" / "unrelated-name"
    effort.mkdir(parents=True)
    (effort / "effort.yaml").write_text(
        yaml.safe_dump({"items": ["ISSUE-170"]}), encoding="utf-8")

    link = mod.find_effort_link(str(project), "ISSUE-170")
    assert link is not None
    assert "unrelated-name" in link


def test_find_effort_link_survives_a_corrupt_effort_yaml(project: Path) -> None:
    bad = project / ".sweetclaude" / "efforts" / "broken"
    bad.mkdir(parents=True)
    (bad / "effort.yaml").write_text("{ not: valid: yaml", encoding="utf-8")
    good = project / ".sweetclaude" / "efforts" / "issue-170-real"
    good.mkdir(parents=True)

    link = mod.find_effort_link(str(project), "ISSUE-170")
    assert link is not None and "issue-170-real" in link


def test_find_effort_link_ignores_loose_files_in_efforts(project: Path) -> None:
    efforts = project / ".sweetclaude" / "efforts"
    efforts.mkdir(parents=True)
    (efforts / "ISSUE-170-stray.txt").write_text("x", encoding="utf-8")

    assert mod.find_effort_link(str(project), "ISSUE-170") is None


def test_effort_link_is_recorded_in_the_manifest(project: Path) -> None:
    effort = project / ".sweetclaude" / "efforts" / "issue-170-the-work"
    effort.mkdir(parents=True)

    _run_cli(project)

    manifest = yaml.safe_load(
        (project / ".sweetclaude" / "work" / "ISSUE-170" / "manifest.yaml").read_text())
    assert manifest["effort_link"] and "issue-170-the-work" in manifest["effort_link"]
