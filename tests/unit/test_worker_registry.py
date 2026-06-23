import pytest

from services.scheduler import worker_registry as registry_module
from services.scheduler.worker_registry import WorkerInfo, WorkerRegistry
from tests.fakes import InMemoryRedis


@pytest.fixture
def registry():
    registry = WorkerRegistry("redis://unit-test")
    registry.redis = InMemoryRedis()
    return registry


def make_worker(
    worker_id: str,
    status: str = "active",
    last_heartbeat: float = 1000.0,
    requests_processed: int = 0,
    is_warm: bool = False,
) -> WorkerInfo:
    return WorkerInfo(
        id=worker_id,
        status=status,
        model_version="v1",
        started_at=900.0,
        last_heartbeat=last_heartbeat,
        requests_processed=requests_processed,
        is_warm=is_warm,
    )


@pytest.mark.anyio
async def test_register_worker_preserves_metadata(registry):
    await registry.register_worker(
        make_worker(
            "worker-a",
            requests_processed=17,
            is_warm=True,
        )
    )

    worker = await registry.get_worker("worker-a")

    assert worker.id == "worker-a"
    assert worker.status == "active"
    assert worker.model_version == "v1"
    assert worker.requests_processed == 17
    assert worker.is_warm is True


@pytest.mark.anyio
async def test_heartbeat_update_refreshes_last_seen(registry, monkeypatch):
    await registry.register_worker(make_worker("worker-a", last_heartbeat=1000.0))
    monkeypatch.setattr(registry_module.time, "time", lambda: 1042.0)

    await registry.update_heartbeat("worker-a")
    worker = await registry.get_worker("worker-a")

    assert worker.last_heartbeat == 1042.0


@pytest.mark.anyio
async def test_active_worker_listing_filters_stale_and_inactive(registry, monkeypatch):
    monkeypatch.setattr(registry_module.time, "time", lambda: 1030.0)
    await registry.register_worker(make_worker("active", last_heartbeat=1025.0))
    await registry.register_worker(make_worker("stale", last_heartbeat=900.0))
    await registry.register_worker(make_worker("inactive", status="draining", last_heartbeat=1028.0))

    workers = await registry.get_active_workers()

    assert [worker.id for worker in workers] == ["active"]


@pytest.mark.anyio
async def test_stale_worker_cleanup_removes_timed_out_workers(registry, monkeypatch):
    monkeypatch.setattr(registry_module.time, "time", lambda: 1030.0)
    await registry.register_worker(make_worker("active", last_heartbeat=1025.0))
    await registry.register_worker(make_worker("stale", last_heartbeat=900.0))

    await registry.cleanup_stale_workers()

    assert await registry.get_worker("active") is not None
    assert await registry.get_worker("stale") is None
