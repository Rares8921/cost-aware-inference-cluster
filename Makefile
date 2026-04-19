.PHONY: setup run test test-integration test-load test-spike benchmark clean deploy-k8s

setup:
	pip install -r requirements-dev.txt

run:
	docker-compose up --build

run-bg:
	docker-compose up -d --build

stop:
	docker-compose down

test:
	pytest tests/ -v --cov=services --cov-report=html --cov-report=term

test-integration:
	pytest tests/test_integration.py -v -s

test-load:
	python tests/load_test.py

test-spike:
	python tests/spike_test.py

benchmark:
	python benchmarks/cost_comparison.py
	python benchmarks/latency_analysis.py
	python benchmarks/gpu_utilization.py

case-study:
	python case-study/generate_charts.py

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
	black services/ tests/ benchmarks/ case-study/
	ruff check --fix services/ tests/ benchmarks/

type-check:
	mypy services/ --ignore-missing-imports
