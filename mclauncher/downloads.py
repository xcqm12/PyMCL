"""多线程下载管理器：任务队列 + 进度回调 + 取消。"""
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import net, config


class Task:
    __slots__ = ("url", "dest", "sha1", "size", "label", "skip_if_exists")

    def __init__(self, url: str, dest: Path, sha1: str | None = None, size: int | None = None,
                 label: str = "", skip_if_exists: bool = True):
        self.url = url
        self.dest = Path(dest)
        self.sha1 = sha1
        self.size = size
        self.label = label or self.dest.name
        self.skip_if_exists = skip_if_exists


class Job:
    def __init__(self, tasks, on_update=None, on_finish=None):
        self.tasks = list(tasks)
        self.total_bytes = sum(t.size or 0 for t in self.tasks)
        self.unknown_count = sum(1 for t in self.tasks if not t.size)
        self.done_bytes = 0
        self.done_files = 0
        self.failed: list[str] = []
        self.cancelled = threading.Event()
        self.finished = threading.Event()
        self.ok = False
        self.error = None
        self._lock = threading.Lock()
        self.on_update = on_update
        self.on_finish = on_finish

    def update(self, delta: int):
        with self._lock:
            self.done_bytes += delta
        if self.on_update:
            try:
                self.on_update(self)
            except Exception:
                pass

    def file_done(self):
        with self._lock:
            self.done_files += 1
        self.on_update and self._update_fire()

    def _update_fire(self):
        if self.on_update:
            try:
                self.on_update(self)
            except Exception:
                pass


class DownloadManager:
    """可同时驱动多个 Job，但 UI 通常一次只跑一个。"""

    def __init__(self, threads: int | None = None):
        self.threads = threads
        self.current: Job | None = None

    def cancel(self):
        if self.current:
            self.current.cancelled.set()

    def run(self, job: Job):
        threading.Thread(target=self._execute, args=(job,), daemon=True).start()

    def run_blocking(self, job: Job, timeout: float | None = None) -> Job:
        self._execute(job)
        job.finished.wait(timeout)
        return job

    def _execute(self, job: Job):
        self.current = job
        workers = self.threads or int(config.get("download_threads", 16))
        workers = max(1, min(workers, 64))
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = [pool.submit(self._work, job, t) for t in job.tasks]
                for f in futs:
                    f.result()
            if job.cancelled.is_set():
                job.error = "已取消"
            elif job.failed:
                job.error = "部分文件下载失败: " + "；".join(job.failed[:5])
            else:
                job.ok = True
        except Exception as e:
            job.error = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        finally:
            job.finished.set()
            self.current = None
            if job.on_finish:
                try:
                    job.on_finish(job)
                except Exception:
                    pass

    def _work(self, job: Job, task: Task):
        if job.cancelled.is_set():
            return
        try:
            if task.dest.exists() and task.skip_if_exists:
                if task.size is None or task.dest.stat().st_size == task.size:
                    if task.size:
                        job.update(task.size)
                    job.file_done()
                    return
            net.download_stream(
                task.url, task.dest, sha1=task.sha1, size=task.size,
                progress=job.update, cancelled=job.cancelled)
            job.file_done()
        except Exception as e:
            if not job.cancelled.is_set():
                job.failed.append(f"{task.label} ({e})")
