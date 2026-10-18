import csv
import json
import shutil

import pytest
from click.testing import CliRunner

from table_extraction import engine as engine_mod
from table_extraction._deps import is_available
from table_extraction.cli.main import cli
from table_extraction.extraction.pipeline import TableExtractionPipeline
from tests.fixtures.generate import read_golden
from tests.tatr_fakes import RuledGridOracle

has_fallback = is_available("camelot") and is_available("tabula") and shutil.which("java")


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def fake_tatr(monkeypatch):
    """Make engine 'tatr' use the geometry oracle instead of the real models."""

    def factory(confidence_threshold=0.5, **kw):
        oracle = RuledGridOracle(factory.pdf, dpi=100)
        return TableExtractionPipeline(
            confidence_threshold=confidence_threshold,
            dpi=100,
            detector=oracle.detector,
            structure_recognizer=oracle.structure_recognizer,
        )

    monkeypatch.setattr(engine_mod, "TableExtractionPipeline", factory)
    return factory


def test_version_and_backends(runner):
    assert "Table Extraction Pro v" in runner.invoke(cli, ["version"]).output
    out = runner.invoke(cli, ["backends"]).output
    assert {line.split()[0] for line in out.strip().splitlines()} == {"tatr", "camelot", "tabula"}


def test_extract_with_tatr_engine_writes_golden_csv(runner, fake_tatr, fixture_pdfs, fixture_specs, tmp_path):
    pdf = fixture_pdfs["lattice_invoice"]
    fake_tatr.pdf = pdf
    result = runner.invoke(cli, ["extract", "-i", str(pdf), "-o", str(tmp_path), "-e", "tatr", "-f", "csv"])
    assert result.exit_code == 0, result.output
    assert read_csv(tmp_path / "lattice_invoice.csv") == read_golden(fixture_specs["lattice_invoice"], 1, 1)


def test_extract_multi_table_json(runner, fake_tatr, fixture_pdfs, fixture_specs, tmp_path):
    pdf = fixture_pdfs["multipage"]
    fake_tatr.pdf = pdf
    result = runner.invoke(cli, ["extract", "-i", str(pdf), "-o", str(tmp_path), "-e", "tatr", "-f", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads((tmp_path / "multipage.json").read_text())
    assert [t["page_number"] for t in payload["tables"]] == [1, 2]


@pytest.mark.skipif(not has_fallback, reason="camelot/tabula/java not installed")
def test_extract_with_fallback_engine(runner, fixture_pdfs, fixture_specs, tmp_path):
    pdf = fixture_pdfs["two_tables_one_page"]
    result = runner.invoke(
        cli,
        ["-q", "extract", "-i", str(pdf), "-o", str(tmp_path), "--use-fallback", "-f", "csv", "-f", "html"],
    )
    assert result.exit_code == 0, result.output
    out_dir = tmp_path / "two_tables_one_page"
    spec = fixture_specs["two_tables_one_page"]
    assert read_csv(out_dir / "table_1_page_1.csv") == read_golden(spec, 1, 1)
    assert read_csv(out_dir / "table_2_page_1.csv") == read_golden(spec, 1, 2)
    assert (tmp_path / "two_tables_one_page.html").exists()


def test_fallback_engine_rejects_images(runner, tmp_path):
    img = tmp_path / "scan.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    result = runner.invoke(cli, ["extract", "-i", str(img), "-o", str(tmp_path), "-e", "fallback"])
    assert result.exit_code != 0
    assert "only read PDFs" in result.output


def test_missing_backend_gives_install_hint(runner, monkeypatch, fixture_pdfs, tmp_path):
    monkeypatch.setattr(
        engine_mod, "available_backends", lambda: dict(tatr=False, camelot=False, tabula=False)
    )
    result = runner.invoke(cli, ["extract", "-i", str(fixture_pdfs["lattice_invoice"]), "-o", str(tmp_path)])
    assert result.exit_code == 1
    assert "pip install 'table-extraction-pro[" in result.output


def test_confidence_is_range_checked(runner, fixture_pdfs, tmp_path):
    result = runner.invoke(
        cli, ["extract", "-i", str(fixture_pdfs["lattice_invoice"]), "-o", str(tmp_path), "-c", "1.5"]
    )
    assert result.exit_code == 2


def test_quick_writes_single_file(runner, fake_tatr, fixture_pdfs, fixture_specs, tmp_path):
    pdf = fixture_pdfs["lattice_invoice"]
    fake_tatr.pdf = pdf
    out = tmp_path / "nested" / "invoice.csv"
    result = runner.invoke(cli, ["quick", "-i", str(pdf), "-o", str(out), "-e", "tatr"])
    assert result.exit_code == 0, result.output
    assert read_csv(out) == read_golden(fixture_specs["lattice_invoice"], 1, 1)


def test_batch_processes_each_file_once(runner, monkeypatch, tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    for name in ("a.pdf", "B.PDF", "notes.txt"):
        (src / name).write_bytes(b"%PDF-1.4\n")
    calls = []

    def fake_extract(path, engine, confidence):
        calls.append(path.name)
        return [
            {
                "table_id": 1,
                "page_number": 1,
                "data": [["h"], [path.stem]],
                "metadata": {"parser": "camelot"},
                "structure": {"num_rows": 2, "num_columns": 1, "rows": [], "columns": []},
                "detection": {"bbox": [0, 0, 0, 0], "confidence": 1.0},
            }
        ]

    monkeypatch.setattr("table_extraction.cli.main.extract_tables", fake_extract)
    out = tmp_path / "out"
    result = runner.invoke(cli, ["batch", "-i", str(src), "-o", str(out), "-f", "csv"])
    assert result.exit_code == 0, result.output
    assert sorted(calls) == ["B.PDF", "a.pdf"]
    assert read_csv(out / "a_tables.csv")[-1] == ["a"]
    summary = json.loads((out / "extraction_summary.json").read_text())
    assert summary["extraction_summary"]["total_tables"] == 2
