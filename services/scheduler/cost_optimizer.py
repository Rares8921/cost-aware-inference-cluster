import time
from typing import Dict
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class CostMetrics:
    active_workers: int
    cost_per_gpu_hour: float
    current_hour_cost: float
    projected_hour_cost: float
    cost_saved: float
    timestamp: float


class CostOptimizer:
    def __init__(
            self,
            cost_per_gpu_hour: float,
            max_cost_per_hour: float
    ):
        self.cost_per_gpu_hour = cost_per_gpu_hour
        self.max_cost_per_hour = max_cost_per_hour

        self.hour_start = time.time()
        self.hour_cost = 0.0
        self.total_cost_saved = 0.0

        self._worker_start_times: Dict[str, float] = {}

    def track_worker_started(self, worker_id: str):
        self._worker_start_times[worker_id] = time.time()
        logger.debug("cost_tracking_worker_started", worker_id=worker_id)

    def track_worker_stopped(self, worker_id: str):
        if worker_id in self._worker_start_times:
            start_time = self._worker_start_times[worker_id]
            duration_hours = (time.time() - start_time) / 3600
            cost = duration_hours * self.cost_per_gpu_hour

            self.hour_cost += cost
            del self._worker_start_times[worker_id]

            logger.info(
                "cost_tracking_worker_stopped",
                worker_id=worker_id,
                duration_hours=duration_hours,
                cost=cost
            )

    def can_scale_up(self, active_workers: int) -> bool:
        projected_cost = self._calculate_projected_cost(active_workers + 1)

        can_scale = projected_cost <= self.max_cost_per_hour

        if not can_scale:
            logger.warning(
                "cost_limit_preventing_scale_up",
                projected_cost=projected_cost,
                max_cost=self.max_cost_per_hour,
                active_workers=active_workers
            )

        return can_scale

    def _calculate_projected_cost(self, num_workers: int) -> float:
        current_time = time.time()
        time_in_hour = current_time - self.hour_start

        if time_in_hour >= 3600:
            self.hour_start = current_time
            self.hour_cost = 0.0
            time_in_hour = 0

        running_costs = 0.0
        for start_time in self._worker_start_times.values():
            duration_hours = (current_time - start_time) / 3600
            running_costs += duration_hours * self.cost_per_gpu_hour

        remaining_seconds = 3600 - time_in_hour
        projected_additional_cost = (
                num_workers * (remaining_seconds / 3600) * self.cost_per_gpu_hour
        )

        return self.hour_cost + running_costs + projected_additional_cost

    def record_cost_saved(self, amount: float):
        self.total_cost_saved += amount
        logger.info("cost_saved", amount=amount, total_saved=self.total_cost_saved)

    def get_metrics(self, active_workers: int) -> CostMetrics:
        current_time = time.time()
        time_in_hour = current_time - self.hour_start

        if time_in_hour >= 3600:
            self.hour_start = current_time
            self.hour_cost = 0.0
            time_in_hour = 0

        running_costs = 0.0
        for start_time in self._worker_start_times.values():
            duration_hours = (current_time - start_time) / 3600
            running_costs += duration_hours * self.cost_per_gpu_hour

        current_hour_cost = self.hour_cost + running_costs
        projected_hour_cost = self._calculate_projected_cost(active_workers)

        return CostMetrics(
            active_workers=active_workers,
            cost_per_gpu_hour=self.cost_per_gpu_hour,
            current_hour_cost=current_hour_cost,
            projected_hour_cost=projected_hour_cost,
            cost_saved=self.total_cost_saved,
            timestamp=current_time,
        )
