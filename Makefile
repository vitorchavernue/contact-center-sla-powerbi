PY ?= python
DATA ?= data

.PHONY: setup data kpis report validate test lint all

setup:
	$(PY) -m pip install -r requirements.txt
	$(PY) -m pip install --no-deps semantic-link-sempy==0.14.3

# Synthetic contacts (24 months, ~1.5 million rows) -> point the DataFolder parameter here
data:
	$(PY) scripts/generate_data.py --out $(DATA)

# Same definitions as the DAX measures, computed in pandas (to check the numbers in Power BI)
kpis:
	$(PY) scripts/kpis.py --data $(DATA)
	$(PY) scripts/kpis.py --data $(DATA) --by Partner Channel

# Report pages (PBIR) and page backgrounds from the layout spec
report:
	$(PY) scripts/build_report.py --render

# Quality gate: TMDL loaded by the Tabular Object Model + best-practice rules + report references
validate:
	$(PY) scripts/validate_model.py

test:
	$(PY) -m pytest -q

lint:
	ruff check .
	ruff format --check .

all: lint validate test
