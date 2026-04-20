#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx


DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_METRICS_URL = "http://localhost:8001/metrics"
RESULTS_PATH = Path("benchmarks") / "cost_comparison_results.json"


def send_request(base_url: str, tenant_id: str, text: str, timeout: float) -> dict:
    start = time.time()
    try:
        response = httpx.post(
            f"{base_url}/infer",
            json={"text": text},
            headers={"X-Tenant-Id": tenant_id},
            timeout=timeout,
        )
        latency_ms = (time.time() - start) * 1000
        return {"success": response.status_code == 200, "latency_ms": latency_ms}
    except Exception as exc:
        return {"success": False, "latency_ms": (time.time() - start) * 1000, "error": str(exc)}


def fetch_metrics(metrics_url: str, timeout: float) -> dict | None:
    try:
        response = httpx.get(metrics_url, timeout=timeout)
        if response.status_code == 200:
            return response.json()
    except Exception:
        return None
    return None


def sample_metrics(metrics_url: str, interval: float, timeout: float, stop: threading.Event, samples: list[dict]) -> None:
    while not stop.is_set():
        metrics = fetch_metrics(metrics_url, timeout)
        if metrics:
            workers = metrics.get("workers", {})
            queue = metrics.get("queue", {})
            samples.append(
                {
                    "active_workers": workers.get("active", 0),
                    "queue_depth": queue.get("queue_depth", 0),
                    "processing_count": queue.get("processing_count", 0),
                }
            )
        stop.wait(interval)


def summarize_samples(samples: list[dict]) -> dict:
    if not samples:
        return {}
    active = [s["active_workers"] for s in samples]
    queue = [s["queue_depth"] for s in samples]
    processing = [s["processing_count"] for s in samples]
    return {
        "avg_active_workers": sum(active) / len(active),
        "avg_queue_depth": sum(queue) / len(queue),
        "avg_processing_count": sum(processing) / len(processing),
        "max_active_workers": max(active),
    }


def run_scenario(
    name: str,
    base_url: str,
    metrics_url: str | None,
    num_requests: int,
    concurrency: int,
    tenant_id: str,
    text: str,
    timeout: float,
    metrics_interval: float,
    metrics_timeout: float,
    cost_per_gpu_hour: float,
) -> dict:
    metrics_samples: list[dict] = []
    stop_event = threading.Event()
    thread = None

    if metrics_url:
        thread = threading.Thread(
            target=sample_metrics,
            args=(metrics_url, metrics_interval, metrics_timeout, stop_event, metrics_samples),
            daemon=True,
        )
        thread.start()

    start_time = time.time()
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
        futures = [
            executor.submit(send_request, base_url, tenant_id, text, timeout)
            for _ in range(num_requests)
        ]
        results = [f.result() for f in futures]
    duration = time.time() - start_time

    if thread:
        stop_event.set()
        thread.join(timeout=metrics_interval + 1)

    success = [r for r in results if r["success"]]
    failed = num_requests - len(success)
    throughput = num_requests / duration if duration > 0 else 0.0

    metrics_summary = summarize_samples(metrics_samples)
    avg_workers = metrics_summary.get("avg_active_workers")

    cost = None
    cost_per_request = None
    if avg_workers is not None:
        cost = (duration / 3600) * avg_workers * cost_per_gpu_hour
        if num_requests > 0:
            cost_per_request = cost / num_requests

    summary = {
        "scenario": name,
        "num_requests": num_requests,
        "concurrency": concurrency,
        "duration_s": duration,
        "successful": len(success),
        "failed": failed,
        "throughput": throughput,
        "avg_active_workers": avg_workers,
        "cost": cost,
        "cost_per_request": cost_per_request,
        "metrics": metrics_summary,
    }

    print(
        f"scenario={name} total={num_requests} "
        f"success={len(success)} fail={failed} "
        f"rps={throughput:.2f} "
        f"avg_workers={avg_workers if avg_workers is not None else 'n/a'} "
        f"cost_per_request={cost_per_request if cost_per_request is not None else 'n/a'}"
    )

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare sequential vs concurrent request execution")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--metrics-url", default=DEFAULT_METRICS_URL)
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--tenant", default="benchmark")
    parser.add_argument("--text", default="Benchmark request")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--metrics-interval", type=float, default=1.0)
    parser.add_argument("--metrics-timeout", type=float, default=5.0)
    parser.add_argument("--cost-per-gpu-hour", type=float, default=2.5)
    parser.add_argument("--no-metrics", action="store_true")
    args = parser.parse_args()

    metrics_url = None if args.no_metrics else args.metrics_url

    sequential = run_scenario(
        "no_batching",
        args.base_url,
        metrics_url,
        args.requests,
        1,
        args.tenant,
        args.text,
        args.timeout,
        args.metrics_interval,
        args.metrics_timeout,
        args.cost_per_gpu_hour,
    )

    concurrent = run_scenario(
        "with_batching",
        args.base_url,
        metrics_url,
        args.requests,
        args.concurrency,
        args.tenant,
        args.text,
        args.timeout,
        args.metrics_interval,
        args.metrics_timeout,
        args.cost_per_gpu_hour,
    )

    comparison = {}
    if sequential["cost"] and concurrent["cost"]:
        comparison["cost_reduction_percent"] = (
            1 - (concurrent["cost"] / sequential["cost"])
        ) * 100
        comparison["cost_savings"] = sequential["cost"] - concurrent["cost"]
    if sequential["throughput"] > 0:
        comparison["throughput_improvement_percent"] = (
            concurrent["throughput"] / sequential["throughput"] - 1
        ) * 100

    results = {
        "no_batching": sequential,
        "with_batching": concurrent,
        "comparison": comparison,
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS_PATH.open("w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2)
    print(f"results={RESULTS_PATH}")


if __name__ == "__main__":
    main()
