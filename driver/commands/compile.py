import html
import os
import re
import shutil
import sys
from argparse import Namespace
from datetime import datetime
from typing import Dict, Optional, Tuple

from .compile_hidden_text import (
    build_final_hidden_text,
    replace_hidden_block,
)
from .shared import (
    DriverAssetContext,
    build_driver_asset_context,
    build_public_page_url,
    resolve_base_url,
)
from .utils import (
    WORKSPACE_PUBLIC_DIR_NAME,
    PostSourceContent,
    TypstInputs,
    build_raw_copy_assets,
    build_page_head_title,
    compile_and_build_html,
    extract_first_description_sentence,
    extract_declared_typst_string,
    extract_required_declared_typst_string,
    extract_typst_headings_from_content,
    extract_typst_figures_from_content,
    extract_typst_info_blocks_from_content,
    extract_typst_links,
    extract_typst_raws_from_content,
    extract_typst_tables_from_content,
    find_latest_revision,
    make_temp_dir,
    minify_html_file,
    reset_directory,
    safe_join_child,
    sources_hash,
)

_SITE_TITLE = "Blog"


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
) -> TypstInputs:
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
    return TypstInputs(svg=input_values_svg, pdf=input_values_pdf)


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
def _replace_required_pattern(
    html_content: str,
    pattern: str,
    replacement: str,
    label: str,
) -> str:
    updated_html, replaced = re.subn(pattern, replacement, html_content, count=1)
    if replaced != 1:
        raise RuntimeError(f"Expected exactly one {label} tag in article HTML.")
    return updated_html


def _finalize_article_metadata(
    index_path: str,
    post_title: str,
    post_subtitle: Optional[str],
    hidden_text: str,
) -> None:
    final_title = build_page_head_title(post_title, _SITE_TITLE, post_subtitle)
    fallback_description = post_subtitle or post_title
    meta_description = extract_first_description_sentence(
        hidden_text,
        fallback_description,
        skip_texts=[post_subtitle] if post_subtitle else None,
    )

    with open(index_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    escaped_title = html.escape(final_title, quote=True)
    escaped_title_text = html.escape(final_title)
    escaped_description = html.escape(meta_description, quote=True)

    html_content = _replace_required_pattern(
        html_content,
        r'<meta name="description" content="[^"]*">',
        f'<meta name="description" content="{escaped_description}">',
        "description",
    )
    html_content = _replace_required_pattern(
        html_content,
        r'<meta property="og:title" content="[^"]*">',
        f'<meta property="og:title" content="{escaped_title}">',
        "og:title",
    )
    html_content = _replace_required_pattern(
        html_content,
        r'<meta property="og:description" content="[^"]*">',
        f'<meta property="og:description" content="{escaped_description}">',
        "og:description",
    )
    html_content = _replace_required_pattern(
        html_content,
        r"<title>.*?</title>",
        f"<title>{escaped_title_text}</title>",
        "title",
    )

    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html_content)


def _stage_workspace_for_compile(
    workspace_path: str, repo_root: str, build_base: str
) -> Tuple[str, str]:
    workspace_abs = os.path.abspath(workspace_path)
    repo_abs = os.path.abspath(repo_root)
    try:
        if os.path.commonpath([repo_abs, workspace_abs]) == repo_abs:
            return workspace_abs, ""
    except ValueError:
        pass

    temp_root = make_temp_dir(build_base, prefix=".compile-workspace-")
    staged_path = os.path.join(temp_root, os.path.basename(workspace_abs))
    shutil.copytree(workspace_abs, staged_path)
    return staged_path, temp_root


