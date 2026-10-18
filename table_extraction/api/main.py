"""
FastAPI REST API for table extraction.

Configuration (environment variables):

- ``TEP_MAX_UPLOAD_MB``   maximum request body size, default 20
- ``TEP_MAX_BATCH_FILES`` maximum files per batch request, default 10
- ``TEP_CORS_ORIGINS``    comma-separated allowed origins, default none
- ``TEP_DEFAULT_ENGINE``  auto | tatr | fallback, default auto

Errors are returned as ``{"error": {"code": str, "message": str, "details": any}}``.
"""

import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .. import __version__
from .._deps import MissingDependencyError, available_backends
from ..engine import ENGINES
from ..engine import extract_tables as run_engine
from ..export.formats import table_to_csv, table_to_html
from ..extraction.pipeline import TableExtractionPipeline
from ..parsers.parser_comparator import ParserComparator

logger = logging.getLogger(__name__)

CHUNK = 1024 * 1024


@dataclass(frozen=True)
class Settings:
    max_upload_bytes: int
    max_batch_files: int
    cors_origins: List[str]
    default_engine: str

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
    def __init__(self, status: int, code: str, message: str, details: Any = None):
        self.status = status
        self.code = code
        self.message = message
        self.details = details


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


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(
        title="Table Extraction Pro API",
        description="Extract tables from PDFs and images",
        version=__version__,
    )
    app.state.settings = settings
    # Models are loaded on first use and reused across requests.
    app.state.pipeline = None
    app.state.comparator = None

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_upload_bytes)

    @app.exception_handler(APIError)
    async def _api_error(request: Request, exc: APIError):
        return JSONResponse(status_code=exc.status, content=error_body(exc.code, exc.message, exc.details))

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

    return app


app = create_app()
