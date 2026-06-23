#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx


DEFAULT_OUTPUT_DIR = Path("benchmarks") / "results"
DEFAULT_ROUTER_URL = "http://localhost:8000"
DEFAULT_SCHEDULER_URL = "http://localhost:8001"
DEFAULT_WORKER_URL = "http://localhost:8002"

LIMITATIONS = [
    "This is a local service smoke/load benchmark, not a production benchmark.",
    "Request latency measures the router /infer HTTP response, which confirms scheduler enqueue, not completed model inference.",
    "Worker metrics are optional because the Compose worker service may not expose port 8002 to the host.",
    "No GPU performance is claimed unless the operator separately documents GPU availability and worker device metrics.",
    "No real cost savings, Kubernetes autoscaling behavior, SLA, or reliability claims are measured by this benchmark.",
]

UNSUPPORTED_CLAIMS = [
    "production performance",
    "real GPU throughput or utilization improvement",
    "real cloud cost savings",
    "Kubernetes autoscaling validation",
    "SLA, uptime, or production reliability",
]


@dataclass(frozen=True)
class BenchmarkConfig:
    router_url: str = DEFAULT_ROUTER_URL
    scheduler_url: str = DEFAULT_SCHEDULER_URL
    worker_url: str = DEFAULT_WORKER_URL
    request_count: int = 20
    concurrency: int = 2
    tenant_id: str = "local-benchmark"
    text: str = "Local stack benchmark request"
    timeout_s: float = 10.0
    settle_seconds: float = 1.0
    output_dir: Path = DEFAULT_OUTPUT_DIR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local router-scheduler-worker smoke/load benchmark")
    parser.add_argument("--router-url", default=DEFAULT_ROUTER_URL)
    parser.add_argument("--scheduler-url", default=DEFAULT_SCHEDULER_URL)
    parser.add_argument("--worker-url", default=DEFAULT_WORKER_URL)
    parser.add_argument("--requests", type=int, default=20, dest="request_count")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--tenant", default="local-benchmark", dest="tenant_id")
    parser.add_argument("--text", default="Local stack benchmark request")
    parser.add_argument("--timeout", type=float, default=10.0, dest="timeout_s")
    parser.add_argument("--settle-seconds", type=float, default=1.0)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--timestamp", default=datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    parser.add_argument("--command", default=" ".join(["python", *sys.argv]))
    return parser


def parse_config(argv: list[str] | None = None) -> tuple[BenchmarkConfig, str, str]:
    args = build_parser().parse_args(argv)
    config = BenchmarkConfig(
        router_url=args.router_url.rstrip("/"),
        scheduler_url=args.scheduler_url.rstrip("/"),
        worker_url=args.worker_url.rstrip("/"),
        request_count=args.request_count,
        concurrency=args.concurrency,
        tenant_id=args.tenant_id,
        text=args.text,
        timeout_s=args.timeout_s,
        settle_seconds=args.settle_seconds,
        output_dir=Path(args.output_dir),
    )
    return config, args.timestamp, args.command


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(len(ordered) * pct)
    index = min(index, len(ordered) - 1)
    return ordered[index]


def summarize_latencies(latencies_ms: list[float]) -> dict[str, float]:
    if not latencies_ms:
        return {"mean_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0}
    return {
        "mean_ms": statistics.mean(latencies_ms),
        "p50_ms": percentile(latencies_ms, 0.50),
        "p95_ms": percentile(latencies_ms, 0.95),
        "p99_ms": percentile(latencies_ms, 0.99),
    }


def fetch_json(url: str, timeout_s: float) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = httpx.get(url, timeout=timeout_s)
        latency_ms = (time.perf_counter() - started) * 1000
        try:
            payload = response.json()
        except Exception:
            payload = None
        return {
            "ok": response.status_code == 200,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "json": payload,
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "status_code": None,
            "latency_ms": (time.perf_counter() - started) * 1000,
            "json": None,
            "error": str(exc),
        }


def send_infer_request(router_url: str, tenant_id: str, text: str, timeout_s: float) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = httpx.post(
            f"{router_url}/infer",
            json={"text": text},
            headers={"X-Tenant-Id": tenant_id},
            timeout=timeout_s,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        return {
            "success": response.status_code == 200,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "error": None,
        }
    except Exception as exc:
        return {
            "success": False,
            "status_code": None,
            "latency_ms": (time.perf_counter() - started) * 1000,
            "error": str(exc),
        }


def run_requests(config: BenchmarkConfig) -> tuple[list[dict[str, Any]], float]:
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, config.concurrency)) as executor:
        futures = [
            executor.submit(
                send_infer_request,
                config.router_url,
                config.tenant_id,
                config.text,
                config.timeout_s,
            )
            for _ in range(config.request_count)
        ]
        results = [future.result() for future in futures]
    return results, time.perf_counter() - started


