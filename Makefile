setup:
	python -m venv .venv
	.venv/Scripts/pip install -r requirements.txt -r requirements-dev.txt || .venv/bin/pip install -r requirements.txt -r requirements-dev.txt

check:
	python scripts/check_setup.py

