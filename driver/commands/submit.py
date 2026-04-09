import os
import sys
import shutil
import html
import json
import re
import tempfile
from datetime import datetime
from argparse import Namespace
from typing import Any, Dict, List, Optional, Set, Tuple

from .compile import run_compile
from .update import update_content
from .utils import (
    build_raw_copy_assets,
    reset_directory,
    compile_and_build_html,
    extract_declared_typst_string,
    extract_typst_raws_from_content,
    hash_text_with_sources,
    validate_workspace_name,
    safe_join_child,
    rewrite_clipboard_script_src,
)


_META_CODE_FIELD_PATTERN = re.compile(
    r"<li>\s*([^:<]+):\s*<code>(.*?)</code>\s*</li>",
    re.IGNORECASE | re.DOTALL,
)
_GENERATED_SOURCE_BUNDLE_FILES = {
    ".workspace-manifest.json",
    "index.html",
}


def _normalize_relative_paths(paths: List[str]) -> List[str]:
    normalized_paths: List[str] = []
    seen: Set[str] = set()
    for raw_path in paths:
        normalized = str(raw_path).replace("\\", "/").strip()
        if not normalized or normalized == ".":
            continue
        if normalized.startswith("/") or normalized.startswith("../") or "/../" in normalized:
            continue
        if normalized.startswith("./"):
            normalized = normalized[2:]
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        normalized_paths.append(normalized)
    normalized_paths.sort()
    return normalized_paths


def _manifest_source_files(source_dir: str) -> List[str]:
    manifest_data = _load_manifest_data(source_dir)
    raw_files = manifest_data.get("files")
    if not isinstance(raw_files, list):
        return []
    normalized_files = _normalize_relative_paths(
        [path for path in raw_files if isinstance(path, str)]
    )
    return [
        path for path in normalized_files
        if path not in _GENERATED_SOURCE_BUNDLE_FILES
    ]


def _build_filelist_markup(file_paths: List[str]) -> Tuple[List[str], str]:
    filelist_typst_lines: List[str] = []
    hidden_items: List[str] = []
    linkable_exts = (".typ", ".txt", ".md", ".py", ".json")
    for rel_path in file_paths:
        escaped_rel = html.escape(rel_path)
        is_linkable = rel_path.endswith(linkable_exts)
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
    return _normalize_relative_paths(file_paths)


def _extract_post_headers(main_typ_path: str, fallback_title: str) -> Tuple[str, Optional[str]]:
    title = extract_declared_typst_string(main_typ_path, "title") or fallback_title
    subtitle = extract_declared_typst_string(main_typ_path, "subtitle")
    return title, subtitle


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


def _load_manifest_data(source_dir: str) -> Dict[str, Any]:
    manifest_path = os.path.join(source_dir, ".workspace-manifest.json")
    if not os.path.isfile(manifest_path):
        return {}
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_meta_fields(post_dir: str) -> Dict[str, str]:
    meta_path = os.path.join(post_dir, "meta.html")
    if not os.path.isfile(meta_path):
        return {}
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta_html = f.read()
    except Exception:
        return {}

    fields: Dict[str, str] = {}
    for key, value in _META_CODE_FIELD_PATTERN.findall(meta_html):
        fields[key.strip()] = html.unescape(value.strip())
    return fields


def _base_workspace_name_from_dir(entry_name: str) -> str:
    match = re.match(r"^(.*)-(\d+)$", entry_name)
    if match:
        return match.group(1)
    return entry_name


