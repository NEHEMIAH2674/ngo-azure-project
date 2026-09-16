from azure.storage.blob import BlobServiceClient
import os

def main():
    conn_str = os.environ.get('AZURE_STORAGE_CONNECTION_STRING')
    if not conn_str:
        print('AZURE_STORAGE_CONNECTION_STRING is not set in environment')
        return
    client = BlobServiceClient.from_connection_string(conn_str)
    container = client.get_container_client(os.environ.get('AZURE_CONTAINER_NAME', 'raw-data'))
    prefix = 'fx_rates/'
    blobs = container.list_blobs(name_starts_with=prefix)
    found = False
    for b in blobs:
        print(b.name)
        found = True
    if not found:
        print('No blobs found with prefix', prefix)

if __name__ == '__main__':
    main()
