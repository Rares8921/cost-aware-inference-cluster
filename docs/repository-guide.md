# Repository Guide

This guide is for someone opening the project for the first time. It explains where the main ideas live and which files are worth reading first.

## Suggested Reading Order

1. `README.md` for the summary, supported claims, current evidence, and limitations.
2. `docs/architecture.md` for the service and data-flow diagrams.
3. `services/router/main.py`, `services/scheduler/main.py`, and `services/worker/main.py` for the three-service flow.
4. `services/scheduler/queue_manager.py` and `services/scheduler/worker_registry.py` for Redis-backed coordination.
5. `services/scheduler/autoscaler.py` and `services/scheduler/cost_optimizer.py` for autoscaling and cost decision logic.
6. `tests/` and `benchmarks/results/` to see what is actually verified.
7. `PROJECT_EVIDENCE.md` before turning the project into resume bullets.

## Core Services

### `services/router/`

- `main.py`: FastAPI router service. Handles `/infer`, checks tenant limits, forwards accepted work to the scheduler, and exposes router metrics.
- `tenant_manager.py`: Redis-backed tenant quota logic. Tracks per-second, per-minute, and per-hour usage and noisy-neighbor signals.
- `config.py`: Router settings such as Redis URL, scheduler URL, tenant quotas, and noisy-neighbor threshold.
- `Dockerfile`: Container build for the router service.

### `services/scheduler/`

- `main.py`: FastAPI scheduler service. Handles enqueue, worker heartbeat, worker dequeue, completion callbacks, health, JSON metrics, and Prometheus metrics.
- `queue_manager.py`: Redis queue implementation. Stores queued items, processing records, completion/failure counters, and latency samples.
- `worker_registry.py`: Worker metadata and heartbeat registry. Tracks active, inactive, and stale workers.
- `autoscaler.py`: Autoscaling decision loop. Evaluates queue pressure, latency thresholds, cooldowns, min/max workers, warm-pool rules, and cost-budget checks.
- `cost_optimizer.py`: Estimated cost accounting from active worker count and configured cost per GPU hour.
- `config.py`: Scheduler settings.
- `Dockerfile`: Container build for the scheduler service.

### `services/worker/`

- `main.py`: Worker service and background loops. Sends heartbeats, polls for queued work, batches requests, reports completions, and exposes worker metrics.
- `batch_processor.py`: `DynamicBatcher` and `BatchItem`. Implements max-size and timeout-triggered batching plus batch statistics.
- `model_loader.py`: Hugging Face/PyTorch model loading and batch prediction.
- `config.py`: Worker settings such as scheduler URL, model name, batch size, timeout, heartbeat interval, and warm-pool flag.
- `Dockerfile`: Container build for the worker service.

## Tests

- `tests/fakes.py`: In-memory Redis double used by deterministic tests.
- `tests/unit/test_priority_queue.py`: Priority ordering, same-priority timestamp tie-break behavior, metadata preservation, and queue metrics.
- `tests/unit/test_worker_registry.py`: Worker registration, heartbeat update, active-worker listing, and stale cleanup.
- `tests/integration/test_scheduler_queue.py`: Sequential enqueue/dequeue/complete flow with success and failure accounting.
- `tests/unit/test_batching.py`: Dynamic batching behavior and stats.
- `tests/unit/test_tenant_isolation.py`: Tenant quota and tenant metrics behavior.
- `tests/unit/test_autoscaler.py`: Autoscaler decisions for queue pressure, latency pressure, scale-down, and cost limit behavior.
- `tests/unit/test_cost_optimizer.py`: Cost tracking, budget checks, and metrics.
- `tests/benchmark/test_autoscaling_simulation.py`: Simulation schema, determinism, metadata, and scenario behavior.
- `tests/benchmark/test_local_stack_benchmark.py`: Local benchmark parsing, percentile calculation, report schema, Markdown output, and unavailable-service handling.
- `tests/load_test.py` and `tests/spike_test.py`: Live-service harnesses. They require a running service stack and are not deterministic unit evidence.

## Benchmarks And Reports

- `benchmarks/autoscaling_simulation.py`: Deterministic simulation of autoscaling decisions. Does not require Docker, Redis, Kubernetes, GPU, or live services.
- `benchmarks/local_stack_benchmark.py`: Local service smoke/load benchmark. Requires running router and scheduler services, and optionally reads worker metrics if the worker port is reachable from the host.
- `benchmarks/results/autoscaling_simulation_latest.*`: Checked-in latest simulation report.
- `benchmarks/results/local_stack_benchmark_latest.*`: Checked-in latest local stack benchmark report.
- `benchmarks/cost_comparison.py`, `benchmarks/latency_analysis.py`, `benchmarks/gpu_utilization.py`: Older live-service benchmark harnesses.
- `version_analysis/`: Historical generated outputs and plots. These are useful artifacts but do not include enough environment metadata to support standalone performance claims.

## Deployment And Infrastructure

- `docker-compose.yml`: Local multi-service stack with Redis, Prometheus, Grafana, router, scheduler, and worker.
- `kubernetes/`: Kubernetes namespace, Redis, router, scheduler, worker, HPA, and PodDisruptionBudget manifests.
- `monitoring/prometheus/prometheus.yml`: Prometheus scrape configuration.
- `monitoring/prometheus/alerts.yml`: Alert rules for emitted metrics.
- `monitoring/grafana/inference-dashboard.json`: Dashboard JSON.
- `scripts/system_start.py`: Helper script for starting Docker Compose or Kubernetes mode after prerequisite checks.
- `Makefile`: Convenience targets for setup, run, test, benchmark, lint, format, type-check, and Kubernetes deploy.

## Documentation Files

- `README.md`: Main reviewer entry point.
- `PROJECT_EVIDENCE.md`: Claim map from safe statements to code, tests, reports, and limitations.
- `docs/architecture.md`: Service diagrams and data-flow explanation.
- `docs/case-study.md`: Project narrative for interview discussion.
- `docs/repository-guide.md`: This file.

## What Not To Infer From The Files

- Kubernetes manifests do not prove live Kubernetes autoscaling.
- GPU-related configuration does not prove real GPU throughput or GPU utilization improvement.
- Cost estimates in code and simulation do not prove real cloud cost savings.
- Local benchmark latency values are router enqueue-response latency, not completed inference latency.
- Historical benchmark artifacts without environment metadata should not be used as standalone performance claims.
