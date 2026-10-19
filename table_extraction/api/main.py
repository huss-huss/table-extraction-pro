"""
FastAPI REST API for table extraction.

Configuration (environment variables):

- ``TEP_MAX_UPLOAD_MB``   maximum request body size, default 20
- ``TEP_MAX_BATCH_FILES`` maximum files per batch request, default 10
- ``TEP_CORS_ORIGINS``    comma-separated allowed origins, default none
- ``TEP_DEFAULT_ENGINE``  auto | tatr | fallback, default auto

Async jobs (``/jobs``), all per-process:

- ``TEP_JOB_WORKERS``          worker threads running jobs, default 1
- ``TEP_JOB_MAX_QUEUED``       jobs waiting for a worker before ``POST /jobs`` gets 429, default 16
- ``TEP_JOB_TTL_SECONDS``      how long a finished job and its files are kept, default 3600
- ``TEP_JOB_CLEANUP_INTERVAL`` seconds between expiry sweeps, default 60
- ``TEP_JOBS_DIR``             parent directory for per-job temp dirs, default the system temp dir

Errors are returned as ``{"error": {"code": str, "message": str, "details": any}}``.
"""

import io
import logging
import os
import re
import tempfile
import zipfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import Depends, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .. import __version__
from .._deps import MissingDependencyError, available_backends
from ..engine import ENGINES
from ..engine import extract_tables as run_engine
from ..export.formats import export_to_excel, export_to_html, table_to_csv, table_to_html
from ..extraction.pipeline import TableExtractionPipeline
from ..parsers.parser_comparator import ParserComparator
from .jobs import FINISHED, SUCCEEDED, JobManager, QueueFull

logger = logging.getLogger(__name__)

CHUNK = 1024 * 1024


@dataclass(frozen=True)
class Settings:
    max_upload_bytes: int
    max_batch_files: int
    cors_origins: List[str]
    default_engine: str
    job_workers: int = 1
    job_max_queued: int = 16
    job_ttl_seconds: float = 3600.0
    job_cleanup_interval: float = 60.0
    jobs_dir: Optional[str] = None

    @classmethod
    def from_env(cls) -> "Settings":
        origins = [o.strip() for o in os.getenv("TEP_CORS_ORIGINS", "").split(",") if o.strip()]
        engine = os.getenv("TEP_DEFAULT_ENGINE", "auto")
        if engine not in ENGINES:
            raise ValueError(f"TEP_DEFAULT_ENGINE must be one of {ENGINES}, got {engine!r}")
        return cls(
            max_upload_bytes=int(float(os.getenv("TEP_MAX_UPLOAD_MB", "20")) * 1024 * 1024),
            max_batch_files=int(os.getenv("TEP_MAX_BATCH_FILES", "10")),
            cors_origins=origins,
            default_engine=engine,
            job_workers=int(os.getenv("TEP_JOB_WORKERS", "1")),
            job_max_queued=int(os.getenv("TEP_JOB_MAX_QUEUED", "16")),
            job_ttl_seconds=float(os.getenv("TEP_JOB_TTL_SECONDS", "3600")),
            job_cleanup_interval=float(os.getenv("TEP_JOB_CLEANUP_INTERVAL", "60")),
            jobs_dir=os.getenv("TEP_JOBS_DIR") or None,
        )


# Accepted upload types: extension -> (allowed declared content types, magic-byte check)
_TIFF = (b"II*\x00", b"MM\x00*")
FILE_TYPES: Dict[str, tuple] = {
    ".pdf": ({"application/pdf", "application/x-pdf"}, lambda h: h.startswith(b"%PDF-")),
    ".png": ({"image/png"}, lambda h: h.startswith(b"\x89PNG\r\n\x1a\n")),
    ".jpg": ({"image/jpeg"}, lambda h: h.startswith(b"\xff\xd8\xff")),
    ".jpeg": ({"image/jpeg"}, lambda h: h.startswith(b"\xff\xd8\xff")),
    ".tif": ({"image/tiff"}, lambda h: h.startswith(_TIFF)),
    ".tiff": ({"image/tiff"}, lambda h: h.startswith(_TIFF)),
    ".bmp": ({"image/bmp", "image/x-ms-bmp"}, lambda h: h.startswith(b"BM")),
}
# Clients often send these for any file; accept them and rely on the magic bytes.
GENERIC_CONTENT_TYPES = {"", "application/octet-stream"}


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None, headers=None):
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


def error_body(code: str, message: str, details: Any = None) -> Dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


