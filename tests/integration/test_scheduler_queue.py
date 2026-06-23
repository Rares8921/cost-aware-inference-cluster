import pytest

from services.scheduler.queue_manager import QueueItem, QueueManager
from tests.fakes import InMemoryRedis


@pytest.fixture
def queue_manager():
    manager = QueueManager("redis://integration-test")
    manager.redis = InMemoryRedis()
    return manager


def make_item(item_id: str, timestamp: float) -> QueueItem:
    return QueueItem(
        id=item_id,
        tenant_id=f"tenant-{item_id}",
        payload={"text": f"request {item_id}"},
        priority=1,
        timestamp=timestamp,
        timeout_ms=5000,
    )


@pytest.mark.anyio
async def test_sequential_scheduler_queue_flow_tracks_success_failure_and_no_loss(queue_manager):
    expected_ids = ["req-1", "req-2", "req-3"]
    for offset, item_id in enumerate(expected_ids):
        await queue_manager.enqueue(make_item(item_id, timestamp=1000.0 + offset))

    first_batch = await queue_manager.dequeue("worker-a", batch_size=2)
    assert [item.id for item in first_batch] == ["req-1", "req-2"]

    await queue_manager.complete("req-1", success=True)
    await queue_manager.complete("req-2", success=False)

    metrics = await queue_manager.get_metrics()
    assert metrics["queue_depth"] == 1
    assert metrics["processing_count"] == 0
    assert metrics["enqueued"] == 3
    assert metrics["dequeued"] == 2
    assert metrics["completed"] == 1
    assert metrics["failed"] == 1

    second_batch = await queue_manager.dequeue("worker-a", batch_size=2)
    assert [item.id for item in second_batch] == ["req-3"]

    await queue_manager.complete("req-3", success=True)
    final_metrics = await queue_manager.get_metrics()
    assert final_metrics["queue_depth"] == 0
    assert final_metrics["processing_count"] == 0
    assert final_metrics["completed"] == 2
    assert final_metrics["failed"] == 1
