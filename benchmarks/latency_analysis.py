#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx


DEFAULT_BASE_URL = "http://localhost:8000"
RESULTS_PATH = Path("benchmarks") / "latency_analysis_results.json"


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


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    idx = int(len(values) * pct)
    idx = min(idx, len(values) - 1)
    return values[idx]


def run_batch_analysis(
    base_url: str,
    batch_sizes: list[int],
    samples_per_size: int,
    tenant_id: str,
    text: str,
    timeout: float,
) -> dict:
    results: dict[str, dict] = {}

    for size in batch_sizes:
        with ThreadPoolExecutor(max_workers=size) as executor:
            futures = [
                executor.submit(send_request, base_url, tenant_id, text, timeout)
                for _ in range(size * samples_per_size)
            ]
            batch_results = [f.result() for f in futures]

        successful = [r for r in batch_results if r["success"]]
        latencies = sorted(r["latency_ms"] for r in successful)
        if not latencies:
            results[str(size)] = {"success_rate": 0.0}
            print(f"batch_size={size} success_rate=0")
            continue

        result = {
            "mean": sum(latencies) / len(latencies),
            "median": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
            "min": latencies[0],
            "max": latencies[-1],
            "success_rate": len(successful) / len(batch_results),
        }
        results[str(size)] = result
        print(
            f"batch_size={size} success_rate={result['success_rate']:.3f} "
            f"p95_ms={result['p95']:.2f} p99_ms={result['p99']:.2f}"
        )

    return results


def run_load_analysis(
    base_url: str,
    loads: list[int],
    samples_per_load: int,
    tenant_id: str,
    text: str,
    timeout: float,
) -> dict:
    results: dict[str, dict] = {}

    for load in loads:
        with ThreadPoolExecutor(max_workers=load) as executor:
            futures = [
                executor.submit(send_request, base_url, tenant_id, text, timeout)
                for _ in range(load * samples_per_load)
            ]
            load_results = [f.result() for f in futures]

        successful = [r for r in load_results if r["success"]]
        latencies = sorted(r["latency_ms"] for r in successful)
        if not latencies:
            results[str(load)] = {"success_rate": 0.0}
            print(f"load={load} success_rate=0")
            continue

        result = {
            "mean": sum(latencies) / len(latencies),
            "median": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
            "min": latencies[0],
            "max": latencies[-1],
            "success_rate": len(successful) / len(load_results),
        }
        results[str(load)] = result
        print(
            f"load={load} success_rate={result['success_rate']:.3f} "
            f"p95_ms={result['p95']:.2f} p99_ms={result['p99']:.2f}"
        )

    return results


def parse_int_list(value: str) -> list[int]:
    return [int(v.strip()) for v in value.split(",") if v.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Latency analysis for batch size and load")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--batch-sizes", default="1,4,8,16,32")
    parser.add_argument("--loads", default="10,50,100,200")
    parser.add_argument("--batch-samples", type=int, default=10)
    parser.add_argument("--load-samples", type=int, default=5)
    parser.add_argument("--tenant", default="latency-benchmark")
    parser.add_argument("--text", default="Latency benchmark request")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    batch_sizes = parse_int_list(args.batch_sizes)
    loads = parse_int_list(args.loads)

    batch_results = run_batch_analysis(
        args.base_url,
        batch_sizes,
        args.batch_samples,
        args.tenant,
        args.text,
        args.timeout,
    )

    load_results = run_load_analysis(
        args.base_url,
        loads,
        args.load_samples,
        args.tenant,
        args.text,
        args.timeout,
    )

    results = {
        "batch_impact": batch_results,
        "load_impact": load_results,
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS_PATH.open("w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2)
    print(f"results={RESULTS_PATH}")


if __name__ == "__main__":
    main()
