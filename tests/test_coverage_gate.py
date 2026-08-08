"""The coverage gate ratchets up, never down (ISSUE-254).

A gate that anyone can lower to make a red build green is not a gate. The
threshold lives in .coveragerc; RATCHET_FLOOR below is the highest value it has
ever held. Raising the gate is a one-line edit. Lowering it means editing this
constant too, which shows up in review as an explicit decision rather than a
quiet slide.
"""

from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]
COVERAGERC = REPO_ROOT / ".coveragerc"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "test.yml"

# Highest threshold the gate has held. Only ever increase this.
RATCHET_FLOOR = 80


def _fail_under() -> int:
    parser = configparser.ConfigParser()
    parser.read(COVERAGERC)
    return int(float(parser["report"]["fail_under"]))


def test_coveragerc_exists() -> None:
    assert COVERAGERC.is_file(), "coverage measurement needs an explicit source scope"


def test_source_is_scoped_to_the_repo() -> None:
    """Without this, pytest tmp fixtures that copy scripts/ into a temporary
    project are measured as repo files and the denominator drifts."""
    parser = configparser.ConfigParser()
    parser.read(COVERAGERC)
    assert parser["run"]["source"].strip() == "scripts"

    omit = parser["report"].get("omit", "") + parser["run"].get("omit", "")
    assert "pytest-of-" in omit, "tmp fixture projects must be omitted"


def test_gate_never_drops_below_the_ratchet_floor() -> None:
    current = _fail_under()
    assert current >= RATCHET_FLOOR, (
        f".coveragerc fail_under is {current}, below the ratchet floor of "
        f"{RATCHET_FLOOR}. Coverage gates move up, not down. If this is a "
        f"deliberate decision, lower RATCHET_FLOOR in this file in the same "
        f"commit and say why in the commit message."
    )


def test_ratchet_floor_tracks_the_gate() -> None:
    """Keeps the two from drifting apart — a gate far above the floor means
    the floor was never updated when coverage improved."""
    current = _fail_under()
    assert current - RATCHET_FLOOR <= 5, (
        f"fail_under ({current}) has moved well above RATCHET_FLOOR "
        f"({RATCHET_FLOOR}). Raise the floor to match."
    )


def test_ci_runs_coverage() -> None:
    """The gate is worthless if CI does not evaluate it."""
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "--cov" in workflow, (
        ".github/workflows/test.yml must run pytest with coverage enabled, "
        "otherwise .coveragerc fail_under is never enforced"
    )
