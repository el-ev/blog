import os
import shutil
import sys
from argparse import Namespace
from typing import List, Optional, Tuple

from .revisions import latest_rev
from .submission_workspace import load_manifest
from .utils import safe_join_child


def _find_latest_post_directory(
    posts_dir: str, workspace_name: str
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    latest = latest_rev(posts_dir, workspace_name)
    if latest is None:
        return None, None, None
    return latest.date, latest.entry_name, latest.path


def _recover_from_manifest(source_dir: str, workspace_path: str) -> int:
    manifest_files: List[str] = load_manifest(source_dir)["files"]

    copied_count = 0
    for rel_path in manifest_files:
        src_path = safe_join_child(source_dir, rel_path)
        dst_path = safe_join_child(workspace_path, rel_path)
        if not os.path.isfile(src_path):
            continue
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        shutil.copy2(src_path, dst_path)
        copied_count += 1
    return copied_count


def run_recover(args: Namespace) -> None:
    workspace_name: str = args.name

    posts_dir = os.path.join(args.root_dir, "posts")
    recovered_date, recovered_name, post_dir = _find_latest_post_directory(
        posts_dir, workspace_name
    )
    if not post_dir:
        print(
            f"No post revision found in '{posts_dir}' for workspace '{workspace_name}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    source_dir = os.path.join(post_dir, "source")
    if not os.path.isdir(source_dir):
        print(
            f"Cannot recover workspace: '{source_dir}' does not exist.", file=sys.stderr
        )
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
    if not os.path.isfile(manifest_path):
        print(
            f"Cannot recover workspace: '{manifest_path}' does not exist.",
            file=sys.stderr,
        )
        sys.exit(1)

    copied_count = _recover_from_manifest(source_dir, workspace_path)

    if copied_count == 0:
        print(
            f"No recoverable source files were found for '{workspace_name}' in '{source_dir}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        f"Recovered workspace '{workspace_name}' at '{workspace_path}' "
        f"from revision '{recovered_date}/{recovered_name}'."
    )
