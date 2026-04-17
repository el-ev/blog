import html
import os
import re
import shutil
import sys
from argparse import Namespace
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

from .compile_hidden_text import (
    build_hidden_text,
    replace_hidden_block,
)
from .shared import (
    build_asset_ctx,
    page_url,
    resolve_base_url,
)
from .utils import (
    CompileBuildRequest,
    HtmlBuildConfig,
    WORKSPACE_PUBLIC_DIR_NAME,
    _query_nodes_from_source,
    build_page_head_title,
    compile_html,
    first_desc,
    decl_str,
    need_decl_str,
    extract_typst_links,
    prev_rev,
    make_temp_dir,
    make_inputs,
    minify_html,
    reset_dir,
    safe_join_child,
    sources_hash,
)

_SITE_TITLE = "Blog"


@dataclass(frozen=True)
class PreparedCompileSources:
    driver_source_bytes: bytes
    main_typ_path: str
    asset_hash: str


@dataclass(frozen=True)
class StagedWorkspace:
    path: str
    temp_root: Optional[str]


@dataclass(frozen=True)
class CompileOutputDirs:
    asset_output_dir: str
    html_output_dir: str
    public_output_dir: str


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
) -> PreparedCompileSources:
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
    return PreparedCompileSources(
        driver_source_bytes=driver_source.encode(),
        main_typ_path=main_typ_abs_path,
        asset_hash=asset_hash,
    )


def _replace_required_pattern(
    html_content: str,
    pattern: str,
    replacement: str,
) -> str:
    updated_html, replaced = re.subn(pattern, replacement, html_content, count=1)
    if replaced != 1:
        raise RuntimeError("Expected exactly one replacement match in article HTML.")
    return updated_html


def _finalize_article_metadata(
    index_path: str,
    post_title: str,
    post_subtitle: Optional[str],
    hidden_text: str,
) -> None:
    final_title = build_page_head_title(post_title, _SITE_TITLE, post_subtitle)
    fallback_desc = post_subtitle or post_title
    meta_description = first_desc(
        hidden_text,
        fallback_desc,
        skip_texts=[post_subtitle] if post_subtitle else None,
    )

    with open(index_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    escaped_title = html.escape(final_title, quote=True)
    escaped_title_text = html.escape(final_title)
    escaped_desc = html.escape(meta_description, quote=True)

    html_content = _replace_required_pattern(
        html_content,
        r'<meta name="description" content="[^"]*">',
        f'<meta name="description" content="{escaped_desc}">',
    )
    html_content = _replace_required_pattern(
        html_content,
        r'<meta property="og:title" content="[^"]*">',
        f'<meta property="og:title" content="{escaped_title}">',
    )
    html_content = _replace_required_pattern(
        html_content,
        r'<meta property="og:description" content="[^"]*">',
        f'<meta property="og:description" content="{escaped_desc}">',
    )
    html_content = _replace_required_pattern(
        html_content,
        r"<title>.*?</title>",
        f"<title>{escaped_title_text}</title>",
    )

    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html_content)


def _stage_workspace_for_compile(
    workspace_path: str, repo_root: str, build_base: str
) -> StagedWorkspace:
    workspace_abs = os.path.abspath(workspace_path)
    repo_abs = os.path.abspath(repo_root)
    try:
        if os.path.commonpath([repo_abs, workspace_abs]) == repo_abs:
            return StagedWorkspace(path=workspace_abs, temp_root=None)
    except ValueError:
        pass

    temp_root = make_temp_dir(build_base, prefix=".compile-workspace-")
    staged_path = os.path.join(temp_root, os.path.basename(workspace_abs))
    shutil.copytree(workspace_abs, staged_path)
    return StagedWorkspace(path=staged_path, temp_root=temp_root)


def _resolve_workspace_path(
    args: Namespace,
    workspace_base: str,
    workspace_name: str,
) -> str:
    workspace_path = getattr(args, "workspace_path_override", None)
    if workspace_path is not None:
        return workspace_path

    workspace_path = safe_join_child(workspace_base, workspace_name)
    if not os.path.exists(workspace_path):
        print(f"Workspace '{workspace_name}' does not exist.", file=sys.stderr)
        sys.exit(1)
    return workspace_path


