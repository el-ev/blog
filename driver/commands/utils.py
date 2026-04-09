import os
import re
import html
import hashlib
import shutil
import subprocess
import sys
import json
import tempfile
from typing import Optional, List, Tuple, Dict, Set, Union
from typing import Any


_typst_path: Optional[str] = None
_WORKSPACE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_TYPST_DECLARED_STRING_PATTERN_TEMPLATE = r'#let\s+{name}\s*=\s*"([^"]*)"'
WORKSPACE_PUBLIC_DIR_NAME = "public"
_SVGO_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "svgo.config.mjs",
)


def make_raw_copy_id(text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    return f"raw-copy-{digest}"


def _resolve_typst_path() -> str:
    global _typst_path
    if _typst_path is None:
        _typst_path = shutil.which("typst") or shutil.which("typst.exe")
    if not _typst_path:
        print("Typst executable not found in PATH.")
        sys.exit(1)
    return _typst_path


def reset_directory(path: str) -> None:
    os.makedirs(path, exist_ok=True)
    if os.listdir(path):
        shutil.rmtree(path)
        os.makedirs(path, exist_ok=True)


def validate_workspace_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ValueError("Workspace name must not be empty.")
    if normalized in {".", ".."}:
        raise ValueError("Workspace name cannot be '.' or '..'.")
    if "/" in normalized or "\\" in normalized:
        raise ValueError("Workspace name must not contain path separators.")
    if not _WORKSPACE_NAME_PATTERN.fullmatch(normalized):
        raise ValueError(
            "Workspace name may only contain letters, numbers, dots, underscores, and hyphens."
        )
    return normalized


def safe_join_child(base_dir: str, child_name: str) -> str:
    base_abs = os.path.abspath(base_dir)
    child_abs = os.path.abspath(os.path.join(base_abs, child_name))
    if os.path.commonpath([base_abs, child_abs]) != base_abs:
        raise ValueError(f"Resolved path escapes base directory: {base_dir}")
    return child_abs


def build_relative_href(from_dir: str, target_path: str) -> str:
    rel_path = os.path.relpath(target_path, start=from_dir).replace("\\", "/")
    if not rel_path.startswith("."):
        return f"./{rel_path}"
    return rel_path


def extract_declared_typst_string_from_source(source: str, name: str) -> Optional[str]:
    pattern = re.compile(_TYPST_DECLARED_STRING_PATTERN_TEMPLATE.format(name=re.escape(name)))
    match = pattern.search(source)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def extract_declared_typst_string(path: str, name: str) -> Optional[str]:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return extract_declared_typst_string_from_source(f.read(), name)
    except Exception:
        return None


def copy_driver_web_js(driver_dir: str, webroot_dir: str) -> int:
    if not os.path.isdir(driver_dir):
        return 0

    os.makedirs(webroot_dir, exist_ok=True)
    copied_count = 0
    for filename in sorted(os.listdir(driver_dir)):
        if not filename.endswith(".js"):
            continue

        src_path = os.path.join(driver_dir, filename)
        if not os.path.isfile(src_path):
            continue

        dst_path = safe_join_child(webroot_dir, filename)
        shutil.copy2(src_path, dst_path)
        copied_count += 1

    return copied_count


def run_typst_compile(
    source_bytes: bytes,
    output_path: str,
    export_format: str,
    inputs: Optional[Dict[str, str]] = None,
) -> None:
    command = [
        _resolve_typst_path(),
        "compile",
        "-",
        output_path,
        "--format",
        export_format,
    ]
    if inputs:
        for key, value in inputs.items():
            command.extend(["--input", f"{key}={value}"])

    try:
        subprocess.run(
            command,
            check=True,
            input=source_bytes,
        )
    except subprocess.CalledProcessError as e:
        print(f"Typst compilation failed for {output_path} (exit code {e.returncode})", file=sys.stderr)
        if e.stderr:
            print(e.stderr.decode("utf-8"), file=sys.stderr)
        elif e.output:
            print(e.output.decode("utf-8"), file=sys.stderr)
        raise RuntimeError(f"Typst compilation failed. Exit code {e.returncode}") from e


def _flatten_query_text(node: Any) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_flatten_query_text(item) for item in node)
    if isinstance(node, dict):
        parts: List[str] = []
        text = node.get("text")
        if isinstance(text, str):
            parts.append(text)
        for key in ("body", "children", "child", "value", "values", "content"):
            if key in node:
                parts.append(_flatten_query_text(node[key]))
        if not parts:
            for value in node.values():
                parts.append(_flatten_query_text(value))
        return "".join(parts)
    return ""


