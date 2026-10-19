"""
In-process job queue for the async extraction API.

Jobs run on a small pool of worker threads owned by the API process. Each job
has its own temporary directory holding the upload and, once it succeeds, the
extracted tables (``tables.json``) and any exported result files. Job
metadata (status, timestamps, errors) is kept in memory.

This is deliberately per-process: jobs are lost when the process restarts and
are not visible to other replicas. See the README for what a Redis/RQ-backed
version would change.
"""

import json
import logging
import shutil
import tempfile
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional

from fastapi.encoders import jsonable_encoder

from .._deps import MissingDependencyError

logger = logging.getLogger(__name__)

QUEUED = "queued"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
FINISHED = (SUCCEEDED, FAILED)

TABLES_FILE = "tables.json"

Clock = Callable[[], float]
Extractor = Callable[[Path, str, float], List[Dict[str, Any]]]


class QueueFull(Exception):
    """Raised when ``max_queued`` jobs are already waiting for a worker."""


def _iso(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def count_pages(path: Path) -> Optional[int]:
    """Number of pages of a PDF (1 for images), or None if it cannot be read."""
    if path.suffix.lower() != ".pdf":
        return 1
    try:
        import fitz

        with fitz.open(path) as doc:
            return doc.page_count
    except Exception:
        return None


@dataclass
class Job:
    id: str
    directory: Path
    filename: str
    engine: str
    confidence: float
    include_metadata: bool
    output_format: str
    created_at: float
    extractor: Optional[Extractor] = None
    upload_path: Optional[Path] = None
    status: str = QUEUED
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    expires_at: Optional[float] = None
    pages_total: Optional[int] = None
    pages_done: int = 0
    total_tables: Optional[int] = None
    error: Optional[Dict[str, Any]] = None
    cancel_requested: bool = False
    _submitted: bool = field(default=False, repr=False)

    @property
    def tables_path(self) -> Path:
        return self.directory / TABLES_FILE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "filename": self.filename,
            "engine": self.engine,
            "progress": {"pages_done": self.pages_done, "pages_total": self.pages_total},
            "total_tables": self.total_tables,
            "created_at": _iso(self.created_at),
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "expires_at": _iso(self.expires_at),
            "cancel_requested": self.cancel_requested,
            "error": self.error,
        }