def _resolve_compile_output_dirs(
    args: Namespace,
    build_base: str,
    workspace_name: str,
) -> CompileOutputDirs:
    output_dir_override = getattr(args, "output_dir_override", None)
    html_output_dir_override = getattr(args, "html_output_dir_override", None)
    public_output_dir_override = getattr(args, "public_output_dir_override", None)

    if output_dir_override is None:
        if html_output_dir_override is None:
            os.makedirs(build_base, exist_ok=True)
            html_output_dir = safe_join_child(build_base, workspace_name)
        else:
            html_output_dir = os.path.abspath(str(html_output_dir_override))
        output_dir = safe_join_child(html_output_dir, "assets")
        reset_dir(html_output_dir)
    else:
        output_dir = os.path.abspath(str(output_dir_override))
        html_output_dir = (
            os.path.abspath(str(html_output_dir_override))
            if html_output_dir_override is not None
            else os.path.dirname(output_dir)
        )
        reset_dir(output_dir)

    public_output_dir = (
        os.path.abspath(str(public_output_dir_override))
        if public_output_dir_override is not None
        else html_output_dir
    )
    os.makedirs(html_output_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(public_output_dir, exist_ok=True)
    return CompileOutputDirs(
        asset_output_dir=output_dir,
        html_output_dir=html_output_dir,
        public_output_dir=public_output_dir,
    )


def run_compile(args: Namespace) -> None:
    workspace_base: str = args.workspace_base
    build_base: str = args.build_base
    workspace_name: str = args.name
    workspace_path = _resolve_workspace_path(args, workspace_base, workspace_name)
    staged_workspace = _stage_workspace_for_compile(
        workspace_path,
        repo_root=os.getcwd(),
        build_base=build_base,
    )
    workspace_path = staged_workspace.path

    try:
        output_dirs = _resolve_compile_output_dirs(
            args, build_base, workspace_name
        )

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        asset_context = build_asset_ctx(base_dir, args.root_dir)
        compile_sources = _prepare_compile_sources(
            base_dir,
            workspace_path,
        )
        post_title = need_decl_str(
            compile_sources.main_typ_path,
            "title",
        )
        post_subtitle = decl_str(
            compile_sources.main_typ_path, "subtitle"
        )

        posts_dir = os.path.join(args.root_dir, "posts")
        skip_latest = getattr(args, "amend", False)
        publish_date = getattr(args, "publish_date_override", None)
        edited_date = None
        if skip_latest:
            edited_date = getattr(
                args, "edited_date_override", None
            ) or _workspace_latest_modified_date(workspace_path)
        last_revision_date, last_revision_url = prev_rev(
            posts_dir,
            workspace_name,
            skip_latest=skip_latest,
        )
        shared_inputs: Dict[str, str] = {}
        if publish_date:
            shared_inputs["publish_date"] = publish_date
        if edited_date:
            shared_inputs["edited_date"] = edited_date
        if last_revision_date and last_revision_url:
            shared_inputs["last_revision_date"] = last_revision_date
            shared_inputs["last_revision_url"] = last_revision_url
        typst_inputs = make_inputs(
            shared_inputs=shared_inputs or None,
        )

        source_links = extract_typst_links(
            compile_sources.main_typ_path,
            query_root=os.getcwd(),
        )

        print("Compiling Typst project...", file=sys.stderr)
        shared_glyphs = bool(getattr(args, "shared_glyphs", True))
        base_url = resolve_base_url(args, required=False)
        og_url = (
            page_url(
                base_url=base_url,
                root_dir=args.root_dir,
                dest_dir=output_dirs.html_output_dir,
                html_filename="index.html",
            )
            if base_url
            else None
        )
        hidden_text = ""
        pdf_href = f"./assets/post.{compile_sources.asset_hash}.pdf"
        compile_html(
            CompileBuildRequest(
                source_bytes=compile_sources.driver_source_bytes,
                output_dir=output_dirs.asset_output_dir,
                asset_hash=compile_sources.asset_hash,
                file_prefix="post",
                typst_inputs=typst_inputs,
                html=HtmlBuildConfig(
                    template_path=os.path.join(base_dir, "index.template.html"),
                    dest_dir=output_dirs.html_output_dir,
                    title_format="Blog Page {i}",
                    default_title=post_title,
                    asset_context=asset_context,
                    description=post_subtitle,
                    hidden_text_override=hidden_text,
                    extract_title_from_pdf=True,
                    svg_href_rewrites={"post.pdf": pdf_href},
                    asset_dest_dir=output_dirs.asset_output_dir,
                    og_type="article",
                    og_url=og_url,
                    shared_glyphs=shared_glyphs,
                    image_source_dir=workspace_path,
                    site_base_url=base_url,
                ),
            )
        )

        doc_elements = [
            value
            for node in _query_nodes_from_source(
                source_content=compile_sources.driver_source_bytes,
                query_root=os.getcwd(),
                selector="<driver-doc>",
                inputs=typst_inputs.svg,
            )
            if isinstance((value := node.get("value")), dict)
        ]
        final_hidden_text = build_hidden_text(
            doc_elements,
            post_title,
            post_subtitle,
            compile_sources.asset_hash,
            nav_links=[
                ("../../../index.html", "Contents"),
                ("meta.html", "Meta"),
                (f"./assets/post.{compile_sources.asset_hash}.pdf", "PDF"),
            ],
            source_links=source_links,
        )

        index_path = os.path.join(output_dirs.html_output_dir, "index.html")
        replace_hidden_block(
            index_path=index_path,
            old_hidden_text=hidden_text,
            new_hidden_text=final_hidden_text,
        )
        _finalize_article_metadata(
            index_path=index_path,
            post_title=post_title,
            post_subtitle=post_subtitle,
            hidden_text=final_hidden_text,
        )
        minify_html(index_path)

        copied_files = _copy_workspace_public_files(
            workspace_path, output_dirs.public_output_dir
        )
        if copied_files:
            print(
                f"Copied {copied_files} file(s) from '{WORKSPACE_PUBLIC_DIR_NAME}/'.",
                file=sys.stderr,
            )
    finally:
        if staged_workspace.temp_root:
            shutil.rmtree(staged_workspace.temp_root, ignore_errors=True)
