#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.scheduler.autoscaler import Autoscaler, AutoscalingDecision
from services.scheduler.config import SchedulerConfig


DEFAULT_OUTPUT_DIR = Path("benchmarks") / "results"
DEFAULT_TIMESTAMP = "2026-01-01T00:00:00Z"

LIMITATIONS = [
    "This benchmark is a deterministic simulation of autoscaling decisions, not a live load test.",
    "No GPU, Kubernetes cluster, Docker Compose stack, or model inference service is required or measured.",
    "Estimated GPU cost is computed from configured worker count and cost-per-GPU-hour values.",
    "Projected avoided cost is simulated and must not be described as real cloud savings.",
    "The scheduler scale-up implementation currently records a target in logs; it does not create pods or workers.",
]

UNSUPPORTED_CLAIMS = [
    "production usage",
    "real GPU cost savings",
    "verified Kubernetes production autoscaling",
    "verified QPS, p95, or p99 performance on live GPUs",
    "production reliability or SLA guarantees",
]


@dataclass(frozen=True)
class SimulationStep:
    elapsed_s: int
    queue_depth: int
    p95_latency_ms: float
    p99_latency_ms: float
    duration_s: int = 60


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    initial_workers: int
    steps: tuple[SimulationStep, ...]
    max_cost_per_hour: float | None = None


class _NoopDependency:
    pass


class SimulatedCostOptimizer:
    def __init__(self, cost_per_gpu_hour: float, max_cost_per_hour: float):
        self.cost_per_gpu_hour = cost_per_gpu_hour
        self.max_cost_per_hour = max_cost_per_hour
        self.last_projected_hourly_cost: float | None = None
        self.last_scale_up_allowed: bool | None = None

    def reset_decision_state(self):
        self.last_projected_hourly_cost = None
        self.last_scale_up_allowed = None

    def can_scale_up(self, active_workers: int) -> bool:
        self.last_projected_hourly_cost = self.projected_hourly_cost(active_workers + 1)
        self.last_scale_up_allowed = self.last_projected_hourly_cost <= self.max_cost_per_hour
        return self.last_scale_up_allowed

    def estimated_hourly_cost(self, active_workers: int) -> float:
        return active_workers * self.cost_per_gpu_hour

    def projected_hourly_cost(self, active_workers: int) -> float:
        return active_workers * self.cost_per_gpu_hour


def build_config(max_cost_per_hour: float | None = None) -> SchedulerConfig:
    return SchedulerConfig(
        redis_url="redis://simulation",
        autoscale_enabled=True,
        autoscale_interval_seconds=10,
        min_workers=2,
        max_workers=10,
        warm_pool_size=2,
        target_queue_depth=50,
        target_p95_latency_ms=50.0,
        max_p99_latency_ms=100.0,
        cost_per_gpu_hour=2.5,
        max_cost_per_hour=max_cost_per_hour if max_cost_per_hour is not None else 20.0,
        scale_up_threshold=0.8,
        scale_down_threshold=0.3,
        scale_cooldown_seconds=60,
    )


