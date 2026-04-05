import os
import sys
import json
import base64
import hashlib
from argparse import Namespace
from typing import Dict, Any, Set, Tuple


def _parent_folder(rel_path: str) -> str:
    folder = os.path.dirname(rel_path).replace("\\", "/")
    if folder == ".":
        return ""
    return folder

def _md5_base64(file_path: str) -> str:
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            md5.update(chunk)
    return base64.b64encode(md5.digest()).decode("ascii")


def _scan_local_files(root_dir: str) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, Set[str]]]:
    local_paths: Dict[str, str] = {}
    local_md5: Dict[str, str] = {}
    local_by_folder: Dict[str, Set[str]] = {}

    for current_dir, _, files in os.walk(root_dir):
        for file in files:
            local_path = os.path.join(current_dir, file)
            relative_path = os.path.relpath(local_path, start=root_dir).replace("\\", "/")
            local_paths[relative_path] = local_path
            local_md5[relative_path] = _md5_base64(local_path)
            folder = _parent_folder(relative_path)
            local_by_folder.setdefault(folder, set()).add(relative_path)

    return local_paths, local_md5, local_by_folder


def _scan_remote_files(
    client: Any, bucket_name: str, prefix: str
) -> Tuple[Dict[str, Any], Dict[str, Set[str]]]:
    remote_by_rel: Dict[str, Any] = {}
    remote_by_folder: Dict[str, Set[str]] = {}

    for blob in client.list_blobs(bucket_name, prefix=prefix):
        blob_name = blob.name
        if prefix and not blob_name.startswith(prefix):
            continue
        rel_path = blob_name[len(prefix) :] if prefix else blob_name
        if not rel_path or rel_path.endswith("/"):
            continue
        remote_by_rel[rel_path] = blob
        folder = _parent_folder(rel_path)
        remote_by_folder.setdefault(folder, set()).add(rel_path)

    return remote_by_rel, remote_by_folder


def _load_config_data(config_path: str) -> Dict[str, Any]:
    if not config_path or not os.path.isfile(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to read config file '{config_path}': {e}", file=sys.stderr)
        return {}


def _resolve_bucket_name(args: Namespace, config_data: Dict[str, Any]) -> str:
    bucket_name_raw = getattr(args, "bucket", None) or config_data.get("bucket")
    return str(bucket_name_raw) if bucket_name_raw else ""


def _resolve_prefix(args: Namespace, config_data: Dict[str, Any]) -> str:
    prefix_raw = getattr(args, "prefix", None)
    if prefix_raw is None:
        prefix_raw = config_data.get("prefix", "blog/")

    prefix = str(prefix_raw) if prefix_raw else ""
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    return prefix


def _build_storage_client(storage: Any, args: Namespace, config_data: Dict[str, Any]) -> Any:
    project_id_raw = getattr(args, "project", None) or config_data.get("project")
    project_id = str(project_id_raw) if project_id_raw else ""
    if project_id:
        return storage.Client(project=project_id)
    return storage.Client()


def _upload_changed_files(
    bucket: Any,
    prefix: str,
    local_paths: Dict[str, str],
    local_md5: Dict[str, str],
    remote_by_rel: Dict[str, Any],
) -> Tuple[int, int, int]:
    uploaded_files_count = 0
    skipped_files_count = 0
    failed_upload_count = 0

    for rel_path in sorted(local_paths.keys()):
        local_path = local_paths[rel_path]
        blob_name = f"{prefix}{rel_path}"
        remote_blob = remote_by_rel.get(rel_path)
        remote_md5 = remote_blob.md5_hash if remote_blob else None
        if remote_md5 and remote_md5 == local_md5[rel_path]:
            skipped_files_count += 1
            continue

        try:
            blob = bucket.blob(blob_name)
            blob.upload_from_filename(local_path)
            print(f"Uploaded: {blob_name}")
            uploaded_files_count += 1
        except Exception as e:
            print(f"Failed to upload {local_path} to {blob_name}: {e}", file=sys.stderr)
            failed_upload_count += 1

    return uploaded_files_count, skipped_files_count, failed_upload_count


def _folders_needing_cleanup(
    local_by_folder: Dict[str, Set[str]],
    remote_by_folder: Dict[str, Set[str]],
) -> Set[str]:
    return {
        folder
        for folder, local_files in local_by_folder.items()
        if local_files != remote_by_folder.get(folder, set())
    }


def _delete_stale_assets(
    bucket: Any,
    prefix: str,
    local_by_folder: Dict[str, Set[str]],
    remote_by_folder: Dict[str, Set[str]],
    remote_by_rel: Dict[str, Any],
) -> Tuple[int, int]:
    deleted_files_count = 0
    failed_delete_count = 0

    for folder in sorted(_folders_needing_cleanup(local_by_folder, remote_by_folder)):
        local_files = local_by_folder.get(folder, set())
        remote_files = remote_by_folder.get(folder, set())
        stale_files = sorted(remote_files - local_files)
        for rel_path in stale_files:
            blob_name = f"{prefix}{rel_path}"
            try:
                blob = remote_by_rel.get(rel_path) or bucket.blob(blob_name)
                blob.delete()
                print(f"Deleted stale asset: {blob_name}")
                deleted_files_count += 1
            except Exception as e:
                print(f"Failed to delete stale asset {blob_name}: {e}", file=sys.stderr)
                failed_delete_count += 1

    return deleted_files_count, failed_delete_count


def run_upload(args: Namespace) -> None:
    try:
        from google.cloud import storage # type: ignore
    except ImportError:
        print("'google-cloud-storage' is not installed.", file=sys.stderr)
        sys.exit(1)

    config_path: str = getattr(args, "config", "")
    config_data = _load_config_data(config_path)
    bucket_name = _resolve_bucket_name(args, config_data)
    if not bucket_name:
        print("Please provide a bucket name using the --bucket argument or in config JSON.", file=sys.stderr)
        sys.exit(1)

    prefix = _resolve_prefix(args, config_data)

    root_dir: str = args.root_dir
    print(f"Uploading '{root_dir}' directory to GCS bucket '{bucket_name}' under prefix '{prefix}'...")

    try:
        client = _build_storage_client(storage, args, config_data)
        bucket = client.bucket(bucket_name)
    except Exception as e:
        print(f"Failed to initialize GCS client: {e}", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(root_dir):
        print(f"Directory '{root_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)

    local_paths, local_md5, local_by_folder = _scan_local_files(root_dir)
    remote_by_rel, remote_by_folder = _scan_remote_files(client, bucket_name, prefix)

    uploaded_files_count, skipped_files_count, failed_upload_count = _upload_changed_files(
        bucket=bucket,
        prefix=prefix,
        local_paths=local_paths,
        local_md5=local_md5,
        remote_by_rel=remote_by_rel,
    )
    deleted_files_count, failed_delete_count = _delete_stale_assets(
        bucket=bucket,
        prefix=prefix,
        local_by_folder=local_by_folder,
        remote_by_folder=remote_by_folder,
        remote_by_rel=remote_by_rel,
    )

    if failed_upload_count or failed_delete_count:
        print(
            "Upload finished with errors: "
            f"{uploaded_files_count} uploaded, {skipped_files_count} skipped, "
            f"{deleted_files_count} deleted, {failed_upload_count} upload failures, "
            f"{failed_delete_count} delete failures.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        f"Upload complete. {uploaded_files_count} uploaded, "
        f"{skipped_files_count} skipped (unchanged), "
        f"{deleted_files_count} stale assets deleted."
    )
