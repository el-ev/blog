import html
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .utils import (
    CompileBuildRequest,
    DriverAssetContext,
    HtmlBuildConfig,
    compile_html,
    hash_text_with_paths,
    make_raw_copy_id,
    make_inputs,
    make_temp_dir,
)


@dataclass(frozen=True)
class MetaFieldsRequest:
    workspace_name: str
    date_str: str
    target_rev: int
    dest_dir_name: str
    post_title: str
    post_subtitle: Optional[str]
    pdf_name: str
    post_source_hash: str
    workspace_files: List[str]
    generated_at: Optional[str] = None


@dataclass(frozen=True)
class MetaPageRequest:
    build_base: str
    base_dir: str
    dest_dir: str
    asset_dir: Optional[str]
    post_title: str
    meta_fields: Dict[str, str]
    workspace_files: List[str]
    asset_context: DriverAssetContext
    og_url: Optional[str] = None
    site_base_url: Optional[str] = None


def extract_post_pdf_name(post_dir: str) -> Tuple[str, str]:
    asset_dir = os.path.join(post_dir, "assets")
    filename = next(
        filename
        for filename in sorted(os.listdir(asset_dir))
        if re.match(r"^post\.[^.]+\.pdf$", filename)
    )
    return f"assets/{filename}", filename[len("post.") : -len(".pdf")]


def build_meta_fields(request: MetaFieldsRequest) -> Dict[str, str]:
    meta_generated_at = request.generated_at or datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    fields: Dict[str, str] = {
        "Post Title": request.post_title,
    }
    if request.post_subtitle:
        fields["Post Subtitle"] = request.post_subtitle
    fields.update(
        {
            "Publish Date": request.date_str,
            "Revision": str(request.target_rev),
            "Workspace Name": request.workspace_name,
            "Post Path": f"{request.date_str}/{request.dest_dir_name}",
            "Source File Count": str(len(request.workspace_files)),
            "Source Hash": request.post_source_hash,
            "PDF Asset": request.pdf_name,
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
    placeholders = {
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
        for placeholder, field_name in placeholders.items()
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
        copy_id = make_raw_copy_id(value)
        lines.append(
            f"<li>{html.escape(key)}: "
            f'<code id="raw-{copy_id}">{html.escape(value)}</code></li>'
        )
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


def compile_meta_page(request: MetaPageRequest) -> None:
    template_path = os.path.join(request.base_dir, "meta.template.typ")
    with open(template_path, "r", encoding="utf-8") as f:
        template_source = f.read()

    meta_source = _build_meta_typst_source(
        template_source=template_source,
        meta_fields=request.meta_fields,
        source_files=request.workspace_files,
    )
    meta_hidden_text = _build_meta_hidden_text(
        request.meta_fields, request.workspace_files
    )
    template_typ_path = os.path.join(request.base_dir, "template.typ")
    meta_hash = hash_text_with_paths(
        meta_source,
        [template_typ_path],
    )

    typst_inputs = make_inputs(shared_inputs={"back_href": "index.html"})

    meta_output_dir = make_temp_dir(request.build_base, prefix=".meta-build-")
    try:
        compile_html(
            CompileBuildRequest(
                source_bytes=meta_source.encode("utf-8"),
                output_dir=meta_output_dir,
                asset_hash=meta_hash,
                file_prefix="meta",
                typst_inputs=typst_inputs,
                html=HtmlBuildConfig(
                    template_path=os.path.join(request.base_dir, "index.template.html"),
                    dest_dir=request.dest_dir,
                    title_format="Meta Page {i}",
                    default_title=f"{request.post_title} - Meta",
                    asset_context=request.asset_context,
                    description=f"Metadata for {request.post_title}",
                    hidden_text_override=meta_hidden_text,
                    svg_name_prefix="meta-page",
                    html_filename="meta.html",
                    asset_dest_dir=request.asset_dir,
                    og_type="article",
                    og_url=request.og_url,
                    shared_glyphs=False,
                    site_base_url=request.site_base_url,
                ),
            )
        )
    finally:
        shutil.rmtree(meta_output_dir, ignore_errors=True)
