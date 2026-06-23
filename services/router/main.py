from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
import structlog
import httpx
from typing import Optional
from prometheus_client import Counter, Histogram, generate_latest

from .config import RouterConfig
from .tenant_manager import TenantManager

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

logger = structlog.get_logger()

config = RouterConfig()
tenant_manager = TenantManager(
    config.redis_url,
    config.default_tenant_quota_per_second,
    config.default_tenant_quota_per_minute,
    config.default_tenant_quota_per_hour,
)

requests_total = Counter(
    "router_requests_total",
    "Total requests",
    ["tenant_id", "status"]
)
request_duration = Histogram(
    "router_request_duration_seconds",
    "Request duration",
    ["tenant_id"]
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await tenant_manager.connect()
    logger.info("router_started", config=config.dict())

    yield

    await tenant_manager.disconnect()
    logger.info("router_stopped")


app = FastAPI(title="Inference Router", lifespan=lifespan)


class InferenceRequest(BaseModel):
    text: str
    priority: int = 0
    timeout_ms: float = 5000


class InferenceResponse(BaseModel):
    request_id: str
    status: str
    message: str


@app.post("/infer", response_model=InferenceResponse)
async def infer(
        request: InferenceRequest,
        x_tenant_id: Optional[str] = Header(default="default")
):
    tenant_id = x_tenant_id

    allowed, reason = await tenant_manager.check_rate_limit(tenant_id)

    if not allowed:
        requests_total.labels(tenant_id=tenant_id, status="rate_limited").inc()
        raise HTTPException(status_code=429, detail=reason)

    is_noisy = await tenant_manager.detect_noisy_neighbor(
        tenant_id,
        config.noisy_neighbor_threshold
    )

    if is_noisy:
        logger.warning("noisy_neighbor_request", tenant_id=tenant_id)

    await tenant_manager.record_request(tenant_id)

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{config.scheduler_url}/infer",
                json={
                    "text": request.text,
                    "tenant_id": tenant_id,
                    "priority": request.priority,
                    "timeout_ms": request.timeout_ms,
                },
                timeout=30.0
            )

            if response.status_code == 200:
                requests_total.labels(tenant_id=tenant_id, status="success").inc()
                return response.json()
            else:
                requests_total.labels(tenant_id=tenant_id, status="error").inc()
                raise HTTPException(
                    status_code=response.status_code,
                    detail="Scheduler error"
                )

        except httpx.RequestError as e:
            requests_total.labels(tenant_id=tenant_id, status="error").inc()
            logger.error("scheduler_request_failed", error=str(e))
            raise HTTPException(
                status_code=503,
                detail="Scheduler unavailable"
            )


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/tenant/metrics")
async def tenant_metrics(tenant_id: str = "default"):
    metrics = await tenant_manager.get_tenant_metrics(tenant_id)
    return metrics


@app.get("/metrics")
async def metrics():
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{config.scheduler_url}/metrics",
                timeout=5.0
            )
            scheduler_metrics = response.json() if response.status_code == 200 else {}
        except:
            scheduler_metrics = {}

    return {
        "router": {
            "status": "healthy",
        },
        "scheduler": scheduler_metrics,
    }


@app.get("/metrics/prometheus")
async def prometheus_metrics():
    return generate_latest()
