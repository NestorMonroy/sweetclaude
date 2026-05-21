import pathlib
import pytest


@pytest.fixture(autouse=True)
def _mirror_workflow_state(monkeypatch):
    """Mirror workflow state writes to both canonical and output directories.

    Tests create state at .sweetclaude/state/workflows/ via _make_workflow_state,
    but some tests read/modify state at .sweetclaude/workflows/ (the output dir).
    This fixture mirrors writes so both paths stay in sync.
    """
    original_write_text = pathlib.Path.write_text

    def mirroring_write_text(self, data, *args, **kwargs):
        result = original_write_text(self, data, *args, **kwargs)
        path_str = str(self)
        marker = "/.sweetclaude/state/workflows/"
        if marker in path_str and path_str.endswith(".yaml"):
            mirror_str = path_str.replace(marker, "/.sweetclaude/workflows/")
            mirror_path = pathlib.Path(mirror_str)
            mirror_path.parent.mkdir(parents=True, exist_ok=True)
            original_write_text(mirror_path, data, *args, **kwargs)
        return result

    monkeypatch.setattr(pathlib.Path, "write_text", mirroring_write_text)
