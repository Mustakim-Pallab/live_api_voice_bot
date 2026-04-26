from google.cloud import storage
import json
import os

# Configuration
service_account_path = "vivasoft-gcp-4210bb348a63.json"
bucket_name = "voice_bot_data_dump"

def set_bucket_cors():
    storage_client = storage.Client.from_service_account_json(service_account_path)
    bucket = storage_client.get_bucket(bucket_name)

    # Define CORS policy
    # We allow all origins for local development, but you can restrict it to your domain later
    bucket.cors = [
        {
            "origin": ["*"],
            "responseHeader": ["Content-Type", "x-goog-resumable"],
            "method": ["GET", "PUT", "POST", "DELETE", "OPTIONS"],
            "maxAgeSeconds": 3600
        }
    ]
    bucket.patch()

    print(f"Successfully set CORS for bucket: {bucket_name}")

if __name__ == "__main__":
    try:
        set_bucket_cors()
    except Exception as e:
        print(f"Error: {e}")
