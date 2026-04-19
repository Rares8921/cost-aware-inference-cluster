import asyncio
import time
import uuid
from contextlib import asynccontextmanager

import httpx
import structlog
from fastapi import FastAPI
from pydantic import BaseModel

from .batch_processor import DynamicBatcher, BatchItem
from .config import WorkerConfig
from .model_loader import ModelLoader

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

logger = structlog.get_logger()

config = WorkerConfig()
if not config.worker_id:
    config.worker_id = f"worker-{uuid.uuid4().hex[:8]}"

model_loader = ModelLoader(config.model_name, config.model_version)
batcher: DynamicBatcher = None

requests_processed = 0


async def heartbeat_loop():
    async with httpx.AsyncClient() as client:
        while True:
            try:
                await client.post(
                    f"{config.scheduler_url}/worker/heartbeat",
                    json={
                        "worker_id": config.worker_id,
                        "status": "active",
                        "model_version": config.model_version,
                        "requests_processed": requests_processed,
                        "is_warm": config.worker_warm_pool,
                    },
                    timeout=5.0
                )
            except Exception as e:
                logger.error("heartbeat_failed", error=str(e))

            await asyncio.sleep(config.heartbeat_interval_seconds)


async def work_loop():
    global requests_processed

    async with httpx.AsyncClient() as client:
        while True:
            try:
                response = await client.get(
                    f"{config.scheduler_url}/worker/dequeue",
                    params={
                        "worker_id": config.worker_id,
                        "batch_size": config.batch_size_max,
                    },
                    timeout=5.0
                )

                if response.status_code == 200:
                    data = response.json()
                    items = data.get("items", [])

                    if items:
                        for item in items:
                            try:
                                batch_item = BatchItem(
                                    id=item["id"],
                                    tenant_id=item["tenant_id"],
                                    text=item["payload"]["text"],
                                    timestamp=item["timestamp"],
                                    future=asyncio.Future()
                                )

                                result = await batcher.add_item(batch_item)

                                await client.post(
                                    f"{config.scheduler_url}/worker/complete/{item['id']}",
                                    params={"success": True},
                                    timeout=5.0
                                )

                                requests_processed += 1

                            except Exception as e:
                                logger.error(
                                    "item_processing_failed",
                                    item_id=item["id"],
                                    error=str(e)
                                )
                                await client.post(
                                    f"{config.scheduler_url}/worker/complete/{item['id']}",
                                    params={"success": False},
                                    timeout=5.0
                                )

            except Exception as e:
                logger.error("work_loop_error", error=str(e))

            await asyncio.sleep(config.poll_interval_ms / 1000)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global batcher

    logger.info("worker_starting", worker_id=config.worker_id)

    model_loader.load()

    if config.worker_warm_pool:
        model_loader.warmup()

    batcher = DynamicBatcher(
        max_batch_size=config.batch_size_max,
        batch_timeout_ms=config.batch_timeout_ms,
        process_fn=model_loader.predict_batch
    )

    await batcher.start()

    asyncio.create_task(heartbeat_loop())
    asyncio.create_task(work_loop())

    logger.info("worker_started", worker_id=config.worker_id)

    yield

    await batcher.stop()
    logger.info("worker_stopped", worker_id=config.worker_id)


app = FastAPI(title="Inference Worker", lifespan=lifespan)


class InferenceRequest(BaseModel):
    text: str


@app.post("/infer")
async def infer(request: InferenceRequest):
    batch_item = BatchItem(
        id=str(uuid.uuid4()),
        tenant_id="direct",
        text=request.text,
        timestamp=time.time(),
        future=asyncio.Future()
    )

    result = await batcher.add_item(batch_item)
    return result


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "worker_id": config.worker_id,
        "model_loaded": model_loader.is_loaded(),
    }


@app.get("/metrics")
async def metrics():
    return {
        "worker_id": config.worker_id,
        "requests_processed": requests_processed,
        "batcher_stats": batcher.get_stats() if batcher else {},
        "model": {
            "name": config.model_name,
            "version": config.model_version,
            "device": model_loader.device,
        }
    }
