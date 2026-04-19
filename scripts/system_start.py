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


def setup_environment():
    if platform.architecture()[0] != "64bit":
        print("64-bit Python is required for dependencies like torch and numpy.")
        return False

    if not venv_dir.exists():
        if not run_command(
                [sys.executable, "-m", "venv", str(venv_dir)],
                "Virtual environment"
        ):
            return False

    python_cmd = (
        venv_dir / "Scripts" / "python"
        if sys.platform == "win32"
        else venv_dir / "bin" / "python"
    )

    if not run_command(
            [str(python_cmd), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
            "Python tooling"
    ):
        return False

    if not run_command(
            [
                str(python_cmd),
                "-m",
                "pip",
                "install",
                "--only-binary=:all:",
                "-r",
                str(requirements_file),
            ],
            "Python dependencies"
    ):
        return False

    return True


def start_services(run_checks: bool):
    try:
        run_command(
            ["docker-compose", "down", "--remove-orphans"],
            "Docker Compose cleanup"
        )

        subprocess.run(
            ["docker-compose", "up", "-d", "--build"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=repo_root
        )

        if run_checks:
            time.sleep(30)

            services = [
                ("http://localhost:8000/health", "Router"),
                ("http://localhost:8001/health", "Scheduler"),
                ("http://localhost:8002/health", "Worker"),
            ]

            import httpx

            for url, name in services:
                try:
                    response = httpx.get(url, timeout=5.0)
                    if response.status_code != 200:
                        print(f"{name} not ready: HTTP {response.status_code}")
                        return False
                except Exception as e:
                    print(f"{name} not reachable: {e}")
                    return False

            print("Services ready")

        return True

    except Exception as e:
        print(f"Service startup failed: {e}")
        return False


def run_test_request():
    import httpx

    try:
        response = httpx.post(
            "http://localhost:8000/infer",
            json={"text": "This is a test inference request."},
            headers={"X-Tenant-Id": "quickstart"},
            timeout=30.0
        )

        if response.status_code == 200:
            print("Test request OK")
            return True
        print(f"Test request failed: HTTP {response.status_code}")
        return False

    except Exception as e:
        print(f"Test request failed: {e}")
        return False


def print_next_steps():
    print("Router: http://localhost:8000")
    print("Scheduler: http://localhost:8001")
    print("Prometheus: http://localhost:9090")
    print("Grafana: http://localhost:3000")
    print("Stop: docker-compose down")


def main():
    parser = argparse.ArgumentParser(description="Start local services")
    parser.add_argument(
        "--docker-only",
        action="store_true",
        help="Run only docker-compose cleanup and up"
    )
    args = parser.parse_args()

    if not requirements_file.exists():
        print(f"requirements-dev.txt not found at {requirements_file}")
        sys.exit(1)

    if not check_docker():
        print("Prerequisites not met.")
        sys.exit(1)

    if not args.docker_only:
        if not setup_environment():
            print("Environment setup failed.")
            sys.exit(1)

    if not start_services(run_checks=not args.docker_only):
        print("Service startup failed.")
        sys.exit(1)

    if not args.docker_only:
        if not run_test_request():
            print("Test request failed, services are running.")

        print_next_steps()


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
