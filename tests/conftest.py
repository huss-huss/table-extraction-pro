import copy

import pytest

from tests.fixtures.generate import FIXTURES, render_all


@pytest.fixture(scope="session")
def fixture_pdfs(tmp_path_factory):
    """Render every fixture spec to a PDF once per test session."""
    return render_all(tmp_path_factory.mktemp("pdfs"))


@pytest.fixture(scope="session")
def fixture_specs():
    return {spec.name: spec for spec in FIXTURES}


def make_table(data, table_id=1, page=1, parser="tatr", confidence=0.9):
    """A table dict shaped like the pipeline / fallback parser output."""
    metadata = {"parser": parser, "num_rows": len(data), "num_columns": len(data[0]) if data else 0}
    if parser == "tatr":
        metadata["confidence"] = confidence
    return {
        "table_id": table_id,
        "page_number": page,
        "data": copy.deepcopy(data),
        "metadata": metadata,
        "structure": {
            "num_rows": len(data),
            "num_columns": len(data[0]) if data else 0,
            "rows": [],
            "columns": [],
        },
        "detection": {"bbox": [0, 0, 0, 0], "confidence": confidence, "class": "table"},
    }
