"""REZE v5.0 — Worker Pool. 병렬 실행."""

import asyncio
import logging
import time
from datetime import datetime

try:
    from config import WORKER_MAX_CONCURRENT
except ImportError:
    WORKER_MAX_CONCURRENT = 3

logger = logging.getLogger("REZE.worker")


class WorkerPool:

    def __init__(self, max_workers: int = None, ssot=None):
        # config.py에서 읽되, 인자로 오버라이드 가능
        self.max_workers = max_workers or WORKER_MAX_CONCURRENT
        self.semaphore = asyncio.Semaphore(self.max_workers)
        self.active: dict[str, asyncio.Task] = {}
        self.history: list[dict] = []
        self.ssot = ssot

    async def submit(self, task_id: str, name: str, coro) -> str:
        async def _worker():
            async with self.semaphore:
                logger.info(f"Worker start: {name}")
                t0 = time.time()
                try:
                    result = await coro
                    dur = round(time.time() - t0, 1)
                    self.history.append({
                        "task_id": task_id, "name": name,
                        "status": "completed", "duration_s": dur,
                        "at": datetime.now().isoformat()
                    })
                    if len(self.history) > 50:
                        self.history = self.history[-50:]
                    logger.info(f"Worker done: {name} ({dur}s)")
                    return result
                except Exception as e:
                    dur = round(time.time() - t0, 1)
                    self.history.append({
                        "task_id": task_id, "name": name,
                        "status": "failed", "error": str(e)[:200],
                        "duration_s": dur, "at": datetime.now().isoformat()
                    })
                    logger.error(f"Worker failed: {name} — {e}")
                    raise

        task = asyncio.create_task(_worker())
        self.active[task_id] = task
        task.add_done_callback(lambda _: self.active.pop(task_id, None))
        return task_id

    async def wait_all(self, timeout=300):
        if not self.active:
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(*self.active.values(), return_exceptions=True),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.warning(f"WorkerPool timeout {timeout}s")

    def status(self) -> dict:
        return {
            "max_workers": self.max_workers,
            "active": len(self.active),
            "completed_total": len(self.history),
            "recent": self.history[-5:]
        }

    async def cancel_all(self):
        for task in self.active.values():
            if not task.done():
                task.cancel()
