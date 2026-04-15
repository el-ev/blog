from concurrent.futures import Future, ThreadPoolExecutor, as_completed
import os
import shutil
import sys
from argparse import Namespace
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .compile import run_compile
from .content import update_content
from .shared import (
    build_driver_asset_context,
    build_public_page_url,
    refresh_glyph_assets,
    resolve_base_url,
)
from .submission_flow import (
    collect_published_workspaces,
    find_latest_revision_entry,
    resolve_submission_destination,
)
from .submission_meta import (
    build_meta_fields,
    compile_meta_page,
    extract_post_pdf_name,
    load_meta_fields,
)
from .submission_workspace import (
    collect_relative_files,
    load_manifest_data,
    resolve_existing_post_metadata,
    sync_snapshot_from_workspace,
    stage_workspace_if_needed,
    write_workspace_manifest,
)
from .utils import (
    extract_declared_typst_string,
    extract_required_declared_typst_string,
    make_temp_dir,
    minify_html_file,
    safe_join_child,
)


def _backup_existing_destination(
    build_base: str,
    dest_dir: str,
    dest_dir_name: str,
) -> Tuple[Optional[str], Optional[str]]:
    if not os.path.isdir(dest_dir):
        return None, None

    backup_root = make_temp_dir(build_base, prefix=".submit-backup-")
    backup_dir = os.path.join(backup_root, dest_dir_name)
    os.replace(dest_dir, backup_dir)
    return backup_root, backup_dir


def _restore_destination_backup(dest_dir: str, backup_dir: Optional[str]) -> None:
    if backup_dir is None or not os.path.isdir(backup_dir):
        return

    if os.path.isdir(dest_dir):
        shutil.rmtree(dest_dir, ignore_errors=True)
    os.replace(backup_dir, dest_dir)


def _resolve_amend_workspace_path(args: Namespace, workspace_name: str, source_dir: str) -> str:
    workspace_path = safe_join_child(args.workspace_base, workspace_name)
    if os.path.isdir(workspace_path):
        return workspace_path
    return source_dir


def _submit_to_destination(
    args: Namespace,
    workspace_name: str,
    workspace_path: str,
    date_str: str,
    dest_dir_name: str,
    target_rev: int,
    amend_mode: bool,
    refresh_assets: bool = True,
) -> None:
    posts_dir = os.path.join(args.root_dir, "posts")
    dest_base_dir = os.path.join(posts_dir, date_str)
    os.makedirs(dest_base_dir, exist_ok=True)
    dest_dir = os.path.join(dest_base_dir, dest_dir_name)
    dest_assets_dir = os.path.join(dest_dir, "assets")

    existing_meta_fields: Dict[str, str] = {}
    existing_manifest_data: Dict[str, Any] = {}
    if amend_mode and os.path.isdir(dest_dir):
        existing_meta_fields = load_meta_fields(dest_dir)
        existing_manifest_data = load_manifest_data(os.path.join(dest_dir, "source"))

    staged_workspace_path, temp_root = stage_workspace_if_needed(
        workspace_path, dest_dir, args.build_base
    )
    backup_root: Optional[str] = None
    backup_dir: Optional[str] = None
    try:
        workspace_files = collect_relative_files(staged_workspace_path)
        backup_root, backup_dir = _backup_existing_destination(
            build_base=args.build_base,
            dest_dir=dest_dir,
            dest_dir_name=dest_dir_name,
        )

        compile_args = Namespace(**vars(args))
        compile_args.name = workspace_name
        compile_args.amend = amend_mode
        compile_args.workspace_path_override = staged_workspace_path
        compile_args.publish_date_override = date_str
        compile_args.enable_shared_glyph_extraction = False
        compile_args.output_dir_override = dest_assets_dir
        compile_args.html_output_dir_override = dest_dir
        compile_args.public_output_dir_override = dest_dir
        run_compile(compile_args)

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        asset_context = build_driver_asset_context(base_dir, args.root_dir)

        source_dest_dir = os.path.join(dest_dir, "source")
        sync_snapshot_from_workspace(staged_workspace_path, source_dest_dir)

        main_typ_path = os.path.join(staged_workspace_path, "main.typ")
        post_title = extract_required_declared_typst_string(main_typ_path, "title")
        post_subtitle = extract_declared_typst_string(main_typ_path, "subtitle")
        pdf_name, post_asset_hash = extract_post_pdf_name(dest_dir)

        meta_generated_at: Optional[str] = None
        if amend_mode:
            previous_source_hash = existing_meta_fields["Source Hash"]
            previous_generated_at = existing_meta_fields["Generated At"]
            if previous_source_hash == post_asset_hash:
                meta_generated_at = previous_generated_at

        meta_fields = build_meta_fields(
            workspace_name=workspace_name,
            date_str=date_str,
            target_rev=target_rev,
            dest_dir_name=dest_dir_name,
            post_title=post_title,
            post_subtitle=post_subtitle,
            pdf_name=pdf_name,
            post_source_hash=post_asset_hash,
            workspace_files=workspace_files,
            generated_at=meta_generated_at,
        )
        base_url = resolve_base_url(args)
        meta_og_url = build_public_page_url(
            base_url=base_url,
            root_dir=args.root_dir,
            dest_dir=dest_dir,
            html_filename="meta.html",
        )
        compile_meta_page(
            build_base=args.build_base,
            base_dir=base_dir,
            stylesheet_asset_path=asset_context.web_assets.stylesheet_path,
            clipboard_asset_path=asset_context.web_assets.clipboard_script_path,
            theme_asset_path=asset_context.web_assets.theme_script_path,
            inline_style=asset_context.web_assets.inline_style,
            inline_script=asset_context.web_assets.inline_script,
            dest_dir=dest_dir,
            asset_dir=dest_assets_dir,
            post_title=post_title,
            meta_fields=meta_fields,
            workspace_files=workspace_files,
            global_glyph_asset_path=asset_context.global_glyph_asset_path,
            global_glyph_map_path=asset_context.global_glyph_map_path,
            rss_feed_path=os.path.join(args.root_dir, "rss.xml"),
            og_url=meta_og_url,
            site_base_url=base_url,
        )

        write_workspace_manifest(
            manifest_path=os.path.join(source_dest_dir, ".workspace-manifest.json"),
            workspace_name=workspace_name,
            publish_date=date_str,
            revision_name=dest_dir_name,
            files=workspace_files,
            generated_at=existing_manifest_data["generated_at"] if amend_mode else None,
        )

        if refresh_assets:
            refresh_glyph_assets(
                root_dir=args.root_dir,
                target_dirs=[dest_dir, dest_assets_dir, source_dest_dir],
            )

        for _html_name in os.listdir(dest_dir):
            if _html_name.endswith(".html"):
                minify_html_file(os.path.join(dest_dir, _html_name))
    except Exception:
        _restore_destination_backup(dest_dir, backup_dir)
        raise
    finally:
        if backup_root is not None:
            shutil.rmtree(backup_root, ignore_errors=True)
        if temp_root is not None:
            shutil.rmtree(temp_root, ignore_errors=True)