def default_scenarios() -> list[Scenario]:
    return [
        Scenario(
            name="low_steady_traffic",
            description="Low queue depth remains within the warm-pool floor.",
            initial_workers=4,
            steps=(
                SimulationStep(0, 5, 20, 35),
                SimulationStep(70, 8, 25, 40),
                SimulationStep(140, 6, 22, 38),
            ),
        ),
        Scenario(
            name="burst_traffic",
            description="A burst raises queue pressure and then settles after cooldown.",
            initial_workers=4,
            steps=(
                SimulationStep(0, 10, 25, 40),
                SimulationStep(70, 150, 45, 80),
                SimulationStep(100, 160, 48, 85),
                SimulationStep(170, 30, 35, 70),
            ),
        ),
        Scenario(
            name="sustained_high_queue_depth",
            description="Persistent queue pressure repeatedly recommends scale-up until pressure is relieved.",
            initial_workers=2,
            steps=(
                SimulationStep(0, 140, 45, 85),
                SimulationStep(70, 145, 48, 90),
                SimulationStep(140, 130, 45, 85),
                SimulationStep(210, 20, 30, 60),
            ),
        ),
        Scenario(
            name="latency_threshold_pressure",
            description="Latency breaches trigger scale-up even with moderate queue depth.",
            initial_workers=3,
            steps=(
                SimulationStep(0, 20, 120, 160),
                SimulationStep(70, 25, 115, 150),
                SimulationStep(140, 15, 35, 80),
            ),
        ),
        Scenario(
            name="cooldown_prevents_thrashing",
            description="Cooldown suppresses immediate opposite or repeated actions after a scale event.",
            initial_workers=4,
            steps=(
                SimulationStep(0, 150, 45, 80),
                SimulationStep(30, 3, 20, 30),
                SimulationStep(70, 3, 20, 30),
            ),
        ),
        Scenario(
            name="warm_pool_floor",
            description="Low traffic does not scale below min_workers plus warm_pool_size.",
            initial_workers=4,
            steps=(
                SimulationStep(0, 2, 15, 25),
                SimulationStep(70, 1, 15, 25),
                SimulationStep(140, 2, 15, 25),
            ),
        ),
        Scenario(
            name="max_worker_limit",
            description="Queue pressure cannot increase workers beyond max_workers.",
            initial_workers=10,
            steps=(
                SimulationStep(0, 250, 80, 140),
                SimulationStep(70, 230, 75, 130),
            ),
        ),
        Scenario(
            name="cost_budget_limit",
            description="Projected hourly cost blocks scale-up under high queue pressure.",
            initial_workers=2,
            max_cost_per_hour=5.0,
            steps=(
                SimulationStep(0, 150, 45, 80),
                SimulationStep(70, 160, 45, 80),
            ),
        ),
        Scenario(
            name="scale_down_after_idle",
            description="Idle queue depth recommends scale-down until the warm-pool floor is reached.",
            initial_workers=6,
            steps=(
                SimulationStep(0, 2, 15, 25),
                SimulationStep(70, 2, 15, 25),
                SimulationStep(140, 2, 15, 25),
            ),
        ),
    ]


def config_to_dict(config: SchedulerConfig) -> dict[str, Any]:
    keys = [
        "min_workers",
        "max_workers",
        "warm_pool_size",
        "target_queue_depth",
        "target_p95_latency_ms",
        "max_p99_latency_ms",
        "cost_per_gpu_hour",
        "max_cost_per_hour",
        "scale_up_threshold",
        "scale_down_threshold",
        "scale_cooldown_seconds",
    ]
    return {key: getattr(config, key) for key in keys}


def _has_scale_pressure(step: SimulationStep, active_workers: int, config: SchedulerConfig) -> bool:
    queue_pressure = step.queue_depth / config.target_queue_depth
    latency_breach = (
        step.p95_latency_ms > config.target_p95_latency_ms
        or step.p99_latency_ms > config.max_p99_latency_ms
    )
    low_worker_pressure = active_workers < config.min_workers
    scale_down_pressure = queue_pressure < config.scale_down_threshold and active_workers > config.min_workers
    return low_worker_pressure or queue_pressure > config.scale_up_threshold or latency_breach or scale_down_pressure


