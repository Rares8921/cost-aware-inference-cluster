import asyncio
import time
from typing import List, Dict, Optional
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class BatchItem:
    id: str
    tenant_id: str
    text: str
    timestamp: float
    future: asyncio.Future


class DynamicBatcher:
    def __init__(
            self,
            max_batch_size: int,
            batch_timeout_ms: float,
            process_fn
    ):
        self.max_batch_size = max_batch_size
        self.batch_timeout_ms = batch_timeout_ms
        self.process_fn = process_fn

        self._queue: List[BatchItem] = []
        self._queue_lock = asyncio.Lock()
        self._batch_event = asyncio.Event()
        self._running = False
        self._task: Optional[asyncio.Task] = None

        self._batches_processed = 0
        self._items_processed = 0
        self._total_wait_time = 0.0

    async def start(self):
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._batch_loop())
        logger.info(
            "batcher_started",
            max_batch_size=self.max_batch_size,
            batch_timeout_ms=self.batch_timeout_ms
        )

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("batcher_stopped")

    async def add_item(self, item: BatchItem) -> dict:
        async with self._queue_lock:
            self._queue.append(item)

            if len(self._queue) >= self.max_batch_size:
                self._batch_event.set()

        return await item.future

    async def _batch_loop(self):
        while self._running:
            try:
                await asyncio.wait_for(
                    self._batch_event.wait(),
                    timeout=self.batch_timeout_ms / 1000
                )
            except asyncio.TimeoutError:
                pass

            self._batch_event.clear()

            async with self._queue_lock:
                if not self._queue:
                    continue

                batch_size = min(len(self._queue), self.max_batch_size)
                batch = self._queue[:batch_size]
                self._queue = self._queue[batch_size:]

            if batch:
                await self._process_batch(batch)

    async def _process_batch(self, batch: List[BatchItem]):
        batch_start = time.time()

        texts = [item.text for item in batch]

        total_wait_time = sum(batch_start - item.timestamp for item in batch)
        avg_wait_time = total_wait_time / len(batch)

        try:
            results = await asyncio.get_event_loop().run_in_executor(
                None,
                self.process_fn,
                texts
            )

            for item, result in zip(batch, results):
                if not item.future.done():
                    item.future.set_result({
                        "id": item.id,
                        "result": result,
                        "batch_size": len(batch),
                        "wait_time_ms": (batch_start - item.timestamp) * 1000,
                        "processing_time_ms": (time.time() - batch_start) * 1000,
                    })

        except Exception as e:
            logger.error("batch_processing_error", error=str(e), batch_size=len(batch))
            for item in batch:
                if not item.future.done():
                    item.future.set_exception(e)

        batch_time = time.time() - batch_start

        self._batches_processed += 1
        self._items_processed += len(batch)
        self._total_wait_time += total_wait_time

        logger.info(
            "batch_processed",
            batch_size=len(batch),
            avg_wait_time_ms=avg_wait_time * 1000,
            batch_time_ms=batch_time * 1000,
            throughput=len(batch) / batch_time if batch_time > 0 else 0,
        )

    def get_stats(self) -> Dict:
        return {
            "batches_processed": self._batches_processed,
            "items_processed": self._items_processed,
            "avg_batch_size": (
                self._items_processed / self._batches_processed
                if self._batches_processed > 0
                else 0
            ),
            "avg_wait_time_ms": (
                (self._total_wait_time / self._items_processed) * 1000
                if self._items_processed > 0
                else 0
            ),
            "queue_size": len(self._queue),
        }
