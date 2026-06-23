# Project Evidence Ledger

This ledger maps safe project claims to repository evidence. It intentionally avoids production, real-GPU cost-savings, live Kubernetes autoscaling, and live performance claims that are not proven by this repository.

## Claim Audit

| Safe claim | Code evidence | Test evidence | Benchmark/report evidence | Limitations |
|---|---|---|---|---|
| Built a FastAPI router/scheduler/worker inference-serving prototype. | `services/router/main.py`, `services/scheduler/main.py`, `services/worker/main.py` | Service-level unit/integration coverage listed below | README architecture section | Prototype only; no production deployment evidence. |
| Coordinated services through Redis-backed queues and worker heartbeats. | `services/scheduler/queue_manager.py`, `services/scheduler/worker_registry.py`, `services/worker/main.py` | `tests/unit/test_priority_queue.py`, `tests/unit/test_worker_registry.py`, `tests/integration/test_scheduler_queue.py` | Not applicable | Unit and service-logic tests use an in-memory Redis double; live Redis flow still needs environment-backed test evidence. |
| Implemented tenant-aware rate limiting. | `services/router/tenant_manager.py`, `services/router/main.py` | `tests/unit/test_tenant_isolation.py` | Not applicable | Tenant tests use an in-memory Redis double. No multi-tenant load benchmark is included. |
| Implemented priority-aware queueing. | `QueueManager.enqueue` score calculation in `services/scheduler/queue_manager.py` | `tests/unit/test_priority_queue.py` | Not applicable | Same-priority ordering is timestamp-tie-break behavior, not a stronger exactly-once or distributed FIFO guarantee. |
| Implemented dynamic batching with batch statistics. | `services/worker/batch_processor.py`, `services/worker/main.py` | `tests/unit/test_batching.py` | Worker Prometheus metric `worker_batch_size` mirrors average batch size | Tests use mock processing, not real model/GPU inference. |
| Implemented worker-side request processing. | `services/worker/main.py`, `services/worker/model_loader.py` | Queue completion flow in `tests/integration/test_scheduler_queue.py`; batching unit tests | Not applicable | No end-to-end live router/scheduler/worker test with a loaded model is included. |
| Designed cost-aware autoscaling decision logic. | `services/scheduler/autoscaler.py`, `services/scheduler/cost_optimizer.py`, `services/scheduler/config.py` | `tests/unit/test_autoscaler.py`, `tests/unit/test_cost_optimizer.py`, `tests/benchmark/test_autoscaling_simulation.py` | `benchmarks/autoscaling_simulation.py`, `benchmarks/results/autoscaling_simulation_latest.json`, `benchmarks/results/autoscaling_simulation_latest.md` | Scale-up logs target worker count only; it does not create Kubernetes pods or Docker workers. Cost values are estimated/simulated. |
| Added deterministic autoscaling simulation evidence. | `benchmarks/autoscaling_simulation.py` | `tests/benchmark/test_autoscaling_simulation.py` | `benchmarks/results/autoscaling_simulation_latest.*` | Simulation only; no live traffic, GPU, or Kubernetes measurement. |
| Added a local stack smoke/load benchmark for router -> scheduler -> worker-path evidence. | `benchmarks/local_stack_benchmark.py`, `services/router/main.py`, `services/scheduler/main.py`, `services/worker/main.py` | `tests/benchmark/test_local_stack_benchmark.py` | `benchmarks/results/local_stack_benchmark_latest.json`, `benchmarks/results/local_stack_benchmark_latest.md` | Measures local router enqueue-response latency, not production performance or completed inference latency. Worker host metrics were unavailable because port 8002 is not published. |
| Added monitoring configuration for emitted metrics. | `services/router/main.py`, `services/scheduler/main.py`, `services/worker/main.py`, `monitoring/prometheus/prometheus.yml`, `monitoring/prometheus/alerts.yml`, `monitoring/grafana/inference-dashboard.json` | `py_compile` verifies changed modules | README monitoring notes | No Grafana screenshot or live Prometheus scrape validation. GPU utilization is not emitted. |
| Added Docker Compose and Kubernetes manifests. | `docker-compose.yml`, `kubernetes/*.yml`, service Dockerfiles | Not covered by automated tests in this sprint | README quickstart | Manifests are configuration evidence, not proof of production Kubernetes operation. |

## Test Evidence

Deterministic tests added in this evidence sprint:

- `tests/unit/test_priority_queue.py`: priority ordering, same-priority timestamp tie-break, metadata preservation, queue metrics.
- `tests/unit/test_worker_registry.py`: registration, heartbeat updates, active-worker filtering, stale cleanup.
- `tests/integration/test_scheduler_queue.py`: sequential enqueue/dequeue/complete flow with success and failure accounting.
- `tests/benchmark/test_autoscaling_simulation.py`: report schema, deterministic output, metadata, cooldown, max-worker, warm-pool, and cost-budget behavior.
- `tests/benchmark/test_local_stack_benchmark.py`: argument parsing, percentile calculation, report schema, Markdown generation, and unavailable-service handling.

