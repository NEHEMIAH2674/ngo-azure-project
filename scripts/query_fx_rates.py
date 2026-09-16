from databricks import sql
import os
import json

def main():
    host = os.environ['DATABRICKS_HOST']
    http_path = os.environ['DATABRICKS_HTTP_PATH']
    token = os.environ['DATABRICKS_TOKEN']
    catalog = os.environ.get('DATABRICKS_CATALOG', 'dlight_analytics')
    schema = os.environ.get('DATABRICKS_SCHEMA', 'dev_dlight_analytics')

    with sql.connect(server_hostname=host, http_path=http_path, access_token=token) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT rate_date, currency, usd_to_local_rate, rate_is_estimated, rate_source, fetched_at FROM {catalog}.{schema}.fx_rates ORDER BY rate_date DESC, currency LIMIT 10")
            cols = [c[0] for c in cur.description] if cur.description else []
            rows = cur.fetchall()
            records = [dict(zip(cols, r)) for r in rows]
            print(json.dumps(records, default=str, indent=2))

if __name__ == '__main__':
    main()
