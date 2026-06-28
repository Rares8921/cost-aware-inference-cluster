.PHONY: setup run test test-unit test-load test-spike benchmark clean deploy-k8s

setup:
	pip install -r requirements-dev.txt

run:
	docker-compose up --build

run-bg:
	docker-compose up -d --build

stop:
	docker-compose down

test:
	docker-compose up -d redis
	pytest tests/ -v
	docker-compose down redis --remove-orphans

test-unit:
	pytest tests/unit -v -s

test-load:
	python tests/load_test.py

test-spike:
	python tests/spike_test.py

benchmark:
	python benchmarks/cost_comparison.py
	python benchmarks/latency_analysis.py
	python benchmarks/gpu_utilization.py

case-study:
	@echo See docs/case-study.md

deploy-k8s:
	kubectl apply -f kubernetes/

clean:
	docker-compose down -v
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache htmlcov .coverage

lint:
	ruff check services/ tests/ benchmarks/
	black --check services/ tests/ benchmarks/

format:
	black services/ tests/ benchmarks/
	ruff check --fix services/ tests/ benchmarks/

type-check:
	mypy services/ --ignore-missing-imports