def extract_typst_links(
    main_typ_path: str,
    query_root: str,
    inputs: Optional[Dict[str, str]] = None,
) -> List[Tuple[str, str]]:
    links: List[Tuple[str, str]] = []
    seen: Set[str] = set()

    abs_main_typ = os.path.abspath(main_typ_path)
    abs_query_root = os.path.abspath(query_root)
    query_input = os.path.relpath(abs_main_typ, start=abs_query_root).replace("\\", "/")

    command = [
        _resolve_typst_path(),
        "query",
        query_input,
        "link",
        "--root",
        abs_query_root,
        "--format",
        "json",
    ]
    if inputs:
        for key, value in inputs.items():
            command.extend(["--input", f"{key}={value}"])

    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Failed to query links from Typst source: {e}", file=sys.stderr)
        stderr = (e.stderr or "").strip()
        if stderr:
            print(stderr, file=sys.stderr)
        return links

    raw = result.stdout.strip()
    if not raw:
        return links

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Failed to parse Typst query output: {e}", file=sys.stderr)
        return links

    if not isinstance(data, list):
        return links

    for item in data:
        if not isinstance(item, dict):
            continue
        href = item.get("dest")
        if not isinstance(href, str) or not href or href in seen:
            continue

        label = re.sub(r"\s+", " ", _flatten_query_text(item.get("body"))).strip()
        if not label:
            label = href

        seen.add(href)
        links.append((href, label))

    return links


def extract_typst_raws(
    main_typ_path: str,
    query_root: str,
    inputs: Optional[Dict[str, str]] = None,
) -> List[Tuple[str, bool]]:
    raws: List[Tuple[str, bool]] = []

    abs_main_typ = os.path.abspath(main_typ_path)
    abs_query_root = os.path.abspath(query_root)
    query_input = os.path.relpath(abs_main_typ, start=abs_query_root).replace("\\", "/")

    command = [
        _resolve_typst_path(),
        "query",
        query_input,
        "raw",
        "--root",
        abs_query_root,
        "--format",
        "json",
    ]
    if inputs:
        for key, value in inputs.items():
            command.extend(["--input", f"{key}={value}"])

    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Failed to query raw elements from Typst source: {e}", file=sys.stderr)
        stderr = (e.stderr or "").strip()
        if stderr:
            print(stderr, file=sys.stderr)
        return raws

    raw = result.stdout.strip()
    if not raw:
        return raws

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Failed to parse Typst raw query output: {e}", file=sys.stderr)
        return raws

    if not isinstance(data, list):
        return raws

    for item in data:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        is_block = bool(item.get("block", False))
        raws.append((text, is_block))

    return raws


def extract_typst_raws_from_content(
    source_content: Union[str, bytes],
    query_root: str,
    inputs: Optional[Dict[str, str]] = None,
) -> List[Tuple[str, bool]]:
    temp_query_path = ""
    try:
        if isinstance(source_content, bytes):
            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=".typ",
                prefix=".raw-query-",
                dir=query_root,
                delete=False,
            ) as temp_file:
                temp_file.write(source_content)
                temp_query_path = temp_file.name
        else:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".typ",
                prefix=".raw-query-",
                dir=query_root,
                delete=False,
                encoding="utf-8",
            ) as temp_file:
                temp_file.write(source_content)
                temp_query_path = temp_file.name

        return extract_typst_raws(
            temp_query_path,
            query_root=query_root,
            inputs=inputs,
        )
    finally:
        if temp_query_path and os.path.exists(temp_query_path):
            os.remove(temp_query_path)


def build_raw_copy_assets(raw_entries: List[Tuple[str, bool]]) -> str:
    raw_copy_ids = [make_raw_copy_id(text) for text, _ in raw_entries]
    raw_texts = {
        raw_copy_id: text
        for raw_copy_id, (text, _) in zip(raw_copy_ids, raw_entries)
    }
    json_payload = json.dumps(raw_texts, ensure_ascii=False).replace("</", "<\\/")
    raw_copy_html = (
        f'<script id="raw-copy-data" type="application/json">{json_payload}</script>'
    )
    return raw_copy_html


