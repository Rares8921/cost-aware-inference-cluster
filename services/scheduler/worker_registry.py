import time
from typing import Dict, List
from dataclasses import dataclass
import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()


@dataclass
class WorkerInfo:
    id: str
    status: str
    model_version: str
    started_at: float
    last_heartbeat: float
    requests_processed: int
    is_warm: bool


class WorkerRegistry:
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.redis: aioredis.Redis = None
        self._workers_key = "scheduler:workers"
        self._heartbeat_timeout = 30

    async def connect(self):
        self.redis = await aioredis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True
        )

    async def disconnect(self):
        if self.redis:
            await self.redis.close()

    async def register_worker(self, worker: WorkerInfo):
        worker_data = {
            "id": worker.id,
            "status": worker.status,
            "model_version": worker.model_version,
            "started_at": worker.started_at,
            "last_heartbeat": worker.last_heartbeat,
            "requests_processed": worker.requests_processed,
            "is_warm": str(worker.is_warm),
        }

        await self.redis.hset(
            f"{self._workers_key}:{worker.id}",
            mapping=worker_data
        )

        logger.info("worker_registered", worker_id=worker.id, is_warm=worker.is_warm)

    async def update_heartbeat(self, worker_id: str):
        await self.redis.hset(
            f"{self._workers_key}:{worker_id}",
            "last_heartbeat",
            time.time()
        )

    async def get_worker(self, worker_id: str) -> WorkerInfo:
        data = await self.redis.hgetall(f"{self._workers_key}:{worker_id}")
        if not data:
            return None

        return WorkerInfo(
            id=data["id"],
            status=data["status"],
            model_version=data["model_version"],
            started_at=float(data["started_at"]),
            last_heartbeat=float(data["last_heartbeat"]),
            requests_processed=int(data["requests_processed"]),
            is_warm=data["is_warm"] == "True",
        )

    async def get_all_workers(self) -> List[WorkerInfo]:
        keys = await self.redis.keys(f"{self._workers_key}:*")
        workers = []

        for key in keys:
            data = await self.redis.hgetall(key)
            if data:
                workers.append(WorkerInfo(
                    id=data["id"],
                    status=data["status"],
                    model_version=data["model_version"],
                    started_at=float(data["started_at"]),
                    last_heartbeat=float(data["last_heartbeat"]),
                    requests_processed=int(data["requests_processed"]),
                    is_warm=data["is_warm"] == "True",
                ))

        return workers

    async def get_active_workers(self) -> List[WorkerInfo]:
        all_workers = await self.get_all_workers()
        current_time = time.time()

        return [
            w for w in all_workers
            if current_time - w.last_heartbeat < self._heartbeat_timeout
               and w.status == "active"
        ]

    async def remove_worker(self, worker_id: str):
        await self.redis.delete(f"{self._workers_key}:{worker_id}")
        logger.info("worker_removed", worker_id=worker_id)

    async def cleanup_stale_workers(self):
        all_workers = await self.get_all_workers()
        current_time = time.time()
        removed = 0

        for worker in all_workers:
            if current_time - worker.last_heartbeat > self._heartbeat_timeout:
                await self.remove_worker(worker.id)
                removed += 1

        if removed > 0:
            logger.info("stale_workers_cleaned", count=removed)