def _compile_initial_post_html(
    output_dir: str,
    html_dest_dir: str,
    base_dir: str,
    driver_source_bytes: bytes,
    asset_hash: str,
    typst_inputs: TypstInputs,
    raw_copy_html: str,
    post_title: str,
    post_subtitle: Optional[str],
    asset_context: DriverAssetContext,
    rss_feed_path: Optional[str],
    og_url: Optional[str],
    site_base_url: Optional[str],
    enable_shared_glyph_extraction: bool,
    image_source_dir: Optional[str] = None,
) -> str:
    initial_hidden_text = ""
    pdf_href = f"./assets/post.{asset_hash}.pdf"
    compile_and_build_html(
        source_bytes=driver_source_bytes,
        output_dir=output_dir,
        asset_hash=asset_hash,
        file_prefix="post",
        template_path=os.path.join(base_dir, "index.template.html"),
        dest_dir=html_dest_dir,
        title_format="Blog Page {i}",
        default_title=post_title,
        description=post_subtitle,
        typst_inputs=typst_inputs,
        extract_title_from_pdf=True,
        hidden_text_override=initial_hidden_text,
        raw_copy_html=raw_copy_html,
        svg_href_rewrites={"post.pdf": pdf_href},
        asset_dest_dir=output_dir,
        asset_context=asset_context,
        rss_feed_path=rss_feed_path,
        og_type="article",
        og_url=og_url,
        site_base_url=site_base_url,
        enable_shared_glyph_extraction=enable_shared_glyph_extraction,
        image_source_dir=image_source_dir,
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
        build_base=build_base,
    )

    try:
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
            reset_directory(html_output_dir)
        else:
            output_dir = os.path.abspath(str(output_dir_override))
            html_output_dir = (
                os.path.abspath(str(html_output_dir_override))
                if html_output_dir_override is not None
                else os.path.dirname(output_dir)
            )
            reset_directory(output_dir)

        public_output_dir = (
            os.path.abspath(str(public_output_dir_override))
            if public_output_dir_override is not None
            else html_output_dir
        )
        os.makedirs(html_output_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(public_output_dir, exist_ok=True)

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        asset_context = build_driver_asset_context(base_dir, args.root_dir)
        driver_source_bytes, main_typ_abs_path, asset_hash = _prepare_compile_sources(
            base_dir,
            workspace_path,
        )
        post_title = extract_required_declared_typst_string(
            main_typ_abs_path,
            "title",
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
        typst_inputs = _build_typst_inputs(
            last_revision_date,
            last_revision_url,
            edited_date=edited_date,
            publish_date=publish_date,
        )

        source_content = PostSourceContent(
            links=extract_typst_links(
                main_typ_abs_path,
                query_root=os.getcwd(),
            ),
            raws=extract_typst_raws_from_content(
                driver_source_bytes,
                query_root=os.getcwd(),
                inputs=typst_inputs.svg,
            ),
            headings=extract_typst_headings_from_content(
                driver_source_bytes,
                query_root=os.getcwd(),
                inputs=typst_inputs.svg,
            ),
            tables=extract_typst_tables_from_content(
                driver_source_bytes,
                query_root=os.getcwd(),
                inputs=typst_inputs.svg,
            ),
            figures=extract_typst_figures_from_content(
                driver_source_bytes,
                query_root=os.getcwd(),
                inputs=typst_inputs.pdf,
            ),
            info_blocks=extract_typst_info_blocks_from_content(
                driver_source_bytes,
                query_root=os.getcwd(),
                inputs=typst_inputs.pdf,
            ),
        )
        raw_copy_html = build_raw_copy_assets(
            source_content.raws,
            asset_dir=output_dir,
        )

        print("Compiling Typst project...", file=sys.stderr)
        enable_shared_glyph_extraction = bool(
            getattr(args, "enable_shared_glyph_extraction", True)
        )
        rss_feed_path: Optional[str] = None
        if output_dir_override is not None:
            rss_feed_path = os.path.join(args.root_dir, "rss.xml")
        base_url = resolve_base_url(args)
        og_url = build_public_page_url(
            base_url=base_url,
            root_dir=args.root_dir,
            dest_dir=html_output_dir,
            html_filename="index.html",
        )
        initial_hidden_text = _compile_initial_post_html(
            output_dir=output_dir,
            html_dest_dir=html_output_dir,
            base_dir=base_dir,
            driver_source_bytes=driver_source_bytes,
            asset_hash=asset_hash,
            typst_inputs=typst_inputs,
            raw_copy_html=raw_copy_html,
            post_title=post_title,
            post_subtitle=post_subtitle,
            asset_context=asset_context,
            rss_feed_path=rss_feed_path,
            og_url=og_url,
            site_base_url=base_url,
            enable_shared_glyph_extraction=enable_shared_glyph_extraction,
            image_source_dir=workspace_path,
        )

        post_pdf_path = os.path.join(output_dir, f"post.{asset_hash}.pdf")
        final_hidden_text_override = build_final_hidden_text(
            post_pdf_path,
            source_content,
            post_subtitle,
            asset_hash,
            last_revision_date,
            last_revision_url,
            nav_links=[
                ("../../../index.html", "Contents"),
                ("meta.html", "Meta"),
                (f"./assets/post.{asset_hash}.pdf", "PDF"),
            ],
        )

        index_path = os.path.join(html_output_dir, "index.html")
        replace_hidden_block(
            index_path=index_path,
            old_hidden_text=initial_hidden_text,
            new_hidden_text=final_hidden_text_override,
        )
        _finalize_article_metadata(
            index_path=index_path,
            post_title=post_title,
            post_subtitle=post_subtitle,
            hidden_text=final_hidden_text_override,
        )
        minify_html_file(index_path)

        copied_files = _copy_workspace_public_files(workspace_path, public_output_dir)
        if copied_files:
            print(
                f"Copied {copied_files} file(s) from '{WORKSPACE_PUBLIC_DIR_NAME}/'.",
                file=sys.stderr,
            )
    finally:
        if temp_workspace_root:
            shutil.rmtree(temp_workspace_root, ignore_errors=True)