def _collect_typ_files(paths: List[str]) -> List[str]:
    typ_files: List[str] = []

    for path in paths:
        if not path:
            continue
        if os.path.isfile(path) and path.endswith(".typ"):
            typ_files.append(os.path.abspath(path))
            continue
        if os.path.isdir(path):
            for root, _, files in os.walk(path):
                for name in files:
                    if name.endswith(".typ"):
                        typ_files.append(os.path.abspath(os.path.join(root, name)))

    return sorted(set(typ_files))


def _update_hash_with_typ_files(hasher: "hashlib._Hash", paths: List[str]) -> None:
    typ_files = _collect_typ_files(paths)
    for file_path in typ_files:
        rel_path = os.path.relpath(file_path, start=os.getcwd()).replace("\\", "/")
        hasher.update(rel_path.encode("utf-8"))
        with open(file_path, "rb") as f:
            hasher.update(f.read())


def sources_hash(paths: List[str], length: int = 6) -> str:
    hasher = hashlib.sha256()
    _update_hash_with_typ_files(hasher, paths)
    return hasher.hexdigest()[:length]


def hash_text_with_sources(text: str, paths: List[str], length: int = 6) -> str:
    hasher = hashlib.sha256()
    hasher.update(text.encode("utf-8"))
    _update_hash_with_typ_files(hasher, paths)

    return hasher.hexdigest()[:length]


def extract_pdf_text(
    pdf_path: str,
    extract_title: bool = False,
    default_title: str = "",
) -> Tuple[str, str]:
    title: str = default_title
    hidden_text: str = ""
    try:
        import pymupdf
        from typing import cast, Any
        
        if os.path.exists(pdf_path):
            doc = pymupdf.open(pdf_path)
            doc_any = cast(Any, doc)
            raw_text = "".join(page.get_text() for page in doc_any)
            if extract_title:
                lines = raw_text.strip().split("\n")
                if lines:
                    title = lines[0].strip()
            hidden_text = f'<div class="sr-only">\n{html.escape(raw_text)}\n</div>'
    except Exception as e:
        print(f"Failed to extract text from PDF: {e}", file=sys.stderr)
    return title, hidden_text


def rewrite_clipboard_script_src(html_path: str, clipboard_asset_path: str) -> bool:
    if not os.path.isfile(html_path):
        return False

    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    clipboard_src = build_relative_href(
        os.path.dirname(html_path),
        clipboard_asset_path,
    )
    updated_html = re.sub(
        r'(<script\s+src=")[^"]*clipboard\.min\.js(")',
        rf"\1{clipboard_src}\2",
        html_content,
        count=1,
    )
    if updated_html == html_content:
        return False

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(updated_html)
    return True


def _is_generated_svg(filename: str, svg_name_prefix: str = "page") -> bool:
    return bool(
        re.match(
            rf"^{re.escape(svg_name_prefix)}\d+(?:\.[^.]+)?\.svg$",
            filename,
        )
    )


