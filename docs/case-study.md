# Case Study

## Problem

Shared inference services need to decide which requests to admit, how to queue them, how workers should pull work, and when extra worker capacity would be worth its cost. This project explores those concerns in a small router -> scheduler -> worker prototype.

The goal was not to build a production platform. The goal was to make the main moving parts visible and testable: tenant limits, priority queueing, worker heartbeats, batching, metrics, and cost-aware autoscaling decisions.

## Design

The project separates the system into three services:

- Router: handles the public request entry point and tenant rate limiting.
- Scheduler: owns queue state, worker state, completion accounting, metrics, and autoscaling decisions.
- Worker: polls for work, batches requests, runs model inference, and reports completion.

Redis is used as the coordination layer. It stores tenant counters, the scheduler queue, in-flight processing records, worker heartbeats, and queue metrics.

The autoscaling policy is intentionally separated into scheduler-side decision logic. It considers queue pressure, p95/p99 latency inputs, minimum workers, warm-pool size, cooldowns, max workers, and projected hourly cost. In the current code, scale-up records a target in logs; it does not provision infrastructure.

## Implementation Notes

The router returns a queued response after the scheduler accepts the request. This keeps admission and processing separate, but it also means router latency is not completed-inference latency.

Workers send heartbeats independently of request processing. The scheduler uses these heartbeats to track active workers and remove stale ones.

Dynamic batching is implemented in the worker through `DynamicBatcher`. It flushes when the batch reaches a maximum size or when the timeout is reached.

Monitoring support is present through JSON metrics endpoints, Prometheus metrics endpoints, Prometheus config, alert rules, and a Grafana dashboard JSON file.

## Evidence

The repository includes three layers of evidence:

1. Deterministic tests for queue behavior, worker registry behavior, scheduler queue flow, batching, tenant limits, cost optimizer behavior, autoscaler behavior, and benchmark report generation.
2. A deterministic autoscaling simulation with checked-in JSON and Markdown reports.
3. A local Docker Compose smoke/load benchmark with checked-in JSON and Markdown reports.

The local stack benchmark result currently shows 30 attempted requests, 30 successful responses, 0 failed responses, scheduler completed count 30, scheduler failed count 0, queue depth 0 after the run, and 2 active workers after the run. The measured latency is router enqueue-response latency.

## Limitations

The evidence is intentionally bounded:

- The autoscaling benchmark is simulation evidence, not live traffic evidence.
- The local benchmark is a local smoke/load run, not production performance evidence.
- Router latency is enqueue-response latency, not completed model inference latency.
- Worker host metrics were unavailable in the checked-in local benchmark because worker port 8002 was not published to the host.
- Kubernetes manifests exist, but live Kubernetes autoscaling was not validated.
- GPU configuration exists, but no real GPU throughput, GPU utilization improvement, or GPU cost savings are proven.
- The project does not prove SLA, uptime, model accuracy, or exactly-once processing.

## What I Learned

This project is a useful example of turning a system-design idea into a reviewable prototype. The most important lesson is that implementation claims and evidence claims are different. It is fair to say the code implements queueing, batching, and autoscaling decision logic. It is not fair to claim production performance or cost savings without the right benchmark environment and measurements.

The evidence sprint also made the project easier to review: tests now cover the core deterministic behaviors, benchmark reports record metadata and limitations, and the documentation separates current functionality from future work.

## Future Work

These are possible next steps, not current claims:

- Add a completed-inference response path or callback flow if end-to-end inference latency becomes a project goal.
- Add a Redis-backed integration test that runs against a real local Redis container and is clearly marked as requiring Redis.
- Publish worker metrics to the host or scrape them through Prometheus in the local stack.
- Validate Kubernetes behavior in a real cluster before making Kubernetes autoscaling claims.
- Run a documented GPU benchmark only with recorded hardware, device metrics, model configuration, command history, and limitations.
- Add a short monitoring walkthrough with Prometheus scrape evidence and Grafana screenshots if observability becomes part of the evidence target.
