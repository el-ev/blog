import os
import sys
import re
import html
import shutil
import tempfile
from argparse import Namespace
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from .utils import (
    extract_typst_links,
    extract_typst_raws_from_content,
    extract_pdf_text,
    reset_directory,
    sources_hash,
    find_latest_revision,
    compile_and_build_html,
    validate_workspace_name,
    safe_join_child,
    WORKSPACE_PUBLIC_DIR_NAME,
    build_raw_copy_assets,
    copy_driver_web_js,
)


def _replace_first(text: str, old: str, new: str) -> Tuple[str, bool]:
    if not old:
        return text, False

    idx = text.find(old)
    if idx < 0:
        return text, False
    return text[:idx] + new + text[idx + len(old) :], True


def _make_hidden_placeholder(index: int) -> str:
    return f"__HIDDEN_HTML_{index}__"


def _embed_links_in_hidden_text(
    inner_hidden: str,
    merged_links: List[Tuple[str, str]],
    placeholder_html: List[Tuple[str, str]],
) -> Tuple[str, List[Tuple[str, str]]]:
    text = inner_hidden
    remaining_links: List[Tuple[str, str]] = []

    for href, label in merged_links:
        if not href:
            continue

        candidates: List[str] = []
        clean_label = label.strip() if label else ""
        if clean_label:
            candidates.append(clean_label)
        if href not in candidates:
            candidates.append(href)

        placed = False
        safe_href = html.escape(href, quote=True)
        for candidate in candidates:
            escaped_candidate = html.escape(candidate)
            if not escaped_candidate:
                continue
            anchor = f'<a href="{safe_href}">{escaped_candidate}</a>'
            placeholder = _make_hidden_placeholder(len(placeholder_html))
            text, replaced = _replace_first(text, escaped_candidate, placeholder)
            if replaced:
                placeholder_html.append((placeholder, anchor))
                placed = True
                break

        if not placed:
            remaining_links.append((href, label or href))

    return text, remaining_links


def _embed_raws_in_hidden_text(
    inner_hidden: str,
    source_raws: List[Tuple[str, bool]],
) -> Tuple[str, List[str], List[str], List[Tuple[str, str]], Set[str]]:
    text = inner_hidden
    remaining_inline_raws: List[str] = []
    remaining_block_raws: List[str] = []
    placeholder_html: List[Tuple[str, str]] = []
    block_placeholders: Set[str] = set()

    for raw_text, is_block in source_raws:
        normalized_raw = raw_text.replace("\r\n", "\n").replace("\r", "\n")
        if not normalized_raw.strip():
            continue

        candidates: List[str] = [normalized_raw]
        stripped_raw = normalized_raw.strip("\n")
        if stripped_raw and stripped_raw not in candidates:
            candidates.append(stripped_raw)

        placed = False
        for candidate in candidates:
            escaped_candidate = html.escape(candidate)
            if not escaped_candidate:
                continue
            placeholder = _make_hidden_placeholder(len(placeholder_html))
            wrapped_candidate = (
                f"<pre><code>{escaped_candidate}</code></pre>"
                if is_block
                else f"<code>{escaped_candidate}</code>"
            )
            text, replaced = _replace_first(text, escaped_candidate, placeholder)
            if replaced:
                placeholder_html.append((placeholder, wrapped_candidate))
                if is_block:
                    block_placeholders.add(placeholder)
                placed = True
                break

        if not placed:
            if is_block:
                remaining_block_raws.append(normalized_raw)
            else:
                remaining_inline_raws.append(normalized_raw)

    return text, remaining_inline_raws, remaining_block_raws, placeholder_html, block_placeholders


def _ends_paragraph(line: str) -> bool:
    return line.endswith((".", "!", "?", ":", ";", ".)", '."'))


def _is_standalone_hidden_line(line: str) -> bool:
    return bool(
        re.fullmatch(r"\d{4}-\d{2}-\d{2}", line)
        or re.fullmatch(r"\d+", line)
        or line.startswith("Edited on ")
        or line.startswith("Compiled at ")
        or line.startswith("Last revision on ")
    )


def _restore_hidden_placeholders(
    text: str,
    placeholder_html: List[Tuple[str, str]],
) -> str:
    restored = text
    for placeholder, html_fragment in placeholder_html:
        restored = restored.replace(placeholder, html_fragment)
    return restored


