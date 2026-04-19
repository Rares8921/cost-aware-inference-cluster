import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Gauge, generate_latest
from pydantic import BaseModel

from .autoscaler import Autoscaler
from .config import SchedulerConfig
from .cost_optimizer import CostOptimizer
from .queue_manager import QueueManager, QueueItem
from .worker_registry import WorkerRegistry, WorkerInfo

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

logger = structlog.get_logger()

config = SchedulerConfig()
queue_manager = QueueManager(config.redis_url)
worker_registry = WorkerRegistry(config.redis_url)
cost_optimizer = CostOptimizer(
    config.cost_per_gpu_hour,
    config.max_cost_per_hour
)
autoscaler = Autoscaler(
    config,
    queue_manager,
    worker_registry,
    cost_optimizer
)

requests_total = Counter("scheduler_requests_total", "Total requests")
queue_depth_gauge = Gauge("scheduler_queue_depth", "Current queue depth")
active_workers_gauge = Gauge("scheduler_active_workers", "Number of active workers")
cost_gauge = Gauge("scheduler_cost_current_hour", "Cost in current hour")


class InferenceRequest(BaseModel):
    text: str
    tenant_id: str = "default"
    priority: int = 0
    timeout_ms: float = 5000


class InferenceResponse(BaseModel):
    request_id: str
    status: str
    message: str


class WorkerHeartbeat(BaseModel):
    worker_id: str
    status: str
    model_version: str
    requests_processed: int
    is_warm: bool


@asynccontextmanager
async def lifespan(app: FastAPI):
    await queue_manager.connect()
    await worker_registry.connect()

    if config.autoscale_enabled:
        await autoscaler.start()

    logger.info("scheduler_started", config=config.dict())

    yield

    if config.autoscale_enabled:
        await autoscaler.stop()

    await worker_registry.disconnect()
    await queue_manager.disconnect()
    logger.info("scheduler_stopped")


app = FastAPI(title="Inference Scheduler", lifespan=lifespan)


@app.post("/infer", response_model=InferenceResponse)
async def infer(request: InferenceRequest):
    request_id = str(uuid.uuid4())

    item = QueueItem(
        id=request_id,
        tenant_id=request.tenant_id,
        payload={"text": request.text},
        priority=request.priority,
        timestamp=time.time(),
        timeout_ms=request.timeout_ms,
    )

    success = await queue_manager.enqueue(item)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to enqueue request")

    requests_total.inc()

    return InferenceResponse(
        request_id=request_id,
        status="queued",
        message="Request queued for processing"
    )


@app.post("/worker/heartbeat")
async def worker_heartbeat(heartbeat: WorkerHeartbeat):
    existing_worker = await worker_registry.get_worker(heartbeat.worker_id)

    if not existing_worker:
        worker = WorkerInfo(
            id=heartbeat.worker_id,
            status=heartbeat.status,
            model_version=heartbeat.model_version,
            started_at=time.time(),
            last_heartbeat=time.time(),
            requests_processed=heartbeat.requests_processed,
            is_warm=heartbeat.is_warm,
        )
        await worker_registry.register_worker(worker)
        cost_optimizer.track_worker_started(heartbeat.worker_id)
    else:
        await worker_registry.update_heartbeat(heartbeat.worker_id)

    return {"status": "ok"}


@app.get("/worker/dequeue")
async def worker_dequeue(worker_id: str, batch_size: int = 1):
    items = await queue_manager.dequeue(worker_id, batch_size)

    return {
        "items": [
            {
                "id": item.id,
                "tenant_id": item.tenant_id,
                "payload": item.payload,
                "priority": item.priority,
                "timestamp": item.timestamp,
            }
            for item in items
        ]
    }


@app.post("/worker/complete/{item_id}")
async def worker_complete(item_id: str, success: bool = True):
    await queue_manager.complete(item_id, success)
    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/metrics")
async def metrics():
    queue_metrics = await queue_manager.get_metrics()
    active_workers = await worker_registry.get_active_workers()
    cost_metrics = cost_optimizer.get_metrics(len(active_workers))

    queue_depth_gauge.set(queue_metrics.get("queue_depth", 0))
    active_workers_gauge.set(len(active_workers))
    cost_gauge.set(cost_metrics.current_hour_cost)

    return {
        "queue": queue_metrics,
        "workers": {
            "active": len(active_workers),
            "total": len(await worker_registry.get_all_workers()),
        },
        "cost": {
            "current_hour": cost_metrics.current_hour_cost,
            "projected_hour": cost_metrics.projected_hour_cost,
            "total_saved": cost_metrics.cost_saved,
        }
    }


@app.get("/metrics/prometheus")
async def prometheus_metrics():
    return generate_latest()
