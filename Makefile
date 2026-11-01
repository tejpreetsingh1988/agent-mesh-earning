.PHONY: install test eval run-scout run-all

install:
	python3 -m venv .venv || true
	.venv/bin/pip install -e ".[dev]"

test:
	PYTHONPATH=. .venv/bin/python -m pytest tests -q || PYTHONPATH=. python3 -m pytest tests -q

eval:
	PYTHONPATH=. python3 -m evals.runner

run-scout:
	PYTHONPATH=. uvicorn agents.scout.main:app --host 0.0.0.0 --port 8001 --reload
