import os
import sys
from typing import List, Set, Tuple

from .post_entries import is_internal_post_entry
from .revisions import find_latest_workspace_revision, parse_workspace_revision_entry
from .submission_workspace import resolve_existing_post_metadata

def find_latest_revision_entry(
    posts_dir: str, workspace_name: str
) -> Tuple[str, str, int]:
    latest = find_latest_workspace_revision(posts_dir, workspace_name)
    if latest is None:
        raise FileNotFoundError(f"No revisions found for workspace '{workspace_name}'.")
    return latest.date, latest.entry_name, latest.revision


def resolve_new_revision_name(date_dir: str, workspace_name: str) -> Tuple[int, str]:
    os.makedirs(date_dir, exist_ok=True)

    existing_dirs: List[int] = []
    for entry_name in os.listdir(date_dir):
        if is_internal_post_entry(entry_name):
            continue
        try:
            existing_dirs.append(
                parse_workspace_revision_entry(entry_name, workspace_name)
            )
        except ValueError:
            continue

    max_rev = max(existing_dirs) if existing_dirs else -1
    target_rev = max_rev + 1
    if target_rev == 0:
        return target_rev, workspace_name
    return target_rev, f"{workspace_name}-{target_rev}"


def resolve_submission_destination(
    posts_dir: str,
    workspace_name: str,
    amend_mode: bool,
    today_str: str,
) -> Tuple[str, str, int, bool]:
    if amend_mode:
        try:
            date_str, dest_dir_name, target_rev = find_latest_revision_entry(
                posts_dir,
                workspace_name,
            )
            return date_str, dest_dir_name, target_rev, True
        except FileNotFoundError:
            print(
                f"No existing revision found for '{workspace_name}'. "
                "Creating a new revision instead of amending."
            )
            return today_str, workspace_name, 0, False

    date_str = today_str
    date_dir = os.path.join(posts_dir, date_str)
    target_rev, dest_dir_name = resolve_new_revision_name(date_dir, workspace_name)
    return date_str, dest_dir_name, target_rev, False


def collect_published_workspaces(posts_dir: str) -> List[str]:
    workspaces: Set[str] = set()
    if not os.path.isdir(posts_dir):
        return []

    for date_str in os.listdir(posts_dir):
        date_dir = os.path.join(posts_dir, date_str)
        if not os.path.isdir(date_dir):
            continue
        for entry_name in os.listdir(date_dir):
            if is_internal_post_entry(entry_name):
                continue
            post_dir = os.path.join(date_dir, entry_name)
            if not os.path.isdir(post_dir):
                continue

            source_dir = os.path.join(post_dir, "source")
            if not os.path.isdir(source_dir):
                print(
                    f"Skipping '{post_dir}': missing source snapshot.",
                    file=sys.stderr,
                )
                continue

            manifest_path = os.path.join(source_dir, ".workspace-manifest.json")
            if not os.path.isfile(manifest_path):
                print(
                    f"Skipping '{post_dir}': missing workspace manifest.",
                    file=sys.stderr,
                )
                continue

            try:
                workspace_name, _, _ = resolve_existing_post_metadata(
                    post_dir=post_dir,
                    date_str=date_str,
                    entry_name=entry_name,
                )
            except (FileNotFoundError, KeyError, ValueError) as exc:
                print(
                    f"Skipping '{post_dir}': {exc}",
                    file=sys.stderr,
                )
                continue
            workspaces.add(workspace_name)

    return sorted(workspaces)