def _paragraphize_hidden_text(
    inner_hidden: str,
    placeholder_html: List[Tuple[str, str]],
    block_placeholders: Set[str],
) -> str:
    normalized = inner_hidden.replace("\r\n", "\n").replace("\r", "\n")
    parts: List[str] = []
    current_lines: List[str] = []
    seen_nonblank = 0

    def flush_current() -> None:
        if not current_lines:
            return
        paragraph = re.sub(r"\s+", " ", " ".join(current_lines)).strip()
        parts.append(f"<p>{paragraph}</p>")
        current_lines.clear()

    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if not line:
            flush_current()
            continue

        if line in block_placeholders:
            flush_current()
            parts.append(line)
            seen_nonblank += 1
            continue

        if seen_nonblank == 0 or _is_standalone_hidden_line(line):
            flush_current()
            parts.append(f"<p>{line}</p>")
            seen_nonblank += 1
            continue

        current_lines.append(line)
        seen_nonblank += 1
        if _ends_paragraph(line):
            flush_current()

    flush_current()
    return _restore_hidden_placeholders("\n".join(parts), placeholder_html)


def _build_hidden_text(
    inner_hidden: str,
    remaining_links: List[Tuple[str, str]],
    remaining_inline_raws: List[str],
    remaining_block_raws: List[str],
    asset_hash: str,
    last_revision_date: Optional[str],
    last_revision_url: Optional[str],
) -> str:
    nav_html: List[str] = ["<h2>Navigation</h2>", "<ul>"]
    nav_html.append('<li><a href="../../../index.html">Contents</a></li>')
    nav_html.append(f'<li><a href="post.{asset_hash}.pdf">PDF</a></li>')
    nav_html.append('<li><a href="source/index.html">Source</a></li>')
    nav_html.append('<li><a href="meta.html">Meta</a></li>')
    
    if last_revision_date and last_revision_url:
        nav_html.append(
            f'<li>Last revision at <a href="{html.escape(last_revision_url)}">{html.escape(last_revision_date)}</a></li>'
        )
    nav_html.append("</ul>")

    hidden_parts: List[str] = []
    if inner_hidden:
        hidden_parts.append(inner_hidden)
    hidden_parts.append("\n".join(nav_html))
    
    if remaining_links:
        links_html: List[str] = ["<h2>Additional Links</h2>", "<ul>"]
        for href, label in remaining_links:
            links_html.append(
                f'<li><a href="{html.escape(href)}">{html.escape(label)}</a></li>'
            )
        links_html.append("</ul>")
        hidden_parts.append("\n".join(links_html))

    if remaining_inline_raws or remaining_block_raws:
        hidden_parts.append("<h2>Additional Code</h2>")
        for raw_text in remaining_inline_raws:
            hidden_parts.append(f"<p><code>{html.escape(raw_text)}</code></p>")
        for raw_text in remaining_block_raws:
            hidden_parts.append(f"<pre><code>{html.escape(raw_text)}</code></pre>")

    return "\n".join(hidden_parts)

def _resolve_workspace_name(args: Namespace) -> str:
    try:
        workspace_name = validate_workspace_name(args.name[0])
    except ValueError as e:
        print(f"Invalid workspace name: {e}", file=sys.stderr)
        sys.exit(1)
    args.name[0] = workspace_name
    return workspace_name


def _resolve_workspace_path(workspace_base: str, workspace_name: str) -> str:
    workspace_path = safe_join_child(workspace_base, workspace_name)
    if not os.path.exists(workspace_path):
        print(f"Workspace '{workspace_name}' does not exist.", file=sys.stderr)
        sys.exit(1)
    return workspace_path


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


def _extract_inner_hidden_text(extracted_hidden: str) -> str:
    if not extracted_hidden:
        return ""
    prefix = '<div class="sr-only">\n'
    suffix = "\n</div>"
    if extracted_hidden.startswith(prefix) and extracted_hidden.endswith(suffix):
        return extracted_hidden[len(prefix) : -len(suffix)]
    return extracted_hidden


def _replace_hidden_block(
    index_path: str,
    old_hidden_text: str,
    new_hidden_text: str,
) -> None:
    if not os.path.exists(index_path):
        return

    with open(index_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    old_hidden = f'<div class="sr-only">\n{old_hidden_text}\n</div>'
    new_hidden = f'<div class="sr-only">\n{new_hidden_text}\n</div>'
    html_content = html_content.replace(old_hidden, new_hidden)

    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html_content)


def _prepare_compile_sources(base_dir: str, workspace_path: str) -> Tuple[bytes, str, str]:
    driver_typ_path = os.path.join(base_dir, "driver.typ")
    template_typ_path = os.path.join(base_dir, "template.typ")

    with open(driver_typ_path, "r", encoding="utf-8") as f:
        driver_source = f.read()

    main_typ_abs_path = os.path.abspath(os.path.join(workspace_path, "main.typ"))
    main_typ_path = os.path.relpath(main_typ_abs_path, start=os.getcwd()).replace("\\", "/")
    asset_hash = sources_hash([workspace_path, driver_typ_path, template_typ_path])
    driver_source = driver_source.replace("// IMPORT_MAIN", f'#import "{main_typ_path}": *')
    return driver_source.encode(), main_typ_abs_path, asset_hash


