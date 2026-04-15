import html
import os
import re
import shutil
import tempfile
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .utils import (
    build_raw_copy_assets,
    compile_and_build_html,
    extract_declared_typst_string,
    extract_typst_raws_from_content,
    hash_text_with_sources,
)

_META_CODE_FIELD_PATTERN = re.compile(
    r"<li>\s*([^:<]+):\s*<code>(.*?)</code>\s*</li>",
    re.IGNORECASE | re.DOTALL,
)


def extract_post_headers(
    main_typ_path: str, fallback_title: str
) -> Tuple[str, Optional[str]]:
    title = extract_declared_typst_string(main_typ_path, "title") or fallback_title
    subtitle = extract_declared_typst_string(main_typ_path, "subtitle")
    return title, subtitle


def extract_post_pdf_name(post_dir: str) -> Tuple[str, str]:
    candidate_dirs = []
    asset_dir = os.path.join(post_dir, "assets")
    if os.path.isdir(asset_dir):
        candidate_dirs.append(("assets", asset_dir))
    candidate_dirs.append(("", post_dir))

    for dir_prefix, current_dir in candidate_dirs:
        for filename in sorted(os.listdir(current_dir)):
            if not re.match(r"^post\.[^.]+\.pdf$", filename):
                continue
            relative_name = (
                f"{dir_prefix}/{filename}" if dir_prefix else filename
            )
            return relative_name, filename[len("post.") : -len(".pdf")]
    raise RuntimeError(f"Compiled post PDF not found in '{post_dir}'.")


def load_meta_fields(post_dir: str) -> Dict[str, str]:
    meta_path = os.path.join(post_dir, "meta.html")
    with open(meta_path, "r", encoding="utf-8") as f:
        meta_html = f.read()

    fields: Dict[str, str] = {}
    for key, value in _META_CODE_FIELD_PATTERN.findall(meta_html):
        fields[key.strip()] = html.unescape(value.strip())
    return fields


def build_meta_fields(
    workspace_name: str,
    date_str: str,
    target_rev: int,
    dest_dir_name: str,
    post_title: str,
    post_subtitle: Optional[str],
    pdf_name: str,
    post_source_hash: str,
    workspace_files: List[str],
    generated_at: Optional[str] = None,
) -> Dict[str, str]:
    meta_generated_at = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fields: Dict[str, str] = {
        "Post Title": post_title,
    }
    if post_subtitle:
        fields["Post Subtitle"] = post_subtitle
    fields.update(
        {
            "Publish Date": date_str,
            "Revision": str(target_rev),
            "Workspace Name": workspace_name,
            "Post Path": f"{date_str}/{dest_dir_name}",
            "Source File Count": str(len(workspace_files)),
            "Source Hash": post_source_hash,
            "PDF Asset": pdf_name,
            "Generated At": meta_generated_at,
        }
    )
    return fields


def _escape_typst_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _build_meta_typst_source(
    template_source: str,
    meta_fields: Dict[str, str],
    source_files: List[str],
) -> str:
    markup_placeholders = {
        "{{POST_TITLE}}": "Post Title",
        "{{PUBLISH_DATE}}": "Publish Date",
        "{{REVISION}}": "Revision",
        "{{WORKSPACE_NAME}}": "Workspace Name",
        "{{POST_PATH}}": "Post Path",
        "{{SOURCE_FILE_COUNT}}": "Source File Count",
        "{{SOURCE_HASH}}": "Source Hash",
        "{{PDF_ASSET}}": "PDF Asset",
        "{{GENERATED_AT}}": "Generated At",
    }
    replacements: Dict[str, str] = {
        placeholder: (
            f'#raw("{_escape_typst_string(meta_fields[field_name])}", block: false)'
        )
        for placeholder, field_name in markup_placeholders.items()
    }
    post_subtitle = (
        meta_fields["Post Subtitle"] if "Post Subtitle" in meta_fields else None
    )
    replacements["{{POST_SUBTITLE}}"] = (
        f'raw("{_escape_typst_string(post_subtitle)}", block: false)'
        if post_subtitle is not None
        else "none"
    )

    source_lines: List[str] = []
    for rel_path in source_files:
        normalized_path = rel_path.replace("\\", "/")
        escaped_path = _escape_typst_string(normalized_path)
        source_lines.append(f'- #link("source/{escaped_path}")[source/{escaped_path}]')
    if not source_lines:
        source_lines.append("- No files recorded.")

    source = template_source
    for placeholder, value in replacements.items():
        source = source.replace(placeholder, value)
    source = source.replace("{{SOURCE_FILES}}", "\n".join(source_lines))
    return source


