import os
import shutil
import sys
import tempfile
from argparse import Namespace
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .compile_hidden_text import (
    build_final_hidden_text,
    build_hidden_text,
    replace_hidden_block,
)
from .shared import build_driver_asset_context
from .utils import (
    WORKSPACE_PUBLIC_DIR_NAME,
    build_raw_copy_assets,
    compile_and_build_html,
    extract_declared_typst_string,
    extract_typst_headings_from_content,
    extract_typst_links,
    extract_typst_raws_from_content,
    extract_typst_tables_from_content,
    find_latest_revision,
    reset_directory,
    safe_join_child,
    sources_hash,
)


def _copy_workspace_public_files(workspace_path: str, output_dir: str) -> int:
    public_dir = os.path.join(workspace_path, WORKSPACE_PUBLIC_DIR_NAME)
    if not os.path.isdir(public_dir):
        return 0

    copied_count = 0
    for current_dir, _, files in os.walk(public_dir):
        rel_dir = os.path.relpath(current_dir, start=public_dir).replace("\\", "/")
        for filename in files:
            src_path = os.path.join(current_dir, filename)
            rel_file = filename if rel_dir == "." else f"{rel_dir}/{filename}"
            dst_path = safe_join_child(output_dir, rel_file)

            if os.path.exists(dst_path):
                print(
                    f"Skipping '{WORKSPACE_PUBLIC_DIR_NAME}/{rel_file}' because "
                    "it would overwrite a generated output file.",
                    file=sys.stderr,
                )
                continue

            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            shutil.copy2(src_path, dst_path)
            copied_count += 1

    return copied_count


def _build_typst_inputs(
    last_revision_date: Optional[str],
    last_revision_url: Optional[str],
    edited_date: Optional[str] = None,
    publish_date: Optional[str] = None,
) -> Tuple[Dict[str, str], Dict[str, str]]:
    input_values_svg: Dict[str, str] = {"with_driver": "true", "export_format": "svg"}
    input_values_pdf: Dict[str, str] = {"with_driver": "true", "export_format": "pdf"}
    if publish_date:
        input_values_svg["publish_date"] = publish_date
        input_values_pdf["publish_date"] = publish_date
    if edited_date:
        input_values_svg["edited_date"] = edited_date
        input_values_pdf["edited_date"] = edited_date
    if last_revision_date and last_revision_url:
        input_values_svg["last_revision_date"] = last_revision_date
        input_values_svg["last_revision_url"] = last_revision_url
        input_values_pdf["last_revision_date"] = last_revision_date
        input_values_pdf["last_revision_url"] = last_revision_url
    return input_values_svg, input_values_pdf


def _workspace_latest_modified_date(workspace_path: str) -> str:
    latest_mtime: Optional[float] = None
    for root, _, files in os.walk(workspace_path):
        for filename in files:
            file_path = os.path.join(root, filename)
            mtime = os.path.getmtime(file_path)
            if latest_mtime is None or mtime > latest_mtime:
                latest_mtime = mtime

    if latest_mtime is None:
        raise RuntimeError(
            f"Workspace '{workspace_path}' does not contain any files."
        )

    return datetime.fromtimestamp(latest_mtime).strftime("%Y-%m-%d")


def _prepare_compile_sources(
    base_dir: str, workspace_path: str
) -> Tuple[bytes, str, str]:
    driver_typ_path = os.path.join(base_dir, "driver.typ")
    template_typ_path = os.path.join(base_dir, "template.typ")

    with open(driver_typ_path, "r", encoding="utf-8") as f:
        driver_source = f.read()

    main_typ_abs_path = os.path.abspath(os.path.join(workspace_path, "main.typ"))
    main_typ_path = os.path.relpath(main_typ_abs_path, start=os.getcwd()).replace(
        "\\", "/"
    )
    asset_hash = sources_hash([workspace_path, driver_typ_path, template_typ_path])
    driver_source = driver_source.replace(
        "// IMPORT_MAIN", f'#import "{main_typ_path}": *'
    )
    return driver_source.encode(), main_typ_abs_path, asset_hash


