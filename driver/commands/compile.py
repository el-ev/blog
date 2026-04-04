import os
import sys
import re
import html
from argparse import Namespace
from typing import List, Tuple, Set, Optional

from .utils import (
    extract_pdf_links,
    extract_pdf_text,
    reset_directory,
    sources_hash,
    find_latest_revision,
    compile_and_build_html,
)


def _extract_source_links(main_typ_source: str) -> List[Tuple[str, str]]:
    source_links: List[Tuple[str, str]] = []
    
    for match in re.finditer(r'#link\("([^"]+)"\)\[([^\]]+)\]', main_typ_source):
        source_links.append((match.group(1), match.group(2)))
        
    for match in re.finditer(r'#link\("([^"]+)"\)', main_typ_source):
        href = match.group(1)
        if not any(existing_href == href for existing_href, _ in source_links):
            source_links.append((href, href))
            
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


def _build_hidden_text(
    inner_hidden: str,
    merged_links: List[Tuple[str, str]],
    asset_hash: str,
    last_revision_date: Optional[str],
    last_revision_url: Optional[str],
) -> str:
    nav_html: List[str] = ["<h2>Navigation</h2>", "<ul>"]
    nav_html.append('<li><a href="../../../index.html">Contents</a></li>')
    nav_html.append(f'<li><a href="post.{asset_hash}.pdf">PDF</a></li>')
    nav_html.append('<li><a href="source/index.html">Source</a></li>')
    
    if last_revision_date and last_revision_url:
        nav_html.append(
            f'<li>Last revision at <a href="{html.escape(last_revision_url)}">{html.escape(last_revision_date)}</a></li>'
        )
    nav_html.append("</ul>")

    hidden_parts: List[str] = []
    if inner_hidden:
        hidden_parts.append(inner_hidden)
    hidden_parts.append("\n".join(nav_html))
    
    if merged_links:
        links_html: List[str] = ["<h2>Links</h2>", "<ul>"]
        for href, label in merged_links:
            links_html.append(
                f'<li><a href="{html.escape(href)}">{html.escape(label)}</a></li>'
            )
        links_html.append("</ul>")
        hidden_parts.append("\n".join(links_html))

    return "\n".join(hidden_parts)


def run_compile(args: Namespace) -> None:
    workspace_base: str = args.workspace_base
    build_base: str = args.build_base
    workspace_name: str = args.name[0]
    workspace_path = os.path.join(workspace_base, workspace_name)
    
    if not os.path.exists(workspace_path):
        print(f"Workspace '{workspace_name}' does not exist.", file=sys.stderr)
        sys.exit(1)
        
    os.makedirs(build_base, exist_ok=True)
    output_dir = os.path.join(build_base, workspace_name)
    reset_directory(output_dir)

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    driver_typ_path = os.path.join(base_dir, "driver.typ")
    template_typ_path = os.path.join(base_dir, "template.typ")
    
    with open(driver_typ_path, "r", encoding="utf-8") as f:
        driver_source = f.read()

    main_typ_abs_path = os.path.abspath(os.path.join(workspace_path, "main.typ"))
    main_typ_path = os.path.relpath(main_typ_abs_path, start=os.getcwd()).replace("\\", "/")
    
    asset_hash = sources_hash([workspace_path, driver_typ_path, template_typ_path])
    driver_source = driver_source.replace("// IMPORT_MAIN", f'#import "{main_typ_path}": *')

    posts_dir = os.path.join(args.root_dir, "posts")

    last_revision_date, last_revision_url = find_latest_revision(posts_dir, workspace_name)

    input_values_svg = {"with_driver": "true", "export_format": "svg"}
    input_values_pdf = {"with_driver": "true", "export_format": "pdf"}
    
    if last_revision_date and last_revision_url:
        input_values_svg["last_revision_date"] = last_revision_date
        input_values_svg["last_revision_url"] = last_revision_url
        input_values_pdf["last_revision_date"] = last_revision_date
        input_values_pdf["last_revision_url"] = last_revision_url

    driver_source_bytes = driver_source.encode()

    with open(main_typ_abs_path, "r", encoding="utf-8") as f:
        main_typ_source = f.read()

    source_links = _extract_source_links(main_typ_source)

    print("Compiling Typst project...", file=sys.stderr)

    template_path = os.path.join(base_dir, "index.template.html")
    
    hidden_text_override = _build_hidden_text(
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
        template_path=template_path,
        dest_dir=output_dir,
        title_format="Blog Page {i}",
        default_title="Blog Post",
        inputs_svg=input_values_svg,
        inputs_pdf=input_values_pdf,
        extract_title_from_pdf=True,
        hidden_text_override=hidden_text_override,
        svg_href_rewrites={"post.pdf": f"post.{asset_hash}.pdf"},
    )
    
    post_pdf_path = os.path.join(output_dir, f"post.{asset_hash}.pdf")
    pdf_links = extract_pdf_links(post_pdf_path)
    merged_links = _merge_links(source_links, pdf_links)

    _, extracted_hidden = extract_pdf_text(
        post_pdf_path,
        extract_title=False,
        default_title="",
    )
    inner_hidden = ""
    prefix = '<div class="sr-only">\n'
    suffix = '\n</div>'
    if extracted_hidden.startswith(prefix) and extracted_hidden.endswith(suffix):
        inner_hidden = extracted_hidden[len(prefix):-len(suffix)]
    elif extracted_hidden:
        inner_hidden = extracted_hidden

    final_hidden_text_override = _build_hidden_text(
        inner_hidden,
        merged_links,
        asset_hash,
        last_revision_date,
        last_revision_url,
    )
    
    index_path = os.path.join(output_dir, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            html_content = f.read()
            
        old_hidden = f'<div class="sr-only">\n{hidden_text_override}\n</div>'
        new_hidden = f'<div class="sr-only">\n{final_hidden_text_override}\n</div>'
        html_content = html_content.replace(old_hidden, new_hidden)
        
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(html_content)