def health_blockers(health: dict[str, dict[str, Any]]) -> list[str]:
    blockers = []
    for service in ("router", "scheduler"):
        if not health[service]["ok"]:
            error = health[service].get("error") or f"status={health[service].get('status_code')}"
            blockers.append(f"{service} health check failed: {error}")
    return blockers


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
    config: BenchmarkConfig,
    timestamp: str,
    command: str,
    commit: str,
    health: dict[str, dict[str, Any]],
    scheduler_metrics_before: dict[str, Any],
    scheduler_metrics_after: dict[str, Any],
    worker_metrics_before: dict[str, Any],
    worker_metrics_after: dict[str, Any],
    request_results: list[dict[str, Any]],
    duration_s: float,
) -> dict[str, Any]:
    blockers = health_blockers(health)
    successes = [result for result in request_results if result["success"]]
    success_latencies = [result["latency_ms"] for result in successes]
    status_counts = Counter(
        str(result["status_code"]) if result["status_code"] is not None else "exception"
        for result in request_results
    )
    status = "completed" if not blockers else "blocked"
    if status == "completed" and len(successes) != len(request_results):
        status = "completed_with_request_failures"

    return {
        "metadata": {
            "command_used": command,
            "timestamp": timestamp,
            "git_commit": commit,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "benchmark_status": status,
        "blockers": blockers,
        "service_urls": {
            "router": config.router_url,
            "scheduler": config.scheduler_url,
            "worker": config.worker_url,
        },
        "config": {
            "request_count": config.request_count,
            "concurrency": config.concurrency,
            "tenant_id": config.tenant_id,
            "timeout_s": config.timeout_s,
            "settle_seconds": config.settle_seconds,
        },
        "health": health,
        "requests": {
            "attempted": len(request_results),
            "successful": len(successes),
            "failed": len(request_results) - len(successes),
            "status_counts": dict(sorted(status_counts.items())),
            "duration_s": duration_s,
            "throughput_requests_per_second": (len(request_results) / duration_s) if duration_s > 0 else 0.0,
            "latency": summarize_latencies(success_latencies),
            "latency_scope": "router /infer enqueue-response latency for successful HTTP 200 responses",
        },
        "scheduler_metrics": {
            "before": scheduler_metrics_before,
            "after": scheduler_metrics_after,
        },
        "worker_metrics": {
            "before": worker_metrics_before,
            "after": worker_metrics_after,
        },
        "limitations": LIMITATIONS,
        "unsupported_claims": UNSUPPORTED_CLAIMS,
    }


def run_benchmark(
    config: BenchmarkConfig,
    fetcher: Callable[[str, float], dict[str, Any]] = fetch_json,
) -> dict[str, Any]:
    health = {
        "router": fetcher(f"{config.router_url}/health", config.timeout_s),
        "scheduler": fetcher(f"{config.scheduler_url}/health", config.timeout_s),
        "worker": fetcher(f"{config.worker_url}/health", config.timeout_s),
    }
    scheduler_before = fetcher(f"{config.scheduler_url}/metrics", config.timeout_s)
    worker_before = fetcher(f"{config.worker_url}/metrics", config.timeout_s)

    request_results: list[dict[str, Any]] = []
    duration_s = 0.0
    if not health_blockers(health):
        request_results, duration_s = run_requests(config)
        if config.settle_seconds > 0:
            time.sleep(config.settle_seconds)

    scheduler_after = fetcher(f"{config.scheduler_url}/metrics", config.timeout_s)
    worker_after = fetcher(f"{config.worker_url}/metrics", config.timeout_s)

    return build_report(
        config=config,
        timestamp="",
        command="",
        commit="",
        health=health,
        scheduler_metrics_before=scheduler_before,
        scheduler_metrics_after=scheduler_after,
        worker_metrics_before=worker_before,
        worker_metrics_after=worker_after,
        request_results=request_results,
        duration_s=duration_s,
    )


def markdown_report(report: dict[str, Any]) -> str:
    metadata = report["metadata"]
    requests = report["requests"]
    latency = requests["latency"]
    lines = [
        "# Local Stack Benchmark Report",
        "",
        "This is a local service smoke/load benchmark. It is not production performance evidence.",
        "",
        "## Metadata",
        "",
        f"- Command: `{metadata['command_used']}`",
        f"- Timestamp: `{metadata['timestamp']}`",
        f"- Git commit: `{metadata['git_commit']}`",
        f"- Python: `{metadata['python_version']}`",
        f"- Platform: `{metadata['platform']}`",
        "",
        "## Service URLs",
        "",
    ]
    for name, url in report["service_urls"].items():
        lines.append(f"- `{name}`: `{url}`")

    lines.extend(
        [
            "",
            "## Result Summary",
            "",
            f"- Benchmark status: `{report['benchmark_status']}`",
            f"- Requests attempted: `{requests['attempted']}`",
            f"- Successful requests: `{requests['successful']}`",
            f"- Failed requests: `{requests['failed']}`",
            f"- Status counts: `{requests['status_counts']}`",
            f"- Throughput: `{requests['throughput_requests_per_second']:.4f}` requests/second",
            f"- P50 latency: `{latency['p50_ms']:.4f}` ms",
            f"- P95 latency: `{latency['p95_ms']:.4f}` ms",
            f"- P99 latency: `{latency['p99_ms']:.4f}` ms",
            f"- Latency scope: {requests['latency_scope']}",
            "",
            "## Health Checks",
            "",
        ]
    )
    for service, status in report["health"].items():
        lines.append(
            f"- `{service}`: ok=`{status['ok']}`, status=`{status['status_code']}`, error=`{status['error']}`"
        )

    if report["blockers"]:
        lines.extend(["", "## Blockers", ""])
        for blocker in report["blockers"]:
            lines.append(f"- {blocker}")

    lines.extend(["", "## Scheduler Metrics", "", "```json"])
    lines.append(json.dumps(report["scheduler_metrics"], indent=2, sort_keys=True))
    lines.extend(["```", "", "## Worker Metrics", "", "```json"])
    lines.append(json.dumps(report["worker_metrics"], indent=2, sort_keys=True))
    lines.extend(["```", "", "## Limitations", ""])
    for limitation in report["limitations"]:
        lines.append(f"- {limitation}")
    lines.extend(["", "## Unsupported Claims", ""])
    for claim in report["unsupported_claims"]:
        lines.append(f"- {claim}")
    return "\n".join(lines) + "\n"


def write_reports(report: dict[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "local_stack_benchmark_latest.json"
    md_path = output_dir / "local_stack_benchmark_latest.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    config, timestamp, command = parse_config()
    report = run_benchmark(config)
    report["metadata"].update(
        {
            "command_used": command,
            "timestamp": timestamp,
            "git_commit": git_commit(),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        }
    )
    json_path, md_path = write_reports(report, config.output_dir)
    print(f"json_report={json_path}")
    print(f"markdown_report={md_path}")
    print(
        "local_stack_benchmark "
        f"status={report['benchmark_status']} "
        f"attempted={report['requests']['attempted']} "
        f"success={report['requests']['successful']} "
        f"failed={report['requests']['failed']}"
    )
    if report["blockers"]:
        for blocker in report["blockers"]:
            print(f"blocker={blocker}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())