class JobManager:
    """
    Bounded in-process job queue.

    - ``workers`` threads run jobs; they are started on the first submission,
      so importing the app or using only the sync endpoints starts no threads.
    - At most ``max_queued`` jobs may wait for a worker; ``create`` raises
      :class:`QueueFull` beyond that. Running jobs do not count.
    - Finished jobs expire ``ttl_seconds`` after they finish. Expired jobs are
      removed by :meth:`cleanup_expired`, which a janitor thread calls every
      ``cleanup_interval`` seconds, and are treated as gone on lookup even
      before the janitor runs.
    - ``clock`` returns the current time in epoch seconds; inject a fake one
      to test expiry.
    """

    def __init__(
        self,
        workers: int = 1,
        max_queued: int = 16,
        ttl_seconds: float = 3600.0,
        cleanup_interval: float = 60.0,
        base_dir: Optional[Path] = None,
        clock: Clock = time.time,
    ):
        if workers < 1:
            raise ValueError("workers must be at least 1")
        if max_queued < 1:
            raise ValueError("max_queued must be at least 1")
        self.workers = workers
        self.max_queued = max_queued
        self.ttl_seconds = ttl_seconds
        self.cleanup_interval = cleanup_interval
        self.base_dir = Path(base_dir) if base_dir else None
        self.clock = clock
        self._jobs: Dict[str, Job] = {}
        self._queue: Deque[str] = deque()
        self._cond = threading.Condition()
        self._threads: List[threading.Thread] = []
        self._stopping = threading.Event()

    # -- lifecycle -----------------------------------------------------------

    def _ensure_started(self):
        # Called with self._cond held.
        if self._threads or self._stopping.is_set():
            return
        for i in range(self.workers):
            t = threading.Thread(target=self._worker, name=f"tep-job-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)
        if self.cleanup_interval > 0:
            t = threading.Thread(target=self._janitor, name="tep-job-janitor", daemon=True)
            t.start()
            self._threads.append(t)

    def shutdown(self, timeout: float = 5.0):
        """Stop the workers and remove every job directory.

        A job that is mid-extraction cannot be interrupted; its worker removes
        the job's files when the extraction returns.
        """
        self._stopping.set()
        with self._cond:
            self._cond.notify_all()
            jobs = list(self._jobs.values())
            self._jobs.clear()
            self._queue.clear()
        for job in jobs:
            if job.status != RUNNING:
                _remove_dir(job.directory)
        for t in self._threads:
            t.join(timeout)
        self._threads = []

    # -- submission ----------------------------------------------------------

    def create(
        self,
        filename: str,
        engine: str,
        confidence: float,
        include_metadata: bool,
        output_format: str,
    ) -> Job:
        """Reserve a queue slot and a temp directory for a new job.

        The job is not visible to workers until :meth:`submit`; call
        :meth:`discard` if the upload turns out to be invalid.
        """
        with self._cond:
            if self._stopping.is_set():
                raise QueueFull("job manager is shutting down")
            if self._queued_count() >= self.max_queued:
                raise QueueFull(f"{self.max_queued} jobs are already queued")
            if self.base_dir:
                self.base_dir.mkdir(parents=True, exist_ok=True)
            directory = Path(tempfile.mkdtemp(prefix="tep-job-", dir=self.base_dir))
            job = Job(
                id=uuid.uuid4().hex,
                directory=directory,
                filename=filename,
                engine=engine,
                confidence=confidence,
                include_metadata=include_metadata,
                output_format=output_format,
                created_at=self.clock(),
            )
            self._jobs[job.id] = job
            return job

    def submit(self, job: Job, upload_path: Path, extractor: Extractor):
        with self._cond:
            if self._jobs.get(job.id) is not job:
                raise KeyError(job.id)
            job.upload_path = upload_path
            job.extractor = extractor
            job._submitted = True
            self._queue.append(job.id)
            self._ensure_started()
            self._cond.notify()

    def discard(self, job: Job):
        with self._cond:
            self._jobs.pop(job.id, None)
        _remove_dir(job.directory)

    def _queued_count(self) -> int:
        return sum(1 for j in self._jobs.values() if j.status == QUEUED)

    # -- queries -------------------------------------------------------------

    def get(self, job_id: str) -> Optional[Job]:
        with self._cond:
            job = self._jobs.get(job_id)
            if job is None or not job._submitted:
                return None
            if self._is_expired(job):
                self._remove_locked(job)
                return None
            return job

    def snapshot(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._cond:
            job = self.get(job_id)
            return job.to_dict() if job else None

    def load_tables(self, job: Job) -> List[Dict[str, Any]]:
        with open(job.tables_path, encoding="utf-8") as f:
            return json.load(f)

    def _is_expired(self, job: Job) -> bool:
        return job.expires_at is not None and self.clock() >= job.expires_at

    # -- cancellation / removal ------------------------------------------------

    def delete(self, job_id: str) -> Optional[str]:
        """Cancel or remove a job.

        Returns ``"cancelled"`` for a queued job (removed before it ran),
        ``"cancel_requested"`` for a running job (its output is discarded and
        its files removed when the extraction returns), ``"deleted"`` for a
        finished job, or None if there is no such job.
        """
        with self._cond:
            job = self.get(job_id)
            if job is None:
                return None
            if job.status == RUNNING:
                job.cancel_requested = True
                return "cancel_requested"
            outcome = "cancelled" if job.status == QUEUED else "deleted"
            self._remove_locked(job)
            return outcome

    def _remove_locked(self, job: Job):
        # Called with self._cond held.
        self._jobs.pop(job.id, None)
        try:
            self._queue.remove(job.id)
        except ValueError:
            pass
        _remove_dir(job.directory)

    def cleanup_expired(self) -> int:
        """Remove every finished job past its TTL. Returns how many were removed."""
        with self._cond:
            expired = [j for j in self._jobs.values() if self._is_expired(j)]
            for job in expired:
                self._remove_locked(job)
        if expired:
            logger.info(f"Removed {len(expired)} expired job(s)")
        return len(expired)

    # -- workers ---------------------------------------------------------------

    def _next_job(self) -> Optional[Job]:
        with self._cond:
            while not self._queue and not self._stopping.is_set():
                self._cond.wait()
            if self._stopping.is_set():
                return None
            job = self._jobs[self._queue.popleft()]
            job.status = RUNNING
            job.started_at = self.clock()
            return job

    def _worker(self):
        while True:
            job = self._next_job()
            if job is None:
                return
            self._run(job)

    def _run(self, job: Job):
        tables = None
        error = None
        try:
            job.pages_total = count_pages(job.upload_path)
            tables = job.extractor(job.upload_path, job.engine, job.confidence)
            with open(job.tables_path, "w", encoding="utf-8") as f:
                json.dump(jsonable_encoder(tables), f)
        except MissingDependencyError as e:
            error = {"code": "backend_unavailable", "message": str(e), "details": {"extra": e.extra}}
        except ValueError as e:
            error = {"code": "unprocessable", "message": str(e), "details": None}
        except Exception:
            logger.exception(f"Job {job.id} failed")
            error = {"code": "internal_error", "message": "Extraction failed", "details": None}
        finally:
            # The upload is no longer needed whatever happened.
            if job.upload_path is not None:
                job.upload_path.unlink(missing_ok=True)

        with self._cond:
            job.extractor = None
            job.finished_at = self.clock()
            if self._jobs.get(job.id) is not job or job.cancel_requested:
                # Cancelled while running, or the manager shut down.
                self._remove_locked(job)
                return
            if error is None:
                job.status = SUCCEEDED
                job.total_tables = len(tables)
                if job.pages_total is not None:
                    job.pages_done = job.pages_total
            else:
                job.status = FAILED
                job.error = error
                # Nothing to download from a failed job: keep only its record.
                _remove_dir(job.directory)
            job.expires_at = job.finished_at + self.ttl_seconds

    def _janitor(self):
        while not self._stopping.wait(self.cleanup_interval):
            try:
                self.cleanup_expired()
            except Exception:
                logger.exception("Job cleanup failed")


def _remove_dir(directory: Path):
    shutil.rmtree(directory, ignore_errors=True)
