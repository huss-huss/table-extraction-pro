import shutil

import pytest
from fastapi.testclient import TestClient

from table_extraction import MissingDependencyError
from table_extraction._deps import is_available
from table_extraction.api.main import Settings, create_app
from tests.conftest import make_table
from tests.fixtures.generate import INVOICE, read_golden

PDF_BYTES = b"%PDF-1.4\n%fake\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class FakeExtractor:
    def __init__(self, result=None, exc=None):
        self.result = result if result is not None else [make_table(INVOICE)]
        self.exc = exc
        self.calls = []

    def __call__(self, path, engine, confidence):
        assert path.exists() and path.stat().st_size > 0  # fully written before extraction
        self.calls.append(
            {"path": path, "engine": engine, "confidence": confidence, "bytes": path.read_bytes()}
        )
        if self.exc:
            raise self.exc
        return self.result


def make_client(extractor=None, **overrides):
    settings = Settings(
        max_upload_bytes=overrides.get("max_upload_bytes", 1024 * 1024),
        max_batch_files=overrides.get("max_batch_files", 3),
        cors_origins=[],
        default_engine="auto",
    )
    app = create_app(settings)
    if extractor is not None:
        app.dependency_overrides[app.state.get_extractor] = lambda: extractor
    return TestClient(app, raise_server_exceptions=False)


def upload(client, content=PDF_BYTES, name="doc.pdf", ctype="application/pdf", **data):
    return client.post("/extract", files={"file": (name, content, ctype)}, data=data)


def test_healthz_reports_backends():
    r = make_client().get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert set(body["backends"]) == {"tatr", "camelot", "tabula"}
    assert make_client().get("/health").status_code == 200


def test_extract_json():
    fake = FakeExtractor()
    r = upload(make_client(fake), confidence="0.7", engine="tatr", include_metadata="false")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_tables"] == 1
    assert body["tables"] == [{"table_id": 1, "page_number": 1, "data": INVOICE}]
    assert fake.calls[0]["engine"] == "tatr" and fake.calls[0]["confidence"] == 0.7
    assert fake.calls[0]["bytes"] == PDF_BYTES


def test_extract_csv_and_html_return_every_table():
    fake = FakeExtractor([make_table(INVOICE), make_table([["<b>x</b>"]], table_id=2)])
    csv_body = upload(make_client(fake), output_format="csv").json()
    assert [t["table_id"] for t in csv_body["tables"]] == [1, 2]
    assert csv_body["tables"][0]["csv"].splitlines()[1] == "Widget A,4,2.50,10.00"
    html_body = upload(make_client(fake), output_format="html").json()
    assert "&lt;b&gt;x&lt;/b&gt;" in html_body["tables"][1]["html"]


def test_no_tables_is_not_an_error():
    r = upload(make_client(FakeExtractor(result=[])))
    assert r.status_code == 200
    assert r.json()["total_tables"] == 0


def test_use_fallback_alias():
    fake = FakeExtractor()
    upload(make_client(fake), use_fallback="true")
    assert fake.calls[0]["engine"] == "fallback"


def test_boolean_form_fields_default_when_omitted():
    # Regression for #6: FastAPI 0.147 reads a missing ``bool = Form(True)`` as False.
    for data in ({}, {"output_format": "json"}, {"include_metadata": "", "use_fallback": ""}):
        fake = FakeExtractor()
        r = upload(make_client(fake), **data)
        assert r.status_code == 200, r.text
        assert r.json()["tables"] == [make_table(INVOICE)]  # include_metadata defaults to true
        assert fake.calls[0]["engine"] == "auto"  # use_fallback defaults to false


def test_batch_boolean_form_fields_default_when_omitted():
    fake = FakeExtractor()
    files = [("files", ("a.pdf", PDF_BYTES, "application/pdf"))]
    body = make_client(fake).post("/extract/batch", files=files).json()
    assert body["engine"] == "auto"
    assert body["results"][0]["tables"] == [make_table(INVOICE)]

    body = make_client(fake).post("/extract/batch", files=files, data={"include_metadata": "no"}).json()
    assert body["results"][0]["tables"] == [{"table_id": 1, "page_number": 1, "data": INVOICE}]


@pytest.mark.parametrize("value", ["true", "True", "1", "yes", "y", "on", "t", " TRUE "])
def test_boolean_form_fields_accept_true_spellings(value):
    fake = FakeExtractor()
    r = upload(make_client(fake), include_metadata=value, use_fallback=value)
    assert r.status_code == 200, r.text
    assert "metadata" in r.json()["tables"][0]
    assert fake.calls[0]["engine"] == "fallback"


@pytest.mark.parametrize("value", ["false", "False", "0", "no", "n", "off", "f"])
def test_boolean_form_fields_accept_false_spellings(value):
    fake = FakeExtractor()
    r = upload(make_client(fake), include_metadata=value, use_fallback=value)
    assert r.status_code == 200, r.text
    assert r.json()["tables"] == [{"table_id": 1, "page_number": 1, "data": INVOICE}]
    assert fake.calls[0]["engine"] == "auto"


