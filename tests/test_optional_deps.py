import subprocess
import sys

import pytest

from table_extraction import MissingDependencyError, TableExtractionPipeline
from table_extraction._deps import require
from table_extraction.parsers import parser_comparator
from table_extraction.parsers.parser_comparator import ParserComparator


def test_base_import_does_not_pull_heavy_backends():
    code = (
        "import sys, table_extraction, table_extraction.cli.main, table_extraction.api.main\n"
        "heavy = [m for m in ('torch', 'transformers', 'camelot', 'tabula') if m in sys.modules]\n"
        "print(','.join(heavy))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == ""


def test_require_names_the_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "camelot", None)  # makes `import camelot` raise ImportError
    with pytest.raises(MissingDependencyError) as exc:
        require("camelot", "the Camelot fallback parser")
    assert "table-extraction-pro[fallback]" in str(exc.value)
    assert exc.value.extra == "fallback"


def test_pipeline_construction_is_lazy_and_errors_on_use(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "torch", None)
    pipeline = TableExtractionPipeline()  # must not touch torch
    image = tmp_path / "page.png"
    from PIL import Image

    Image.new("RGB", (40, 40), "white").save(image)
    with pytest.raises(MissingDependencyError) as exc:
        pipeline.extract_from_file(image)
    assert "table-extraction-pro[ml]" in str(exc.value)


def test_comparator_without_any_backend_raises(monkeypatch):
    monkeypatch.setattr(parser_comparator, "is_available", lambda name: False)
    with pytest.raises(MissingDependencyError):
        ParserComparator().compare_parsers("missing.pdf")
