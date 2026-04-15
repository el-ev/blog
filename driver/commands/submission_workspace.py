import json
import os
import shutil
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from .revisions import parse_workspace_revision_entry
from .utils import make_temp_dir, safe_join_child, validate_workspace_name

_GENERATED_SOURCE_BUNDLE_FILES = {
    ".workspace-manifest.json",
}


def normalize_relative_paths(paths: List[str]) -> List[str]:
    normalized_paths: List[str] = []
    seen: Set[str] = set()
    for raw_path in paths:
        normalized = str(raw_path).replace("\\", "/").strip()
        if not normalized or normalized == ".":
            continue
        if (
            normalized.startswith("/")
            or normalized.startswith("../")
            or "/../" in normalized
        ):
            continue
        if normalized.startswith("./"):
            normalized = normalized[2:]
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        normalized_paths.append(normalized)
    normalized_paths.sort()
    return normalized_paths


def load_manifest_data(source_dir: str) -> Dict[str, Any]:
    manifest_path = os.path.join(source_dir, ".workspace-manifest.json")
    if not os.path.isfile(manifest_path):
        return {}
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def manifest_source_files(source_dir: str) -> List[str]:
    manifest_data = load_manifest_data(source_dir)
    if not manifest_data:
        return []

    raw_files = manifest_data["files"]
    return [
        path
        for path in normalize_relative_paths(raw_files)
        if path not in _GENERATED_SOURCE_BUNDLE_FILES
    ]


def collect_relative_files(base_dir: str) -> List[str]:
    file_paths: List[str] = []
    for root, _, files in os.walk(base_dir):
        for filename in files:
            abs_path = os.path.join(root, filename)
            rel_path = os.path.relpath(abs_path, start=base_dir).replace("\\", "/")
            file_paths.append(rel_path)
    return normalize_relative_paths(file_paths)


def _collect_relative_directories(base_dir: str) -> List[str]:
    directories: List[str] = []
    for root, dirs, _ in os.walk(base_dir):
        rel_root = os.path.relpath(root, start=base_dir).replace("\\", "/")
        if rel_root == ".":
            rel_root = ""
        directories.append(rel_root)
        for directory in dirs:
            rel_dir = os.path.join(rel_root, directory).replace("\\", "/")
            directories.append(rel_dir)
    normalized = normalize_relative_paths(directories)
    return [""] + normalized


def sync_snapshot_from_workspace(workspace_path: str, source_dest_dir: str) -> None:
    workspace_files = collect_relative_files(workspace_path)
    os.makedirs(source_dest_dir, exist_ok=True)

    workspace_file_set = set(workspace_files)
    existing_source_files = collect_relative_files(source_dest_dir)
    for rel_path in existing_source_files:
        if rel_path in workspace_file_set:
            continue
        stale_path = safe_join_child(source_dest_dir, rel_path)
        os.remove(stale_path)

    for rel_path in workspace_files:
        src_path = safe_join_child(workspace_path, rel_path)
        dst_path = safe_join_child(source_dest_dir, rel_path)
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        shutil.copy2(src_path, dst_path)

    for root, _, _ in os.walk(source_dest_dir, topdown=False):
        if root == source_dest_dir:
            continue
        try:
            os.rmdir(root)
        except OSError:
            continue

    workspace_dirs = _collect_relative_directories(workspace_path)
    for rel_dir in workspace_dirs:
        src_dir = (
            workspace_path if rel_dir == "" else safe_join_child(workspace_path, rel_dir)
        )
        dst_dir = (
            source_dest_dir
            if rel_dir == ""
            else safe_join_child(source_dest_dir, rel_dir)
        )
        os.makedirs(dst_dir, exist_ok=True)
        shutil.copystat(src_dir, dst_dir)


def write_workspace_manifest(
    manifest_path: str,
    workspace_name: str,
    publish_date: str,
    revision_name: str,
    files: List[str],
    generated_at: Optional[str] = None,
) -> None:
    manifest_generated_at = generated_at or datetime.now().isoformat(timespec="seconds")
    payload: Dict[str, Any] = {
        "workspace": workspace_name,
        "publish_date": publish_date,
        "revision": revision_name,
        "files": files,
        "generated_at": manifest_generated_at,
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


def stage_workspace_if_needed(
    workspace_path: str, dest_dir: str, build_base: str
) -> Tuple[str, Optional[str]]:
    tracked_files = manifest_source_files(workspace_path)
    if tracked_files:
        temp_root = make_temp_dir(build_base, prefix=".amend-workspace-")
        staged_path = os.path.join(
            temp_root, os.path.basename(os.path.abspath(workspace_path))
        )
        os.makedirs(staged_path, exist_ok=True)

        copied_any = False
        for rel_path in tracked_files:
            src_path = safe_join_child(workspace_path, rel_path)
            if not os.path.isfile(src_path):
                continue
            dst_path = safe_join_child(staged_path, rel_path)
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            shutil.copy2(src_path, dst_path)
            copied_any = True

        if copied_any:
            return staged_path, temp_root

        shutil.rmtree(temp_root, ignore_errors=True)

    workspace_abs = os.path.abspath(workspace_path)
    dest_abs = os.path.abspath(dest_dir)
    try:
        if os.path.commonpath([workspace_abs, dest_abs]) != dest_abs:
            return workspace_path, None
    except ValueError:
        return workspace_path, None

    temp_root = make_temp_dir(build_base, prefix=".amend-workspace-")
    staged_path = os.path.join(temp_root, os.path.basename(workspace_abs))
    shutil.copytree(workspace_abs, staged_path)
    return staged_path, temp_root


def resolve_existing_post_metadata(
    post_dir: str,
    date_str: str,
    entry_name: str,
) -> Tuple[str, str, int]:
    source_dir = os.path.join(post_dir, "source")
    manifest_data = load_manifest_data(source_dir)
    if not manifest_data:
        raise FileNotFoundError(f"Missing source manifest in '{source_dir}'.")

    try:
        workspace_name_raw = manifest_data["workspace"]
        publish_date_raw = manifest_data["publish_date"]
    except KeyError as exc:
        raise KeyError(
            f"Manifest in '{source_dir}' is missing required key: {exc.args[0]}"
        ) from exc

    workspace_name = validate_workspace_name(str(workspace_name_raw))
    publish_date = str(publish_date_raw)
    revision = parse_workspace_revision_entry(entry_name, workspace_name)

    return workspace_name, publish_date, revision
