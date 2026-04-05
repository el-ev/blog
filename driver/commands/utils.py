import os
import re
import html
import hashlib
import shutil
import subprocess
import sys
from typing import Optional, List, Tuple, Dict, Set


_typst_path: Optional[str] = None
_WORKSPACE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


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


def run_typst_compile(
    source_bytes: bytes,
    output_path: str,
    export_format: str,
    inputs: Optional[Dict[str, str]] = None,
) -> None:
    global _typst_path
    if _typst_path is None:
        _typst_path = shutil.which("typst") or shutil.which("typst.exe")
        if not _typst_path:
            print("Typst executable not found in PATH.")
            sys.exit(1)

    command = [
        _typst_path,
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


def sources_hash(paths: List[str], length: int = 6) -> str:
    hasher = hashlib.sha256()
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

    typ_files = sorted(set(typ_files))
    for file_path in typ_files:
        rel_path = os.path.relpath(file_path, start=os.getcwd()).replace("\\", "/")
        hasher.update(rel_path.encode("utf-8"))
        with open(file_path, "rb") as f:
            hasher.update(f.read())

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


def extract_pdf_links(pdf_path: str) -> List[Tuple[str, str]]:
    links: List[Tuple[str, str]] = []
    seen: Set[str] = set()
    try:
        import pymupdf
        from typing import cast, Any
        
        if os.path.exists(pdf_path):
            doc = pymupdf.open(pdf_path)
            doc_any = cast(Any, doc)
            for page in doc_any:
                for item in page.get_links():
                    href = item.get("uri") or item.get("file")
                    if not href or href in seen:
                        continue
                    seen.add(href)
                    links.append((href, href))
    except Exception:
        pass
    return links


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
    svg_href_rewrites: Optional[Dict[str, str]]
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

    svg_data = svg_data.replace("<a ", '<a target="_top" ')
    svg_data = re.sub(r'\sclass="[^"]+"', "", svg_data)

    with open(dst_path, "w", encoding="utf-8") as svg_file:
        svg_file.write(svg_data)

    svgo_path = shutil.which("svgo") or shutil.which("svgo.cmd")
    if svgo_path:
        try:
            subprocess.run([svgo_path, dst_path, "-o", dst_path], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            print(f"SVGO failed for {dst_path}", file=sys.stderr)
            if e.stderr:
                print(e.stderr.decode("utf-8"), file=sys.stderr)
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
    top_bar_html: str = "",
    revision_html: str = "",
    svg_name_prefix: str = "page",
    html_filename: str = "index.html",
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

        aspect_ratio, max_width_style = patch_svg_file(src_path, dst_path, svg_href_rewrites)

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
    index_content = index_content.replace("{{TOPBAR}}", top_bar_html)
    index_content = index_content.replace("{{REVISION}}", revision_html)

    index_path = os.path.join(dest_dir, html_filename)
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
    svg_href_rewrites: Optional[Dict[str, str]] = None,
    svg_name_prefix: str = "page",
    html_filename: str = "index.html",
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
        svg_name_prefix=svg_name_prefix,
        html_filename=html_filename,
    )
