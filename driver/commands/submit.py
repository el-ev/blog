import os
import sys
import shutil
import hashlib
import html
import json
import re
from datetime import datetime
from argparse import Namespace
from typing import Any, Dict, List, Tuple

from .compile import run_compile
from .update import update_content
from .utils import (
    reset_directory,
    compile_and_build_html,
    validate_workspace_name,
    safe_join_child,
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


def _collect_relative_files(base_dir: str) -> List[str]:
    file_paths: List[str] = []
    for root, _, files in os.walk(base_dir):
        for filename in files:
            abs_path = os.path.join(root, filename)
            rel_path = os.path.relpath(abs_path, start=base_dir).replace("\\", "/")
            file_paths.append(rel_path)
    file_paths.sort()
    return file_paths


def _extract_declared_title(main_typ_path: str, fallback: str) -> str:
    if not os.path.isfile(main_typ_path):
        return fallback
    try:
        with open(main_typ_path, "r", encoding="utf-8") as f:
            source = f.read()
        match = re.search(r'#let\s+title\s*=\s*"([^"]+)"', source)
        if match:
            title = match.group(1).strip()
            if title:
                return title
    except Exception:
        pass
    return fallback


def _extract_post_pdf_name(post_dir: str) -> Tuple[str, str]:
    for filename in sorted(os.listdir(post_dir)):
        if re.match(r"^post\.[^.]+\.pdf$", filename):
            return filename, filename[len("post.") : -len(".pdf")]
    return "post.pdf", "unknown"


def _parse_workspace_revision(entry_name: str, workspace_name: str) -> int:
    if entry_name == workspace_name:
        return 0
    if entry_name.startswith(workspace_name + "-"):
        suffix = entry_name[len(workspace_name) + 1 :]
        return int(suffix)
    raise ValueError("not a matching workspace revision")


def _find_latest_revision_entry(posts_dir: str, workspace_name: str) -> Tuple[str, str, int]:
    if not os.path.isdir(posts_dir):
        raise FileNotFoundError(posts_dir)

    for date_str in sorted(os.listdir(posts_dir), reverse=True):
        date_dir = os.path.join(posts_dir, date_str)
        if not os.path.isdir(date_dir):
            continue

        revisions: List[Tuple[int, str]] = []
        for entry in os.listdir(date_dir):
            entry_path = os.path.join(date_dir, entry)
            if not os.path.isdir(entry_path):
                continue
            try:
                rev = _parse_workspace_revision(entry, workspace_name)
            except ValueError:
                continue
            revisions.append((rev, entry))

        if revisions:
            revisions.sort(key=lambda x: x[0], reverse=True)
            rev, entry = revisions[0]
            return date_str, entry, rev

    raise FileNotFoundError(f"No revisions found for workspace '{workspace_name}'.")


def _write_workspace_manifest(
    manifest_path: str,
    workspace_name: str,
    publish_date: str,
    revision_name: str,
    files: List[str],
) -> None:
    payload: Dict[str, Any] = {
        "workspace": workspace_name,
        "publish_date": publish_date,
        "revision": revision_name,
        "files": files,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _escape_typst_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _build_meta_typst_source(
    template_source: str,
    meta_fields: Dict[str, str],
    source_files: List[str],
) -> str:
    field_lines: List[str] = []
    for key, value in meta_fields.items():
        field_lines.append(f'- *{key}:* {_escape_typst_string(value)}')

    source_lines: List[str] = []
    for rel_path in source_files:
        normalized_path = rel_path.replace("\\", "/")
        escaped_path = _escape_typst_string(normalized_path)
        source_lines.append(f'- #link("source/{escaped_path}")[source/{escaped_path}]')
    if not source_lines:
        source_lines.append("- No files recorded.")

    source = template_source.replace("{{META_FIELDS}}", "\n".join(field_lines))
    source = source.replace("{{SOURCE_FILES}}", "\n".join(source_lines))
    return source


def _build_meta_hidden_text(meta_fields: Dict[str, str], source_files: List[str]) -> str:
    lines: List[str] = ["<h1>Meta</h1>", "<ul>"]
    for key, value in meta_fields.items():
        lines.append(f"<li>{html.escape(key)}: {html.escape(value)}</li>")
    lines.append("</ul>")
    lines.append("<h2>Source Files</h2>")
    lines.append("<ul>")
    for rel_path in source_files:
        safe_path = html.escape(rel_path.replace("\\", "/"))
        lines.append(f'<li><a href="source/{safe_path}">source/{safe_path}</a></li>')
    if not source_files:
        lines.append("<li>No files recorded.</li>")
    lines.append("</ul>")
    return "\n".join(lines)


def _resolve_workspace_name(args: Namespace) -> str:
    try:
        workspace_name = validate_workspace_name(args.name[0])
    except ValueError as e:
        print(f"Invalid workspace name: {e}", file=sys.stderr)
        sys.exit(1)
    args.name[0] = workspace_name
    return workspace_name


def _resolve_new_revision_name(date_dir: str, workspace_name: str) -> Tuple[int, str]:
    os.makedirs(date_dir, exist_ok=True)

    existing_dirs: List[int] = []
    for entry_name in os.listdir(date_dir):
        try:
            existing_dirs.append(_parse_workspace_revision(entry_name, workspace_name))
        except ValueError:
            continue

    max_rev = max(existing_dirs) if existing_dirs else -1
    target_rev = max_rev + 1
    if target_rev == 0:
        return target_rev, workspace_name
    return target_rev, f"{workspace_name}-{target_rev}"


def _resolve_submission_destination(
    posts_dir: str,
    workspace_name: str,
    amend_mode: bool,
    today_str: str,
) -> Tuple[str, str, int, bool]:
    if amend_mode:
        try:
            date_str, dest_dir_name, target_rev = _find_latest_revision_entry(
                posts_dir,
                workspace_name,
            )
            return date_str, dest_dir_name, target_rev, True
        except FileNotFoundError:
            print(
                f"No existing revision found for '{workspace_name}'. "
                "Creating a new revision instead of amending."
            )
            return today_str, workspace_name, 0, False

    date_str = today_str
    date_dir = os.path.join(posts_dir, date_str)
    target_rev, dest_dir_name = _resolve_new_revision_name(date_dir, workspace_name)
    return date_str, dest_dir_name, target_rev, False


def _prepare_submission_tree(
    source_dir: str,
    workspace_path: str,
    dest_dir: str,
) -> str:
    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir)

    shutil.copytree(source_dir, dest_dir)
    source_dest_dir = os.path.join(dest_dir, "source")
    shutil.copytree(workspace_path, source_dest_dir)
    return source_dest_dir


def _compile_filelist_page(
    build_base: str,
    base_dir: str,
    source_dest_dir: str,
) -> None:
    file_entries = _collect_source_entries(source_dest_dir)
    filelist_typst_lines, hidden_text = _build_filelist_markup(file_entries)

    filelist_template_path = os.path.join(base_dir, "filelist.template.typ")
    with open(filelist_template_path, "r", encoding="utf-8") as f:
        filelist_template = f.read()

    parsed_title = "Files"
    title_match = re.search(r'#let\s+title\s*=\s*"([^"]+)"', filelist_template)
    if title_match:
        parsed_title = title_match.group(1)

    hidden_text = f"<h1>{html.escape(parsed_title)}</h1>\n{hidden_text}"
    filelist_source = filelist_template.replace("{{FILES}}", "\n".join(filelist_typst_lines))

    filelist_output_dir = os.path.join(build_base, "filelist")
    reset_directory(filelist_output_dir)

    filelist_hash = hashlib.sha256(filelist_source.encode("utf-8")).hexdigest()[:6]
    template_path = os.path.join(base_dir, "index.template.html")
    index_path = compile_and_build_html(
        source_bytes=filelist_source.encode(),
        output_dir=filelist_output_dir,
        asset_hash=filelist_hash,
        file_prefix="filelist",
        template_path=template_path,
        dest_dir=source_dest_dir,
        title_format="Source Files Page {i}",
        default_title=parsed_title,
        description=parsed_title,
        extract_title_from_pdf=False,
        hidden_text_override=hidden_text,
    )
    shutil.copy2(index_path, os.path.join(filelist_output_dir, "index.html"))


def _build_meta_fields(
    workspace_name: str,
    date_str: str,
    target_rev: int,
    dest_dir_name: str,
    post_title: str,
    pdf_name: str,
    post_source_hash: str,
    workspace_files: List[str],
) -> Dict[str, str]:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "Post Title": post_title,
        "Workspace": workspace_name,
        "Publish Date": date_str,
        "Revision": str(target_rev),
        "Post Directory": f"{date_str}/{dest_dir_name}",
        "PDF Asset": pdf_name,
        "Source Hash": post_source_hash,
        "Generated At": generated_at,
        "Source File Count": str(len(workspace_files)),
    }


