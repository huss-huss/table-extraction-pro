import numpy as np
import pytest
from PIL import Image

from table_extraction import TableExtractionPipeline
from table_extraction.extraction.pipeline import fill_cells_from_words
from table_extraction.models.tatr_structure import build_cell_grid
from tests.fixtures.generate import read_golden
from tests.tatr_fakes import RuledGridOracle


def oracle_pipeline(pdf_path, dpi=150):
    oracle = RuledGridOracle(pdf_path, dpi=dpi)
    return TableExtractionPipeline(
        dpi=dpi, detector=oracle.detector, structure_recognizer=oracle.structure_recognizer
    )


@pytest.mark.parametrize("name", ["lattice_invoice", "two_tables_one_page", "multipage"])
def test_pipeline_fills_cells_from_text_layer(fixture_pdfs, fixture_specs, name):
    tables = oracle_pipeline(fixture_pdfs[name]).extract_from_file(fixture_pdfs[name])
    spec = fixture_specs[name]
    expected = [(p, read_golden(spec, p, i)) for p, i, _ in spec.iter_tables()]
    assert [(t["page_number"], t["data"]) for t in tables] == expected
    assert [t["table_id"] for t in tables] == list(range(1, len(tables) + 1))
    for t in tables:
        assert t["metadata"]["parser"] == "tatr"
        assert t["metadata"]["text_source"] == "pdf_text_layer"
        assert t["detection"]["page_bbox"][0] == pytest.approx(72, abs=1)


def test_pipeline_works_at_any_dpi(fixture_pdfs, fixture_specs):
    pdf = fixture_pdfs["lattice_invoice"]
    for dpi in (72, 200):
        tables = oracle_pipeline(pdf, dpi=dpi).extract_from_pdf(pdf)
        assert tables[0]["data"] == read_golden(fixture_specs["lattice_invoice"], 1, 1)


def test_build_cell_grid_marks_header_rows():
    structure = {
        "rows": [{"bbox": [0, 0, 100, 10]}, {"bbox": [0, 10, 100, 20]}],
        "columns": [{"bbox": [0, 0, 40, 20]}, {"bbox": [40, 0, 100, 20]}],
        "column_headers": [{"bbox": [0, 0, 100, 10]}],
    }
    grid = build_cell_grid(structure)
    assert [[c["bbox"] for c in row] for row in grid] == [
        [[0, 0, 40, 10], [40, 0, 100, 10]],
        [[0, 10, 40, 20], [40, 10, 100, 20]],
    ]
    assert [row[0]["is_header"] for row in grid] == [True, False]


def test_fill_cells_joins_multiword_cells_in_reading_order():
    # Cell is 0..100 x 0..40 px in the crop; the crop starts at (100, 100) px on
    # a 2 px/pt page image, so the cell covers x 50..100, y 50..70 in points.
    grid = [[{"bbox": [0, 0, 100, 40]}]]
    words = [
        {"bbox": [55, 61, 65, 65], "text": "line2"},
        {"bbox": [75, 51, 85, 55], "text": "world"},
        {"bbox": [55, 51, 65, 55], "text": "hello"},
        {"bbox": [10, 10, 20, 20], "text": "outside"},
    ]
    assert fill_cells_from_words(grid, words, [100, 100], 2.0) == [["hello world line2"]]


def test_image_input_without_ocr_returns_empty_cells(tmp_path):
    img = tmp_path / "page.png"
    Image.fromarray(np.full((200, 300, 3), 255, dtype=np.uint8)).save(img)

    class Det:
        def detect_tables(self, image, threshold):
            assert image.shape == (200, 300, 3)
            return [{"bbox": [10, 10, 290, 190], "confidence": 0.9, "class": "table"}]

        from table_extraction.models.tatr_detector import TATRTableDetector

        extract_table_regions = staticmethod(TATRTableDetector.extract_table_regions)

    class Struct:
        def recognize_structure(self, region, threshold):
            return {
                "rows": [{"bbox": [0, 0, 280, 90]}, {"bbox": [0, 90, 280, 180]}],
                "columns": [{"bbox": [0, 0, 140, 180]}, {"bbox": [140, 0, 280, 180]}],
                "num_rows": 2,
                "num_columns": 2,
            }

        create_cell_grid = staticmethod(build_cell_grid)

    tables = TableExtractionPipeline(detector=Det(), structure_recognizer=Struct()).extract_from_file(img)
    assert tables[0]["data"] == [["", ""], ["", ""]]
    assert tables[0]["metadata"]["text_source"] == "none"


def test_unsupported_and_missing_files(tmp_path):
    pipeline = TableExtractionPipeline()
    with pytest.raises(FileNotFoundError):
        pipeline.extract_from_file(tmp_path / "nope.pdf")
    other = tmp_path / "notes.txt"
    other.write_text("x")
    with pytest.raises(ValueError, match="Unsupported"):
        pipeline.extract_from_file(other)
