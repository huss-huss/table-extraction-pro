"""
Real TATR models. Deselected by default (marker `ml`); run with:

    pytest -m ml

Requires the ml extra and downloads the two Hugging Face checkpoints
(about 230 MB) on first run.
"""

import pytest

from table_extraction._deps import is_available
from table_extraction.evaluation import grits_con
from tests.fixtures.generate import read_golden

pytestmark = [
    pytest.mark.ml,
    pytest.mark.skipif(
        not (is_available("torch") and is_available("transformers")), reason="ml extra missing"
    ),
]


@pytest.fixture(scope="module")
def pipeline():
    from table_extraction import TableExtractionPipeline

    return TableExtractionPipeline(dpi=150)


def test_tatr_detects_and_reads_ruled_table(pipeline, fixture_pdfs, fixture_specs):
    tables = pipeline.extract_from_pdf(fixture_pdfs["lattice_invoice"])
    assert len(tables) == 1
    golden = read_golden(fixture_specs["lattice_invoice"], 1, 1)
    assert grits_con(golden, tables[0]["data"])["f1"] > 0.9


def test_tatr_finds_tables_on_each_page(pipeline, fixture_pdfs):
    tables = pipeline.extract_from_pdf(fixture_pdfs["multipage"])
    assert sorted({t["page_number"] for t in tables}) == [1, 2]