def _resolve_existing_post_metadata(
    post_dir: str,
    date_str: str,
    entry_name: str,
) -> Tuple[str, str, int]:
    source_dir = os.path.join(post_dir, "source")
    manifest_data = _load_manifest_data(source_dir)
    meta_fields = _load_meta_fields(post_dir)

    workspace_name_raw = (
        manifest_data.get("workspace")
        or meta_fields.get("Workspace Name")
        or _base_workspace_name_from_dir(entry_name)
    )
    workspace_name = validate_workspace_name(str(workspace_name_raw))

    publish_date_raw = (
        manifest_data.get("publish_date")
        or meta_fields.get("Publish Date")
        or date_str
    )
    publish_date = str(publish_date_raw)

    revision_raw = manifest_data.get("revision") or meta_fields.get("Revision")
    if revision_raw is not None:
        try:
            revision = int(revision_raw)
        except (TypeError, ValueError):
            revision = _parse_workspace_revision(entry_name, workspace_name)
    else:
        revision = _parse_workspace_revision(entry_name, workspace_name)

    return workspace_name, publish_date, revision


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


def _inline_code_typst(value: str) -> str:
    return f'#raw("{_escape_typst_string(value)}", block: false)'


def _build_meta_typst_source(
    template_source: str,
    meta_fields: Dict[str, str],
    source_files: List[str],
) -> str:
    field_lines: List[str] = []
    for key, value in meta_fields.items():
        field_lines.append(f'- *{key}:* {_inline_code_typst(value)}')

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
        lines.append(f"<li>{html.escape(key)}: <code>{html.escape(value)}</code></li>")
    lines.append("</ul>")
    lines.append("<h2>Source Files</h2>")
    lines.append("<ul>")
    for rel_path in source_files:
        safe_path = html.escape(rel_path.replace("\\", "/"))
        lines.append(
            f'<li><a href="source/{safe_path}">source/{safe_path}</a></li>'
        )
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


def _build_compile_args(
    args: Namespace,
    workspace_name: str,
    workspace_path: str,
    publish_date: str,
    amend_mode: bool,
) -> Namespace:
    compile_args = Namespace(**vars(args))
    compile_args.name = [workspace_name]
    compile_args.amend = amend_mode
    compile_args.workspace_path_override = workspace_path
    compile_args.publish_date_override = publish_date
    return compile_args


def _stage_workspace_if_needed(workspace_path: str, dest_dir: str) -> Tuple[str, Optional[str]]:
    manifest_files = _manifest_source_files(workspace_path)
    if manifest_files:
        temp_root = tempfile.mkdtemp(prefix=".amend-workspace-", dir=os.getcwd())
        staged_path = os.path.join(temp_root, os.path.basename(os.path.abspath(workspace_path)))
        os.makedirs(staged_path, exist_ok=True)

        copied_any = False
        for rel_path in manifest_files:
            src_path = safe_join_child(workspace_path, rel_path)
            if not os.path.isfile(src_path):
                continue
            dst_path = safe_join_child(staged_path, rel_path)
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            shutil.copy2(src_path, dst_path)
            copied_any = True

        if copied_any:
            return staged_path, temp_root

        shutil.rmtree(temp_root, ignore_errors=True)

    workspace_abs = os.path.abspath(workspace_path)
    dest_abs = os.path.abspath(dest_dir)
    try:
        if os.path.commonpath([workspace_abs, dest_abs]) != dest_abs:
            return workspace_path, None
    except ValueError:
        return workspace_path, None

    temp_root = tempfile.mkdtemp(prefix=".amend-workspace-", dir=os.getcwd())
    staged_path = os.path.join(temp_root, os.path.basename(workspace_abs))
    shutil.copytree(workspace_abs, staged_path)
    return staged_path, temp_root


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
    root_dir: str,
    source_dest_dir: str,
    workspace_files: List[str],
) -> None:
    filelist_typst_lines, hidden_text = _build_filelist_markup(workspace_files)

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

    template_typ_path = os.path.join(base_dir, "template.typ")
    filelist_hash = hash_text_with_sources(
        filelist_source,
        [template_typ_path],
    )
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
        clipboard_asset_path=os.path.join(root_dir, "clipboard.min.js"),
    )
    shutil.copy2(index_path, os.path.join(filelist_output_dir, "index.html"))