def run_submit(args: Namespace) -> None:
    workspace_name: str = args.name
    workspace_path = safe_join_child(args.workspace_base, workspace_name)
    posts_dir = os.path.join(args.root_dir, "posts")
    today_str = datetime.now().strftime("%Y-%m-%d")
    amend_mode = getattr(args, "amend", False)

    date_str, dest_dir_name, target_rev, did_amend_existing = (
        resolve_submission_destination(
            posts_dir=posts_dir,
            workspace_name=workspace_name,
            amend_mode=amend_mode,
            today_str=today_str,
        )
    )

    _submit_to_destination(
        args=args,
        workspace_name=workspace_name,
        workspace_path=workspace_path,
        date_str=date_str,
        dest_dir_name=dest_dir_name,
        target_rev=target_rev,
        amend_mode=did_amend_existing,
    )

    if did_amend_existing:
        print(
            f"Amended '{workspace_name}' in '{os.path.join(posts_dir, date_str, dest_dir_name)}'"
        )
    else:
        print(
            f"Submitted '{workspace_name}' to '{os.path.join(posts_dir, date_str, dest_dir_name)}'"
        )

    update_content(args)


def _amend_latest_workspace(
    args: Namespace,
    posts_dir: str,
    workspace_name: str,
) -> Optional[Tuple[str, str, str]]:
    date_str, dest_dir_name, target_rev = find_latest_revision_entry(
        posts_dir,
        workspace_name,
    )
    post_dir = os.path.join(posts_dir, date_str, dest_dir_name)
    source_dir = os.path.join(post_dir, "source")
    if not os.path.isdir(source_dir):
        print(
            f"Skipping '{workspace_name}': '{source_dir}' does not exist.",
            file=sys.stderr,
        )
        return None

    _, publish_date, revision = resolve_existing_post_metadata(
        post_dir=post_dir,
        date_str=date_str,
        entry_name=dest_dir_name,
    )
    workspace_path = _resolve_amend_workspace_path(args, workspace_name, source_dir)
    _submit_to_destination(
        args=args,
        workspace_name=workspace_name,
        workspace_path=workspace_path,
        date_str=publish_date,
        dest_dir_name=dest_dir_name,
        target_rev=revision if revision == target_rev else target_rev,
        amend_mode=True,
        refresh_assets=False,
    )
    return workspace_name, post_dir, source_dir


def run_amend_all(args: Namespace, refresh_content: bool = True) -> int:
    posts_dir = os.path.join(args.root_dir, "posts")
    workspaces = collect_published_workspaces(posts_dir)
    if not workspaces:
        print(f"No published workspaces found in '{posts_dir}'.")
        return 0

    amended_count = 0
    glyph_target_dirs: List[str] = []
    max_workers = min(len(workspaces), max(1, os.cpu_count() or 1))
    future_to_workspace: Dict[Future[Optional[Tuple[str, str, str]]], str] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for workspace_name in workspaces:
            future = executor.submit(
                _amend_latest_workspace,
                args,
                posts_dir,
                workspace_name,
            )
            future_to_workspace[future] = workspace_name

        try:
            for future in as_completed(future_to_workspace):
                result = future.result()
                if result is None:
                    continue

                workspace_name, post_dir, source_dir = result
                amended_count += 1
                glyph_target_dirs.extend([post_dir, source_dir])
                print(f"Amended '{workspace_name}' in '{post_dir}'")
        except Exception:
            for pending_future in future_to_workspace:
                pending_future.cancel()
            raise

    if refresh_content:
        update_content(args)
    elif glyph_target_dirs:
        refresh_glyph_assets(
            root_dir=args.root_dir,
            target_dirs=glyph_target_dirs,
        )
    print(f"Amended {amended_count} published workspace(s).")
    return amended_count