def _stage_workspace_for_compile(workspace_path: str, repo_root: str) -> Tuple[str, str]:
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
    root_dir: str,
    driver_source_bytes: bytes,
    asset_hash: str,
    source_links: List[Tuple[str, str]],
    last_revision_date: Optional[str],
    last_revision_url: Optional[str],
    input_values_svg: Dict[str, str],
    input_values_pdf: Dict[str, str],
    raw_copy_html: str,
) -> str:
    initial_hidden_text = _build_hidden_text(
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
        default_title="Blog Post",
        inputs_svg=input_values_svg,
        inputs_pdf=input_values_pdf,
        extract_title_from_pdf=True,
        hidden_text_override=initial_hidden_text,
        raw_copy_html=raw_copy_html,
        svg_href_rewrites={"post.pdf": f"post.{asset_hash}.pdf"},
        clipboard_asset_path=os.path.join(root_dir, "clipboard.min.js"),
    )
    return initial_hidden_text


def _build_final_hidden_text(
    post_pdf_path: str,
    source_links: List[Tuple[str, str]],
    source_raws: List[Tuple[str, bool]],
    asset_hash: str,
    last_revision_date: Optional[str],
    last_revision_url: Optional[str],
) -> str:
    _, extracted_hidden = extract_pdf_text(
        post_pdf_path,
        extract_title=False,
        default_title="",
    )
    inner_hidden = _extract_inner_hidden_text(extracted_hidden)
    placeholder_html: List[Tuple[str, str]] = []
    embedded_hidden_text, remaining_links = _embed_links_in_hidden_text(
        inner_hidden,
        source_links,
        placeholder_html,
    )
    (
        embedded_hidden_text,
        remaining_inline_raws,
        remaining_block_raws,
        raw_placeholder_html,
        block_placeholders,
    ) = _embed_raws_in_hidden_text(
        embedded_hidden_text,
        source_raws,
    )
    placeholder_html.extend(raw_placeholder_html)
    paragraphized_hidden_text = _paragraphize_hidden_text(
        embedded_hidden_text,
        placeholder_html,
        block_placeholders,
    )
    return _build_hidden_text(
        paragraphized_hidden_text,
        remaining_links,
        remaining_inline_raws,
        remaining_block_raws,
        asset_hash,
        last_revision_date,
        last_revision_url,
    )

def run_compile(args: Namespace) -> None:
    workspace_base: str = args.workspace_base
    build_base: str = args.build_base
    workspace_name = _resolve_workspace_name(args)
    workspace_path = getattr(args, "workspace_path_override", None)
    if workspace_path is None:
        workspace_path = _resolve_workspace_path(workspace_base, workspace_name)
    workspace_path, temp_workspace_root = _stage_workspace_for_compile(
        workspace_path,
        repo_root=os.getcwd(),
    )

    try:
        os.makedirs(build_base, exist_ok=True)
        output_dir = safe_join_child(build_base, workspace_name)
        reset_directory(output_dir)

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        copied_driver_js = copy_driver_web_js(base_dir, args.root_dir)
        if copied_driver_js:
            print(
                f"Copied {copied_driver_js} driver JS file(s) to '{args.root_dir}'.",
                file=sys.stderr,
            )
        driver_source_bytes, main_typ_abs_path, asset_hash = _prepare_compile_sources(
            base_dir,
            workspace_path,
        )

        posts_dir = os.path.join(args.root_dir, "posts")
        skip_latest = getattr(args, "amend", False)
        publish_date = getattr(args, "publish_date_override", None)
        edited_date = None
        if skip_latest:
            edited_date = getattr(args, "edited_date_override", None) or datetime.now().strftime("%Y-%m-%d")
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
        raw_copy_html = build_raw_copy_assets(source_raws)

        print("Compiling Typst project...", file=sys.stderr)
        initial_hidden_text = _compile_initial_post_html(
            output_dir=output_dir,
            base_dir=base_dir,
            root_dir=args.root_dir,
            driver_source_bytes=driver_source_bytes,
            asset_hash=asset_hash,
            source_links=source_links,
            last_revision_date=last_revision_date,
            last_revision_url=last_revision_url,
            input_values_svg=input_values_svg,
            input_values_pdf=input_values_pdf,
            raw_copy_html=raw_copy_html,
        )

        post_pdf_path = os.path.join(output_dir, f"post.{asset_hash}.pdf")
        final_hidden_text_override = _build_final_hidden_text(
            post_pdf_path,
            source_links,
            source_raws,
            asset_hash,
            last_revision_date,
            last_revision_url,
        )

        index_path = os.path.join(output_dir, "index.html")
        _replace_hidden_block(
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