def _build_meta_fields(
    workspace_name: str,
    date_str: str,
    target_rev: int,
    dest_dir_name: str,
    post_title: str,
    post_subtitle: Optional[str],
    pdf_name: str,
    post_source_hash: str,
    workspace_files: List[str],
) -> Dict[str, str]:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fields = {
        "Post Title": post_title,
        "Workspace Name": workspace_name,
        "Publish Date": date_str,
        "Revision": str(target_rev),
        "Post Path": f"{date_str}/{dest_dir_name}",
        "PDF Asset": pdf_name,
        "Source Hash": post_source_hash,
        "Generated At": generated_at,
        "Source File Count": str(len(workspace_files)),
    }
    if post_subtitle:
        fields["Post Subtitle"] = post_subtitle
    return fields


def _compile_meta_page(
    build_base: str,
    base_dir: str,
    root_dir: str,
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
    template_typ_path = os.path.join(base_dir, "template.typ")
    meta_hash = hash_text_with_sources(
        meta_source,
        [template_typ_path],
    )
    input_values_svg: Dict[str, str] = {"with_driver": "true", "export_format": "svg"}
    input_values_pdf: Dict[str, str] = {"with_driver": "true", "export_format": "pdf"}
    meta_raws = extract_typst_raws_from_content(
        meta_source,
        query_root=os.getcwd(),
        inputs=input_values_svg,
    )
    raw_copy_html = build_raw_copy_assets(meta_raws)

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
        inputs_svg=input_values_svg,
        inputs_pdf=input_values_pdf,
        extract_title_from_pdf=False,
        hidden_text_override=meta_hidden_text,
        raw_copy_html=raw_copy_html,
        svg_name_prefix="meta-page",
        html_filename="meta.html",
        clipboard_asset_path=os.path.join(root_dir, "clipboard.min.js"),
    )


def _submit_to_destination(
    args: Namespace,
    workspace_name: str,
    workspace_path: str,
    date_str: str,
    dest_dir_name: str,
    target_rev: int,
    amend_mode: bool,
) -> None:
    posts_dir = os.path.join(args.root_dir, "posts")
    dest_base_dir = os.path.join(posts_dir, date_str)
    os.makedirs(dest_base_dir, exist_ok=True)
    dest_dir = os.path.join(dest_base_dir, dest_dir_name)

    staged_workspace_path, temp_root = _stage_workspace_if_needed(workspace_path, dest_dir)
    try:
        run_compile(
            _build_compile_args(
                args=args,
                workspace_name=workspace_name,
                workspace_path=staged_workspace_path,
                publish_date=date_str,
                amend_mode=amend_mode,
            )
        )

        source_dir = safe_join_child(args.build_base, workspace_name)
        if not os.path.exists(source_dir):
            print(f"Build directory '{source_dir}' does not exist.", file=sys.stderr)
            sys.exit(1)

        workspace_files = _collect_relative_files(staged_workspace_path)
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        source_dest_dir = _prepare_submission_tree(
            source_dir=source_dir,
            workspace_path=staged_workspace_path,
            dest_dir=dest_dir,
        )
        _compile_filelist_page(
            build_base=args.build_base,
            base_dir=base_dir,
            root_dir=args.root_dir,
            source_dest_dir=source_dest_dir,
            workspace_files=workspace_files,
        )

        post_title, post_subtitle = _extract_post_headers(
            os.path.join(staged_workspace_path, "main.typ"),
            workspace_name,
        )
        pdf_name, post_asset_hash = _extract_post_pdf_name(dest_dir)
        meta_fields = _build_meta_fields(
            workspace_name=workspace_name,
            date_str=date_str,
            target_rev=target_rev,
            dest_dir_name=dest_dir_name,
            post_title=post_title,
            post_subtitle=post_subtitle,
            pdf_name=pdf_name,
            post_source_hash=post_asset_hash,
            workspace_files=workspace_files,
        )
        _compile_meta_page(
            build_base=args.build_base,
            base_dir=base_dir,
            root_dir=args.root_dir,
            dest_dir=dest_dir,
            post_title=post_title,
            meta_fields=meta_fields,
            workspace_files=workspace_files,
        )
        rewrite_clipboard_script_src(
            os.path.join(dest_dir, "index.html"),
            os.path.join(args.root_dir, "clipboard.min.js"),
        )
        _write_workspace_manifest(
            manifest_path=os.path.join(source_dest_dir, ".workspace-manifest.json"),
            workspace_name=workspace_name,
            publish_date=date_str,
            revision_name=dest_dir_name,
            files=workspace_files,
        )
    finally:
        if temp_root is not None:
            shutil.rmtree(temp_root, ignore_errors=True)


