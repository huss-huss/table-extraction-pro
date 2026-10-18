import csv
import json

import openpyxl
import pytest

from table_extraction.export import TableExporter, export_to_csv, export_to_html, export_to_json
from tests.conftest import make_table
from tests.fixtures.generate import INVOICE, STAFF


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def test_csv_single_table_roundtrip(tmp_path):
    out = tmp_path / "invoice.csv"
    export_to_csv([make_table(INVOICE)], out)
    assert read_csv(out) == INVOICE


def test_csv_metadata_header_for_tatr_table(tmp_path):
    out = tmp_path / "invoice.csv"
    export_to_csv([make_table(INVOICE, confidence=0.876)], out, include_metadata=True)
    rows = read_csv(out)
    assert rows[0] == ["# Table ID: 1"]
    assert rows[2] == ["# Parser: tatr"]
    assert rows[3] == ["# Confidence: 0.876"]
    assert rows[4] == ["# Rows: 5, Columns: 4"]
    assert rows[6:] == INVOICE


def test_json_export(tmp_path):
    out = tmp_path / "t.json"
    export_to_json([make_table(INVOICE), make_table(STAFF, table_id=2)], out, include_metadata=False)
    payload = json.loads(out.read_text())
    assert payload["extraction_info"]["total_tables"] == 2
    assert [t["data"] for t in payload["tables"]] == [INVOICE, STAFF]
    assert "metadata" not in payload["tables"][0]


def test_html_export_contains_cells(tmp_path):
    out = tmp_path / "t.html"
    export_to_html([make_table(INVOICE)], out)
    html = out.read_text()
    assert html.count("<tr>") == len(INVOICE)
    assert "<td>Widget A</td>" in html


def test_excel_export_one_sheet_per_table(tmp_path):
    out = tmp_path / "t.xlsx"
    TableExporter(tmp_path).export_tables(
        [make_table(INVOICE), make_table(STAFF, table_id=2)], "t", ["excel"]
    )
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ["Summary", "Table_1_Page_1", "Table_2_Page_1"]
    sheet = wb["Table_1_Page_1"]
    values = [[str(c) for c in row] for row in sheet.iter_rows(min_row=2, values_only=True)]
    assert values == INVOICE


def test_exporter_rejects_unknown_format(tmp_path):
    with pytest.raises(ValueError, match="Unsupported formats"):
        TableExporter(tmp_path).export_tables([make_table(INVOICE)], "t", ["pdf"])


@pytest.mark.parametrize("fmt", ["csv", "json", "html", "excel"])
def test_fallback_tables_export_with_metadata(tmp_path, fmt):
    """Camelot/Tabula tables carry confidence in `detection`, not `metadata`."""
    table = make_table(INVOICE, parser="camelot", confidence=0.97)
    assert "confidence" not in table["metadata"]
    paths = TableExporter(tmp_path).export_tables([table], "t", [fmt], include_metadata=True)
    assert paths[fmt].exists()


def test_summary_report_with_fallback_tables(tmp_path):
    table = make_table(INVOICE, parser="tabula", confidence=0.8)
    path = TableExporter(tmp_path).create_summary_report({"a.pdf": [table]})
    summary = json.loads(path.read_text())
    assert summary["file_details"]["a.pdf"]["tables"][0]["confidence"] == 0.8


def test_html_export_escapes_cell_text(tmp_path):
    out = tmp_path / "t.html"
    data = [["Name", "Note"], ["<script>alert(1)</script>", "a & b < c"]]
    export_to_html([make_table(data)], out)
    html = out.read_text()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "a &amp; b &lt; c" in html


def test_csv_multiple_tables_written_to_directory(tmp_path):
    tables = [make_table(INVOICE, table_id=1), make_table(STAFF, table_id=1, page=1, parser="camelot")]
    paths = TableExporter(tmp_path).export_tables(tables, "report", ["csv"], include_metadata=False)
    out_dir = paths["csv"]
    assert out_dir == tmp_path / "report"
    assert out_dir.is_dir()
    assert not (tmp_path / "report.csv").exists()
    files = sorted(p.name for p in out_dir.iterdir())
    assert files == ["table_1_page_1.csv", "table_2_page_1.csv"]
    assert read_csv(out_dir / "table_1_page_1.csv") == INVOICE
    assert read_csv(out_dir / "table_2_page_1.csv") == STAFF


def test_excel_tables_with_duplicate_ids_get_separate_sheets(tmp_path):
    tables = [make_table(INVOICE, table_id=1), make_table(STAFF, table_id=1)]
    path = TableExporter(tmp_path).export_tables(tables, "t", ["xlsx"])["xlsx"]
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == ["Summary", "Table_1_Page_1", "Table_2_Page_1"]
    assert wb["Table_2_Page_1"].cell(row=2, column=1).value == "Name"
