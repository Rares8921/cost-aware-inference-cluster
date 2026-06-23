from pathlib import Path

from benchmarks.local_stack_benchmark import (
    BenchmarkConfig,
    build_report,
    markdown_report,
    parse_config,
    percentile,
    run_benchmark,
)


def healthy(status_code=200, payload=None):
    return {
        "ok": status_code == 200,
        "status_code": status_code,
        "latency_ms": 1.0,
        "json": payload or {"status": "healthy"},
        "error": None,
    }


def unhealthy(error="connection refused"):
    return {
        "ok": False,
        "status_code": None,
        "latency_ms": 1.0,
        "json": None,
        "error": error,
    }


def sample_report():
    config = BenchmarkConfig(request_count=2, concurrency=1)
    health = {
        "router": healthy(),
        "scheduler": healthy(),
        "worker": unhealthy("worker port not exposed"),
    }
    return build_report(
        config=config,
        timestamp="2026-06-23T00:00:00Z",
        command="test-command",
        commit="abc123",
        health=health,
        scheduler_metrics_before=healthy(payload={"queue": {"queue_depth": 0}}),
        scheduler_metrics_after=healthy(payload={"queue": {"queue_depth": 0}}),
        worker_metrics_before=unhealthy("worker port not exposed"),
        worker_metrics_after=unhealthy("worker port not exposed"),
        request_results=[
            {"success": True, "status_code": 200, "latency_ms": 10.0, "error": None},
            {"success": True, "status_code": 200, "latency_ms": 20.0, "error": None},
        ],
        duration_s=0.5,
    )


def test_parse_config_from_args():
    config, timestamp, command = parse_config(
        [
            "--router-url",
            "http://router.local/",
            "--scheduler-url",
            "http://scheduler.local/",
            "--worker-url",
            "http://worker.local/",
            "--requests",
            "7",
            "--concurrency",
            "3",
            "--tenant",
            "tenant-a",
            "--timeout",
            "2.5",
            "--output-dir",
            "tmp-results",
            "--timestamp",
            "2026-06-23T00:00:00Z",
            "--command",
            "local command",
        ]
    )

    assert config.router_url == "http://router.local"
    assert config.scheduler_url == "http://scheduler.local"
    assert config.worker_url == "http://worker.local"
    assert config.request_count == 7
    assert config.concurrency == 3
    assert config.tenant_id == "tenant-a"
    assert config.timeout_s == 2.5
    assert config.output_dir == Path("tmp-results")
    assert timestamp == "2026-06-23T00:00:00Z"
    assert command == "local command"


def test_percentile_calculation():
    values = [100.0, 10.0, 50.0, 20.0, 30.0]

    assert percentile(values, 0.0) == 10.0
    assert percentile(values, 0.50) == 30.0
    assert percentile(values, 0.95) == 100.0
    assert percentile([], 0.95) == 0.0


def test_report_schema_contains_required_sections():
    report = sample_report()

    assert report["benchmark_status"] == "completed"
    assert report["metadata"]["command_used"] == "test-command"
    assert report["requests"]["attempted"] == 2
    assert report["requests"]["successful"] == 2
    assert report["requests"]["status_counts"] == {"200": 2}
    assert "scheduler_metrics" in report
    assert "worker_metrics" in report
    assert "unsupported_claims" in report


def test_markdown_report_contains_limitations_and_latency_scope():
    rendered = markdown_report(sample_report())

    assert "Local Stack Benchmark Report" in rendered
    assert "not production performance evidence" in rendered
    assert "router /infer enqueue-response latency" in rendered
    assert "Unsupported Claims" in rendered


def test_unavailable_services_are_reported_as_blockers_without_requests():
    def fake_fetcher(url, timeout_s):
        if url.endswith("/health"):
            return unhealthy("service unavailable")
        return unhealthy("metrics unavailable")

    report = run_benchmark(BenchmarkConfig(request_count=5), fetcher=fake_fetcher)

    assert report["benchmark_status"] == "blocked"
    assert report["requests"]["attempted"] == 0
    assert report["blockers"] == [
        "router health check failed: service unavailable",
        "scheduler health check failed: service unavailable",
    ]