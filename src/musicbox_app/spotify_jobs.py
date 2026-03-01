import threading
import time
import uuid
from typing import Any, Dict, List

from .mappings import normalize_spotify_target
from .spotify_cache import SpotifyCacheResolver
from .store import AppStore


class SpotifyCacheJobManager:
    def __init__(self, store: AppStore, resolver: SpotifyCacheResolver, max_jobs: int = 120) -> None:
        self.store = store
        self.resolver = resolver
        self.max_jobs = max(20, int(max_jobs))
        self._lock = threading.RLock()
        self._queue_cond = threading.Condition(self._lock)
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._order: List[str] = []
        self._queue: List[str] = []
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def _now(self) -> int:
        return int(time.time())

    def _copy_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        return {
            'id': str(job.get('id', '')),
            'target': str(job.get('target', '')),
            'refresh': bool(job.get('refresh', False)),
            'status': str(job.get('status', 'queued')),
            'cached_path': job.get('cached_path'),
            'error': job.get('error'),
            'created_at': int(job.get('created_at', 0) or 0),
            'updated_at': int(job.get('updated_at', 0) or 0),
        }

    def _prune_locked(self) -> None:
        while len(self._order) > self.max_jobs:
            oldest = self._order.pop(0)
            self._jobs.pop(oldest, None)
            try:
                self._queue.remove(oldest)
            except ValueError:
                pass

    def list_jobs(self, *, limit: int = 40) -> List[Dict[str, Any]]:
        lim = max(1, min(200, int(limit)))
        with self._lock:
            out: List[Dict[str, Any]] = []
            for job_id in reversed(self._order[-lim:]):
                job = self._jobs.get(job_id)
                if not job:
                    continue
                out.append(self._copy_job(job))
            return out

    def enqueue(self, target: str, *, refresh: bool = False) -> Dict[str, Any]:
        uri = normalize_spotify_target(target)
        now = self._now()
        with self._lock:
            for job_id in reversed(self._order):
                job = self._jobs.get(job_id)
                if not job:
                    continue
                if str(job.get('target')) == uri and str(job.get('status')) in {'queued', 'running'}:
                    if refresh and str(job.get('status')) == 'queued':
                        job['refresh'] = True
                        job['updated_at'] = now
                    return self._copy_job(job)

            job_id = uuid.uuid4().hex[:12]
            job = {
                'id': job_id,
                'target': uri,
                'refresh': bool(refresh),
                'status': 'queued',
                'cached_path': None,
                'error': None,
                'created_at': now,
                'updated_at': now,
            }
            self._jobs[job_id] = job
            self._order.append(job_id)
            self._prune_locked()

        self.store.add_event(f'SPOTIFY_JOB_QUEUED {uri} refresh={1 if refresh else 0}')
        with self._queue_cond:
            self._queue.append(job_id)
            self._queue_cond.notify()
        return self._copy_job(job)

    def _worker_loop(self) -> None:
        while True:
            with self._queue_cond:
                while not self._queue:
                    self._queue_cond.wait(timeout=2.0)
                job_id = self._queue.pop(0)
            self._run_job(job_id)

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job['status'] = 'running'
            job['updated_at'] = self._now()
            target = str(job.get('target', '')).strip()
            refresh = bool(job.get('refresh', False))

        self.store.add_event(f'SPOTIFY_JOB_START {target} refresh={1 if refresh else 0}')
        try:
            cached_path = self.resolver.resolve(target, refresh=refresh)
            with self._lock:
                job = self._jobs.get(job_id)
                if not job:
                    return
                job['status'] = 'done'
                job['cached_path'] = cached_path
                job['error'] = None
                job['updated_at'] = self._now()
            self.store.add_event(f'SPOTIFY_JOB_DONE {target} -> {cached_path}')
        except Exception as exc:
            with self._lock:
                job = self._jobs.get(job_id)
                if not job:
                    return
                job['status'] = 'error'
                job['cached_path'] = None
                job['error'] = str(exc)
                job['updated_at'] = self._now()
            self.store.add_event(f'SPOTIFY_JOB_ERR {target}: {exc}', level='error')