def _build_meta_hidden_text(
    meta_fields: Dict[str, str], source_files: List[str]
) -> str:
    lines: List[str] = ["<h1>Meta</h1>", "<ul>"]
    for key, value in meta_fields.items():
        lines.append(f"<li>{html.escape(key)}: <code>{html.escape(value)}</code></li>")
    lines.append("</ul>")
    lines.append("<h2>Source Files</h2>")
    lines.append("<ul>")
    for rel_path in source_files:
        safe_path = html.escape(rel_path.replace("\\", "/"))
        lines.append(
            '<li><a href="source/'
            f'{safe_path}" tabindex="-1">source/{safe_path}</a></li>'
        )
    if not source_files:
        lines.append("<li>No files recorded.</li>")
    lines.append("</ul>")
    return "\n".join(lines)


def compile_meta_page(
    build_base: str,
    base_dir: str,
    stylesheet_asset_path: str,
    clipboard_asset_path: str,
    theme_asset_path: str,
    dest_dir: str,
    asset_dir: Optional[str],
    post_title: str,
    meta_fields: Dict[str, str],
    workspace_files: List[str],
    global_glyph_asset_path: str,
    global_glyph_map_path: str,
    rss_feed_path: Optional[str] = None,
    og_url: Optional[str] = None,
    inline_style: str = "",
    inline_script: str = "",
) -> None:
    meta_template_path = os.path.join(base_dir, "meta.template.typ")
    with open(meta_template_path, "r", encoding="utf-8") as f:
        meta_template_source = f.read()

    meta_source = _build_meta_typst_source(
        template_source=meta_template_source,
        meta_fields=meta_fields,
        source_files=workspace_files,
    )
    meta_hidden_text = _build_meta_hidden_text(meta_fields, workspace_files)
    template_typ_path = os.path.join(base_dir, "template.typ")
    meta_hash = hash_text_with_sources(
        meta_source,
        [template_typ_path],
    )

    input_values_svg: Dict[str, str] = {
        "with_driver": "true",
        "export_format": "svg",
        "back_href": "index.html",
    }
    input_values_pdf: Dict[str, str] = {
        "with_driver": "true",
        "export_format": "pdf",
        "back_href": "index.html",
    }

    meta_raws = extract_typst_raws_from_content(
        meta_source,
        query_root=os.getcwd(),
        inputs=input_values_svg,
    )
    raw_copy_html = build_raw_copy_assets(
        meta_raws,
        asset_dir=asset_dir,
        html_dir=dest_dir,
    )

    os.makedirs(build_base, exist_ok=True)
    meta_output_dir = tempfile.mkdtemp(prefix=".meta-build-", dir=build_base)
    try:
        compile_and_build_html(
            source_bytes=meta_source.encode("utf-8"),
            output_dir=meta_output_dir,
            asset_hash=meta_hash,
            file_prefix="meta",
            template_path=os.path.join(base_dir, "index.template.html"),
            dest_dir=dest_dir,
            title_format="Meta Page {i}",
            default_title=f"{post_title} - Meta",
            description=f"Metadata for {post_title}",
            inputs_svg=input_values_svg,
            inputs_pdf=input_values_pdf,
            extract_title_from_pdf=False,
            hidden_text_override=meta_hidden_text,
            raw_copy_html=raw_copy_html,
            svg_name_prefix="meta-page",
            html_filename="meta.html",
            asset_dest_dir=asset_dir,
            stylesheet_asset_path=stylesheet_asset_path,
            clipboard_asset_path=clipboard_asset_path,
            theme_asset_path=theme_asset_path,
            rss_feed_path=rss_feed_path,
            og_type="article",
            og_url=og_url,
            enable_shared_glyph_extraction=False,
            global_glyph_asset_path=global_glyph_asset_path,
            global_glyph_map_path=global_glyph_map_path,
            inline_style=inline_style,
            inline_script=inline_script,
        )
    finally:
        shutil.rmtree(meta_output_dir, ignore_errors=True)
