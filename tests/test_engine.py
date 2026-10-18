import pytest

from table_extraction import MissingDependencyError
from table_extraction import engine as engine_mod
from table_extraction.engine import extract_tables


class Recorder:
    def __init__(self, result):
        self.result = result
        self.calls = []
        self.confidence_threshold = None

    def extract_from_file(self, path):
        self.calls.append(("tatr", path.name))
        return self.result

    def compare_parsers(self, path, tatr_tables=None):
        self.calls.append(("compare", tatr_tables))
        return ["merged"]


@pytest.fixture
def pdf(tmp_path):
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.4\n")
    return p


@pytest.fixture
def png(tmp_path):
    p = tmp_path / "scan.png"
    p.write_bytes(b"\x89PNG")
    return p


def backends(monkeypatch, tatr, fallback):
    monkeypatch.setattr(
        engine_mod, "available_backends", lambda: {"tatr": tatr, "camelot": fallback, "tabula": fallback}
    )


def test_auto_combines_tatr_and_fallback_on_pdf(monkeypatch, pdf):
    backends(monkeypatch, tatr=True, fallback=True)
    pipe, comp = Recorder(["t1"]), Recorder(None)
    assert extract_tables(pdf, "auto", 0.7, pipeline=pipe, comparator=comp) == ["merged"]
    assert pipe.confidence_threshold == 0.7
    assert comp.calls == [("compare", ["t1"])]


def test_auto_uses_fallback_only_without_ml(monkeypatch, pdf):
    backends(monkeypatch, tatr=False, fallback=True)
    pipe, comp = Recorder(["t1"]), Recorder(None)
    extract_tables(pdf, "auto", pipeline=pipe, comparator=comp)
    assert pipe.calls == [] and comp.calls == [("compare", None)]


def test_auto_image_uses_tatr_only(monkeypatch, png):
    backends(monkeypatch, tatr=True, fallback=True)
    pipe, comp = Recorder(["t1"]), Recorder(None)
    assert extract_tables(png, "auto", pipeline=pipe, comparator=comp) == ["t1"]
    assert comp.calls == []


@pytest.mark.parametrize("fixture,extra", [("pdf", "fallback"), ("png", "ml")])
def test_auto_without_backends_names_extra(monkeypatch, request, fixture, extra):
    backends(monkeypatch, tatr=False, fallback=False)
    with pytest.raises(MissingDependencyError) as exc:
        extract_tables(
            request.getfixturevalue(fixture), "auto", pipeline=Recorder([]), comparator=Recorder([])
        )
    assert exc.value.extra == extra


def test_rejects_unknown_engine_and_types(tmp_path, pdf):
    with pytest.raises(ValueError, match="Unknown engine"):
        extract_tables(pdf, "magic")
    txt = tmp_path / "a.txt"
    txt.write_text("x")
    with pytest.raises(ValueError, match="Unsupported file type"):
        extract_tables(txt)
    with pytest.raises(FileNotFoundError):
        extract_tables(tmp_path / "missing.pdf")
