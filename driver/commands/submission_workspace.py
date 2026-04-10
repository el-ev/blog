import json
import os
import shutil
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from .revisions import parse_workspace_revision_entry
from .utils import safe_join_child, validate_workspace_name

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
    workspace_path: str, dest_dir: str
) -> Tuple[str, Optional[str]]:
    tracked_files = manifest_source_files(workspace_path)
    if tracked_files:
        temp_root = tempfile.mkdtemp(prefix=".amend-workspace-", dir=os.getcwd())
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

    temp_root = tempfile.mkdtemp(prefix=".amend-workspace-", dir=os.getcwd())
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
