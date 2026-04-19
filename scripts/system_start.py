#!/usr/bin/env python3

import argparse
import shutil
import subprocess
import sys
import time
import platform
from pathlib import Path


def run_command(cmd, description):
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=repo_root
        )
        print(f"{description} OK")
        return True
    except subprocess.CalledProcessError as e:
        message = e.stderr.strip() or e.stdout.strip() or str(e)
        print(f"{description} FAILED: {message}")
        return False


def check_docker():
    if shutil.which("docker") is None:
        print("Docker not found. Install: https://docs.docker.com/get-docker/")
        return False

    if shutil.which("docker-compose") is None:
        print("docker-compose not found. Install Docker Compose.")
        return False

    if not run_command(["docker", "--version"], "Docker"):
        return False

    if not run_command(["docker-compose", "--version"], "Docker Compose"):
        return False

    return True


def check_kubectl():
    if shutil.which("kubectl") is None:
        print("kubectl not found. Install Kubernetes CLI.")
        return False
    if not run_command(["kubectl", "version", "--client"], "kubectl"):
        return False
    return True


def start_docker_services():
    try:
        run_command(
            ["docker-compose", "down", "--remove-orphans"],
            "Docker Compose cleanup"
        )

        run_command(
            [
                "docker",
                "rm",
                "-f",
                "cost-aware-inference-cluster-redis-1",
                "cost-aware-inference-cluster-prometheus-1",
            ],
            "Docker container cleanup"
        )

        if not run_command(
                ["docker-compose", "up", "-d", "--build"],
                "Docker Compose up"
        ):
            return False

        return True

    except Exception as e:
        print(f"Docker startup failed: {e}")
        return False


def start_k8s_services():
    if not run_command(["kubectl", "apply", "-f", "kubernetes\\"], "kubectl apply"):
        return False
    run_command(
        ["kubectl", "get", "pods", "-n", "inference-cluster"],
        "kubectl get pods"
    )
    run_command(
        ["kubectl", "get", "svc", "-n", "inference-cluster"],
        "kubectl get svc"
    )
    return True


def main():
    parser = argparse.ArgumentParser(description="Start services")
    parser.add_argument(
        "--mode",
        choices=["docker", "k8s"],
        default="docker",
        help="Select docker-compose or kubernetes mode"
    )
    args = parser.parse_args()

    if args.mode == "docker":
        if not check_docker():
            print("Prerequisites not met.")
            sys.exit(1)
        if not start_docker_services():
            print("Docker startup failed.")
            sys.exit(1)
    else:
        if not check_kubectl():
            print("Prerequisites not met.")
            sys.exit(1)
        if not start_k8s_services():
            print("Kubernetes deploy failed.")
            sys.exit(1)


if __name__ == "__main__":
    try:
        repo_root = Path(__file__).resolve().parent.parent
        venv_dir = repo_root / "venv"
        requirements_file = repo_root / "requirements-dev.txt"
        main()
    except KeyboardInterrupt:
        print("Interrupted.")
        sys.exit(0)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)