@pytest.mark.parametrize("field", ["include_metadata", "use_fallback"])
def test_invalid_boolean_form_field_is_a_validation_error(field):
    fake = FakeExtractor()
    r = upload(make_client(fake), **{field: "maybe"})
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["loc"] == ["body", field]
    assert fake.calls == []


@pytest.mark.parametrize(
    "name,content,ctype",
    [
        ("notes.txt", b"hello", "text/plain"),  # extension
        ("doc.pdf", PDF_BYTES, "text/html"),  # declared type mismatch
        ("doc.pdf", b"<html>not a pdf</html>", "application/pdf"),  # magic bytes
        ("scan.png", PDF_BYTES, "image/png"),  # pdf bytes posing as png
    ],
)
def test_content_type_validation(name, content, ctype):
    fake = FakeExtractor()
    r = upload(make_client(fake), content=content, name=name, ctype=ctype)
    assert r.status_code == 415
    assert r.json()["error"]["code"] == "unsupported_media_type"
    assert fake.calls == []


def test_generic_content_type_accepted_when_bytes_match():
    r = upload(
        make_client(FakeExtractor()), content=PNG_BYTES, name="scan.png", ctype="application/octet-stream"
    )
    assert r.status_code == 200


def test_upload_size_limit_by_content_length():
    fake = FakeExtractor()
    r = upload(make_client(fake, max_upload_bytes=1024), content=PDF_BYTES + b"0" * 4096)
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"
    assert fake.calls == []


def test_upload_size_limit_without_content_length():
    """Chunked bodies have no Content-Length; the stream itself is counted."""
    fake = FakeExtractor()
    client = make_client(fake, max_upload_bytes=1024)
    body = (
        b'--BOUNDARY\r\nContent-Disposition: form-data; name="file"; filename="doc.pdf"\r\n'
        b"Content-Type: application/pdf\r\n\r\n" + PDF_BYTES + b"0" * 8192 + b"\r\n--BOUNDARY--\r\n"
    )

    def chunks():
        for i in range(0, len(body), 512):
            yield body[i : i + 512]

    r = client.post(
        "/extract", content=chunks(), headers={"Content-Type": "multipart/form-data; boundary=BOUNDARY"}
    )
    assert r.status_code == 413
    assert fake.calls == []


def test_empty_file_rejected():
    r = upload(make_client(FakeExtractor()), content=b"")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "empty_file"


def test_temp_files_removed_after_success_and_failure():
    ok = FakeExtractor()
    upload(make_client(ok))
    assert not ok.calls[0]["path"].exists()
    assert not ok.calls[0]["path"].parent.exists()

    boom = FakeExtractor(exc=RuntimeError("kaboom"))
    r = upload(make_client(boom))
    assert r.status_code == 500
    assert r.json() == {
        "error": {"code": "internal_error", "message": "Internal server error", "details": None}
    }
    assert not boom.calls[0]["path"].parent.exists()


def test_missing_backend_is_503_with_extra():
    fake = FakeExtractor(exc=MissingDependencyError("torch", "ml", "TATR"))
    r = upload(make_client(fake))
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "backend_unavailable"
    assert r.json()["error"]["details"] == {"extra": "ml"}


def test_parameter_and_validation_errors_are_structured():
    client = make_client(FakeExtractor())
    for data, field in (
        (dict(confidence="2"), "confidence"),
        (dict(engine="x"), "engine"),
        (dict(output_format="xml"), "output_format"),
    ):
        r = upload(client, **data)
        assert r.status_code == 400
        assert field in r.json()["error"]["message"]
    r = client.post("/extract", data={"confidence": "0.5"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert client.get("/nope").json()["error"]["code"] == "not_found"


def test_batch_reports_per_file_results():
    client = make_client(FakeExtractor(), max_batch_files=3)
    files = [
        ("files", ("a.pdf", PDF_BYTES, "application/pdf")),
        ("files", ("b.txt", b"x", "text/plain")),
    ]
    body = client.post("/extract/batch", files=files).json()
    assert body["total_files"] == 2
    assert body["results"][0]["total_tables"] == 1
    assert body["results"][1]["error"]["code"] == "unsupported_media_type"

    too_many = [("files", (f"{i}.pdf", PDF_BYTES, "application/pdf")) for i in range(4)]
    r = client.post("/extract/batch", files=too_many)
    assert r.status_code == 400 and r.json()["error"]["code"] == "too_many_files"


@pytest.mark.skipif(
    not (is_available("camelot") and is_available("tabula") and shutil.which("java")),
    reason="fallback parsers not installed",
)
def test_real_fallback_extraction(fixture_pdfs, fixture_specs):
    client = make_client(max_upload_bytes=5 * 1024 * 1024)
    pdf = fixture_pdfs["lattice_invoice"]
    r = upload(client, content=pdf.read_bytes(), engine="fallback", include_metadata="false")
    assert r.status_code == 200, r.text
    assert r.json()["tables"][0]["data"] == read_golden(fixture_specs["lattice_invoice"], 1, 1)