def _compile_meta_page(
    build_base: str,
    base_dir: str,
    dest_dir: str,
    post_title: str,
    meta_fields: Dict[str, str],
    workspace_files: List[str],
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
    meta_hash = hashlib.sha256(meta_source.encode("utf-8")).hexdigest()[:6]

    meta_output_dir = os.path.join(build_base, "meta")
    reset_directory(meta_output_dir)
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
        extract_title_from_pdf=False,
        hidden_text_override=meta_hidden_text,
        svg_name_prefix="meta-page",
        html_filename="meta.html",
    )


def run_submit(args: Namespace) -> None:
    workspace_name = _resolve_workspace_name(args)
    run_compile(args)

    source_dir = safe_join_child(args.build_base, workspace_name)
    if not os.path.exists(source_dir):
        print(f"Build directory '{source_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)

    workspace_path = safe_join_child(args.workspace_base, workspace_name)
    workspace_files = _collect_relative_files(workspace_path)

    posts_dir = os.path.join(args.root_dir, "posts")
    today_str = datetime.now().strftime("%Y-%m-%d")
    amend_mode = getattr(args, "amend", False)
    date_str, dest_dir_name, target_rev, did_amend_existing = _resolve_submission_destination(
        posts_dir=posts_dir,
        workspace_name=workspace_name,
        amend_mode=amend_mode,
        today_str=today_str,
    )

    dest_base_dir = os.path.join(posts_dir, date_str)
    os.makedirs(dest_base_dir, exist_ok=True)
    dest_dir = os.path.join(dest_base_dir, dest_dir_name)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    source_dest_dir = _prepare_submission_tree(
        source_dir=source_dir,
        workspace_path=workspace_path,
        dest_dir=dest_dir,
    )
    _compile_filelist_page(
        build_base=args.build_base,
        base_dir=base_dir,
        source_dest_dir=source_dest_dir,
    )

    post_title = _extract_declared_title(
        os.path.join(workspace_path, "main.typ"),
        workspace_name,
    )
    pdf_name, post_asset_hash = _extract_post_pdf_name(dest_dir)
    meta_fields = _build_meta_fields(
        workspace_name=workspace_name,
        date_str=date_str,
        target_rev=target_rev,
        dest_dir_name=dest_dir_name,
        post_title=post_title,
        pdf_name=pdf_name,
        post_source_hash=post_asset_hash,
        workspace_files=workspace_files,
    )
    _compile_meta_page(
        build_base=args.build_base,
        base_dir=base_dir,
        dest_dir=dest_dir,
        post_title=post_title,
        meta_fields=meta_fields,
        workspace_files=workspace_files,
    )

    _write_workspace_manifest(
        manifest_path=os.path.join(source_dest_dir, ".workspace-manifest.json"),
        workspace_name=workspace_name,
        publish_date=date_str,
        revision_name=dest_dir_name,
        files=workspace_files,
    )

    if did_amend_existing:
        print(f"Amended '{workspace_name}' in '{dest_dir}'")
    else:
        print(f"Submitted '{workspace_name}' to '{dest_dir}'")
    
    update_content(args)
