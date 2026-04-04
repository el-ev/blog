import os
import sys
import shutil
import hashlib
import html
import re
from datetime import datetime
from argparse import Namespace
from typing import List, Tuple

from .compile import run_compile
from .update import update_content
from .utils import (
    reset_directory,
    compile_and_build_html,
)


def _collect_source_entries(source_dest_dir: str) -> List[Tuple[str, bool]]:
    file_entries: List[Tuple[str, bool]] = []
    linkable_exts = (".typ", ".txt", ".md", ".py", ".json")
    for root, _, files in os.walk(source_dest_dir):
        for file in files:
            abs_path = os.path.join(root, file)
            rel_path = os.path.relpath(abs_path, start=source_dest_dir).replace("\\", "/")
            file_entries.append((rel_path, file.endswith(linkable_exts)))
    file_entries.sort(key=lambda x: x[0])
    return file_entries


def _build_filelist_markup(file_entries: List[Tuple[str, bool]]) -> Tuple[List[str], str]:
    filelist_typst_lines: List[str] = []
    hidden_items: List[str] = []
    for rel_path, is_linkable in file_entries:
        escaped_rel = html.escape(rel_path)
        if is_linkable:
            filelist_typst_lines.append(f'- #link("{rel_path}")[{rel_path}]')
            hidden_items.append(f'<li><a href="{escaped_rel}">{escaped_rel}</a></li>')
        else:
            filelist_typst_lines.append(f"- [{rel_path}]")
            hidden_items.append(f"<li>{escaped_rel}</li>")

    hidden_text = "<ul>\n" + "\n".join(hidden_items) + "\n</ul>"
    return filelist_typst_lines, hidden_text


def run_submit(args: Namespace) -> None:
    workspace_name: str = args.name[0]

    run_compile(args)

    source_dir = os.path.join(args.build_base, workspace_name)
    if not os.path.exists(source_dir):
        print(f"Build directory '{source_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)

    date_str = datetime.now().strftime("%Y-%m-%d")
    dest_base_dir = os.path.join(args.root_dir, "posts", date_str)

    os.makedirs(dest_base_dir, exist_ok=True)

    existing_dirs: List[int] = []
    for d in os.listdir(dest_base_dir):
        if d == workspace_name:
            existing_dirs.append(0)
        elif d.startswith(workspace_name + "-"):
            try:
                rev = int(d[len(workspace_name) + 1 :])
                existing_dirs.append(rev)
            except ValueError:
                pass

    if existing_dirs:
        max_rev = max(existing_dirs)
    else:
        max_rev = -1

    if getattr(args, 'amend', False) and max_rev >= 0:
        target_rev = max_rev
    else:
        target_rev = max_rev + 1

    if target_rev == 0:
        dest_dir_name = workspace_name
    else:
        dest_dir_name = f"{workspace_name}-{target_rev}"

    dest_dir = os.path.join(dest_base_dir, dest_dir_name)

    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir)

    shutil.copytree(source_dir, dest_dir)
    source_dest_dir = os.path.join(dest_dir, "source")
    
    workspace_path = os.path.join(args.workspace_base, workspace_name)
    shutil.copytree(workspace_path, source_dest_dir)

    file_entries = _collect_source_entries(source_dest_dir)
    filelist_typst_lines, hidden_text = _build_filelist_markup(file_entries)

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    filelist_template_path = os.path.join(base_dir, "filelist.template.typ")

    with open(filelist_template_path, "r", encoding="utf-8") as f:
        filelist_template = f.read()

    parsed_title = "Files"
    title_match = re.search(r'#let\s+title\s*=\s*"([^"]+)"', filelist_template)
    if title_match:
        parsed_title = title_match.group(1)
        
    hidden_text = f"<h1>{html.escape(parsed_title)}</h1>\n" + hidden_text

    filelist_source = filelist_template.replace("{{FILES}}", "\n".join(filelist_typst_lines))

    build_base: str = args.build_base
    output_dir = os.path.join(build_base, "filelist")
    reset_directory(output_dir)

    asset_hash = hashlib.sha256(filelist_source.encode("utf-8")).hexdigest()[:6]
    filelist_source_bytes = filelist_source.encode()
    
    template_path = os.path.join(base_dir, "index.template.html")

    index_path = compile_and_build_html(
        source_bytes=filelist_source_bytes,
        output_dir=output_dir,
        asset_hash=asset_hash,
        file_prefix="filelist",
        template_path=template_path,
        dest_dir=source_dest_dir,
        title_format="Source Files Page {i}",
        default_title="Source Files List",
        extract_title_from_pdf=False,
        hidden_text_override=hidden_text,
    )
    
    shutil.copy2(index_path, os.path.join(output_dir, "index.html"))
    if getattr(args, 'amend', False) and max_rev >= 0:
        print(f"Amended '{workspace_name}' in '{dest_dir}'")
    else:
        print(f"Submitted '{workspace_name}' to '{dest_dir}'")
    
    update_content(args)