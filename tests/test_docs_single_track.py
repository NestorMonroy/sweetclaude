"""Single user-guide track (ISSUE-238): the versioned 3.x / 4.x-beta doc
tracks are consolidated to docs/user-guide/ root on this branch. stable-3.x
users read docs from the stable-3.x branch."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "user-guide"


def _tracked_files():
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True
    )
    return [ROOT / line for line in out.stdout.splitlines() if line]


def test_no_track_subdirectories():
    assert not (GUIDE / "3.x").exists(), "3.x doc track must not exist on this branch"
    assert not (GUIDE / "4.x-beta").exists(), "4.x-beta doc track must be promoted to root"


def test_no_references_to_versioned_doc_tracks():
    offenders = []
    for f in _tracked_files():
        if f.suffix not in (".md", ".py", ".yml", ".yaml", ".sh", ".json"):
            continue
        if f.name == "test_docs_single_track.py":
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "user-guide/3.x" in text or "user-guide/4.x-beta" in text:
            offenders.append(str(f.relative_to(ROOT)))
    assert offenders == [], f"stale versioned doc-track references: {offenders}"


def test_user_guide_relative_links_resolve():
    link_re = re.compile(r"\]\(([^)#\s]+)(?:#[^)\s]*)?\)")
    broken = []
    for f in GUIDE.glob("*.md"):
        for target in link_re.findall(f.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = (f.parent / target).resolve()
            if not resolved.exists():
                broken.append(f"{f.name} -> {target}")
    assert broken == [], f"broken relative links in user guide: {broken}"


def test_root_guide_is_content_not_stubs():
    for name in ("quickstart.md", "install.md", "doctor.md",
                 "evidence-and-contracts.md", "index.md"):
        f = GUIDE / name
        assert f.is_file(), f"{name} missing from consolidated guide"
        text = f.read_text(encoding="utf-8")
        assert "moved into the separate SweetClaude user-guide tracks" not in text, (
            f"{name} is still a redirect stub"
        )
