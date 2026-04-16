import os
from dataclasses import dataclass
from typing import List, Optional

from .post_entries import is_internal_post_entry


@dataclass(frozen=True)
class WorkspaceRevision:
    date: str
    entry_name: str
    revision: int
    path: str


def parse_revision(entry_name: str, workspace_name: str) -> int:
    if entry_name == workspace_name:
        return 0

    if not entry_name.startswith(workspace_name + "-"):
        raise ValueError("not a matching workspace revision")

    suffix = entry_name[len(workspace_name) + 1 :]
    return int(suffix)


def list_revisions(posts_dir: str, workspace_name: str) -> List[WorkspaceRevision]:
    if not os.path.isdir(posts_dir):
        return []

    revisions: List[WorkspaceRevision] = []
    for date_str in sorted(os.listdir(posts_dir), reverse=True):
        date_dir = os.path.join(posts_dir, date_str)
        if not os.path.isdir(date_dir):
            continue

        day_revisions: List[WorkspaceRevision] = []
        for entry_name in os.listdir(date_dir):
            if is_internal_post_entry(entry_name):
                continue
            entry_path = os.path.join(date_dir, entry_name)
            if not os.path.isdir(entry_path):
                continue

            try:
                revision = parse_revision(entry_name, workspace_name)
            except ValueError:
                continue

            day_revisions.append(
                WorkspaceRevision(
                    date=date_str,
                    entry_name=entry_name,
                    revision=revision,
                    path=entry_path,
                )
            )

        day_revisions.sort(key=lambda item: item.revision, reverse=True)
        revisions.extend(day_revisions)

    return revisions


def latest_rev(posts_dir: str, workspace_name: str) -> Optional[WorkspaceRevision]:
    revisions = list_revisions(posts_dir, workspace_name)
    if not revisions:
        return None
    return revisions[0]
