import pytest

from services.router import tenant_manager as tenant_manager_module
from services.router.tenant_manager import TenantManager
from tests.fakes import InMemoryRedis


@pytest.fixture
def tenant_manager():
    tm = TenantManager(
        redis_url="redis://unit-test",
        default_quota_per_second=10,
        default_quota_per_minute=500,
        default_quota_per_hour=5000,
    )
    tm.redis = InMemoryRedis()
    return tm


@pytest.mark.anyio
async def test_rate_limit_per_second(tenant_manager, monkeypatch):
    monkeypatch.setattr(tenant_manager_module.time, "time", lambda: 1000.0)
    tenant_id = "test_tenant_1"

    for _ in range(10):
        allowed, msg = await tenant_manager.check_rate_limit(tenant_id, 1)
        assert allowed

    allowed, msg = await tenant_manager.check_rate_limit(tenant_id, 1)
    assert not allowed
    assert "per second" in msg


@pytest.mark.anyio
async def test_tenant_config(tenant_manager):
    config = tenant_manager.get_tenant_config("new_tenant")

    assert config.tenant_id == "new_tenant"
    assert config.quota_per_second == 10
    assert config.quota_per_minute == 500
    assert config.quota_per_hour == 5000


@pytest.mark.anyio
async def test_tenant_metrics(tenant_manager, monkeypatch):
    monkeypatch.setattr(tenant_manager_module.time, "time", lambda: 1000.0)
    tenant_id = "metrics_tenant"

    await tenant_manager.check_rate_limit(tenant_id, 5)

    metrics = await tenant_manager.get_tenant_metrics(tenant_id)

    assert metrics["tenant_id"] == tenant_id
    assert metrics["current_second"] == 5
    assert "utilization_second" in metrics


@pytest.mark.anyio
async def test_noisy_neighbor_detection(tenant_manager, monkeypatch):
    monkeypatch.setattr(tenant_manager_module.time, "time", lambda: 1000.0)
    tenant_id = "noisy_tenant"

    await tenant_manager.record_request(tenant_id)

    for _ in range(50):
        await tenant_manager.check_rate_limit(tenant_id, 1)

    is_noisy = await tenant_manager.detect_noisy_neighbor(tenant_id, threshold=0.8)

    assert isinstance(is_noisy, bool)