def _stage_workspace_for_compile(
    workspace_path: str, repo_root: str
) -> Tuple[str, str]:
    workspace_abs = os.path.abspath(workspace_path)
    repo_abs = os.path.abspath(repo_root)
    try:
        if os.path.commonpath([repo_abs, workspace_abs]) == repo_abs:
            return workspace_abs, ""
    except ValueError:
        pass

    temp_root = tempfile.mkdtemp(prefix=".compile-workspace-", dir=repo_abs)
    staged_path = os.path.join(temp_root, os.path.basename(workspace_abs))
    shutil.copytree(workspace_abs, staged_path)
    return staged_path, temp_root


def _compile_initial_post_html(
    output_dir: str,
    base_dir: str,
    driver_source_bytes: bytes,
    asset_hash: str,
    source_links: List[Tuple[str, str]],
    last_revision_date: Optional[str],
    last_revision_url: Optional[str],
    input_values_svg: Dict[str, str],
    input_values_pdf: Dict[str, str],
    raw_copy_html: str,
    post_title: str,
    post_subtitle: Optional[str],
    stylesheet_asset_path: str,
    clipboard_asset_path: str,
    theme_asset_path: str,
    rss_feed_path: Optional[str],
    enable_shared_glyph_extraction: bool,
    global_glyph_asset_path: Optional[str] = None,
    global_glyph_map_path: Optional[str] = None,
) -> str:
    initial_hidden_text = build_hidden_text(
        "",
        source_links,
        [],
        [],
        asset_hash,
        last_revision_date,
        last_revision_url,
    )
    compile_and_build_html(
        source_bytes=driver_source_bytes,
        output_dir=output_dir,
        asset_hash=asset_hash,
        file_prefix="post",
        template_path=os.path.join(base_dir, "index.template.html"),
        dest_dir=output_dir,
        title_format="Blog Page {i}",
        default_title=post_title,
        description=post_subtitle,
        inputs_svg=input_values_svg,
        inputs_pdf=input_values_pdf,
        extract_title_from_pdf=True,
        hidden_text_override=initial_hidden_text,
        raw_copy_html=raw_copy_html,
        svg_href_rewrites={"post.pdf": f"post.{asset_hash}.pdf"},
        stylesheet_asset_path=stylesheet_asset_path,
        clipboard_asset_path=clipboard_asset_path,
        theme_asset_path=theme_asset_path,
        rss_feed_path=rss_feed_path,
        enable_shared_glyph_extraction=enable_shared_glyph_extraction,
        global_glyph_asset_path=global_glyph_asset_path,
        global_glyph_map_path=global_glyph_map_path,
    )
    return initial_hidden_text


