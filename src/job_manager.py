import uuid
import time
import threading
import json
import queue
from typing import Dict, Any, Callable
from . import database

class JobManager:
    def __init__(self):
        self.active_jobs: Dict[str, threading.Thread] = {}
        self.job_cancellation_events: Dict[str, threading.Event] = {}
        self.active_types: Dict[str, str] = {}
        self.lock = threading.Lock()
        
        # High-performance asynchronous log queue
        self._log_queue: queue.Queue = queue.Queue(maxsize=10000)
        self._last_progress: Dict[str, tuple[float, float, str]] = {}
        
        # Background worker for draining and batching logs into SQLite
        self._log_worker = threading.Thread(target=self._log_drain_loop, daemon=True, name="JobManager-LogWorker")
        self._log_worker.start()

    def _log_drain_loop(self):
        """Worker thread that continuously batches log inserts to minimize SQLite connection thrashing."""
        while True:
            try:
                first_item = self._log_queue.get(timeout=0.4)
            except queue.Empty:
                continue

            batch = [first_item]
            while len(batch) < 150:
                try:
                    batch.append(self._log_queue.get_nowait())
                except queue.Empty:
                    break

            try:
                conn = database.get_db()
                try:
                    conn.executemany(
                        "INSERT INTO logs (timestamp, level, message, job_id, details) VALUES (?, ?, ?, ?, ?)",
                        batch
                    )
                    conn.commit()
                finally:
                    conn.close()
            except Exception as e:
                print(f"[JobManager] Error committing log batch: {e}")
            finally:
                for _ in batch:
                    self._log_queue.task_done()

    def flush_logs(self, timeout: float = 1.0):
        """Waits until all currently queued logs are written to SQLite."""
        try:
            self._log_queue.join()
        except Exception:
            pass

    def _run_job(self, job_id: str, job_func: Callable, kwargs: dict, cancel_event: threading.Event):
        try:
            # Mark running
            self._update_job_status(job_id, "RUNNING")
            
            # Execute the job logic
            result = job_func(job_id=job_id, cancel_event=cancel_event, **kwargs)
            if isinstance(result, dict) and result.get("error"):
                raise RuntimeError(result["error"])
            
            if cancel_event.is_set():
                self._update_job_status(job_id, "CANCELLED")
                self.log(job_id, "INFO", "Job was cancelled by user.")
            else:
                message = result.get("message") if isinstance(result, dict) else None
                self._update_job_status(job_id, "COMPLETED", progress=100.0, message=message,
                                        details=json.dumps(result) if result else None)
                self.log(job_id, "INFO", "Job completed successfully.")
                
        except Exception as e:
            message = str(e) if type(e) in {ValueError, RuntimeError} else type(e).__name__
            self._update_job_status(job_id, "FAILED", message=message)
            self.log(job_id, "ERROR", f"Job failed: {message}")
        finally:
            # Cleanup active tracking first to avoid race conditions with subsequent jobs
            with self.lock:
                self.active_jobs.pop(job_id, None)
                self.job_cancellation_events.pop(job_id, None)
                self.active_types.pop(job_id, None)
                self._last_progress.pop(job_id, None)
            self.flush_logs(timeout=1.0)

    def start_job(self, job_type: str, job_func: Callable, **kwargs) -> str:
        with self.lock:
            heavy_jobs = {'storage', 'integrity', 'export_import', 'quality_scan', 'reconciliation', 'rebuild'}
            if job_type in self.active_types.values() or any(t in heavy_jobs for t in self.active_types.values()) or (
                job_type in heavy_jobs and self.active_types
            ) or (
                job_type in {"discovery", "download"}
                and any(t in {"discovery", "download"} for t in self.active_types.values())
            ):
                raise ValueError(f"A conflicting {job_type} job is already running")

            job_id = str(uuid.uuid4())
            now = int(time.time())
            conn = database.get_db()
            try:
                conn.execute(
                    "INSERT INTO jobs (id, type, status, progress, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (job_id, job_type, "QUEUED", 0.0, now, now)
                )
                conn.commit()
            finally:
                conn.close()

            cancel_event = threading.Event()
            thread = threading.Thread(target=self._run_job, args=(job_id, job_func, kwargs, cancel_event), daemon=True)
            self.job_cancellation_events[job_id] = cancel_event
            self.active_jobs[job_id] = thread
            self.active_types[job_id] = job_type
            thread.start()

        self.log(job_id, "INFO", f"Job {job_type} created.")
        return job_id
        
    def cancel_job(self, job_id: str):
        with self.lock:
            event = self.job_cancellation_events.get(job_id)
        if event:
            event.set()
            self.log(job_id, "INFO", "Cancellation requested.")
            return True
        return False

    def storage_busy(self):
        with self.lock:
            return 'storage' in self.active_types.values()
            
    def get_job(self, job_id: str) -> dict:
        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
        
    def get_all_jobs(self) -> list:
        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def _update_job_status(self, job_id: str, status: str, progress: float = None, message: str = None, details: str = None):
        conn = database.get_db()
        cursor = conn.cursor()
        now = int(time.time())
        
        updates = ["status = ?", "updated_at = ?"]
        params = [status, now]
        
        if progress is not None:
            updates.append("progress = ?")
            params.append(progress)
        if message is not None:
            updates.append("message = ?")
            params.append(message)
        if details is not None:
            updates.append("details = ?")
            params.append(details)
            
        params.append(job_id)
        
        query = f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, tuple(params))
        conn.commit()
        conn.close()
        
    def update_progress(self, job_id: str, progress: float, message: str = None):
        """Helper for services to update their progress with smart throttling to prevent disk churn."""
        now = time.time()
        last = self._last_progress.get(job_id)
        if last is not None:
            last_time, last_prog, last_msg = last
            # Throttle intermediate updates if called within 250ms and jump is small
            if (now - last_time < 0.25) and abs(progress - last_prog) < 3.0 and (message == last_msg) and progress < 100.0:
                return

        self._last_progress[job_id] = (now, progress, message)
        self._update_job_status(job_id, "RUNNING", progress=progress, message=message)

    def log(self, job_id: str, level: str, message: str, details: str = None):
        """Logs an event tied to a job asynchronously without blocking or locking SQLite."""
        now = int(time.time())
        try:
            self._log_queue.put_nowait((now, level, str(message), job_id, details))
        except queue.Full:
            # Fallback direct insert if queue is completely full
            try:
                conn = database.get_db()
                try:
                    conn.execute(
                        "INSERT INTO logs (timestamp, level, message, job_id, details) VALUES (?, ?, ?, ?, ?)",
                        (now, level, str(message), job_id, details)
                    )
                    conn.commit()
                finally:
                    conn.close()
            except Exception:
                pass
        
    def get_logs(self, limit: int = 100) -> list:
        # Flush pending logs first so queries are up-to-date
        self.flush_logs(timeout=0.2)
        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM logs ORDER BY timestamp DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

# Global instance
manager = JobManager()
