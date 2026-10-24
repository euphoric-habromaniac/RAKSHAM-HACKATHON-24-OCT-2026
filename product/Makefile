# Asli Awaaz Makefile
PYTHON = .venv/bin/python
PYTEST = .venv/bin/pytest

.PHONY: setup test smoke demo-reset preflight run clean

setup:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements-service.txt
	.venv/bin/pip install numpy scipy soundfile pandas tqdm

test:
	PYTHONPATH=. $(PYTEST) tests -q

smoke:
	PYTHONPATH=. $(PYTHON) tools/smoke.py

demo-reset:
	PYTHONPATH=. $(PYTHON) tools/demo_reset.py

preflight:
	PYTHONPATH=. $(PYTHON) tools/preflight.py

run:
	PYTHONPATH=. $(PYTHON) -m uvicorn service.api:app --host 0.0.0.0 --port 8000 --reload
