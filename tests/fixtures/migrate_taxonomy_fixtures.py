"""
Shared fixtures for migrate_taxonomy tests.

All fixtures use tmp_path for real filesystem I/O — no mocks.
"""
import hashlib
import tarfile
import textwrap
import yaml
import pytest


# ---------------------------------------------------------------------------
# Path constants helpers
# ---------------------------------------------------------------------------

def product_base(project_dir):
    return project_dir / ".sweetclaude" / "product"


def backlog_dir(project_dir):
    return product_base(project_dir) / "backlog"


def done_dir(project_dir):
    return backlog_dir(project_dir) / "done"


def spike_dir(project_dir):
    return backlog_dir(project_dir) / "spike-reports"


def issues_dir(project_dir):
    return product_base(project_dir) / "issues"


def roadmap_dir(project_dir):
    return product_base(project_dir) / "roadmap"


def milestones_dir(project_dir):
    return product_base(project_dir) / "milestones"


def roadmap_issues_dir(project_dir):
    return roadmap_dir(project_dir) / "issues"


def roadmap_issues_done_dir(project_dir):
    return roadmap_issues_dir(project_dir) / "done"


def roadmap_milestones_dir(project_dir):
    return roadmap_dir(project_dir) / "milestones"


def roadmap_epics_dir(project_dir):
    return roadmap_dir(project_dir) / "epics"


def backlog_archived_dir(project_dir):
    return backlog_dir(project_dir) / "archived"


def archive_spikes_dir(project_dir):
    return product_base(project_dir) / "archive" / "spikes"


def state_dir(project_dir):
    return project_dir / ".sweetclaude" / "state"


def backups_dir(project_dir):
    return state_dir(project_dir) / "backups"


def artifact_privacy_path(project_dir):
    return project_dir / ".sweetclaude" / "artifact-privacy.yaml"


def migration_state_path(project_dir):
    return state_dir(project_dir) / "migration-state.yaml"


def collision_map_path(project_dir):
    return state_dir(project_dir) / "taxonomy-collision-map.yaml"


# ---------------------------------------------------------------------------
# Content helpers
# ---------------------------------------------------------------------------

def make_yaml_frontmatter_file(path, frontmatter: dict, body: str = ""):
    """Write a file with YAML frontmatter and optional body."""
    fm = yaml.safe_dump(frontmatter, default_flow_style=False).strip()
    content = f"---\n{fm}\n---\n\n{body}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def make_bold_format_file(path, title: str, fields: dict = None, body: str = ""):
    """Write a file using markdown bold metadata format."""
    lines = [f"# {title}", ""]
    for key, value in (fields or {}).items():
        lines.append(f"**{key}:** {value}")
    if fields:
        lines.append("")
    if body:
        lines.append(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))
    return path


# ---------------------------------------------------------------------------
# Core project fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def project_dir(tmp_path):
    """
    Minimal project directory with:
    - .sweetclaude/artifact-privacy.yaml pointing to default product base
    - All required subdirectory scaffolding under .sweetclaude/product/
    """
    # Write artifact-privacy.yaml with default product base
    sc_dir = tmp_path / ".sweetclaude"
    sc_dir.mkdir(parents=True)
    privacy = {"product": {"base_path": ".sweetclaude/product"}}
    (sc_dir / "artifact-privacy.yaml").write_text(yaml.safe_dump(privacy))

    # Create product subdirectories
    for d in [
        product_base(tmp_path) / "backlog" / "done",
        product_base(tmp_path) / "backlog" / "spike-reports",
        product_base(tmp_path) / "issues",
        product_base(tmp_path) / "roadmap",
        product_base(tmp_path) / "milestones",
        state_dir(tmp_path),
    ]:
        d.mkdir(parents=True, exist_ok=True)

    return tmp_path


# ---------------------------------------------------------------------------
# BL file helpers
# ---------------------------------------------------------------------------

def write_bl_file(project_dir, number: str, title: str, status: str = "open",
                  priority: str = "P2", epic: str = None, milestone: str = None,
                  depends_on=None, body: str = "", use_yaml: bool = False,
                  extra_fields: dict = None):
    """Write a BL file in backlog/."""
    slug = title.lower().replace(" ", "-") if title else number
    filename = f"BL-{number}-{slug}.md"
    path = backlog_dir(project_dir) / filename
    fm = {
        "id": f"BL-{number}",
        "title": title,
        "status": status,
        "priority": priority,
    }
    if epic:
        fm["epic"] = epic
    if milestone:
        fm["milestone"] = milestone
    if depends_on is not None:
        fm["depends_on"] = depends_on
    if extra_fields:
        fm.update(extra_fields)
    if use_yaml:
        make_yaml_frontmatter_file(path, fm, body)
    else:
        fields = {"Status": status, "Priority": priority}
        if epic:
            fields["Epic"] = epic
        if milestone:
            fields["Milestone"] = milestone
        if depends_on:
            fields["Depends-on"] = ", ".join(depends_on) if isinstance(depends_on, list) else depends_on
        make_bold_format_file(path, f"BL-{number}: {title}", fields, body)
    return path


def write_story_file(project_dir, number: str, title: str, status: str = "done",
                     extra_fields: dict = None):
    """Write a STORY file in backlog/done/."""
    slug = title.lower().replace(" ", "-")
    filename = f"STORY-{number}-{slug}.md"
    path = done_dir(project_dir) / filename
    fm = {"id": f"STORY-{number}", "title": title, "status": status}
    if extra_fields:
        fm.update(extra_fields)
    make_yaml_frontmatter_file(path, fm)
    return path
