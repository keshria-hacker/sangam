[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts =
    -v
    --strict-markers
    --strict-config
    --tb=short
    --cov=backend
    --cov-report=term-missing
    --cov-report=html:htmlcov
    --cov-fail-under=80
    --asyncio-mode=auto

markers =
    unit: Unit tests
    integration: Integration tests
    e2e: End-to-end tests
    slow: Slow running tests
    requires_network: Tests requiring network access

filterwarnings =
    ignore::DeprecationWarning
    ignore::PendingDeprecationWarning