Existing tests used as evidence:

- `tests/unit/test_batching.py`: dynamic batch size, timeout, and stats behavior.
- `tests/unit/test_cost_optimizer.py`: cost tracking, scale-up budget checks, cost-saved accounting, metrics.
- `tests/unit/test_autoscaler.py`: scale-up/down decisions and cost/latency triggers using the in-memory Redis double.
- `tests/unit/test_tenant_isolation.py`: rate-limit and tenant metric behavior using the in-memory Redis double.

## Simulation Evidence

Command used for the checked-in report:

```bash
python benchmarks/autoscaling_simulation.py --timestamp 2026-06-23T00:00:00Z
```

Checked-in outputs:

- `benchmarks/results/autoscaling_simulation_latest.json`
- `benchmarks/results/autoscaling_simulation_latest.md`

Aggregate simulated result:

| Metric | Value |
|---|---:|
| Scenarios | 9 |
| Steps | 27 |
| Scale-up decisions | 7 |
| Scale-down decisions | 3 |
| Cooldown blocks | 2 |
| Cost-budget blocks | 2 |
| Max-worker blocks | 2 |
| Warm-pool floor blocks | 8 |
| Simulated estimated GPU cost | $5.041666 |
| Simulated projected avoided cost | $0.208333 |

These values are deterministic, simulated, and projected. They are not real traffic, live GPU usage, or cloud billing evidence.

## Local Stack Benchmark Evidence

Command used for the checked-in local report:

```bash
python benchmarks/local_stack_benchmark.py --requests 30 --concurrency 3 --settle-seconds 2 --timestamp 2026-06-23T00:00:00Z
```

Checked-in outputs:

- `benchmarks/results/local_stack_benchmark_latest.json`
- `benchmarks/results/local_stack_benchmark_latest.md`

Aggregate local result:

| Metric | Value |
|---|---:|
| Benchmark status | completed |
| Requests attempted | 30 |
| Successful requests | 30 |
| Failed requests | 0 |
| Status counts | `{'200': 30}` |
| Throughput | 3.4303 requests/second |
| Router enqueue-response p50 | 663.7707 ms |
| Router enqueue-response p95 | 2389.2557 ms |
| Router enqueue-response p99 | 2390.5513 ms |
| Scheduler completed count after run | 30 |
| Scheduler failed count after run | 0 |
| Scheduler queue depth after run | 0 |
| Scheduler active workers after run | 2 |

This run confirms a local router -> scheduler -> worker processing path under a small controlled workload. It does not prove production performance, GPU throughput, SLA, or scalability. Worker host metrics were unavailable because Docker Compose did not publish worker port 8002 to the host; scheduler metrics still reported two active workers and 30 completed queue items.

## Monitoring Evidence

Emitted metrics now align with the Prometheus/Grafana expressions for router request rate, scheduler queue depth, scheduler latency percentiles, active workers, scheduler current-hour cost, and worker average batch size.

The unsupported `worker_gpu_utilization` alert was removed because no GPU utilization metric is emitted. This is a limitation, not a hidden feature.

## Unsupported Claims

Do not claim:

- Production usage.
- Real GPU cost savings.
- Real Kubernetes production autoscaling.
- Verified live QPS or p95/p99 latency.
- Production reliability, uptime, or SLA.
- GPU utilization improvement.
- Model quality or accuracy.
- Exactly-once queueing or production-grade fault tolerance.

## Safest Current CV Wording

Cost-Aware Autoscaling GPU Inference Cluster

- Built a FastAPI-based inference serving prototype with separate router, scheduler, and worker services coordinated through Redis-backed queues and worker heartbeats.
- Implemented Redis-backed tenant rate limiting, priority-aware queueing, dynamic batching, and worker-side request processing with batch statistics.
- Added deterministic tests for queue ordering, worker registry behavior, scheduler queue flow, batching, cost accounting, and autoscaling decision behavior.
- Created deterministic autoscaling simulation evidence covering queue pressure, latency thresholds, cooldowns, warm-pool floors, max-worker limits, and projected cost-budget blocks.
- Added a local stack smoke/load benchmark that reports request status counts, router enqueue-response latency percentiles, scheduler queue metrics, active workers, and explicit limitations.

## Stronger Wording Only After More Evidence

After adding live, reproducible benchmark runs with environment metadata and service health evidence, the project could claim measured latency/throughput under a specific local setup. After adding a real Kubernetes scaler integration and validation, it could claim Kubernetes autoscaling behavior. Neither is proven yet.