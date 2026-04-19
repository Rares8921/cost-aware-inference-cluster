import pytest
from services.scheduler.autoscaler import Autoscaler, AutoscalingDecision
from services.scheduler.queue_manager import QueueManager
from services.scheduler.worker_registry import WorkerRegistry, WorkerInfo
from services.scheduler.cost_optimizer import CostOptimizer
from services.scheduler.config import SchedulerConfig


@pytest.fixture
def config():
    return SchedulerConfig(
        redis_url="redis://localhost:6379",
        min_workers=2,
        max_workers=10,
        target_queue_depth=50,
        target_p95_latency_ms=50.0,
        cost_per_gpu_hour=2.5,
        max_cost_per_hour=20.0,
    )


@pytest.fixture
async def queue_manager(config):
    qm = QueueManager(config.redis_url)
    await qm.connect()
    yield qm
    await qm.disconnect()


@pytest.fixture
async def worker_registry(config):
    wr = WorkerRegistry(config.redis_url)
    await wr.connect()
    yield wr
    await wr.disconnect()


@pytest.fixture
def cost_optimizer(config):
    return CostOptimizer(config.cost_per_gpu_hour, config.max_cost_per_hour)


@pytest.fixture
def autoscaler(config, queue_manager, worker_registry, cost_optimizer):
    return Autoscaler(config, queue_manager, worker_registry, cost_optimizer)


@pytest.mark.anyio
async def test_scale_up_on_high_queue_depth(autoscaler, queue_manager, worker_registry):
    for i in range(2):
        worker = WorkerInfo(
            id=f"worker-{i}",
            status="active",
            model_version="v1",
            started_at=0,
            last_heartbeat=0,
            requests_processed=0,
            is_warm=False,
        )
        await worker_registry.register_worker(worker)

    for i in range(150):
        from services.scheduler.queue_manager import QueueItem
        item = QueueItem(
            id=f"item-{i}",
            tenant_id="test",
            payload={"text": "test"},
            priority=0,
            timestamp=0,
            timeout_ms=5000,
        )
        await queue_manager.enqueue(item)

    decision = await autoscaler._make_scaling_decision(2, 150, 30, 50)
    assert decision == AutoscalingDecision.SCALE_UP


@pytest.mark.anyio
async def test_scale_down_on_low_queue_depth(autoscaler, queue_manager, worker_registry):
    for i in range(5):
        worker = WorkerInfo(
            id=f"worker-{i}",
            status="active",
            model_version="v1",
            started_at=0,
            last_heartbeat=0,
            requests_processed=i * 10,
            is_warm=(i < 2),
        )
        await worker_registry.register_worker(worker)

    decision = await autoscaler._make_scaling_decision(5, 5, 10, 20)
    assert decision == AutoscalingDecision.SCALE_DOWN


@pytest.mark.anyio
async def test_no_scale_on_cost_limit(autoscaler, cost_optimizer):
    for i in range(8):
        cost_optimizer.track_worker_started(f"worker-{i}")

    can_scale = cost_optimizer.can_scale_up(8)
    assert not can_scale


@pytest.mark.anyio
async def test_scale_up_on_latency_breach(autoscaler):
    decision = await autoscaler._make_scaling_decision(3, 30, 120, 150)
    assert decision == AutoscalingDecision.SCALE_UP