def patch_svg_file(
    src_path: str,
    dst_path: str,
    svg_href_rewrites: Optional[Dict[str, str]],
) -> Tuple[str, str]:
    with open(src_path, "r", encoding="utf-8") as svg_file:
        svg_data = svg_file.read()

    aspect_ratio = "auto"
    max_width_style = ""
    match_w = re.search(r'<svg[^>]*?\swidth="([^"]+)"', svg_data)
    match_vb = re.search(
        r'<svg[^>]*?\sviewBox="[^"]+\s+[^"]+\s+([\d\.]+)\s+([\d\.]+)"', svg_data
    )

    svg_data = re.sub(
        r'(<svg[^>]*?)\swidth="[^"]+"', r'\1 width="100%"', svg_data, count=1
    )
    svg_data = re.sub(
        r'(<svg[^>]*?)\sheight="[^"]+"', r'\1 height="100%"', svg_data, count=1
    )

    if svg_href_rewrites:
        def _rewrite_href(match: re.Match) -> str:
            attr = match.group(1)
            value = match.group(2)
            safe_rewrites: Dict[str, str] = svg_href_rewrites or {}
            return f'{attr}="{safe_rewrites.get(value, value)}"'

        svg_data = re.sub(
            r'(xlink:href|href)="([^"]+)"',
            _rewrite_href,
            svg_data,
        )

    def _rewrite_anchor_tag(match: re.Match) -> str:
        attrs = match.group(1)
        raw_copy_match = re.search(
            r'\s+(?:xlink:href|href)="javascript:parent.copyCode\(\"raw-copy-[0-9a-f]{10}\"\)"',
            attrs,
        )
        if raw_copy_match:
            return f"<a{attrs}>"

        if re.search(r'\s+target="[^"]*"', attrs):
            return f"<a{attrs}>"
        return f'<a target="_top"{attrs}>'

    svg_data = re.sub(r"<a([^>]*)>", _rewrite_anchor_tag, svg_data)
    svg_data = re.sub(r'\sclass="[^"]+"', "", svg_data)

    with open(dst_path, "w", encoding="utf-8") as svg_file:
        svg_file.write(svg_data)

    svgo_path = shutil.which("svgo") or shutil.which("svgo.cmd")
    if svgo_path:
        command = [
            svgo_path,
            dst_path,
            "-o",
            dst_path,
            "--multipass",
            "--precision",
            "2",
        ]
        if os.path.isfile(_SVGO_CONFIG_PATH):
            command.extend(["--config", _SVGO_CONFIG_PATH])

        try:
            subprocess.run(command, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            print(f"Aggressive SVGO failed for {dst_path}; retrying with defaults.", file=sys.stderr)
            if e.stderr:
                print(e.stderr.decode("utf-8"), file=sys.stderr)
            try:
                subprocess.run([svgo_path, dst_path, "-o", dst_path], check=True, capture_output=True)
            except subprocess.CalledProcessError as fallback_error:
                print(f"SVGO failed for {dst_path}", file=sys.stderr)
                if fallback_error.stderr:
                    print(fallback_error.stderr.decode("utf-8"), file=sys.stderr)
    else:
        print("SVGO not found, skipping SVG optimization.", file=sys.stderr)

    if match_vb:
        w, h = float(match_vb.group(1)), float(match_vb.group(2))
        aspect_ratio = f"{w} / {h}"
    if match_w:
        max_width_style = f"max-width: {match_w.group(1)}; width: 100%;"

    return aspect_ratio, max_width_style


def build_html_from_svgs(
    template_path: str,
    output_dir: str,
    dest_dir: str,
    page_count: int,
    title_format: str,
    pdf_path: Optional[str] = None,
    svg_href_rewrites: Optional[Dict[str, str]] = None,
    extract_title_from_pdf: bool = False,
    default_title: str = "Blog Post",
    description: Optional[str] = None,
    hidden_text_override: Optional[str] = None,
    raw_copy_html: str = "",
    top_bar_html: str = "",
    revision_html: str = "",
    svg_name_prefix: str = "page",
    html_filename: str = "index.html",
    clipboard_asset_path: Optional[str] = None,
) -> str:
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    page_links_list: List[str] = []
    os.makedirs(dest_dir, exist_ok=True)

    svg_files = sorted(
        f for f in os.listdir(output_dir) if _is_generated_svg(f, svg_name_prefix)
    )
    if page_count:
        svg_files = svg_files[:page_count]

    current_svg_set = set(svg_files)
    for filename in os.listdir(dest_dir):
        if _is_generated_svg(filename, svg_name_prefix) and filename not in current_svg_set:
            os.remove(os.path.join(dest_dir, filename))

    for i, filename in enumerate(svg_files, start=1):
        src_path = os.path.join(output_dir, filename)
        dst_path = os.path.join(dest_dir, filename)

        aspect_ratio, max_width_style = patch_svg_file(
            src_path,
            dst_path,
            svg_href_rewrites,
        )

        page_title = title_format.replace("{i}", str(i))
        page_links_list.append(
            f'<object class="page" type="image/svg+xml" data="./{filename}" '
            f'title="{page_title}" style="aspect-ratio: {aspect_ratio}; {max_width_style}"></object>'
        )

    page_links = "\n".join(page_links_list)
    index_content = template.replace("{{PAGES}}", page_links)

    title = default_title
    hidden_text = ""

    if pdf_path:
        title, hidden_text = extract_pdf_text(
            pdf_path,
            extract_title=extract_title_from_pdf,
            default_title=default_title,
        )

    if hidden_text_override is not None:
        hidden_text = f'<div class="sr-only">\n{hidden_text_override}\n</div>'

    meta_description = description if description else title
    index_content = index_content.replace("{{DESCRIPTION}}", html.escape(meta_description))
    index_content = index_content.replace("{{TITLE}}", html.escape(title))
    index_content = index_content.replace("{{TEXT}}", hidden_text)
    index_content = index_content.replace("{{RAW_COPY}}", raw_copy_html)
    index_content = index_content.replace("{{TOPBAR}}", top_bar_html)
    index_content = index_content.replace("{{REVISION}}", revision_html)

    index_path = os.path.join(dest_dir, html_filename)
    clipboard_src = ""
    if clipboard_asset_path:
        clipboard_src = build_relative_href(
            os.path.dirname(index_path),
            clipboard_asset_path,
        )
    index_content = index_content.replace("{{CLIPBOARD_SRC}}", html.escape(clipboard_src))

    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_content)

    return index_path