def _collect_published_workspaces(posts_dir: str) -> List[str]:
    workspaces: Set[str] = set()
    if not os.path.isdir(posts_dir):
        return []

    for date_str in os.listdir(posts_dir):
        date_dir = os.path.join(posts_dir, date_str)
        if not os.path.isdir(date_dir):
            continue
        for entry_name in os.listdir(date_dir):
            post_dir = os.path.join(date_dir, entry_name)
            if not os.path.isdir(post_dir):
                continue
            try:
                workspace_name, _, _ = _resolve_existing_post_metadata(
                    post_dir=post_dir,
                    date_str=date_str,
                    entry_name=entry_name,
                )
            except Exception:
                continue
            workspaces.add(workspace_name)

    return sorted(workspaces)


def run_submit(args: Namespace) -> None:
    workspace_name = _resolve_workspace_name(args)
    workspace_path = safe_join_child(args.workspace_base, workspace_name)
    posts_dir = os.path.join(args.root_dir, "posts")
    today_str = datetime.now().strftime("%Y-%m-%d")
    amend_mode = getattr(args, "amend", False)
    date_str, dest_dir_name, target_rev, did_amend_existing = _resolve_submission_destination(
        posts_dir=posts_dir,
        workspace_name=workspace_name,
        amend_mode=amend_mode,
        today_str=today_str,
    )
    _submit_to_destination(
        args=args,
        workspace_name=workspace_name,
        workspace_path=workspace_path,
        date_str=date_str,
        dest_dir_name=dest_dir_name,
        target_rev=target_rev,
        amend_mode=did_amend_existing,
    )

    if did_amend_existing:
        print(f"Amended '{workspace_name}' in '{os.path.join(posts_dir, date_str, dest_dir_name)}'")
    else:
        print(f"Submitted '{workspace_name}' to '{os.path.join(posts_dir, date_str, dest_dir_name)}'")
    
    update_content(args)


def run_amend_all(args: Namespace) -> None:
    posts_dir = os.path.join(args.root_dir, "posts")
    workspaces = _collect_published_workspaces(posts_dir)
    if not workspaces:
        print(f"No published workspaces found in '{posts_dir}'.")
        return

    amended_count = 0
    for workspace_name in workspaces:
        date_str, dest_dir_name, target_rev = _find_latest_revision_entry(posts_dir, workspace_name)
        post_dir = os.path.join(posts_dir, date_str, dest_dir_name)
        source_dir = os.path.join(post_dir, "source")
        if not os.path.isdir(source_dir):
            print(f"Skipping '{workspace_name}': '{source_dir}' does not exist.", file=sys.stderr)
            continue

        _, publish_date, revision = _resolve_existing_post_metadata(
            post_dir=post_dir,
            date_str=date_str,
            entry_name=dest_dir_name,
        )
        _submit_to_destination(
            args=args,
            workspace_name=workspace_name,
            workspace_path=source_dir,
            date_str=publish_date,
            dest_dir_name=dest_dir_name,
            target_rev=revision if revision == target_rev else target_rev,
            amend_mode=True,
        )
        amended_count += 1
        print(f"Amended '{workspace_name}' in '{post_dir}'")

    update_content(args)
    print(f"Amended {amended_count} published workspace(s).")
