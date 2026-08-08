"""Unit coverage for the v1 to v2 migration handlers (ISSUE-253).

These three handlers rewrite project state and had zero coverage. Each exposes
up() and down(); down() is documented as lossy, so these tests lock exactly
what survives a reverse and exactly what is dropped. A future change that
silently drops more fails here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]
MIGRATIONS = REPO_ROOT / "scripts" / "migrations"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, MIGRATIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


phase_h = _load("phase_yaml_v1_to_v2")
skills_h = _load("skills_yaml_v1_to_v2")
sc_h = _load("sweetclaude_yaml_v1_to_v2")

ALL_HANDLERS = [
    pytest.param(phase_h, id="phase_yaml"),
    pytest.param(skills_h, id="skills_yaml"),
    pytest.param(sc_h, id="sweetclaude_yaml"),
]


# --- contract shared by every handler ------------------------------------

@pytest.mark.parametrize("handler", ALL_HANDLERS)
def test_handler_declares_version_contract(handler) -> None:
    assert handler.FROM_VERSION == 1
    assert handler.TO_VERSION == 2
    assert isinstance(handler.FILE_KEY, str) and handler.FILE_KEY.endswith(".yaml")


@pytest.mark.parametrize("handler", ALL_HANDLERS)
def test_up_stamps_target_schema_version(handler) -> None:
    out = handler.up({}, None)
    assert out["schema_version"] == 2


@pytest.mark.parametrize("handler", ALL_HANDLERS)
def test_down_stamps_source_schema_version(handler) -> None:
    out = handler.down(handler.up({}, None), None)
    assert out["schema_version"] == 1


@pytest.mark.parametrize("handler", ALL_HANDLERS)
def test_up_tolerates_empty_and_missing_fields(handler) -> None:
    """A v1 file in the wild may be missing anything. up() must not raise."""
    assert handler.up({}, None)["schema_version"] == 2
    assert handler.up({}, {})["schema_version"] == 2


@pytest.mark.parametrize("handler", ALL_HANDLERS)
def test_up_does_not_mutate_its_input(handler) -> None:
    """The runner reads, migrates, then writes. Mutating the input in place
    would corrupt any caller that still holds the pre-migration document."""
    data = {"schema_version": 1, "deference_level": "autonomous"}
    before = dict(data)
    handler.up(data, None)
    assert data == before


# --- phase.yaml ----------------------------------------------------------

def test_phase_up_maps_v1_shape_to_v2() -> None:
    v1 = {
        "schema_version": 1,
        "phase": "IMPLEMENT",
        "work_type": "refactor",
        "deference_level": "autonomous",
        "project_type": "existing-code",
        "safety_snapshot": "pre-sweetclaude",
    }
    out = phase_h.up(v1, {"version_stage": "GA"})

    assert out["schema_version"] == 2
    assert out["version_stage"] == "GA"
    assert out["deference_level"] == "autonomous"
    assert out["safety_snapshot"] == "pre-sweetclaude"
    assert out["active_work_item"]["type"] == "tech-debt"
    assert out["active_work_item"]["phase"] == "IMPLEMENT"
    assert out["last_work_item_id"] is None


def test_phase_up_defaults_version_stage_to_beta() -> None:
    assert phase_h.up({}, None)["version_stage"] == "BETA"
    assert phase_h.up({}, {})["version_stage"] == "BETA"


@pytest.mark.parametrize("terminal", ["SHIP", "DONE", "ship", "done"])
def test_phase_up_treats_terminal_phases_as_no_active_work(terminal) -> None:
    out = phase_h.up({"phase": terminal}, None)
    assert out["active_work_item"]["phase"] is None


def test_phase_up_drops_unknown_work_type_rather_than_guessing() -> None:
    """An unmapped v1 work_type becomes None. Locking this so the silent drop
    is a decision on record, not an accident."""
    out = phase_h.up({"work_type": "not-a-real-type"}, None)
    assert out["active_work_item"]["type"] is None


@pytest.mark.parametrize("v1,v2", list(phase_h.WORK_TYPE_MAP.items()))
def test_phase_work_type_map_round_trips(v1, v2) -> None:
    up = phase_h.up({"work_type": v1}, None)
    assert up["active_work_item"]["type"] == v2
    assert phase_h.down(up, None)["work_type"] == v1


def test_phase_down_is_lossy_in_exactly_the_documented_way() -> None:
    v2 = phase_h.up(
        {"phase": "DESIGN", "work_type": "bug-fix", "deference_level": "guided"},
        {"version_stage": "GA"},
    )
    v2["last_work_item_id"] = "ISSUE-042"
    v2["active_work_item"]["id"] = "ISSUE-042"
    v2["active_work_item"]["title"] = "something"

    down = phase_h.down(v2, None)

    assert down["phase"] == "DESIGN"
    assert down["work_type"] == "bug-fix"
    assert down["deference_level"] == "guided"
    # Documented losses.
    for dropped in ("version_stage", "last_work_item_id", "active_work_item"):
        assert dropped not in down


def test_phase_down_survives_absent_active_work_item() -> None:
    assert phase_h.down({"schema_version": 2}, None)["phase"] is None


# --- skills.yaml ---------------------------------------------------------

def test_skills_up_produces_v2_document() -> None:
    out = skills_h.up({"schema_version": 1}, None)
    assert out["schema_version"] == 2


def test_skills_down_returns_to_v1() -> None:
    out = skills_h.down(skills_h.up({"schema_version": 1}, None), None)
    assert out["schema_version"] == 1


def test_skills_up_maps_enabled_true_to_active() -> None:
    out = skills_h.up(
        {"schema_version": 1, "backlog": {"enabled": True, "onboarded_at": "2026-01-02"}},
        {"today": "2026-08-08"},
    )
    assert out["backlog"] == {
        "status": "active",
        "last_changed_at": "2026-01-02",
        "last_changed_by": "migrated",
    }


def test_skills_up_maps_disabled_but_previously_onboarded_to_paused() -> None:
    out = skills_h.up(
        {"backlog": {"enabled": False, "onboarded_at": "2026-01-02",
                     "offboarded_at": "2026-03-04"}},
        {"today": "2026-08-08"},
    )
    assert out["backlog"]["status"] == "paused"
    assert out["backlog"]["last_changed_at"] == "2026-03-04"


def test_skills_up_falls_back_to_onboarded_at_when_offboarded_missing() -> None:
    out = skills_h.up(
        {"backlog": {"enabled": False, "onboarded_at": "2026-01-02"}},
        {"today": "2026-08-08"},
    )
    assert out["backlog"]["last_changed_at"] == "2026-01-02"


def test_skills_up_maps_never_onboarded_to_uninitialized() -> None:
    out = skills_h.up({"backlog": {"enabled": False}}, {"today": "2026-08-08"})
    assert out["backlog"] == {
        "status": "uninitialized",
        "last_changed_at": None,
        "last_changed_by": None,
    }


def test_skills_up_stamps_today_when_no_timestamp_exists() -> None:
    out = skills_h.up({"backlog": {"enabled": True}}, {"today": "2026-08-08"})
    assert out["backlog"]["last_changed_at"] == "2026-08-08"


def test_skills_up_preserves_unrelated_entry_keys() -> None:
    """Projects can carry their own keys on a skill entry; migration must not
    silently drop them."""
    out = skills_h.up(
        {"backlog": {"enabled": True, "onboarded_at": "2026-01-02", "note": "keep me"}},
        {"today": "2026-08-08"},
    )
    assert out["backlog"]["note"] == "keep me"


def test_skills_up_passes_through_non_dict_top_level_values() -> None:
    out = skills_h.up({"schema_version": 1, "stray": "scalar"}, {"today": "2026-08-08"})
    assert out["stray"] == "scalar"


def test_skills_up_generates_a_timestamp_without_params() -> None:
    """The _today() default path — exercised only when no override is given."""
    out = skills_h.up({"backlog": {"enabled": True}}, None)
    assert out["backlog"]["last_changed_at"]


@pytest.mark.parametrize(
    "status,enabled", [("active", True), ("paused", False), ("uninitialized", False)]
)
def test_skills_down_collapses_v2_statuses(status, enabled) -> None:
    v2 = {"schema_version": 2,
          "backlog": {"status": status, "last_changed_at": "2026-01-02",
                      "last_changed_by": "migrated"}}
    out = skills_h.down(v2, None)
    assert out["backlog"]["enabled"] is enabled


# --- sweetclaude.yaml ----------------------------------------------------

def test_sweetclaude_up_produces_v2_document() -> None:
    out = sc_h.up({"schema_version": 1}, None)
    assert out["schema_version"] == 2


def test_sweetclaude_down_returns_to_v1() -> None:
    out = sc_h.down(sc_h.up({"schema_version": 1}, None), None)
    assert out["schema_version"] == 1


@pytest.mark.parametrize(
    "raw,expected",
    [("1.2.3", (1, 2, 3)), ("v1.2.3", (1, 2, 3)), ("4.5.2", (4, 5, 2))],
)
def test_sweetclaude_semver_tuple_parses_known_forms(raw, expected) -> None:
    assert sc_h._semver_tuple(raw)[:3] == expected


@pytest.mark.parametrize("junk", ["", None, "not-a-version", "abc.def"])
def test_sweetclaude_semver_tuple_survives_junk(junk) -> None:
    """Version strings come off disk and can be anything. Must not raise."""
    sc_h._semver_tuple(junk)
