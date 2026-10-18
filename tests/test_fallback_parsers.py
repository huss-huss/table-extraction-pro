"""Integration tests for the Camelot/Tabula wrappers on the generated fixtures."""

import shutil

import pytest

from table_extraction._deps import is_available
from tests.fixtures.generate import read_golden

needs_camelot = pytest.mark.skipif(not is_available("camelot"), reason="camelot not installed")
needs_tabula = pytest.mark.skipif(
    not (is_available("tabula") and shutil.which("java")), reason="tabula-py or java not installed"
)


@needs_camelot
def test_camelot_lattice_reads_ruled_table(fixture_pdfs, fixture_specs):
    from table_extraction.parsers import CamelotParser

    tables = CamelotParser(flavor="lattice").extract_tables(fixture_pdfs["lattice_invoice"])
    assert len(tables) == 1
    assert tables[0]["data"] == read_golden(fixture_specs["lattice_invoice"], 1, 1)
    assert tables[0]["metadata"]["flavor"] == "lattice"
    x0, top, x1, bottom = tables[0]["detection"]["page_bbox"]
    assert 60 < x0 < x1 < 400 and 80 < top < bottom < 300  # top-left origin, points


@needs_camelot
def test_camelot_multiple_flavors_keeps_pages_and_does_not_mutate(fixture_pdfs, fixture_specs):
    from table_extraction.parsers import CamelotParser

    parser = CamelotParser(flavor="lattice")
    tables = parser.extract_tables_with_multiple_flavors(fixture_pdfs["multipage"])
    assert parser.flavor == "lattice"
    spec = fixture_specs["multipage"]
    for page in (1, 2):
        on_page = [t["data"] for t in tables if t["page_number"] == page]
        assert read_golden(spec, page, 1) in on_page
    assert [t["table_id"] for t in tables] == list(range(1, len(tables) + 1))


@needs_camelot
def test_camelot_rejects_columns_for_lattice(fixture_pdfs):
    from table_extraction.parsers import CamelotParser

    with pytest.raises(ValueError):
        CamelotParser().extract_tables(fixture_pdfs["lattice_invoice"], columns=["100,200"])


@needs_camelot
def test_camelot_table_areas_are_valid_camelot_input(fixture_pdfs, fixture_specs):
    from table_extraction.parsers import CamelotParser

    parser = CamelotParser(flavor="lattice")
    areas = parser.get_table_areas(fixture_pdfs["lattice_invoice"])
    assert len(areas) == 1
    again = parser.extract_tables(fixture_pdfs["lattice_invoice"], table_areas=areas)
    assert again[0]["data"] == read_golden(fixture_specs["lattice_invoice"], 1, 1)


def test_tabula_page_range_parsing():
    from table_extraction.parsers.tabula_parser import _parse_pages

    assert _parse_pages("all", 3) == [1, 2, 3]
    assert _parse_pages("1,3", 3) == [1, 3]
    assert _parse_pages("2-end", 4) == [2, 3, 4]
    assert _parse_pages("1-2,9", 3) == [1, 2]


@needs_tabula
def test_tabula_reports_real_page_numbers(fixture_pdfs, fixture_specs):
    from table_extraction.parsers import TabulaParser

    tables = TabulaParser().extract_tables(fixture_pdfs["multipage"], method={"lattice": True})
    spec = fixture_specs["multipage"]
    assert [(t["page_number"], t["data"]) for t in tables] == [
        (1, read_golden(spec, 1, 1)),
        (2, read_golden(spec, 2, 1)),
    ]


@needs_tabula
def test_tabula_cells_are_strings_without_nan(fixture_pdfs):
    from table_extraction.parsers import TabulaParser

    for table in TabulaParser().extract_tables_with_different_methods(fixture_pdfs["stream_quarterly"]):
        for row in table["data"]:
            for cell in row:
                assert isinstance(cell, str)
                assert cell.lower() != "nan"
