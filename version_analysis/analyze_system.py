#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import matplotlib.pyplot as plt


DEFAULT_INPUT_DIR = Path("benchmarks")
DEFAULT_OUTPUT_DIR = "plots"


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def ensure_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def format_float(value: float) -> str:
    return f"{value:.2f}"


def run_benchmarks() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    benchmarks = [
        repo_root / "benchmarks" / "cost_comparison.py",
        repo_root / "benchmarks" / "latency_analysis.py",
        repo_root / "benchmarks" / "gpu_utilization.py",
    ]

    for script in benchmarks:
        subprocess.run(
            [sys.executable, str(script)],
            check=True,
            cwd=repo_root,
        )


def plot_cost_comparison(data: dict, output_dir: Path) -> Path:
    no_batch = data["no_batching"]
    with_batch = data["with_batching"]

    labels = ["No batching", "With batching"]
    cost_per_request = [
        no_batch["cost_per_request"],
        with_batch["cost_per_request"],
    ]
    throughput = [
        no_batch["throughput"],
        with_batch["throughput"],
    ]

    fig, (ax_cost, ax_tp) = plt.subplots(1, 2, figsize=(12, 5))
    cost_bars = ax_cost.bar(labels, cost_per_request, color=["#c0392b", "#27ae60"])
    ax_cost.set_ylabel("Cost per request ($)")
    ax_cost.set_title("Cost per request")
    ax_cost.grid(axis="y", alpha=0.2)

    for bar in cost_bars:
        height = bar.get_height()
        ax_cost.text(
            bar.get_x() + bar.get_width() / 2,
            height,
            format_float(height),
            ha="center",
            va="bottom",
        )

    tp_bars = ax_tp.bar(labels, throughput, color=["#c0392b", "#27ae60"])
    ax_tp.set_ylabel("Requests per second")
    ax_tp.set_title("Throughput")
    ax_tp.grid(axis="y", alpha=0.2)

    for bar in tp_bars:
        height = bar.get_height()
        ax_tp.text(
            bar.get_x() + bar.get_width() / 2,
            height,
            format_float(height),
            ha="center",
            va="bottom",
        )

    fig.tight_layout()
    output_path = output_dir / "cost_throughput_comparison.png"
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)
    return output_path


def plot_latency_by_batch(data: dict, output_dir: Path) -> Path:
    batch_impact = data["batch_impact"]
    sizes = sorted(int(k) for k in batch_impact.keys())
    p95 = [batch_impact[str(size)]["p95"] for size in sizes]
    p99 = [batch_impact[str(size)]["p99"] for size in sizes]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(sizes, p95, marker="o", label="P95")
    ax.plot(sizes, p99, marker="o", label="P99")
    ax.set_xlabel("Batch size")
    ax.set_ylabel("Latency (ms)")
    ax.set_title("Latency by batch size")
    ax.grid(True, alpha=0.2)
    ax.legend()

    fig.tight_layout()
    output_path = output_dir / "latency_by_batch_size.png"
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)
    return output_path


def plot_latency_by_load(data: dict, output_dir: Path) -> Path:
    load_impact = data["load_impact"]
    loads = sorted(int(k) for k in load_impact.keys())
    p95 = [load_impact[str(load)]["p95"] for load in loads]
    p99 = [load_impact[str(load)]["p99"] for load in loads]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(loads, p95, marker="o", label="P95")
    ax.plot(loads, p99, marker="o", label="P99")
    ax.set_xlabel("Concurrent requests")
    ax.set_ylabel("Latency (ms)")
    ax.set_title("Latency by load")
    ax.grid(True, alpha=0.2)
    ax.legend()

    fig.tight_layout()
    output_path = output_dir / "latency_by_load.png"
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)
    return output_path


def plot_gpu_utilization(data: dict, output_dir: Path) -> Path:
    scenarios = list(data.keys())
    utilization = [
        data[scenario]["stats"]["estimated_utilization"] for scenario in scenarios
    ]

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(scenarios, utilization, color="#2ecc71")
    ax.set_ylabel("Estimated utilization (%)")
    ax.set_title("GPU utilization by scenario")
    ax.set_ylim(0, 100)
    ax.grid(axis="y", alpha=0.2)

    for bar in bars:
        height = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            height,
            format_float(height),
            ha="center",
            va="bottom",
        )

    fig.tight_layout()
    output_path = output_dir / "gpu_utilization_by_scenario.png"
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate case study charts")
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--require-all", action="store_true")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    ensure_output_dir(output_dir)

    cost_path = input_dir / "cost_comparison_results.json"
    latency_path = input_dir / "latency_analysis_results.json"
    gpu_path = input_dir / "gpu_utilization_results.json"

    missing: list[str] = []
    generated: list[Path] = []

    cost_data = load_json(cost_path)
    if cost_data:
        generated.append(plot_cost_comparison(cost_data, output_dir))
    else:
        missing.append(cost_path.name)

    latency_data = load_json(latency_path)
    if latency_data:
        generated.append(plot_latency_by_batch(latency_data, output_dir))
        generated.append(plot_latency_by_load(latency_data, output_dir))
    else:
        missing.append(latency_path.name)

    gpu_data = load_json(gpu_path)
    if gpu_data:
        generated.append(plot_gpu_utilization(gpu_data, output_dir))
    else:
        missing.append(gpu_path.name)

    if missing and args.require_all:
        print(f"Missing input files: {', '.join(missing)}")
        sys.exit(1)

    for path in generated:
        print(f"Generated {path}")

    if missing:
        print(f"Skipped missing inputs: {', '.join(missing)}")


if __name__ == "__main__":
    # run_benchmarks()
    main()
