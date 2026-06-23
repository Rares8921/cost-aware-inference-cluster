from benchmarks.autoscaling_simulation import build_report, markdown_report


def scenario_by_name(report, name):
    return next(scenario for scenario in report["scenarios"] if scenario["name"] == name)


def test_scenario_schema_contains_required_evidence_fields():
    report = build_report(timestamp="2026-01-01T00:00:00Z", commit="test", command="test-command")
    scenario = report["scenarios"][0]

    required = {
        "name",
        "steps_simulated",
        "queue_depth_over_time",
        "p95_latency_ms_over_time",
        "p99_latency_ms_over_time",
        "active_workers_over_time",
        "scale_up_decisions",
        "scale_down_decisions",
        "cooldown_blocks",
        "cost_budget_blocks",
        "estimated_gpu_cost_usd",
        "limitations",
    }

    assert required.issubset(scenario)


def test_report_output_is_deterministic_with_fixed_metadata():
    first = build_report(timestamp="2026-01-01T00:00:00Z", commit="test", command="test-command")
    second = build_report(timestamp="2026-01-01T00:00:00Z", commit="test", command="test-command")

    assert first == second


def test_report_contains_required_metadata_and_limitations():
    report = build_report(timestamp="2026-01-01T00:00:00Z", commit="test", command="test-command")
    rendered = markdown_report(report)

    assert report["metadata"]["command_used"] == "test-command"
    assert report["metadata"]["git_commit"] == "test"
    assert "not a live GPU" in rendered
    assert "Unsupported Claims" in rendered


def test_cooldown_behavior_is_recorded():
    report = build_report(timestamp="2026-01-01T00:00:00Z", commit="test", command="test-command")
    scenario = scenario_by_name(report, "cooldown_prevents_thrashing")

    assert scenario["scale_up_decisions"] == 1
    assert scenario["cooldown_blocks"] >= 1


def test_max_worker_limit_behavior_is_recorded():
    report = build_report(timestamp="2026-01-01T00:00:00Z", commit="test", command="test-command")
    scenario = scenario_by_name(report, "max_worker_limit")

    assert scenario["scale_up_decisions"] == 0
    assert scenario["max_worker_blocks"] >= 1


def test_warm_pool_floor_behavior_is_recorded():
    report = build_report(timestamp="2026-01-01T00:00:00Z", commit="test", command="test-command")
    scenario = scenario_by_name(report, "warm_pool_floor")

    assert scenario["scale_down_decisions"] == 0
    assert scenario["warm_pool_floor_blocks"] >= 1


def test_cost_budget_behavior_is_recorded():
    report = build_report(timestamp="2026-01-01T00:00:00Z", commit="test", command="test-command")
    scenario = scenario_by_name(report, "cost_budget_limit")

    assert scenario["scale_up_decisions"] == 0
    assert scenario["cost_budget_blocks"] >= 1
