# Local Stack Benchmark Report

This is a local service smoke/load benchmark. It is not production performance evidence.

## Metadata

- Command: `python benchmarks/local_stack_benchmark.py --requests 30 --concurrency 3 --settle-seconds 2 --timestamp 2026-06-23T00:00:00Z`
- Timestamp: `2026-06-23T00:00:00Z`
- Git commit: `0393c8a`
- Python: `3.13.12`
- Platform: `Windows-11-10.0.26200-SP0`

## Service URLs

- `router`: `http://localhost:8000`
- `scheduler`: `http://localhost:8001`
- `worker`: `http://localhost:8002`

## Result Summary

- Benchmark status: `completed`
- Requests attempted: `30`
- Successful requests: `30`
- Failed requests: `0`
- Status counts: `{'200': 30}`
- Throughput: `3.4303` requests/second
- P50 latency: `663.7707` ms
- P95 latency: `2389.2557` ms
- P99 latency: `2390.5513` ms
- Latency scope: router /infer enqueue-response latency for successful HTTP 200 responses

## Health Checks

- `router`: ok=`True`, status=`200`, error=`None`
- `scheduler`: ok=`True`, status=`200`, error=`None`
- `worker`: ok=`False`, status=`None`, error=`[WinError 10061] No connection could be made because the target machine actively refused it`

## Scheduler Metrics

```json
{
  "after": {
    "error": null,
    "json": {
      "cost": {
        "current_hour": 0.08296491338147058,
        "projected_hour": 4.937156894471911,
        "total_saved": 0.0
      },
      "queue": {
        "completed": 30,
        "dequeued": 30,
        "enqueued": 30,
        "failed": 0,
        "latency_mean": 101.98165575663249,
        "latency_p50": 64.85390663146973,
        "latency_p95": 353.69372367858887,
        "latency_p99": 383.6956024169922,
        "processing_count": 0,
        "queue_depth": 0
      },
      "workers": {
        "active": 2,
        "total": 2
      }
    },
    "latency_ms": 467.4990999046713,
    "ok": true,
    "status_code": 200
  },
  "before": {
    "error": null,
    "json": {
      "cost": {
        "current_hour": 0.06031792528099483,
        "projected_hour": 4.937156894471911,
        "total_saved": 0.0
      },
      "queue": {
        "completed": 0,
        "dequeued": 0,
        "enqueued": 0,
        "failed": 0,
        "processing_count": 0,
        "queue_depth": 0
      },
      "workers": {
        "active": 2,
        "total": 2
      }
    },
    "latency_ms": 941.4074999513105,
    "ok": true,
    "status_code": 200
  }
}
```

## Worker Metrics

```json
{
  "after": {
    "error": "[WinError 10061] No connection could be made because the target machine actively refused it",
    "json": null,
    "latency_ms": 4566.759300068952,
    "ok": false,
    "status_code": null
  },
  "before": {
    "error": "[WinError 10061] No connection could be made because the target machine actively refused it",
    "json": null,
    "latency_ms": 4560.5492000468075,
    "ok": false,
    "status_code": null
  }
}
```

## Limitations

- This is a local service smoke/load benchmark, not a production benchmark.
- Request latency measures the router /infer HTTP response, which confirms scheduler enqueue, not completed model inference.
- Worker metrics are optional because the Compose worker service may not expose port 8002 to the host.
- No GPU performance is claimed unless the operator separately documents GPU availability and worker device metrics.
- No real cost savings, Kubernetes autoscaling behavior, SLA, or reliability claims are measured by this benchmark.

## Unsupported Claims

- production performance
- real GPU throughput or utilization improvement
- real cloud cost savings
- Kubernetes autoscaling validation
- SLA, uptime, or production reliability