def run_compile(args: Namespace) -> None:
    workspace_base: str = args.workspace_base
    build_base: str = args.build_base
    workspace_name: str = args.name
    workspace_path = getattr(args, "workspace_path_override", None)
    if workspace_path is None:
        workspace_path = safe_join_child(workspace_base, workspace_name)
        if not os.path.exists(workspace_path):
            print(f"Workspace '{workspace_name}' does not exist.", file=sys.stderr)
            sys.exit(1)
    workspace_path, temp_workspace_root = _stage_workspace_for_compile(
        workspace_path,
        repo_root=os.getcwd(),
    )

    try:
        output_dir_override = getattr(args, "output_dir_override", None)
        if output_dir_override is None:
            os.makedirs(build_base, exist_ok=True)
            output_dir = safe_join_child(build_base, workspace_name)
        else:
            output_dir = os.path.abspath(str(output_dir_override))
            os.makedirs(os.path.dirname(output_dir), exist_ok=True)
        reset_directory(output_dir)

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        asset_context = build_driver_asset_context(base_dir, args.root_dir)
        driver_source_bytes, main_typ_abs_path, asset_hash = _prepare_compile_sources(
            base_dir,
            workspace_path,
        )
        post_title = (
            extract_declared_typst_string(main_typ_abs_path, "title") or workspace_name
        )
        post_subtitle = extract_declared_typst_string(main_typ_abs_path, "subtitle")

        posts_dir = os.path.join(args.root_dir, "posts")
        skip_latest = getattr(args, "amend", False)
        publish_date = getattr(args, "publish_date_override", None)
        edited_date = None
        if skip_latest:
            edited_date = getattr(
                args, "edited_date_override", None
            ) or _workspace_latest_modified_date(workspace_path)
        last_revision_date, last_revision_url = find_latest_revision(
            posts_dir,
            workspace_name,
            skip_latest=skip_latest,
        )
        input_values_svg, input_values_pdf = _build_typst_inputs(
            last_revision_date,
            last_revision_url,
            edited_date=edited_date,
            publish_date=publish_date,
        )

        source_links = extract_typst_links(
            main_typ_abs_path,
            query_root=os.getcwd(),
        )
        source_raws = extract_typst_raws_from_content(
            driver_source_bytes,
            query_root=os.getcwd(),
            inputs=input_values_svg,
        )
        source_headings = extract_typst_headings_from_content(
            driver_source_bytes,
            query_root=os.getcwd(),
            inputs=input_values_svg,
        )
        source_tables = extract_typst_tables_from_content(
            driver_source_bytes,
            query_root=os.getcwd(),
            inputs=input_values_svg,
        )
        raw_copy_html = build_raw_copy_assets(
            source_raws,
            asset_dir=output_dir,
        )

        print("Compiling Typst project...", file=sys.stderr)
        enable_shared_glyph_extraction = bool(
            getattr(args, "enable_shared_glyph_extraction", True)
        )
        rss_feed_path: Optional[str] = None
        if output_dir_override is not None:
            rss_feed_path = os.path.join(args.root_dir, "rss.xml")
        initial_hidden_text = _compile_initial_post_html(
            output_dir=output_dir,
            base_dir=base_dir,
            driver_source_bytes=driver_source_bytes,
            asset_hash=asset_hash,
            source_links=source_links,
            last_revision_date=last_revision_date,
            last_revision_url=last_revision_url,
            input_values_svg=input_values_svg,
            input_values_pdf=input_values_pdf,
            raw_copy_html=raw_copy_html,
            post_title=post_title,
            post_subtitle=post_subtitle,
            stylesheet_asset_path=asset_context.web_assets.stylesheet_path,
            clipboard_asset_path=asset_context.web_assets.clipboard_script_path,
            theme_asset_path=asset_context.web_assets.theme_script_path,
            rss_feed_path=rss_feed_path,
            enable_shared_glyph_extraction=enable_shared_glyph_extraction,
            global_glyph_asset_path=asset_context.global_glyph_asset_path,
            global_glyph_map_path=asset_context.global_glyph_map_path,
        )

        post_pdf_path = os.path.join(output_dir, f"post.{asset_hash}.pdf")
        final_hidden_text_override = build_final_hidden_text(
            post_pdf_path,
            source_links,
            source_raws,
            source_headings,
            source_tables,
            post_subtitle,
            asset_hash,
            last_revision_date,
            last_revision_url,
        )

        index_path = os.path.join(output_dir, "index.html")
        replace_hidden_block(
            index_path=index_path,
            old_hidden_text=initial_hidden_text,
            new_hidden_text=final_hidden_text_override,
        )

        copied_files = _copy_workspace_public_files(workspace_path, output_dir)
        if copied_files:
            print(
                f"Copied {copied_files} file(s) from '{WORKSPACE_PUBLIC_DIR_NAME}/'.",
                file=sys.stderr,
            )
    finally:
        if temp_workspace_root:
            shutil.rmtree(temp_workspace_root, ignore_errors=True)
