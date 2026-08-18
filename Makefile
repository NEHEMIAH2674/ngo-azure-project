.PHONY: install ingest fx transform test lint lint-py lint-sql dashboard dagster all clean

install:
	pip install -r requirements.txt
	cd dbt && dbt deps

# Load today's (or a given DATE=YYYY-MM-DD) CSV extracts into BigQuery raw.
ingest:
	python ingestion/load_csv_to_bq.py --date $(DATE)

# Fetch/cache any missing daily FX rates needed by the payments in raw.
fx:
	python ingestion/api/fx/main.py

# Run the full dbt DAG (seeds + staging + intermediate + marts) with tests.
transform:
	cd dbt && dbt seed && dbt build

test:
	pytest ingestion/tests
	cd dbt && dbt test

lint-py:
	ruff check ingestion orchestration dashboard

# Requires GCP auth (sqlfluff's dbt templater compiles the project the same
# way `dbt build` does), so this isn't part of `make test`.
lint-sql:
	cd dbt && sqlfluff lint models

lint: lint-py lint-sql

dashboard:
	streamlit run dashboard/streamlit_app.py

# Wrapped in a bounded retry -- see orchestration/run_dagster_dev.sh for why.
dagster:
	bash orchestration/run_dagster_dev.sh

# One command: delete + rebuild everything from scratch, per the brief's ask.
all: ingest fx transform

clean:
	cd dbt && dbt clean
