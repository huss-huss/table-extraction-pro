import pymupdf

from tests.fixtures.generate import read_golden


def test_golden_csvs_match_specs(fixture_specs):
    for spec in fixture_specs.values():
        for page, index, rows in spec.iter_tables():
            assert read_golden(spec, page, index) == rows


def test_rendered_pdfs_contain_every_cell(fixture_pdfs, fixture_specs):
    for name, path in fixture_pdfs.items():
        spec = fixture_specs[name]
        with pymupdf.open(path) as doc:
            assert len(doc) == len(spec.pages)
            for page, _, rows in spec.iter_tables():
                text = doc[page - 1].get_text("text")
                for row in rows:
                    for cell in row:
                        assert cell in text, (name, page, cell)
