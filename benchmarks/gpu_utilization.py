#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx


DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_METRICS_URL = "http://localhost:8001/metrics"
RESULTS_PATH = Path("benchmarks") / "gpu_utilization_results.json"


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


def summarize_metrics(samples: list[dict]) -> dict:
    if not samples:
        return {}
    workers = [s["active_workers"] for s in samples]
    queues = [s["queue_depth"] for s in samples]
    processing = [s["processing_count"] for s in samples]

    avg_workers = sum(workers) / len(workers)
    avg_processing = sum(processing) / len(processing)
    utilization = (avg_processing / avg_workers) * 100 if avg_workers > 0 else 0.0

    return {
        "avg_workers": avg_workers,
        "max_workers": max(workers),
        "min_workers": min(workers),
        "avg_queue_depth": sum(queues) / len(queues),
        "max_queue_depth": max(queues),
        "avg_processing": avg_processing,
        "estimated_utilization": utilization,
    }


def run_scenario(
    name: str,
    base_url: str,
    metrics_url: str,
    duration_s: int,
    target_rps: int,
    tenant_id: str,
    text: str,
    timeout: float,
    metrics_timeout: float,
) -> dict:
    metrics_samples: list[dict] = []
    latencies: list[float] = []
    success = 0
    total = 0

    max_workers = max(1, min(target_rps, 200))
    start = time.monotonic()
    next_tick = start

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while time.monotonic() - start < duration_s:
            metrics = fetch_metrics(metrics_url, metrics_timeout)
            if metrics:
                queue = metrics.get("queue", {})
                workers = metrics.get("workers", {})
                metrics_samples.append(
                    {
                        "active_workers": workers.get("active", 0),
                        "queue_depth": queue.get("queue_depth", 0),
                        "processing_count": queue.get("processing_count", 0),
                    }
                )

            futures = [
                executor.submit(send_request, base_url, tenant_id, text, timeout)
                for _ in range(target_rps)
            ]
            for future in futures:
                result = future.result()
                total += 1
                if result["success"]:
                    success += 1
                    latencies.append(result["latency_ms"])

            next_tick += 1
            sleep_for = next_tick - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)

    stats = summarize_metrics(metrics_samples)
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

    summary = {
        "stats": stats,
        "success_rate": success / total if total else 0.0,
        "avg_latency_ms": avg_latency,
        "target_rps": target_rps,
        "duration_s": duration_s,
        "metrics_count": len(metrics_samples),
    }

    print(
        f"scenario={name} rps={target_rps} "
        f"success_rate={summary['success_rate']:.3f} "
        f"avg_workers={stats.get('avg_workers', 0):.2f} "
        f"utilization={stats.get('estimated_utilization', 0):.1f}"
    )

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Estimate utilization under target load")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--metrics-url", default=DEFAULT_METRICS_URL)
    parser.add_argument("--duration", type=int, default=30)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--metrics-timeout", type=float, default=5.0)
    parser.add_argument("--tenant", default="utilization")
    parser.add_argument("--text", default="Utilization benchmark request")
    args = parser.parse_args()

    scenarios = [
        ("low", 10),
        ("medium", 50),
        ("high", 100),
        ("burst", 200),
    ]

    results = {}
    for name, rps in scenarios:
        results[name] = run_scenario(
            name,
            args.base_url,
            args.metrics_url,
            args.duration,
            rps,
            args.tenant,
            args.text,
            args.timeout,
            args.metrics_timeout,
        )

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS_PATH.open("w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2)
    print(f"results={RESULTS_PATH}")


if __name__ == "__main__":
    main()