def find_latest_revision(posts_dir: str, workspace_name: str, skip_latest: bool = False) -> Tuple[Optional[str], Optional[str]]:
    if not os.path.exists(posts_dir):
        return None, None

    date_dirs = sorted(os.listdir(posts_dir), reverse=True)
    for date_str in date_dirs:
        date_dir = os.path.join(posts_dir, date_str)
        if not os.path.isdir(date_dir):
            continue

        revs: List[Tuple[int, str]] = []
        for d in os.listdir(date_dir):
            if d == workspace_name:
                revs.append((0, d))
            elif d.startswith(workspace_name + "-"):
                try:
                    revs.append((int(d[len(workspace_name) + 1 :]), d))
                except ValueError:
                    pass

        if revs:
            revs.sort(key=lambda x: x[0], reverse=True)
            if skip_latest and len(revs) > 1:
                last_dir_name = revs[1][1]
                return date_str, f"../../{date_str}/{last_dir_name}/index.html"
            elif skip_latest and len(revs) <= 1:
                continue
            else:
                last_dir_name = revs[0][1]
                return date_str, f"../../{date_str}/{last_dir_name}/index.html"

    return None, None


def compile_and_build_html(
    source_bytes: bytes,
    output_dir: str,
    asset_hash: str,
    file_prefix: str,
    template_path: str,
    dest_dir: str,
    title_format: str,
    default_title: str,
    description: Optional[str] = None,
    inputs_svg: Optional[Dict[str, str]] = None,
    inputs_pdf: Optional[Dict[str, str]] = None,
    extract_title_from_pdf: bool = False,
    hidden_text_override: Optional[str] = None,
    raw_copy_html: str = "",
    svg_href_rewrites: Optional[Dict[str, str]] = None,
    svg_name_prefix: str = "page",
    html_filename: str = "index.html",
    clipboard_asset_path: Optional[str] = None,
) -> str:
    svg_prefix = f"{svg_name_prefix}{{0p}}.{asset_hash}.svg"
    pdf_name = f"{file_prefix}.{asset_hash}.pdf"
    
    run_typst_compile(
        source_bytes,
        os.path.join(output_dir, svg_prefix),
        export_format="svg",
        inputs=inputs_svg,
    )
    
    pdf_path = os.path.join(output_dir, pdf_name)
    run_typst_compile(
        source_bytes,
        pdf_path,
        export_format="pdf",
        inputs=inputs_pdf,
    )
    
    page_count = len(
        [f for f in os.listdir(output_dir) if _is_generated_svg(f, svg_name_prefix)]
    )
    
    return build_html_from_svgs(
        template_path=template_path,
        output_dir=output_dir,
        dest_dir=dest_dir,
        page_count=page_count,
        title_format=title_format,
        pdf_path=pdf_path,
        svg_href_rewrites=svg_href_rewrites,
        extract_title_from_pdf=extract_title_from_pdf,
        default_title=default_title,
        description=description,
        hidden_text_override=hidden_text_override,
        raw_copy_html=raw_copy_html,
        svg_name_prefix=svg_name_prefix,
        html_filename=html_filename,
        clipboard_asset_path=clipboard_asset_path,
    )