async def simulate_scenario(scenario: Scenario) -> dict[str, Any]:
    config = build_config(scenario.max_cost_per_hour)
    cost_optimizer = SimulatedCostOptimizer(
        cost_per_gpu_hour=config.cost_per_gpu_hour,
        max_cost_per_hour=config.max_cost_per_hour,
    )
    autoscaler = Autoscaler(config, _NoopDependency(), _NoopDependency(), cost_optimizer)

    active_workers = scenario.initial_workers
    last_scale_time = -10_000.0
    details: list[dict[str, Any]] = []

    scale_up_decisions = 0
    scale_down_decisions = 0
    cooldown_blocks = 0
    cost_budget_blocks = 0
    max_worker_blocks = 0
    warm_pool_floor_blocks = 0
    estimated_gpu_cost_usd = 0.0
    projected_cost_avoided_usd = 0.0

    for idx, step in enumerate(scenario.steps):
        cost_optimizer.reset_decision_state()
        autoscaler.last_scale_time = last_scale_time
        in_cooldown = step.elapsed_s - last_scale_time < config.scale_cooldown_seconds
        pressure_present = _has_scale_pressure(step, active_workers, config)

        estimated_gpu_cost_usd += (
            active_workers * config.cost_per_gpu_hour * (step.duration_s / 3600)
        )

        with patch("services.scheduler.autoscaler.time.time", return_value=float(step.elapsed_s)):
            decision = await autoscaler._make_scaling_decision(
                active_workers,
                step.queue_depth,
                step.p95_latency_ms,
                step.p99_latency_ms,
            )

        active_before = active_workers
        blocked_by_cooldown = decision == AutoscalingDecision.NO_CHANGE and in_cooldown and pressure_present
        blocked_by_cost = (
            decision == AutoscalingDecision.NO_CHANGE
            and cost_optimizer.last_scale_up_allowed is False
        )
        blocked_by_max_workers = (
            decision == AutoscalingDecision.NO_CHANGE
            and active_workers >= config.max_workers
            and step.queue_depth > config.target_queue_depth * 2
        )
        blocked_by_warm_pool = (
            decision == AutoscalingDecision.NO_CHANGE
            and step.queue_depth / config.target_queue_depth < config.scale_down_threshold
            and active_workers <= config.min_workers + config.warm_pool_size
        )

        if decision == AutoscalingDecision.SCALE_UP:
            scale_up_decisions += 1
            active_workers = min(active_workers + 1, config.max_workers)
            last_scale_time = step.elapsed_s
        elif decision == AutoscalingDecision.SCALE_DOWN:
            scale_down_decisions += 1
            active_workers = max(active_workers - 1, 0)
            last_scale_time = step.elapsed_s
            projected_cost_avoided_usd += config.cost_per_gpu_hour * (step.duration_s / 3600)
        elif blocked_by_cost:
            cost_budget_blocks += 1
            projected_cost_avoided_usd += config.cost_per_gpu_hour * (step.duration_s / 3600)
        elif blocked_by_cooldown:
            cooldown_blocks += 1
        elif blocked_by_max_workers:
            max_worker_blocks += 1
        elif blocked_by_warm_pool:
            warm_pool_floor_blocks += 1

        details.append(
            {
                "step": idx,
                **asdict(step),
                "active_workers_before": active_before,
                "decision": decision,
                "active_workers_after": active_workers,
                "projected_hourly_cost_if_scaled_up": cost_optimizer.last_projected_hourly_cost,
                "blocked_by_cooldown": blocked_by_cooldown,
                "blocked_by_cost_budget": blocked_by_cost,
                "blocked_by_max_workers": blocked_by_max_workers,
                "blocked_by_warm_pool_floor": blocked_by_warm_pool,
            }
        )

    return {
        "name": scenario.name,
        "description": scenario.description,
        "steps_simulated": len(scenario.steps),
        "initial_workers": scenario.initial_workers,
        "queue_depth_over_time": [step.queue_depth for step in scenario.steps],
        "p95_latency_ms_over_time": [step.p95_latency_ms for step in scenario.steps],
        "p99_latency_ms_over_time": [step.p99_latency_ms for step in scenario.steps],
        "active_workers_over_time": [detail["active_workers_before"] for detail in details],
        "scale_up_decisions": scale_up_decisions,
        "scale_down_decisions": scale_down_decisions,
        "cooldown_blocks": cooldown_blocks,
        "cost_budget_blocks": cost_budget_blocks,
        "max_worker_blocks": max_worker_blocks,
        "warm_pool_floor_blocks": warm_pool_floor_blocks,
        "estimated_gpu_cost_usd": round(estimated_gpu_cost_usd, 6),
        "projected_cost_avoided_usd": round(projected_cost_avoided_usd, 6),
        "details": details,
        "limitations": LIMITATIONS,
    }


async def run_simulation() -> list[dict[str, Any]]:
    return [await simulate_scenario(scenario) for scenario in default_scenarios()]


def aggregate_summary(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "total_scenarios": len(scenarios),
        "total_steps": sum(scenario["steps_simulated"] for scenario in scenarios),
        "scale_up_decisions": sum(scenario["scale_up_decisions"] for scenario in scenarios),
        "scale_down_decisions": sum(scenario["scale_down_decisions"] for scenario in scenarios),
        "cooldown_blocks": sum(scenario["cooldown_blocks"] for scenario in scenarios),
        "cost_budget_blocks": sum(scenario["cost_budget_blocks"] for scenario in scenarios),
        "max_worker_blocks": sum(scenario["max_worker_blocks"] for scenario in scenarios),
        "warm_pool_floor_blocks": sum(scenario["warm_pool_floor_blocks"] for scenario in scenarios),
        "estimated_gpu_cost_usd": round(
            sum(scenario["estimated_gpu_cost_usd"] for scenario in scenarios),
            6,
        ),
        "projected_cost_avoided_usd": round(
            sum(scenario["projected_cost_avoided_usd"] for scenario in scenarios),
            6,
        ),
    }


