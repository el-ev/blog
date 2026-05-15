from concurrent.futures import Future, ThreadPoolExecutor, as_completed
import json
import os
import shutil
import sys
from argparse import Namespace
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .compile import run_compile
from .content import update_content
from .shared import (
    build_asset_ctx,
    driver_dir,
    page_url,
    refresh_glyphs,
    resolve_base_url,
)
from .revisions import latest_rev
from .submission_flow import (
    published_workspaces,
    resolve_submit_dest,
)
from .submission_meta import (
    MetaFieldsRequest,
    MetaPageRequest,
    build_meta_fields,
    compile_meta_page,
    extract_post_pdf_name,
)
from .submission_workspace import (
    collect_files,
    load_manifest,
    resolve_post_meta,
    stage_workspace,
    sync_snapshot,
    write_manifest,
)
from .utils import (
    decl_str_from_source,
    first_desc,
    need_decl_str_from_source,
    make_temp_dir,
    minify_html,
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

    post_json: Dict[str, Any] = {}
    manifest: Dict[str, Any] = {}
    if amend_mode and os.path.isdir(dest_dir):
        _post_json_path = os.path.join(dest_dir, "post.json")
        if os.path.isfile(_post_json_path):
            with open(_post_json_path, "r", encoding="utf-8") as _f:
                post_json = json.load(_f)
        manifest = load_manifest(os.path.join(dest_dir, "source"))

    stage_path, temp_root = stage_workspace(
        workspace_path, dest_dir, args.build_base
    )
    backup_root: Optional[str] = None
    backup_dir: Optional[str] = None
    try:
        workspace_files = collect_files(stage_path)
        backup_root, backup_dir = _backup_existing_destination(
            build_base=args.build_base,
            dest_dir=dest_dir,
            dest_dir_name=dest_dir_name,
        )

        compile_args = Namespace(**vars(args))
        compile_args.name = workspace_name
        compile_args.amend = amend_mode
        compile_args.workspace_path_override = stage_path
        compile_args.publish_date_override = date_str
        compile_args.shared_glyphs = False
        compile_args.output_dir_override = dest_assets_dir
        compile_args.html_output_dir_override = dest_dir
        compile_args.public_output_dir_override = dest_dir
        run_compile(compile_args)

        base_dir = driver_dir()
        asset_context = build_asset_ctx(base_dir, args.root_dir)

        source_dest_dir = os.path.join(dest_dir, "source")
        sync_snapshot(stage_path, source_dest_dir)

        main_typ_path = os.path.join(stage_path, "main.typ")
        with open(main_typ_path, "r", encoding="utf-8") as f:
            main_typ_source = f.read()
        post_title = need_decl_str_from_source(main_typ_source, "title")
        post_subtitle = decl_str_from_source(main_typ_source, "subtitle")
        pdf_name, post_asset_hash = extract_post_pdf_name(dest_dir)

        meta_generated_at: Optional[str] = None
        if amend_mode and post_json.get("source_hash") == post_asset_hash:
            meta_generated_at = post_json.get("generated_at")

        meta_fields = build_meta_fields(
            MetaFieldsRequest(
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
        )
        base_url = resolve_base_url(args)
        meta_og_url = page_url(
            base_url=base_url,
            root_dir=args.root_dir,
            dest_dir=dest_dir,
            html_filename="meta.html",
        )
        compile_meta_page(
            MetaPageRequest(
                build_base=args.build_base,
                base_dir=base_dir,
                dest_dir=dest_dir,
                asset_dir=dest_assets_dir,
                post_title=post_title,
                meta_fields=meta_fields,
                workspace_files=workspace_files,
                asset_context=asset_context,
                og_url=meta_og_url,
                site_base_url=base_url,
            )
        )

        index_html_path = os.path.join(dest_dir, "index.html")
        with open(index_html_path, "r", encoding="utf-8") as _f:
            index_html = _f.read()
        description = first_desc(
            index_html,
            post_title,
            skip_texts=[post_subtitle] if post_subtitle else None,
        )
        with open(os.path.join(dest_dir, "post.json"), "w", encoding="utf-8") as _f:
            json.dump(
                {
                    "title": post_title,
                    "subtitle": post_subtitle,
                    "description": description,
                    "source_hash": post_asset_hash,
                    "generated_at": meta_fields["Generated At"],
                },
                _f,
                ensure_ascii=False,
                indent=2,
            )

        write_manifest(
            manifest_path=os.path.join(source_dest_dir, ".workspace-manifest.json"),
            workspace_name=workspace_name,
            publish_date=date_str,
            revision_name=dest_dir_name,
            files=workspace_files,
            generated_at=manifest["generated_at"] if amend_mode else None,
        )

        if refresh_assets:
            refresh_glyphs(
                root_dir=args.root_dir,
                target_dirs=[dest_dir, dest_assets_dir, source_dest_dir],
            )

        for _html_name in os.listdir(dest_dir):
            if _html_name.endswith(".html"):
                minify_html(os.path.join(dest_dir, _html_name))
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

    date_str, dest_dir_name, target_rev, did_amend = resolve_submit_dest(
            posts_dir=posts_dir,
            workspace_name=workspace_name,
            amend_mode=amend_mode,
            today_str=today_str,
        )

    _submit_to_destination(
        args=args,
        workspace_name=workspace_name,
        workspace_path=workspace_path,
        date_str=date_str,
        dest_dir_name=dest_dir_name,
        target_rev=target_rev,
        amend_mode=did_amend,
    )

    if did_amend:
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
    latest = latest_rev(posts_dir, workspace_name)
    if latest is None:
        raise FileNotFoundError(f"No revisions found for workspace '{workspace_name}'.")
    date_str, dest_dir_name, target_rev = (
        latest.date,
        latest.entry_name,
        latest.revision,
    )
    post_dir = os.path.join(posts_dir, date_str, dest_dir_name)
    source_dir = os.path.join(post_dir, "source")
    if not os.path.isdir(source_dir):
        print(
            f"Skipping '{workspace_name}': '{source_dir}' does not exist.",
            file=sys.stderr,
        )
        return None

    _, publish_date, revision = resolve_post_meta(
        post_dir=post_dir,
        entry_name=dest_dir_name,
    )
    workspace_path = safe_join_child(args.workspace_base, workspace_name)
    if not os.path.isdir(workspace_path):
        workspace_path = source_dir
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
    workspaces = published_workspaces(posts_dir)
    if not workspaces:
        print(f"No published workspaces found in '{posts_dir}'.")
        return 0

    amended_count = 0
    glyph_target_dirs: List[str] = []
    max_workers = min(len(workspaces), max(1, os.cpu_count() or 1))
    future_map: Dict[Future[Optional[Tuple[str, str, str]]], str] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for workspace_name in workspaces:
            future = executor.submit(
                _amend_latest_workspace,
                args,
                posts_dir,
                workspace_name,
            )
            future_map[future] = workspace_name

        try:
            for future in as_completed(future_map):
                result = future.result()
                if result is None:
                    continue

                workspace_name, post_dir, source_dir = result
                amended_count += 1
                glyph_target_dirs.extend([post_dir, source_dir])
                print(f"Amended '{workspace_name}' in '{post_dir}'")
        except Exception:
            for pending_future in future_map:
                pending_future.cancel()
            raise

    if refresh_content:
        update_content(args)
    elif glyph_target_dirs:
        refresh_glyphs(
            root_dir=args.root_dir,
            target_dirs=glyph_target_dirs,
        )
    print(f"Amended {amended_count} published workspace(s).")
    return amended_count
