import argparse
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


def run_spike_phase(
    base_url: str,
    phase_name: str,
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

    p99 = 0.0
    if latencies:
        latencies_sorted = sorted(latencies)
        p99 = latencies_sorted[int(len(latencies) * 0.99)]

    summary = {
        "phase": phase_name,
        "duration": duration,
        "success_rate": len(successful) / num_requests if num_requests else 0.0,
        "throughput": num_requests / duration if duration > 0 else 0.0,
        "latency_p99": p99,
    }

    print(
        "spike_phase "
        f"phase={phase_name} "
        f"total={num_requests} "
        f"success_rate={summary['success_rate']:.3f} "
        f"rps={summary['throughput']:.2f} "
        f"p99_ms={summary['latency_p99']:.2f}"
    )

    return summary


def run_spike_test(
    base_url: str,
    tenant_id: str,
    text: str,
    sleep_seconds: int,
) -> list[dict]:
    phases = [
        ("baseline", 100, 10),
        ("ramp", 200, 20),
        ("spike", 500, 50),
        ("recovery", 100, 10),
    ]

    results = []
    for idx, (name, total, concurrency) in enumerate(phases):
        results.append(
            run_spike_phase(
                base_url,
                name,
                total,
                concurrency,
                tenant_id,
                text,
            )
        )
        if idx < len(phases) - 1:
            time.sleep(sleep_seconds)

    return results


def main():
    parser = argparse.ArgumentParser(description="Run spike test against router")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--tenant", default="spike-test")
    parser.add_argument("--text", default="Spike test request")
    parser.add_argument("--sleep", type=int, default=5)
    args = parser.parse_args()

    run_spike_test(
        base_url=args.base_url,
        tenant_id=args.tenant,
        text=args.text,
        sleep_seconds=args.sleep,
    )


if __name__ == "__main__":
    main()
