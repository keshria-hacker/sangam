"""qa package — Batch 12: one testing/QA + dev/platform surface.

Pure helpers live in :mod:`backend.qa.devqa`; routes live in
``api_routes/devqa_routes.py``. Nothing here imports the app, so the
helpers are unit-testable without a database.
"""
