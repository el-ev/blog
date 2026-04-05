import os
import sys
import re
import html
from argparse import Namespace
from typing import Dict, List, Optional, Set, Tuple

from .utils import (
    extract_pdf_links,
    extract_pdf_text,
    reset_directory,
    sources_hash,
    find_latest_revision,
    compile_and_build_html,
    validate_workspace_name,
    safe_join_child,
)


def _extract_source_links(main_typ_source: str) -> List[Tuple[str, str]]:
    source_links: List[Tuple[str, str]] = []
    seen_hrefs: Set[str] = set()

    def _append_unique(href: str, label: str) -> None:
        if not href or href in seen_hrefs:
            return
        seen_hrefs.add(href)
        source_links.append((href, label if label else href))

    # #link("href", "label")
    for match in re.finditer(r'#link\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)', main_typ_source):
        _append_unique(match.group(1), match.group(2))

    # #link("href")[label]
    for match in re.finditer(r'#link\("([^"]+)"\)\[([^\]]+)\]', main_typ_source):
        _append_unique(match.group(1), match.group(2))

    # #link("href")
    for match in re.finditer(r'#link\("([^"]+)"\)', main_typ_source):
        _append_unique(match.group(1), match.group(1))

    return source_links


def _merge_links(*links_groups: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    merged_links: List[Tuple[str, str]] = []
    seen_hrefs: Set[str] = set()
    for group in links_groups:
        for href, label in group:
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            merged_links.append((href, label))
    return merged_links

def _replace_first_outside_tags(text: str, old: str, new: str) -> Tuple[str, bool]:
    if not old:
        return text, False

    parts = re.split(r"(<[^>]+>)", text)
    anchor_depth = 0
    for i, part in enumerate(parts):
        if i % 2 == 1:
            tag = part.lower()
            if re.match(r"<a\b", tag):
                anchor_depth += 1
            elif re.match(r"</a\b", tag) and anchor_depth > 0:
                anchor_depth -= 1
            continue

        if anchor_depth > 0:
            continue

        idx = part.find(old)
        if idx >= 0:
            parts[i] = part[:idx] + new + part[idx + len(old) :]
            return "".join(parts), True
    return text, False


def _embed_links_in_hidden_text(
    inner_hidden: str,
    merged_links: List[Tuple[str, str]],
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
            text, replaced = _replace_first_outside_tags(text, escaped_candidate, anchor)
            if replaced:
                placed = True
                break

        if not placed:
            remaining_links.append((href, label or href))

    return text, remaining_links


def _build_hidden_text(
    inner_hidden: str,
    remaining_links: List[Tuple[str, str]],
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


def _build_typst_inputs(
    last_revision_date: Optional[str],
    last_revision_url: Optional[str],
) -> Tuple[Dict[str, str], Dict[str, str]]:
    input_values_svg: Dict[str, str] = {"with_driver": "true", "export_format": "svg"}
    input_values_pdf: Dict[str, str] = {"with_driver": "true", "export_format": "pdf"}
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
) -> str:
    initial_hidden_text = _build_hidden_text(
        "",
        source_links,
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
        svg_href_rewrites={"post.pdf": f"post.{asset_hash}.pdf"},
    )
    return initial_hidden_text


def _build_final_hidden_text(
    post_pdf_path: str,
    source_links: List[Tuple[str, str]],
    asset_hash: str,
    last_revision_date: Optional[str],
    last_revision_url: Optional[str],
) -> str:
    pdf_links = extract_pdf_links(post_pdf_path)
    merged_links = _merge_links(source_links, pdf_links)

    _, extracted_hidden = extract_pdf_text(
        post_pdf_path,
        extract_title=False,
        default_title="",
    )
    inner_hidden = _extract_inner_hidden_text(extracted_hidden)
    embedded_hidden_text, remaining_links = _embed_links_in_hidden_text(
        inner_hidden,
        merged_links,
    )
    return _build_hidden_text(
        embedded_hidden_text,
        remaining_links,
        asset_hash,
        last_revision_date,
        last_revision_url,
    )

def run_compile(args: Namespace) -> None:
    workspace_base: str = args.workspace_base
    build_base: str = args.build_base
    workspace_name = _resolve_workspace_name(args)
    workspace_path = _resolve_workspace_path(workspace_base, workspace_name)

    os.makedirs(build_base, exist_ok=True)
    output_dir = safe_join_child(build_base, workspace_name)
    reset_directory(output_dir)

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    driver_source_bytes, main_typ_abs_path, asset_hash = _prepare_compile_sources(
        base_dir,
        workspace_path,
    )

    posts_dir = os.path.join(args.root_dir, "posts")
    skip_latest = getattr(args, "amend", False)
    last_revision_date, last_revision_url = find_latest_revision(
        posts_dir,
        workspace_name,
        skip_latest=skip_latest,
    )
    input_values_svg, input_values_pdf = _build_typst_inputs(
        last_revision_date,
        last_revision_url,
    )

    with open(main_typ_abs_path, "r", encoding="utf-8") as f:
        main_typ_source = f.read()

    source_links = _extract_source_links(main_typ_source)

    print("Compiling Typst project...", file=sys.stderr)
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
    )

    post_pdf_path = os.path.join(output_dir, f"post.{asset_hash}.pdf")
    final_hidden_text_override = _build_final_hidden_text(
        post_pdf_path,
        source_links,
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
