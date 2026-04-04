import os
import sys
import json
from argparse import Namespace
from typing import Dict, Any

def run_upload(args: Namespace) -> None:
    try:
        from google.cloud import storage # type: ignore
    except ImportError:
        print("'google-cloud-storage' is not installed.", file=sys.stderr)
        sys.exit(1)

    config_data: Dict[str, Any] = {}
    config_path: str = getattr(args, 'config', '')
    if config_path and os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
        except Exception as e:
            print(f"Failed to read config file '{config_path}': {e}", file=sys.stderr)

    bucket_name_raw = getattr(args, 'bucket', None) or config_data.get("bucket")
    bucket_name: str = str(bucket_name_raw) if bucket_name_raw else ""
    if not bucket_name:
        print("Please provide a bucket name using the --bucket argument or in config JSON.", file=sys.stderr)
        sys.exit(1)

    prefix_raw = getattr(args, 'prefix', None)
    if prefix_raw is None:
        prefix_raw = config_data.get("prefix", "blog/")
    prefix: str = str(prefix_raw) if prefix_raw else ""
    if prefix and not prefix.endswith('/'):
        prefix += '/'

    root_dir: str = args.root_dir
    print(f"Uploading '{root_dir}' directory to GCS bucket '{bucket_name}' under prefix '{prefix}'...")
    
    try:
        project_id_raw = getattr(args, 'project', None) or config_data.get("project")
        project_id: str = str(project_id_raw) if project_id_raw else ""
        if project_id:
            client = storage.Client(project=project_id)
        else:
            client = storage.Client()
        bucket = client.bucket(bucket_name)
    except Exception as e:
        print(f"Failed to initialize GCS client: {e}", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(root_dir):
        print(f"Directory '{root_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)

    uploaded_files_count = 0
    
    for current_dir, _, files in os.walk(root_dir):
        for file in files:
            local_path = os.path.join(current_dir, file)
            relative_path = os.path.relpath(local_path, start=root_dir).replace("\\", "/")
            blob_name = f"{prefix}{relative_path}"
            
            try:
                blob = bucket.blob(blob_name)
                blob.upload_from_filename(local_path)
                print(f"Uploaded: {blob_name}")
                uploaded_files_count += 1
            except Exception as e:
                print(f"Failed to upload {local_path} to {blob_name}: {e}", file=sys.stderr)

    print(f"Upload complete. {uploaded_files_count} files uploaded to bucket '{bucket_name}'.")