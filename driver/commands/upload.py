import os
import sys
import base64
import hashlib
from argparse import Namespace
from typing import Dict, Any, Set, Tuple

from .shared import load_config_data


def _md5_base64(file_path: str) -> str:
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            md5.update(chunk)
    return base64.b64encode(md5.digest()).decode("ascii")


def _scan_local_files(
    root_dir: str,
) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, Set[str]]]:
    local_paths: Dict[str, str] = {}
    local_md5: Dict[str, str] = {}
    local_by_folder: Dict[str, Set[str]] = {}

    for current_dir, _, files in os.walk(root_dir):
        for file in files:
            local_path = os.path.join(current_dir, file)
            relative_path = os.path.relpath(local_path, start=root_dir).replace(
                "\\", "/"
            )
            local_paths[relative_path] = local_path
            local_md5[relative_path] = _md5_base64(local_path)
            folder = os.path.dirname(relative_path).replace("\\", "/")
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
        folder = os.path.dirname(rel_path).replace("\\", "/")
        remote_by_folder.setdefault(folder, set()).add(rel_path)

    return remote_by_rel, remote_by_folder


def _upload_changed_files(
    bucket: Any,
    prefix: str,
    local_paths: Dict[str, str],
    local_md5: Dict[str, str],
    remote_by_rel: Dict[str, Any],
) -> Tuple[int, int]:
    uploaded_files_count = 0
    skipped_files_count = 0

    for rel_path in sorted(local_paths.keys()):
        local_path = local_paths[rel_path]
        blob_name = f"{prefix}{rel_path}"
        remote_blob = remote_by_rel[rel_path] if rel_path in remote_by_rel else None
        remote_md5 = remote_blob.md5_hash if remote_blob else None
        if remote_md5 and remote_md5 == local_md5[rel_path]:
            skipped_files_count += 1
            continue

        blob = bucket.blob(blob_name)
        blob.upload_from_filename(local_path)
        print(f"Uploaded: {blob_name}")
        uploaded_files_count += 1

    return uploaded_files_count, skipped_files_count


def _folders_needing_cleanup(
    local_by_folder: Dict[str, Set[str]],
    remote_by_folder: Dict[str, Set[str]],
) -> Set[str]:
    folders: Set[str] = set()
    for folder, local_files in local_by_folder.items():
        remote_files = remote_by_folder[folder] if folder in remote_by_folder else set()
        if local_files != remote_files:
            folders.add(folder)
    return folders


def _delete_stale_assets(
    bucket: Any,
    prefix: str,
    local_by_folder: Dict[str, Set[str]],
    remote_by_folder: Dict[str, Set[str]],
    remote_by_rel: Dict[str, Any],
) -> int:
    deleted_files_count = 0

    for folder in sorted(_folders_needing_cleanup(local_by_folder, remote_by_folder)):
        local_files = local_by_folder[folder] if folder in local_by_folder else set()
        remote_files = remote_by_folder[folder] if folder in remote_by_folder else set()
        stale_files = sorted(remote_files - local_files)
        for rel_path in stale_files:
            blob_name = f"{prefix}{rel_path}"
            blob = (
                remote_by_rel[rel_path]
                if rel_path in remote_by_rel
                else bucket.blob(blob_name)
            )
            blob.delete()
            print(f"Deleted stale asset: {blob_name}")
            deleted_files_count += 1

    return deleted_files_count


def run_upload(args: Namespace) -> None:
    try:
        from google.cloud import storage  # type: ignore
    except ImportError:
        print("'google-cloud-storage' is not installed.", file=sys.stderr)
        sys.exit(1)

    config_path: str = getattr(args, "config", "")
    config_data = load_config_data(config_path, warn_to_stderr=True)

    bucket_arg = getattr(args, "bucket", None)
    if bucket_arg is not None:
        bucket_name_raw = bucket_arg
    elif "bucket" in config_data:
        bucket_name_raw = config_data["bucket"]
    else:
        bucket_name_raw = None
    bucket_name = str(bucket_name_raw) if bucket_name_raw else ""
    if not bucket_name:
        print(
            "Please provide a bucket name using the --bucket argument or in config JSON.",
            file=sys.stderr,
        )
        sys.exit(1)

    prefix_raw = getattr(args, "prefix", None)
    if prefix_raw is None:
        prefix_raw = config_data["prefix"] if "prefix" in config_data else "blog/"
    prefix = str(prefix_raw) if prefix_raw else ""
    if prefix and not prefix.endswith("/"):
        prefix += "/"

    root_dir: str = args.root_dir
    print(
        f"Uploading '{root_dir}' directory to GCS bucket '{bucket_name}' under prefix '{prefix}'..."
    )

    project_arg = getattr(args, "project", None)
    if project_arg is not None:
        project_id_raw = project_arg
    elif "project" in config_data:
        project_id_raw = config_data["project"]
    else:
        project_id_raw = None
    project_id = str(project_id_raw) if project_id_raw else ""
    client = storage.Client(project=project_id) if project_id else storage.Client()
    bucket = client.bucket(bucket_name)

    if not os.path.exists(root_dir):
        print(f"Directory '{root_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)

    local_paths, local_md5, local_by_folder = _scan_local_files(root_dir)
    remote_by_rel, remote_by_folder = _scan_remote_files(client, bucket_name, prefix)

    uploaded_files_count, skipped_files_count = _upload_changed_files(
        bucket=bucket,
        prefix=prefix,
        local_paths=local_paths,
        local_md5=local_md5,
        remote_by_rel=remote_by_rel,
    )
    deleted_files_count = _delete_stale_assets(
        bucket=bucket,
        prefix=prefix,
        local_by_folder=local_by_folder,
        remote_by_folder=remote_by_folder,
        remote_by_rel=remote_by_rel,
    )

    print(
        f"Upload complete. {uploaded_files_count} uploaded, "
        f"{skipped_files_count} skipped (unchanged), "
        f"{deleted_files_count} stale assets deleted."
    )
