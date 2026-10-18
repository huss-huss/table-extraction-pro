from fastapi.testclient import TestClient

from table_extraction.api import main as api_main


def test_upload_is_fully_written_before_extraction(fixture_pdfs, monkeypatch):
    pdf = fixture_pdfs["lattice_invoice"].read_bytes()
    seen = {}

    class Recorder:
        def extract_from_file(self, path):
            with open(path, "rb") as f:
                seen["bytes"] = f.read()
            return []

    with TestClient(api_main.app) as client:
        monkeypatch.setattr(api_main, "pipeline", Recorder())
        client.post("/extract", files={"file": ("doc.pdf", pdf, "application/pdf")})
    assert seen["bytes"] == pdf
