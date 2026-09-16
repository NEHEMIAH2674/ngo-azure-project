from databricks import sql
from azure.storage.blob import BlobServiceClient
import os
import json

def main():
    host = os.environ['DATABRICKS_HOST']
    http_path = os.environ['DATABRICKS_HTTP_PATH']
    token = os.environ['DATABRICKS_TOKEN']
    catalog = os.environ.get('DATABRICKS_CATALOG', 'dlight_analytics')
    schema = os.environ.get('DATABRICKS_SCHEMA', 'dev_dlight_analytics')

    conn_str = os.environ.get('AZURE_STORAGE_CONNECTION_STRING')
    if not conn_str:
        print('AZURE_STORAGE_CONNECTION_STRING not set')
        return

    # Fetch all fx_rates
    with sql.connect(server_hostname=host, http_path=http_path, access_token=token) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT rate_date, currency, usd_to_local_rate, rate_is_estimated, rate_source, fetched_at FROM {catalog}.{schema}.fx_rates")
            cols = [c[0] for c in cur.description] if cur.description else []
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    if not rows:
        print('No rows found in fx_rates')
        return

    # Group by date and upload
    client = BlobServiceClient.from_connection_string(conn_str)
    container = client.get_container_client(os.environ.get('AZURE_CONTAINER_NAME', 'raw-data'))

    by_date = {}
    for r in rows:
        d = str(r['rate_date'])
        by_date.setdefault(d, []).append(r)

    for d, recs in by_date.items():
        y, m, day = d.split('-')
        blob_path = f"fx_rates/{y}/{m}/{day}/fx_rates_{d}.json"
        blob = container.get_blob_client(blob_path)
        blob.upload_blob(json.dumps(recs, default=str), overwrite=True)
        print('Uploaded', blob_path)

if __name__ == '__main__':
    main()