def git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def build_report(
    timestamp: str = DEFAULT_TIMESTAMP,
    commit: str = "unknown",
    command: str = "python benchmarks/autoscaling_simulation.py",
) -> dict[str, Any]:
    scenarios = asyncio.run(run_simulation())
    base_config = build_config()
    return {
        "metadata": {
            "command_used": command,
            "timestamp": timestamp,
            "git_commit": commit,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "config": config_to_dict(base_config),
        "scenarios": scenarios,
        "aggregate_summary": aggregate_summary(scenarios),
        "limitations": LIMITATIONS,
        "unsupported_claims": UNSUPPORTED_CLAIMS,
    }


def markdown_report(report: dict[str, Any]) -> str:
    metadata = report["metadata"]
    aggregate = report["aggregate_summary"]
    lines = [
        "# Autoscaling Simulation Report",
        "",
        "This report is generated by a deterministic simulation. It is not a live GPU, Docker, or Kubernetes benchmark.",
        "",
        "## Metadata",
        "",
        f"- Command: `{metadata['command_used']}`",
        f"- Timestamp: `{metadata['timestamp']}`",
        f"- Git commit: `{metadata['git_commit']}`",
        f"- Python: `{metadata['python_version']}`",
        f"- Platform: `{metadata['platform']}`",
        "",
        "## Config",
        "",
    ]
    for key, value in report["config"].items():
        lines.append(f"- `{key}`: `{value}`")

    lines.extend(
        [
            "",
            "## Scenario Summary",
            "",
            "| Scenario | Steps | Scale up | Scale down | Cooldown blocks | Cost blocks | Max blocks | Warm-pool blocks | Estimated cost | Projected avoided cost |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for scenario in report["scenarios"]:
        lines.append(
            "| {name} | {steps_simulated} | {scale_up_decisions} | {scale_down_decisions} | "
            "{cooldown_blocks} | {cost_budget_blocks} | {max_worker_blocks} | "
            "{warm_pool_floor_blocks} | ${estimated_gpu_cost_usd:.6f} | "
            "${projected_cost_avoided_usd:.6f} |".format(**scenario)
        )

    lines.extend(
        [
            "",
            "## Aggregate Summary",
            "",
        ]
    )
    for key, value in aggregate.items():
        lines.append(f"- `{key}`: `{value}`")

    lines.extend(
        [
            "",
            "## Limitations",
            "",
        ]
    )
    for limitation in report["limitations"]:
        lines.append(f"- {limitation}")

    lines.extend(
        [
            "",
            "## Unsupported Claims",
            "",
        ]
    )
    for claim in report["unsupported_claims"]:
        lines.append(f"- {claim}")

    return "\n".join(lines) + "\n"


def write_reports(report: dict[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "autoscaling_simulation_latest.json"
    md_path = output_dir / "autoscaling_simulation_latest.md"

    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic autoscaling simulation")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--timestamp", default=datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    parser.add_argument("--command", default=" ".join(["python", *sys.argv]))
    args = parser.parse_args()

    report = build_report(
        timestamp=args.timestamp,
        commit=git_commit(),
        command=args.command,
    )
    json_path, md_path = write_reports(report, Path(args.output_dir))

    aggregate = report["aggregate_summary"]
    print(f"json_report={json_path}")
    print(f"markdown_report={md_path}")
    print(
        "aggregate "
        f"scenarios={aggregate['total_scenarios']} "
        f"steps={aggregate['total_steps']} "
        f"scale_up={aggregate['scale_up_decisions']} "
        f"scale_down={aggregate['scale_down_decisions']} "
        f"cooldown_blocks={aggregate['cooldown_blocks']} "
        f"cost_blocks={aggregate['cost_budget_blocks']} "
        f"estimated_cost_usd={aggregate['estimated_gpu_cost_usd']:.6f}"
    )


if __name__ == "__main__":
    main()
