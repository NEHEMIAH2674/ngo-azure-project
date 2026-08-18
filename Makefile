.PHONY: install ingest fx transform test dashboard dagster all clean

install:
	pip install -r requirements.txt
	cd dbt && dbt deps

# Load today's (or a given DATE=YYYY-MM-DD) CSV extracts into BigQuery raw.
ingest:
	python ingestion/load_csv_to_bq.py --date $(DATE)

# Fetch/cache any missing daily FX rates needed by the payments in raw.
fx:
	python ingestion/fetch_fx_rates.py

# Run the full dbt DAG (seeds + staging + intermediate + marts) with tests.
transform:
	cd dbt && dbt seed && dbt build

test:
	pytest ingestion/tests
	cd dbt && dbt test

dashboard:
	streamlit run dashboard/streamlit_app.py

dagster:
	cd orchestration && dagster dev -w workspace.yaml

# One command: delete + rebuild everything from scratch, per the brief's ask.
all: ingest fx transform

clean:
	cd dbt && dbt clean