class BodySizeLimitMiddleware:
    """Reject request bodies above ``max_bytes`` before they are parsed or spooled."""

    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            return await self._reject(send)

        received = 0
        exceeded = False
        replaced = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            if exceeded:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Stop reading; whatever the app answers is replaced by a 413 below.
                    exceeded = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message):
            nonlocal replaced
            if exceeded:
                if not replaced:
                    replaced = True
                    await self._reject(send)
                return
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not exceeded:
                raise
            if not replaced:
                await self._reject(send)

    async def _reject(self, send: Send):
        response = JSONResponse(
            status_code=413,
            content=error_body(
                "payload_too_large",
                f"Request body exceeds the {self.max_bytes // (1024 * 1024)} MB limit",
                {"max_bytes": self.max_bytes},
            ),
        )
        await response({"type": "http"}, _empty_receive, send)


async def _empty_receive() -> Message:
    return {"type": "http.disconnect"}


Extractor = Callable[[Path, str, float], List[Dict[str, Any]]]


RESULT_FORMATS = ("json", "csv", "html", "xlsx")
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def create_app(settings: Optional[Settings] = None, job_manager: Optional[JobManager] = None) -> FastAPI:
    """Build the API. ``job_manager`` can be injected (tests use a fake clock)."""
    settings = settings or Settings.from_env()
    jobs = job_manager or JobManager(
        workers=settings.job_workers,
        max_queued=settings.job_max_queued,
        ttl_seconds=settings.job_ttl_seconds,
        cleanup_interval=settings.job_cleanup_interval,
        base_dir=Path(settings.jobs_dir) if settings.jobs_dir else None,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        # Job workers start on the first submission; stop them and remove
        # every job directory on shutdown (jobs do not survive a restart).
        jobs.shutdown()

    app = FastAPI(
        title="Table Extraction Pro API",
        description="Extract tables from PDFs and images",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.jobs = jobs
    # Models are loaded on first use and reused across requests.
    app.state.pipeline = None
    app.state.comparator = None

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["*"],
        )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_upload_bytes)

    @app.exception_handler(APIError)
    async def _api_error(request: Request, exc: APIError):
        return JSONResponse(
            status_code=exc.status,
            content=error_body(exc.code, exc.message, exc.details),
            headers=exc.headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(status_code=exc.status_code, content=error_body(code, str(exc.detail)))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse(
            status_code=422, content=error_body("validation_error", "Invalid request", details)
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        logger.exception("Unhandled error")
        return JSONResponse(status_code=500, content=error_body("internal_error", "Internal server error"))

    def get_extractor() -> Extractor:
        def extract(path: Path, engine: str, confidence: float) -> List[Dict[str, Any]]:
            if app.state.pipeline is None:
                app.state.pipeline = TableExtractionPipeline()
                app.state.comparator = ParserComparator()
            return run_engine(path, engine, confidence, app.state.pipeline, app.state.comparator)

        return extract

    app.state.get_extractor = get_extractor

    @app.get("/")
    def root():
        return {
            "name": "Table Extraction Pro API",
            "version": __version__,
            "endpoints": {
                "extract": "/extract",
                "batch": "/extract/batch",
                "jobs": "/jobs",
                "health": "/healthz",
                "docs": "/docs",
            },
        }

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "version": __version__, "backends": available_backends()}

    @app.get("/health", include_in_schema=False)
    def health():
        return healthz()

    def _validate_params(confidence: float, engine: str, output_format: str):
        if not 0.0 <= confidence <= 1.0:
            raise APIError(400, "invalid_parameter", "confidence must be between 0.0 and 1.0")
        if engine not in ENGINES:
            raise APIError(400, "invalid_parameter", f"engine must be one of {', '.join(ENGINES)}")
        if output_format not in ("json", "csv", "html"):
            raise APIError(400, "invalid_parameter", "output_format must be json, csv or html")

    def _save_upload(upload: UploadFile, directory: Path) -> Path:
        """Validate the upload's type and copy it into ``directory``."""
        name = Path(upload.filename or "").name
        suffix = Path(name).suffix.lower()
        if suffix not in FILE_TYPES:
            raise APIError(
                415,
                "unsupported_media_type",
                f"Unsupported file extension {suffix or '(none)'!r}",
                {"allowed": sorted(FILE_TYPES)},
            )
        allowed_types, magic = FILE_TYPES[suffix]
        declared = (upload.content_type or "").split(";")[0].strip().lower()
        if declared not in allowed_types | GENERIC_CONTENT_TYPES:
            raise APIError(
                415,
                "unsupported_media_type",
                f"Content-Type {declared!r} does not match a {suffix} file",
                {"expected": sorted(allowed_types)},
            )
        head = upload.file.read(16)
        if not head:
            raise APIError(400, "empty_file", "Uploaded file is empty")
        if not magic(head):
            raise APIError(415, "unsupported_media_type", f"File content is not a valid {suffix} file")
        upload.file.seek(0)
        dest = directory / f"upload{suffix}"
        size = 0
        with open(dest, "wb") as out:  # closed (and flushed) before extraction reads it
            while chunk := upload.file.read(CHUNK):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise APIError(413, "payload_too_large", "Uploaded file is too large")
                out.write(chunk)
        return dest

    def _run(upload: UploadFile, extractor: Extractor, engine: str, confidence: float):
        with tempfile.TemporaryDirectory(prefix="tep-") as tmp:
            path = _save_upload(upload, Path(tmp))
            try:
                return extractor(path, engine, confidence)
            except MissingDependencyError as e:
                raise APIError(503, "backend_unavailable", str(e), {"extra": e.extra}) from e
            except ValueError as e:
                raise APIError(422, "unprocessable", str(e)) from e

    def _format(tables: List[Dict[str, Any]], output_format: str, include_metadata: bool) -> Dict[str, Any]:
        if output_format == "csv":
            return {
                "tables": [
                    {"table_id": t["table_id"], "page_number": t["page_number"], "csv": table_to_csv(t)}
                    for t in tables
                ]
            }
        if output_format == "html":
            return {
                "tables": [
                    {"table_id": t["table_id"], "page_number": t["page_number"], "html": table_to_html(t)}
                    for t in tables
                ]
            }
        if include_metadata:
            return {"tables": tables}
        return {
            "tables": [
                {"table_id": t["table_id"], "page_number": t["page_number"], "data": t["data"]}
                for t in tables
            ]
        }

    # Sync endpoints: FastAPI runs them in a worker thread, so CPU-bound
    # extraction does not block the event loop.
    @app.post("/extract")
    def extract(
        file: UploadFile = File(...),
        confidence: float = Form(0.5),
        engine: Optional[str] = Form(None),
        use_fallback: bool = Form(False),
        include_metadata: bool = Form(True),
        output_format: str = Form("json"),
        extractor: Extractor = Depends(get_extractor),
    ):
        engine = "fallback" if use_fallback else (engine or settings.default_engine)
        _validate_params(confidence, engine, output_format)
        tables = _run(file, extractor, engine, confidence)
        return {
            "filename": file.filename,
            "engine": engine,
            "total_tables": len(tables),
            "format": output_format,
            **_format(tables, output_format, include_metadata),
        }

    @app.post("/extract/batch")
    def extract_batch(
        files: List[UploadFile] = File(...),
        confidence: float = Form(0.5),
        engine: Optional[str] = Form(None),
        use_fallback: bool = Form(False),
        include_metadata: bool = Form(True),
        output_format: str = Form("json"),
        extractor: Extractor = Depends(get_extractor),
    ):
        engine = "fallback" if use_fallback else (engine or settings.default_engine)
        _validate_params(confidence, engine, output_format)
        if len(files) > settings.max_batch_files:
            raise APIError(
                400, "too_many_files", f"At most {settings.max_batch_files} files per batch request"
            )
        results = []
        for upload in files:
            try:
                tables = _run(upload, extractor, engine, confidence)
                results.append(
                    {
                        "filename": upload.filename,
                        "total_tables": len(tables),
                        **_format(tables, output_format, include_metadata),
                    }
                )
            except APIError as e:
                results.append({"filename": upload.filename, **error_body(e.code, e.message, e.details)})
            except Exception:
                logger.exception(f"Failed to process {upload.filename}")
                results.append(
                    {"filename": upload.filename, **error_body("internal_error", "Extraction failed")}
                )
        return {"total_files": len(files), "engine": engine, "results": results}

    # Async jobs: the upload is validated and stored in the request, then
    # extracted by the in-process worker pool (see jobs.py).
    def _job_or_404(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            raise APIError(404, "job_not_found", f"No job with id {job_id!r}")
        return job

    def _job_status(job_id: str) -> Dict[str, Any]:
        status = jobs.snapshot(job_id)
        if status is None:
            raise APIError(404, "job_not_found", f"No job with id {job_id!r}")
        status["status_url"] = f"/jobs/{job_id}"
        status["result_url"] = f"/jobs/{job_id}/result" if status["status"] == SUCCEEDED else None
        return status

    @app.post("/jobs", status_code=202)
    def create_job(
        file: UploadFile = File(...),
        confidence: float = Form(0.5),
        engine: Optional[str] = Form(None),
        use_fallback: bool = Form(False),
        include_metadata: bool = Form(True),
        output_format: str = Form("json"),
        extractor: Extractor = Depends(get_extractor),
    ):
        engine = "fallback" if use_fallback else (engine or settings.default_engine)
        _validate_params(confidence, engine, output_format)
        try:
            job = jobs.create(file.filename or "", engine, confidence, include_metadata, output_format)
        except QueueFull:
            raise APIError(
                429,
                "queue_full",
                "Too many jobs are waiting; retry later",
                {"max_queued": jobs.max_queued},
                headers={"Retry-After": "5"},
            ) from None
        try:
            path = _save_upload(file, job.directory)
        except BaseException:
            jobs.discard(job)  # invalid upload: no job, no files
            raise
        jobs.submit(job, path, extractor)
        status = _job_status(job.id)
        return JSONResponse(status_code=202, content=status, headers={"Location": status["status_url"]})

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str):
        return _job_status(job_id)

    @app.get("/jobs/{job_id}/result")
    def get_job_result(
        job_id: str,
        format: Optional[str] = Query(None, description="json, csv, html or xlsx"),
        table_id: Optional[int] = Query(None, description="csv only: return just this table"),
    ):
        job = _job_or_404(job_id)
        if job.status not in FINISHED:
            raise APIError(409, "job_not_ready", f"Job is {job.status}", {"status": job.status})
        if job.status != SUCCEEDED:
            raise APIError(409, "job_failed", "Job failed; it has no result", job.error)
        fmt = format or job.output_format
        if fmt not in RESULT_FORMATS:
            raise APIError(400, "invalid_parameter", f"format must be one of {', '.join(RESULT_FORMATS)}")
        try:
            tables = jobs.load_tables(job)
            return _job_result(job, tables, fmt, table_id)
        except FileNotFoundError:
            # Deleted or expired while this request was being served.
            raise APIError(404, "job_not_found", f"No job with id {job_id!r}") from None

    def _job_result(job, tables: List[Dict[str, Any]], fmt: str, table_id: Optional[int]):
        stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(job.filename).stem) or "tables"
        if fmt == "json":
            return {
                "filename": job.filename,
                "engine": job.engine,
                "total_tables": len(tables),
                "format": "json",
                **_format(tables, "json", job.include_metadata),
            }
        if fmt == "csv":
            if table_id is not None:
                tables = [t for t in tables if t["table_id"] == table_id]
                if not tables:
                    raise APIError(404, "table_not_found", f"No table with table_id {table_id}")
            if len(tables) <= 1:
                body = table_to_csv(tables[0]) if tables else ""
                return _download(body.encode("utf-8"), "text/csv; charset=utf-8", f"{stem}.csv")
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for n, t in enumerate(tables, start=1):
                    zf.writestr(f"table_{n}_page_{t['page_number']}.csv", table_to_csv(t))
            return _download(buf.getvalue(), "application/zip", f"{stem}_csv.zip")
        # html and xlsx are written into the job directory, so they are removed with it.
        if fmt == "html":
            content = _export_in_job_dir(job, export_to_html, tables, ".html")
            return _download(content, "text/html; charset=utf-8", f"{stem}.html")
        content = _export_in_job_dir(job, export_to_excel, tables, ".xlsx")
        return _download(content, XLSX_MEDIA_TYPE, f"{stem}.xlsx")

    def _export_in_job_dir(job, exporter, tables, suffix: str) -> bytes:
        # A unique name per request, so concurrent downloads do not share a file.
        fd, name = tempfile.mkstemp(prefix="result-", suffix=suffix, dir=job.directory)
        os.close(fd)
        out = Path(name)
        try:
            exporter(tables, out, job.include_metadata)
            return out.read_bytes()
        finally:
            out.unlink(missing_ok=True)

    def _download(content: bytes, media_type: str, filename: str) -> Response:
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.delete("/jobs/{job_id}")
    def delete_job(job_id: str):
        outcome = jobs.delete(job_id)
        if outcome is None:
            raise APIError(404, "job_not_found", f"No job with id {job_id!r}")
        code = 202 if outcome == "cancel_requested" else 200
        return JSONResponse(status_code=code, content={"id": job_id, "result": outcome})

    return app


app = create_app()
