import pytest
from services.scheduler.cost_optimizer import CostOptimizer


def test_cost_tracking():
    optimizer = CostOptimizer(cost_per_gpu_hour=2.5, max_cost_per_hour=20.0)

    optimizer.track_worker_started("worker-1")
    optimizer.track_worker_started("worker-2")

    assert len(optimizer._worker_start_times) == 2

    optimizer.track_worker_stopped("worker-1")

    assert len(optimizer._worker_start_times) == 1
    assert optimizer.hour_cost > 0


def test_can_scale_up():
    optimizer = CostOptimizer(cost_per_gpu_hour=2.5, max_cost_per_hour=10.0)

    for i in range(3):
        optimizer.track_worker_started(f"worker-{i}")

    assert optimizer.can_scale_up(3)

    optimizer.track_worker_started("worker-4")

    assert not optimizer.can_scale_up(4)


def test_cost_saved_recording():
    optimizer = CostOptimizer(cost_per_gpu_hour=2.5, max_cost_per_hour=20.0)

    optimizer.record_cost_saved(1.5)
    optimizer.record_cost_saved(2.0)

    assert optimizer.total_cost_saved == 3.5


def test_get_metrics():
    optimizer = CostOptimizer(cost_per_gpu_hour=2.5, max_cost_per_hour=20.0)

    optimizer.track_worker_started("worker-1")
    optimizer.record_cost_saved(1.0)

    metrics = optimizer.get_metrics(1)

    assert metrics.active_workers == 1
    assert metrics.cost_per_gpu_hour == 2.5
    assert metrics.cost_saved == 1.0
    assert metrics.current_hour_cost >= 0
