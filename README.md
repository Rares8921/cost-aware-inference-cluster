# Cost-Aware Autoscaling GPU Inference Cluster

A FastAPI-based inference serving prototype with separate router, scheduler, and worker services. The project demonstrates Redis-backed queueing, worker heartbeats, tenant-aware rate limiting, dynamic batching, cost-aware autoscaling decision logic, and monitoring/deployment configuration.

This is a tested prototype and simulation-backed case study. It is not evidence of production usage, real GPU cost savings, live Kubernetes autoscaling, or verified production QPS/latency.

## Architecture

```text
client
  -> router /infer
     -> TenantManager Redis counters
     -> scheduler /infer
        -> QueueManager Redis sorted set
        -> worker /worker/dequeue
           -> DynamicBatcher
           -> ModelLoader PyTorch/Hugging Face inference
        <- worker /worker/complete/{item_id}
```

Main components:

- `services/router/main.py`: accepts tenant-scoped inference requests and forwards accepted work to the scheduler.
- `services/router/tenant_manager.py`: checks per-second, per-minute, and per-hour Redis-backed tenant quotas.
- `services/scheduler/main.py`: exposes enqueue, heartbeat, dequeue, completion, JSON metrics, and Prometheus metrics endpoints.
- `services/scheduler/queue_manager.py`: stores queued requests in a Redis sorted set and tracks processing/completion metrics.
- `services/scheduler/worker_registry.py`: records worker metadata and heartbeats and cleans stale workers.
- `services/scheduler/autoscaler.py`: makes scale-up, scale-down, or no-change decisions from queue depth, latency, warm-pool, cooldown, worker-limit, and cost-budget inputs.
- `services/scheduler/cost_optimizer.py`: estimates current/projected hourly GPU cost from worker count and configured cost per GPU hour.
- `services/worker/main.py`: sends heartbeats, dequeues work, batches requests, processes them, and reports completion.
- `services/worker/batch_processor.py`: implements max-size and timeout-triggered dynamic batching.
- `services/worker/model_loader.py`: loads a Hugging Face sequence-classification model and runs PyTorch inference.

## What This Demonstrates

Supported by code and tests:

- Multi-service router/scheduler/worker prototype.
- Redis-backed queueing and worker heartbeat registry.
- Tenant-aware rate limiting.
- Priority-aware queue ordering.
- Worker-side dynamic batching and batch statistics.
- Cost-aware autoscaling decision logic.
- Deterministic autoscaling simulation with explicit limitations.
- Prometheus/Grafana-oriented monitoring configuration for emitted router, scheduler, and worker metrics.

## What This Does Not Prove

Do not use this repository to claim:

- Production deployment or production traffic.
- Real GPU cost savings.
- Real Kubernetes-driven custom autoscaling.
- Verified live-GPU QPS, p95, or p99 latency.
- SLA, uptime, or production reliability.
- GPU utilization improvements. No GPU utilization metric is emitted.
- Model quality, accuracy, F1, precision, or recall.

## Local Quickstart

Install dependencies:

```bash
pip install -r requirements-dev.txt
```

Start the local stack with Docker Compose:

```bash
docker-compose up --build
```

Send a sample request:

```bash
curl -X POST http://localhost:8000/infer \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: demo" \
  -d '{"text":"hello from the inference cluster","priority":1}'
```

Useful endpoints:

- Router health: `http://localhost:8000/health`
- Router JSON metrics: `http://localhost:8000/metrics`
- Router Prometheus metrics: `http://localhost:8000/metrics/prometheus`
- Scheduler health: `http://localhost:8001/health`
- Scheduler JSON metrics: `http://localhost:8001/metrics`
- Scheduler Prometheus metrics: `http://localhost:8001/metrics/prometheus`
- Worker JSON metrics: `http://localhost:8002/metrics`
- Worker Prometheus metrics: `http://localhost:8002/metrics/prometheus`

## Tests

Deterministic tests that do not require Docker, Redis, Kubernetes, or GPU:

```bash
python -m pytest -p no:cacheprovider \
  tests/unit/test_batching.py \
  tests/unit/test_cost_optimizer.py \
  tests/unit/test_autoscaler.py \
  tests/unit/test_tenant_isolation.py \
  tests/unit/test_priority_queue.py \
  tests/unit/test_worker_registry.py \
  tests/integration/test_scheduler_queue.py \
  tests/benchmark/test_autoscaling_simulation.py
```

The focused unit and service-logic tests use an in-memory Redis double. Live Docker Compose and live benchmark scripts still require the service stack.

## Autoscaling Simulation Benchmark

Run the deterministic autoscaling simulation:

```bash
python benchmarks/autoscaling_simulation.py
```

Generated reports:

- `benchmarks/results/autoscaling_simulation_latest.json`
- `benchmarks/results/autoscaling_simulation_latest.md`

The simulation feeds controlled queue-depth, p95/p99 latency, active-worker, warm-pool, cooldown, worker-limit, and cost-budget scenarios into the autoscaler decision logic. It does not run model inference, Docker, Kubernetes, or GPUs.

Current checked-in simulation summary:

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

Treat those values as simulated/projected decision evidence only.

## Other Benchmark Scripts

The repository also contains live-service harnesses:

- `benchmarks/cost_comparison.py`
- `benchmarks/latency_analysis.py`
- `benchmarks/gpu_utilization.py`
- `tests/load_test.py`
- `tests/spike_test.py`

Existing historical outputs under `version_analysis/` are useful artifacts, but they do not include enough environment metadata to support live performance or cost-savings claims.

## Monitoring Notes

Prometheus config is in `monitoring/prometheus/prometheus.yml`; alerts are in `monitoring/prometheus/alerts.yml`; Grafana dashboard JSON is in `monitoring/grafana/inference-dashboard.json`.

Current emitted Prometheus metrics include:

- `router_requests_total`
- `router_request_duration_seconds`
- `scheduler_requests_total`
- `scheduler_queue_depth`
- `scheduler_active_workers`
- `scheduler_cost_current_hour`
- `scheduler_latency_p50_ms`
- `scheduler_latency_p95_ms`
- `scheduler_latency_p99_ms`
- `worker_requests_processed`
- `worker_batch_size`
- `worker_batch_queue_size`

GPU utilization is not emitted and the alert for it was removed rather than faked.

## Evidence Ledger

See `PROJECT_EVIDENCE.md` for the CV-safe claim map: code files, tests, benchmark/report evidence, and limitations.