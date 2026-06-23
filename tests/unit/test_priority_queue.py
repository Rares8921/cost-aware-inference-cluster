import pytest

from services.scheduler.queue_manager import QueueItem, QueueManager
from tests.fakes import InMemoryRedis


@pytest.fixture
def queue_manager():
    manager = QueueManager("redis://unit-test")
    manager.redis = InMemoryRedis()
    return manager


def make_item(
    item_id: str,
    priority: int,
    timestamp: float,
    tenant_id: str = "tenant-a",
    text: str = "hello",
) -> QueueItem:
    return QueueItem(
        id=item_id,
        tenant_id=tenant_id,
        payload={"text": text, "trace_id": f"trace-{item_id}"},
        priority=priority,
        timestamp=timestamp,
        timeout_ms=5000,
    )


@pytest.mark.anyio
async def test_higher_priority_requests_dequeue_first(queue_manager):
    await queue_manager.enqueue(make_item("low", priority=1, timestamp=1000.0))
    await queue_manager.enqueue(make_item("high", priority=10, timestamp=1001.0))
    await queue_manager.enqueue(make_item("medium", priority=5, timestamp=1002.0))

    items = await queue_manager.dequeue("worker-1", batch_size=3)

    assert [item.id for item in items] == ["high", "medium", "low"]


@pytest.mark.anyio
async def test_same_priority_uses_timestamp_tie_break(queue_manager):
    await queue_manager.enqueue(make_item("first", priority=3, timestamp=1000.0))
    await queue_manager.enqueue(make_item("second", priority=3, timestamp=1001.0))
    await queue_manager.enqueue(make_item("third", priority=3, timestamp=1002.0))

    items = await queue_manager.dequeue("worker-1", batch_size=3)

    assert [item.id for item in items] == ["first", "second", "third"]


@pytest.mark.anyio
async def test_tenant_and_payload_metadata_survive_enqueue_dequeue(queue_manager):
    await queue_manager.enqueue(
        make_item(
            "metadata",
            priority=7,
            timestamp=1000.0,
            tenant_id="tenant-gold",
            text="metadata check",
        )
    )

    [item] = await queue_manager.dequeue("worker-1", batch_size=1)

    assert item.id == "metadata"
    assert item.tenant_id == "tenant-gold"
    assert item.priority == 7
    assert item.payload == {"text": "metadata check", "trace_id": "trace-metadata"}
    assert item.timeout_ms == 5000


@pytest.mark.anyio
async def test_queue_metrics_track_pending_dequeued_and_completed(queue_manager):
    await queue_manager.enqueue(make_item("one", priority=1, timestamp=1000.0))
    await queue_manager.enqueue(make_item("two", priority=1, timestamp=1001.0))

    metrics = await queue_manager.get_metrics()
    assert metrics["queue_depth"] == 2
    assert metrics["processing_count"] == 0
    assert metrics["enqueued"] == 2

    [item] = await queue_manager.dequeue("worker-1", batch_size=1)
    metrics = await queue_manager.get_metrics()
    assert item.id == "one"
    assert metrics["queue_depth"] == 1
    assert metrics["processing_count"] == 1
    assert metrics["dequeued"] == 1

    await queue_manager.complete(item.id, success=True)
    metrics = await queue_manager.get_metrics()
    assert metrics["queue_depth"] == 1
    assert metrics["processing_count"] == 0
    assert metrics["completed"] == 1
    assert "latency_p95" in metrics
