import asyncio
import time
from typing import Optional
import structlog
from .config import SchedulerConfig
from .queue_manager import QueueManager
from .worker_registry import WorkerRegistry, WorkerInfo
from .cost_optimizer import CostOptimizer

logger = structlog.get_logger()


class AutoscalingDecision:
    SCALE_UP = "scale_up"
    SCALE_DOWN = "scale_down"
    NO_CHANGE = "no_change"


class Autoscaler:
    def __init__(
            self,
            config: SchedulerConfig,
            queue_manager: QueueManager,
            worker_registry: WorkerRegistry,
            cost_optimizer: CostOptimizer,
    ):
        self.config = config
        self.queue_manager = queue_manager
        self.worker_registry = worker_registry
        self.cost_optimizer = cost_optimizer

        self.last_scale_time = 0.0
        self.running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        if self.running:
            return

        self.running = True
        self._task = asyncio.create_task(self._autoscale_loop())
        logger.info("autoscaler_started", interval=self.config.autoscale_interval_seconds)

    async def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("autoscaler_stopped")

    async def _autoscale_loop(self):
        while self.running:
            try:
                await self._run_autoscaling_cycle()
            except Exception as e:
                logger.error("autoscaling_error", error=str(e), exc_info=True)

            await asyncio.sleep(self.config.autoscale_interval_seconds)

    async def _run_autoscaling_cycle(self):
        await self.worker_registry.cleanup_stale_workers()

        active_workers = await self.worker_registry.get_active_workers()
        num_active = len(active_workers)

        metrics = await self.queue_manager.get_metrics()
        queue_depth = metrics.get("queue_depth", 0)
        p95_latency = metrics.get("latency_p95", 0)
        p99_latency = metrics.get("latency_p99", 0)

        decision = await self._make_scaling_decision(
            num_active,
            queue_depth,
            p95_latency,
            p99_latency
        )

        if decision == AutoscalingDecision.SCALE_UP:
            await self._scale_up(num_active)
        elif decision == AutoscalingDecision.SCALE_DOWN:
            await self._scale_down(active_workers)

        cost_metrics = self.cost_optimizer.get_metrics(num_active)

        logger.info(
            "autoscaling_cycle_complete",
            active_workers=num_active,
            queue_depth=queue_depth,
            p95_latency=p95_latency,
            p99_latency=p99_latency,
            decision=decision,
            current_hour_cost=cost_metrics.current_hour_cost,
            projected_hour_cost=cost_metrics.projected_hour_cost,
        )

    async def _make_scaling_decision(
            self,
            num_active: int,
            queue_depth: int,
            p95_latency: float,
            p99_latency: float,
    ) -> str:
        current_time = time.time()

        if current_time - self.last_scale_time < self.config.scale_cooldown_seconds:
            return AutoscalingDecision.NO_CHANGE

        if num_active < self.config.min_workers:
            return AutoscalingDecision.SCALE_UP

        if num_active >= self.config.max_workers:
            if queue_depth > self.config.target_queue_depth * 2:
                logger.warning(
                    "at_max_capacity",
                    num_active=num_active,
                    queue_depth=queue_depth
                )
            return AutoscalingDecision.NO_CHANGE

        queue_per_worker = queue_depth / max(num_active, 1)
        queue_pressure = queue_depth / self.config.target_queue_depth

        latency_breach = (
                p95_latency > self.config.target_p95_latency_ms or
                p99_latency > self.config.max_p99_latency_ms
        )

        if queue_pressure > self.config.scale_up_threshold or latency_breach:
            if self.cost_optimizer.can_scale_up(num_active):
                logger.info(
                    "scaling_up_triggered",
                    reason="queue_pressure" if queue_pressure > self.config.scale_up_threshold else "latency_breach",
                    queue_pressure=queue_pressure,
                    p95_latency=p95_latency,
                    p99_latency=p99_latency,
                )
                return AutoscalingDecision.SCALE_UP
            else:
                logger.warning("scale_up_prevented_by_cost_limit")
                return AutoscalingDecision.NO_CHANGE

        if queue_pressure < self.config.scale_down_threshold:
            if num_active > self.config.min_workers + self.config.warm_pool_size:
                logger.info(
                    "scaling_down_triggered",
                    queue_pressure=queue_pressure,
                    num_active=num_active,
                )
                return AutoscalingDecision.SCALE_DOWN

        return AutoscalingDecision.NO_CHANGE

    async def _scale_up(self, current_workers: int):
        new_workers = min(current_workers + 1, self.config.max_workers)

        logger.info(
            "executing_scale_up",
            current=current_workers,
            target=new_workers
        )

        self.last_scale_time = time.time()

    async def _scale_down(self, workers: list[WorkerInfo]):
        non_warm_workers = [w for w in workers if not w.is_warm]

        if not non_warm_workers:
            logger.info("no_workers_to_scale_down", reason="all_in_warm_pool")
            return

        worker_to_remove = min(non_warm_workers, key=lambda w: w.requests_processed)

        logger.info(
            "executing_scale_down",
            worker_id=worker_to_remove.id,
            requests_processed=worker_to_remove.requests_processed
        )

        await self.worker_registry.remove_worker(worker_to_remove.id)
        self.cost_optimizer.track_worker_stopped(worker_to_remove.id)

        cost_saved = self.config.cost_per_gpu_hour / 6
        self.cost_optimizer.record_cost_saved(cost_saved)

        self.last_scale_time = time.time()
