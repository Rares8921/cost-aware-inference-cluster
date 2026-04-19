import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import httpx


DEFAULT_BASE_URL = "http://localhost:8000"


def send_request(base_url: str, tenant_id: str, text: str) -> dict:
    start = time.time()
    try:
        response = httpx.post(
            f"{base_url}/infer",
            json={"text": text},
            headers={"X-Tenant-Id": tenant_id},
            timeout=30.0,
        )
        latency = (time.time() - start) * 1000
        return {
            "success": response.status_code == 200,
            "latency_ms": latency,
            "status_code": response.status_code,
        }
    except Exception as e:
        return {
            "success": False,
            "latency_ms": (time.time() - start) * 1000,
            "error": str(e),
        }


def run_load_test(
    base_url: str,
    num_requests: int,
    concurrent_users: int,
    tenant_id: str,
    text: str,
) -> dict:
    start_time = time.time()
    with ThreadPoolExecutor(max_workers=concurrent_users) as executor:
        futures = [
            executor.submit(send_request, base_url, tenant_id, text)
            for _ in range(num_requests)
        ]
        results = [f.result() for f in futures]

    duration = time.time() - start_time
    successful = [r for r in results if r["success"]]
    latencies = [r["latency_ms"] for r in successful]

    p50 = p95 = p99 = None
    if latencies:
        latencies_sorted = sorted(latencies)
        p50 = latencies_sorted[len(latencies) // 2]
        p95 = latencies_sorted[int(len(latencies) * 0.95)]
        p99 = latencies_sorted[int(len(latencies) * 0.99)]

    summary = {
        "duration": duration,
        "total": num_requests,
        "successful": len(successful),
        "failed": num_requests - len(successful),
        "throughput": num_requests / duration if duration > 0 else 0.0,
        "latency_mean": statistics.mean(latencies) if latencies else 0.0,
        "latency_p50": p50 or 0.0,
        "latency_p95": p95 or 0.0,
        "latency_p99": p99 or 0.0,
    }

    print(
        "load_test "
        f"total={summary['total']} "
        f"success={summary['successful']} "
        f"fail={summary['failed']} "
        f"rps={summary['throughput']:.2f} "
        f"p50_ms={summary['latency_p50']:.2f} "
        f"p95_ms={summary['latency_p95']:.2f} "
        f"p99_ms={summary['latency_p99']:.2f}"
    )

    return summary


def main():
    parser = argparse.ArgumentParser(description="Run load test against router")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--tenant", default="load-test")
    parser.add_argument("--text", default="Load test request")
    args = parser.parse_args()

    run_load_test(
        base_url=args.base_url,
        num_requests=args.requests,
        concurrent_users=args.concurrency,
        tenant_id=args.tenant,
        text=args.text,
    )


if __name__ == "__main__":
    main()
