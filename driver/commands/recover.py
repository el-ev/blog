import json
import os
import re
import shutil
import sys
from argparse import Namespace
from typing import Any, List, Optional, Tuple

from .utils import safe_join_child, validate_workspace_name


def _find_latest_post_directory(posts_dir: str, workspace_name: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if not os.path.isdir(posts_dir):
        return None, None, None

    for date_str in sorted(os.listdir(posts_dir), reverse=True):
        date_dir = os.path.join(posts_dir, date_str)
        if not os.path.isdir(date_dir):
            continue

        revisions: List[Tuple[int, str]] = []
        for entry in os.listdir(date_dir):
            if entry == workspace_name:
                revisions.append((0, entry))
            elif entry.startswith(workspace_name + "-"):
                suffix = entry[len(workspace_name) + 1 :]
                try:
                    revisions.append((int(suffix), entry))
                except ValueError:
                    continue

        if revisions:
            revisions.sort(key=lambda x: x[0], reverse=True)
            latest_dir_name = revisions[0][1]
            latest_dir_path = os.path.join(date_dir, latest_dir_name)
            return date_str, latest_dir_name, latest_dir_path

    return None, None, None


def _is_generated_source_artifact(filename: str) -> bool:
    if filename == "index.html":
        return True
    return bool(re.match(r"^page\d+(?:\.[^.]+)?\.svg$", filename))


def _recover_from_manifest(source_dir: str, workspace_path: str, manifest_path: str) -> int:
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest: Any = json.load(f)
    except Exception as e:
        raise RuntimeError(f"Failed to read manifest: {e}") from e

    manifest_files = manifest.get("files")
    if not isinstance(manifest_files, list):
        raise RuntimeError("Manifest is invalid: 'files' must be a list.")

    copied_count = 0
    for rel_path in manifest_files:
        if not isinstance(rel_path, str) or not rel_path:
            continue
        try:
            src_path = safe_join_child(source_dir, rel_path)
            dst_path = safe_join_child(workspace_path, rel_path)
        except ValueError:
            continue
        if not os.path.isfile(src_path):
            continue
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        shutil.copy2(src_path, dst_path)
        copied_count += 1
    return copied_count


def _recover_without_manifest(source_dir: str, workspace_path: str) -> int:
    copied_count = 0
    for current_dir, _, files in os.walk(source_dir):
        for filename in files:
            if filename == ".workspace-manifest.json":
                continue
            if _is_generated_source_artifact(filename):
                continue

            src_path = os.path.join(current_dir, filename)
            rel_path = os.path.relpath(src_path, start=source_dir).replace("\\", "/")
            dst_path = safe_join_child(workspace_path, rel_path)
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            shutil.copy2(src_path, dst_path)
            copied_count += 1
    return copied_count


def run_recover(args: Namespace) -> None:
    try:
        workspace_name = validate_workspace_name(args.name[0])
    except ValueError as e:
        print(f"Invalid workspace name: {e}", file=sys.stderr)
        sys.exit(1)

    posts_dir = os.path.join(args.root_dir, "posts")
    recovered_date, recovered_dir_name, post_dir = _find_latest_post_directory(posts_dir, workspace_name)
    if not post_dir:
        print(f"No post revision found in '{posts_dir}' for workspace '{workspace_name}'.", file=sys.stderr)
        sys.exit(1)

    source_dir = os.path.join(post_dir, "source")
    if not os.path.isdir(source_dir):
        print(f"Cannot recover workspace: '{source_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(args.workspace_base, exist_ok=True)
    workspace_path = safe_join_child(args.workspace_base, workspace_name)

    if os.path.exists(workspace_path):
        if not getattr(args, "force", False):
            print(
                f"Workspace '{workspace_name}' already exists at '{workspace_path}'. "
                "Use --force to overwrite.",
                file=sys.stderr,
            )
            sys.exit(1)
        shutil.rmtree(workspace_path)

    os.makedirs(workspace_path, exist_ok=True)

    manifest_path = os.path.join(source_dir, ".workspace-manifest.json")
    if os.path.isfile(manifest_path):
        try:
            copied_count = _recover_from_manifest(source_dir, workspace_path, manifest_path)
        except RuntimeError as e:
            print(
                f"Manifest recovery failed ({e}). Falling back to heuristic recovery.",
                file=sys.stderr,
            )
            copied_count = _recover_without_manifest(source_dir, workspace_path)
    else:
        copied_count = _recover_without_manifest(source_dir, workspace_path)

    if copied_count == 0:
        print(
            f"No recoverable source files were found for '{workspace_name}' in '{source_dir}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        f"Recovered workspace '{workspace_name}' at '{workspace_path}' "
        f"from revision '{recovered_date}/{recovered_dir_name}'."
    )
