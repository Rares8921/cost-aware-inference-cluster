import pytest
import asyncio
import time
from services.worker.batch_processor import DynamicBatcher, BatchItem


def mock_process_fn(texts):
    return [{"result": f"processed_{text}"} for text in texts]


@pytest.mark.asyncio
async def test_batch_fills_to_max_size():
    batcher = DynamicBatcher(
        max_batch_size=4,
        batch_timeout_ms=100,
        process_fn=mock_process_fn
    )

    await batcher.start()

    items = []
    for i in range(4):
        item = BatchItem(
            id=f"item-{i}",
            tenant_id="test",
            text=f"text-{i}",
            timestamp=time.time(),
            future=asyncio.Future()
        )
        items.append(item)
        asyncio.create_task(batcher.add_item(item))

    await asyncio.sleep(0.2)

    for item in items:
        assert item.future.done()
        result = await item.future
        assert result["batch_size"] == 4

    await batcher.stop()


@pytest.mark.asyncio
async def test_batch_timeout():
    batcher = DynamicBatcher(
        max_batch_size=10,
        batch_timeout_ms=50,
        process_fn=mock_process_fn
    )

    await batcher.start()

    item = BatchItem(
        id="item-1",
        tenant_id="test",
        text="text-1",
        timestamp=time.time(),
        future=asyncio.Future()
    )

    asyncio.create_task(batcher.add_item(item))

    await asyncio.sleep(0.1)

    assert item.future.done()
    result = await item.future
    assert result["batch_size"] == 1

    await batcher.stop()


@pytest.mark.asyncio
async def test_batch_stats():
    batcher = DynamicBatcher(
        max_batch_size=5,
        batch_timeout_ms=50,
        process_fn=mock_process_fn
    )

    await batcher.start()

    items = []
    for i in range(7):
        item = BatchItem(
            id=f"item-{i}",
            tenant_id="test",
            text=f"text-{i}",
            timestamp=time.time(),
            future=asyncio.Future()
        )
        items.append(item)
        asyncio.create_task(batcher.add_item(item))
        await asyncio.sleep(0.01)

    await asyncio.sleep(0.2)

    stats = batcher.get_stats()
    assert stats["items_processed"] == 7
    assert stats["batches_processed"] >= 2

    await batcher.stop()
