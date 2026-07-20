# DriveAuth Edge — common developer targets
.PHONY: help install bootstrap test lint coverage demo openapi stress clean

PYTHON ?= python3
PIP ?= $(PYTHON) -m pip

help:
	@echo "Targets: install bootstrap test lint coverage demo openapi stress clean"

install:
	$(PIP) install -U pip
	$(PIP) install -e ".[dev,dashboard,onnx]"
	$(PIP) install "httpx>=0.27" "pytest-cov>=5.0"

bootstrap:
	$(PYTHON) scripts/bootstrap.py

test:
	$(PYTHON) -m pytest -q --tb=short

lint:
	ruff check driveauth hardware dashboard demo tests scripts
	ruff format --check driveauth hardware dashboard demo tests scripts || true

coverage:
	$(PYTHON) -m pytest -q --cov=driveauth --cov=dashboard --cov=hardware \
		--cov-report=term-missing --cov-report=xml \
		--cov-fail-under=55

demo:
	DRIVEAUTH_USE_MOCK=1 DRIVEAUTH_ALLOW_INSECURE_DASHBOARD=1 driveauth-dashboard

openapi:
	$(PYTHON) scripts/export_openapi.py

stress:
	$(PYTHON) scripts/stress_test.py --seconds 20 --iterations 200

clean:
	rm -rf .pytest_cache .ruff_cache .coverage coverage.xml htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
