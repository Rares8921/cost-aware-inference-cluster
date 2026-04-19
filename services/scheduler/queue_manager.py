import json
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()


@dataclass
class QueueItem:
    id: str
    tenant_id: str
    payload: dict
    priority: int
    timestamp: float
    timeout_ms: float


class QueueManager:
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.redis: Optional[aioredis.Redis] = None
        self._queue_key = "inference:queue"
        self._processing_key = "inference:processing"
        self._metrics_key = "inference:metrics"

    async def connect(self):
        self.redis = await aioredis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True
        )
        logger.info("queue_manager_connected", redis_url=self.redis_url)

    async def disconnect(self):
        if self.redis:
            await self.redis.close()

    async def enqueue(self, item: QueueItem) -> bool:
        if not self.redis:
            raise RuntimeError("Redis not connected")

        item_data = {
            "id": item.id,
            "tenant_id": item.tenant_id,
            "payload": json.dumps(item.payload),
            "priority": item.priority,
            "timestamp": item.timestamp,
            "timeout_ms": item.timeout_ms,
        }

        score = -item.priority + item.timestamp / 1000000

        await self.redis.zadd(
            self._queue_key,
            {json.dumps(item_data): score}
        )

        await self._update_metrics("enqueued", 1)
        logger.debug("item_enqueued", item_id=item.id, tenant_id=item.tenant_id)
        return True

    async def dequeue(self, worker_id: str, batch_size: int = 1) -> List[QueueItem]:
        if not self.redis:
            raise RuntimeError("Redis not connected")

        items = []

        for _ in range(batch_size):
            result = await self.redis.zpopmin(self._queue_key, 1)
            if not result:
                break

            item_json, _ = result[0]
            item_data = json.loads(item_json)

            item = QueueItem(
                id=item_data["id"],
                tenant_id=item_data["tenant_id"],
                payload=json.loads(item_data["payload"]),
                priority=item_data["priority"],
                timestamp=item_data["timestamp"],
                timeout_ms=item_data["timeout_ms"],
            )

            await self.redis.hset(
                f"{self._processing_key}:{item.id}",
                mapping={
                    "worker_id": worker_id,
                    "start_time": time.time(),
                    "item": item_json,
                }
            )

            items.append(item)

        if items:
            await self._update_metrics("dequeued", len(items))
            logger.debug("items_dequeued", count=len(items), worker_id=worker_id)

        return items

    async def complete(self, item_id: str, success: bool = True):
        if not self.redis:
            raise RuntimeError("Redis not connected")

        processing_key = f"{self._processing_key}:{item_id}"
        item_data = await self.redis.hgetall(processing_key)

        if item_data:
            start_time = float(item_data.get("start_time", 0))
            latency_ms = (time.time() - start_time) * 1000

            await self._record_latency(latency_ms)
            await self._update_metrics("completed" if success else "failed", 1)
            await self.redis.delete(processing_key)

            logger.debug(
                "item_completed",
                item_id=item_id,
                success=success,
                latency_ms=latency_ms
            )

    async def get_queue_depth(self) -> int:
        if not self.redis:
            return 0
        return await self.redis.zcard(self._queue_key)

    async def get_processing_count(self) -> int:
        if not self.redis:
            return 0
        keys = await self.redis.keys(f"{self._processing_key}:*")
        return len(keys)

    async def get_metrics(self) -> Dict:
        if not self.redis:
            return {}

        metrics = await self.redis.hgetall(self._metrics_key)
        latencies = await self._get_latencies()

        result = {
            "queue_depth": await self.get_queue_depth(),
            "processing_count": await self.get_processing_count(),
            "enqueued": int(metrics.get("enqueued", 0)),
            "dequeued": int(metrics.get("dequeued", 0)),
            "completed": int(metrics.get("completed", 0)),
            "failed": int(metrics.get("failed", 0)),
        }

        if latencies:
            latencies_sorted = sorted(latencies)
            result["latency_p50"] = latencies_sorted[len(latencies) // 2]
            result["latency_p95"] = latencies_sorted[int(len(latencies) * 0.95)]
            result["latency_p99"] = latencies_sorted[int(len(latencies) * 0.99)]
            result["latency_mean"] = sum(latencies) / len(latencies)

        return result

    async def _update_metrics(self, metric: str, value: int):
        if self.redis:
            await self.redis.hincrby(self._metrics_key, metric, value)

    async def _record_latency(self, latency_ms: float):
        if self.redis:
            await self.redis.lpush(f"{self._metrics_key}:latencies", latency_ms)
            await self.redis.ltrim(f"{self._metrics_key}:latencies", 0, 999)

    async def _get_latencies(self) -> List[float]:
        if not self.redis:
            return []
        latencies_str = await self.redis.lrange(f"{self._metrics_key}:latencies", 0, -1)
        return [float(l) for l in latencies_str]
