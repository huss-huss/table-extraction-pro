"""Async job API: lifecycle, error paths, cancellation, expiry and temp-file cleanup.

Extraction is stubbed, so no model or fallback parser is needed.
"""

import io
import threading
import time
import zipfile

import openpyxl
import pytest
from fastapi.testclient import TestClient

from table_extraction import MissingDependencyError
from table_extraction.api.jobs import JobManager
from table_extraction.api.main import Settings, create_app
from tests.conftest import make_table
from tests.fixtures.generate import INVOICE
from tests.test_api import PDF_BYTES, FakeExtractor

TIMEOUT = 10.0


class FakeClock:
    def __init__(self, now=1_700_000_000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class BlockingExtractor(FakeExtractor):
    """Blocks inside extraction until ``release`` is set."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(self, path, engine, confidence):
        self.started.set()
        assert self.release.wait(TIMEOUT), "test never released the extractor"
        return super().__call__(path, engine, confidence)


def make_client(tmp_path, extractor=None, clock=None, **job_options):
    max_upload_bytes = job_options.pop("max_upload_bytes", 1024 * 1024)
    options = dict(workers=1, max_queued=4, ttl_seconds=600, cleanup_interval=0)
    options.update(job_options)
    manager = JobManager(base_dir=tmp_path / "jobs", clock=clock or FakeClock(), **options)
    settings = Settings(
        max_upload_bytes=max_upload_bytes,
        max_batch_files=3,
        cors_origins=[],
        default_engine="auto",
    )
    app = create_app(settings, job_manager=manager)
    if extractor is not None:
        app.dependency_overrides[app.state.get_extractor] = lambda: extractor
    return TestClient(app, raise_server_exceptions=False), manager


def submit(client, content=PDF_BYTES, name="doc.pdf", ctype="application/pdf", **data):
    return client.post("/jobs", files={"file": (name, content, ctype)}, data=data)


def wait_for(client, job_id, *statuses):
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        r = client.get(f"/jobs/{job_id}")
        if r.status_code == 200 and r.json()["status"] in statuses:
            return r.json()
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} never reached {statuses}: {r.status_code} {r.text}")


def wait_gone(client, job_id):
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        if client.get(f"/jobs/{job_id}").status_code == 404:
            return
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} was never removed")


def job_dirs(tmp_path):
    base = tmp_path / "jobs"
    return sorted(base.iterdir()) if base.exists() else []


def test_job_lifecycle(tmp_path):
    clock = FakeClock()
    fake = FakeExtractor()
    client, manager = make_client(tmp_path, fake, clock=clock)

    r = submit(client, engine="fallback", confidence="0.7", include_metadata="false")
    assert r.status_code == 202, r.text
    body = r.json()
    job_id = body["id"]
    assert body["status"] in ("queued", "running", "succeeded")
    assert body["status_url"] == f"/jobs/{job_id}"
    assert r.headers["location"] == f"/jobs/{job_id}"
    assert body["created_at"] == "2023-11-14T22:13:20Z"

    status = wait_for(client, job_id, "succeeded")
    assert status["total_tables"] == 1
    assert status["error"] is None
    assert status["result_url"] == f"/jobs/{job_id}/result"
    assert status["started_at"] and status["finished_at"]
    assert status["expires_at"] == "2023-11-14T22:23:20Z"  # finished + 600 s TTL
    assert fake.calls[0]["engine"] == "fallback" and fake.calls[0]["confidence"] == 0.7
    assert fake.calls[0]["bytes"] == PDF_BYTES
    # The upload is removed once extraction is done; the result stays until expiry.
    assert not fake.calls[0]["path"].exists()
    assert [p.name for p in job_dirs(tmp_path)[0].iterdir()] == ["tables.json"]

    r = client.get(f"/jobs/{job_id}/result")
    assert r.status_code == 200
    assert r.json() == {
        "filename": "doc.pdf",
        "engine": "fallback",
        "total_tables": 1,
        "format": "json",
        "tables": [{"table_id": 1, "page_number": 1, "data": INVOICE}],
    }

    r = client.delete(f"/jobs/{job_id}")
    assert r.status_code == 200 and r.json() == {"id": job_id, "result": "deleted"}
    assert client.get(f"/jobs/{job_id}").status_code == 404
    assert job_dirs(tmp_path) == []


def test_job_boolean_form_fields_default_when_omitted(tmp_path):
    # Regression for #6: an omitted include_metadata must mean true, use_fallback false.
    fake = FakeExtractor()
    client, manager = make_client(tmp_path, fake)
    job_id = submit(client).json()["id"]
    wait_for(client, job_id, "succeeded")
    assert manager.get(job_id).include_metadata is True
    body = client.get(f"/jobs/{job_id}/result").json()
    assert body["engine"] == "auto"
    assert body["tables"] == [make_table(INVOICE)]


def test_job_invalid_boolean_form_field_creates_no_job(tmp_path):
    client, _ = make_client(tmp_path, FakeExtractor())
    r = submit(client, include_metadata="maybe")
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    assert job_dirs(tmp_path) == []


def test_progress_reports_pdf_pages(tmp_path, fixture_pdfs):
    client, _ = make_client(tmp_path, FakeExtractor())
    job_id = submit(client, content=fixture_pdfs["multipage"].read_bytes()).json()["id"]
    status = wait_for(client, job_id, "succeeded")
    assert status["progress"] == {"pages_done": 2, "pages_total": 2}


def test_result_formats(tmp_path):
    tables = [make_table(INVOICE), make_table([["<b>x</b>", "y"]], table_id=2, page=2)]
    client, _ = make_client(tmp_path, FakeExtractor(tables))
    job_id = submit(client, name="Q3 report.pdf", output_format="csv").json()["id"]
    wait_for(client, job_id, "succeeded")
    url = f"/jobs/{job_id}/result"

    # Default format is the one given at submission; several CSV tables come as a zip.
    r = client.get(url)
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"] == 'attachment; filename="Q3_report_csv.zip"'
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert zf.namelist() == ["table_1_page_1.csv", "table_2_page_2.csv"]
        assert zf.read("table_1_page_1.csv").decode().splitlines()[1] == "Widget A,4,2.50,10.00"

    r = client.get(url, params={"format": "csv", "table_id": 2})
    assert r.headers["content-type"].startswith("text/csv")
    assert r.text == "<b>x</b>,y\n"
    assert client.get(url, params={"format": "csv", "table_id": 9}).status_code == 404

    r = client.get(url, params={"format": "html"})
    assert r.headers["content-type"].startswith("text/html")
    assert "Widget A" in r.text and "&lt;b&gt;x&lt;/b&gt;" in r.text

    r = client.get(url, params={"format": "xlsx"})
    assert r.status_code == 200, r.text
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Summary", "Table_1_Page_1", "Table_2_Page_2"]

    r = client.get(url, params={"format": "json"})
    assert [t["table_id"] for t in r.json()["tables"]] == [1, 2]
    assert "metadata" in r.json()["tables"][0]

    r = client.get(url, params={"format": "xml"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_parameter"
    # Exports are generated per request and do not pile up in the job directory.
    assert [p.name for p in job_dirs(tmp_path)[0].iterdir()] == ["tables.json"]


def test_no_tables_result(tmp_path):
    client, _ = make_client(tmp_path, FakeExtractor(result=[]))
    job_id = submit(client).json()["id"]
    assert wait_for(client, job_id, "succeeded")["total_tables"] == 0
    assert client.get(f"/jobs/{job_id}/result").json()["tables"] == []
    assert client.get(f"/jobs/{job_id}/result?format=csv").text == ""
    assert client.get(f"/jobs/{job_id}/result?format=xlsx").status_code == 200


def test_result_before_done_is_409(tmp_path):
    blocking = BlockingExtractor()
    client, _ = make_client(tmp_path, blocking)
    running = submit(client).json()["id"]
    assert blocking.started.wait(TIMEOUT)
    queued = submit(client).json()["id"]
    try:
        assert client.get(f"/jobs/{running}").json()["status"] == "running"
        for job_id, status in ((running, "running"), (queued, "queued")):
            r = client.get(f"/jobs/{job_id}/result")
            assert r.status_code == 409
            assert r.json()["error"] == {
                "code": "job_not_ready",
                "message": f"Job is {status}",
                "details": {"status": status},
            }
    finally:
        blocking.release.set()
    wait_for(client, queued, "succeeded")
    assert client.get(f"/jobs/{running}/result").status_code == 200


def test_unknown_job_is_404(tmp_path):
    client, _ = make_client(tmp_path, FakeExtractor())
    for method, url in (("get", "/jobs/nope"), ("get", "/jobs/nope/result"), ("delete", "/jobs/nope")):
        r = getattr(client, method)(url)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "job_not_found"


def test_full_queue_is_429(tmp_path):
    blocking = BlockingExtractor()
    client, _ = make_client(tmp_path, blocking, max_queued=1)
    try:
        first = submit(client).json()["id"]
        assert blocking.started.wait(TIMEOUT)  # running jobs do not count against the queue
        assert submit(client).status_code == 202
        dirs_before = job_dirs(tmp_path)

        r = submit(client)
        assert r.status_code == 429
        assert r.headers["retry-after"] == "5"
        assert r.json()["error"]["code"] == "queue_full"
        assert r.json()["error"]["details"] == {"max_queued": 1}
        assert job_dirs(tmp_path) == dirs_before  # nothing written for a rejected job
    finally:
        blocking.release.set()
    wait_for(client, first, "succeeded")
    # Capacity frees up once the queue drains.
    deadline = time.monotonic() + TIMEOUT
    while submit(client).status_code == 429:
        assert time.monotonic() < deadline


def test_cancel_queued_job(tmp_path):
    blocking = BlockingExtractor()
    client, _ = make_client(tmp_path, blocking)
    running = submit(client).json()["id"]
    assert blocking.started.wait(TIMEOUT)
    queued = submit(client).json()["id"]
    assert len(job_dirs(tmp_path)) == 2

    r = client.delete(f"/jobs/{queued}")
    assert r.status_code == 200 and r.json() == {"id": queued, "result": "cancelled"}
    assert client.get(f"/jobs/{queued}").status_code == 404
    assert len(job_dirs(tmp_path)) == 1

    blocking.release.set()
    wait_for(client, running, "succeeded")
    assert len(blocking.calls) == 1  # the cancelled job never ran


def test_cancel_running_job_discards_output(tmp_path):
    blocking = BlockingExtractor()
    client, _ = make_client(tmp_path, blocking)
    job_id = submit(client).json()["id"]
    assert blocking.started.wait(TIMEOUT)

    r = client.delete(f"/jobs/{job_id}")
    assert r.status_code == 202 and r.json()["result"] == "cancel_requested"
    status = client.get(f"/jobs/{job_id}").json()
    assert status["status"] == "running" and status["cancel_requested"] is True

    blocking.release.set()
    wait_gone(client, job_id)
    assert job_dirs(tmp_path) == []


def test_ttl_expiry_and_cleanup(tmp_path):
    clock = FakeClock()
    client, manager = make_client(tmp_path, FakeExtractor(), clock=clock, ttl_seconds=60)
    a = submit(client).json()["id"]
    wait_for(client, a, "succeeded")
    clock.advance(30)
    b = submit(client).json()["id"]
    wait_for(client, b, "succeeded")

    clock.advance(29)  # a: 59 s old
    assert manager.cleanup_expired() == 0
    assert client.get(f"/jobs/{a}/result").status_code == 200

    clock.advance(1)  # a: 60 s, b: 30 s
    assert manager.cleanup_expired() == 1
    assert client.get(f"/jobs/{a}").status_code == 404
    assert client.get(f"/jobs/{b}").status_code == 200
    assert len(job_dirs(tmp_path)) == 1

    # An expired job is gone on lookup even before the next sweep.
    clock.advance(30)
    assert client.get(f"/jobs/{b}/result").status_code == 404
    assert job_dirs(tmp_path) == []
    assert manager.cleanup_expired() == 0


def test_janitor_removes_expired_jobs_periodically(tmp_path):
    clock = FakeClock()
    client, manager = make_client(
        tmp_path, FakeExtractor(), clock=clock, ttl_seconds=60, cleanup_interval=0.02
    )
    job_id = submit(client).json()["id"]
    wait_for(client, job_id, "succeeded")
    clock.advance(61)
    deadline = time.monotonic() + TIMEOUT
    while job_dirs(tmp_path):  # removed by the janitor thread, not by a request
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert manager.get(job_id) is None
    manager.shutdown()


@pytest.mark.parametrize(
    "exc,code",
    [
        (RuntimeError("kaboom"), "internal_error"),
        (ValueError("bad page"), "unprocessable"),
        (MissingDependencyError("torch", "ml", "TATR"), "backend_unavailable"),
    ],
)
def test_failed_job_removes_temp_files(tmp_path, exc, code):
    fake = FakeExtractor(exc=exc)
    client, _ = make_client(tmp_path, fake)
    job_id = submit(client).json()["id"]
    status = wait_for(client, job_id, "failed")
    assert status["error"]["code"] == code
    assert status["result_url"] is None
    if code == "internal_error":
        assert status["error"]["message"] == "Extraction failed"  # no internals leaked
    if code == "backend_unavailable":
        assert status["error"]["details"] == {"extra": "ml"}
    # Upload and job directory are gone; only the in-memory record remains.
    assert not fake.calls[0]["path"].exists()
    assert job_dirs(tmp_path) == []

    r = client.get(f"/jobs/{job_id}/result")
    assert r.status_code == 409 and r.json()["error"]["code"] == "job_failed"
    assert r.json()["error"]["details"]["code"] == code
    assert client.delete(f"/jobs/{job_id}").json()["result"] == "deleted"


@pytest.mark.parametrize(
    "kwargs,status,code",
    [
        (dict(name="notes.txt", content=b"hello", ctype="text/plain"), 415, "unsupported_media_type"),
        (dict(content=b"<html></html>"), 415, "unsupported_media_type"),
        (dict(content=b""), 400, "empty_file"),
        (dict(confidence="2"), 400, "invalid_parameter"),
        (dict(engine="x"), 400, "invalid_parameter"),
        (dict(output_format="xml"), 400, "invalid_parameter"),
        (dict(content=PDF_BYTES + b"0" * (2 * 1024 * 1024)), 413, "payload_too_large"),
    ],
)
def test_submission_is_validated_like_sync_extract(tmp_path, kwargs, status, code):
    fake = FakeExtractor()
    client, manager = make_client(tmp_path, fake)
    r = submit(client, **kwargs)
    assert r.status_code == status
    assert r.json()["error"]["code"] == code
    assert fake.calls == []
    assert job_dirs(tmp_path) == []
    assert manager._jobs == {}


def test_missing_file_is_422(tmp_path):
    client, _ = make_client(tmp_path, FakeExtractor())
    r = client.post("/jobs", data={"engine": "fallback"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_shutdown_removes_all_job_files(tmp_path):
    blocking = BlockingExtractor()
    with make_client(tmp_path, blocking, cleanup_interval=60)[0] as client:
        running = submit(client).json()["id"]
        assert blocking.started.wait(TIMEOUT)
        submit(client)  # queued
        assert len(job_dirs(tmp_path)) == 2
        # The running job finishes after shutdown starts; its files must still go.
        threading.Timer(0.1, blocking.release.set).start()
    assert running
    deadline = time.monotonic() + TIMEOUT
    while job_dirs(tmp_path):
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert len(blocking.calls) == 1


def test_no_threads_until_first_job(tmp_path):
    client, manager = make_client(tmp_path, FakeExtractor())
    client.get("/healthz")
    assert manager._threads == []
    wait_for(client, submit(client).json()["id"], "succeeded")
    assert len(manager._threads) == 1
    manager.shutdown()
    assert manager._threads == []


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("TEP_JOB_WORKERS", "3")
    monkeypatch.setenv("TEP_JOB_MAX_QUEUED", "7")
    monkeypatch.setenv("TEP_JOB_TTL_SECONDS", "120")
    monkeypatch.setenv("TEP_JOB_CLEANUP_INTERVAL", "5")
    monkeypatch.setenv("TEP_JOBS_DIR", "/tmp/tep-jobs-test")
    s = Settings.from_env()
    assert (s.job_workers, s.job_max_queued, s.job_ttl_seconds, s.job_cleanup_interval, s.jobs_dir) == (
        3,
        7,
        120.0,
        5.0,
        "/tmp/tep-jobs-test",
    )
    app = create_app(s)
    assert app.state.jobs.workers == 3 and app.state.jobs.max_queued == 7


def test_invalid_pool_size():
    with pytest.raises(ValueError):
        JobManager(workers=0)
    with pytest.raises(ValueError):
        JobManager(max_queued=0)
