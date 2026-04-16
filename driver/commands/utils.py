import os
import re
import html
import hashlib
import shutil
import subprocess
import sys
import json
import tempfile
from urllib.parse import parse_qs, unquote, urlparse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, TypeVar, Union

from .revisions import list_workspace_revisions


_typst_path: Optional[str] = None
_typst_version: Optional[str] = None
_svgo_path: Optional[str] = None
_svgo_path_checked = False
_svgo_missing_warned = False
_lightningcss_command: Optional[List[str]] = None
_lightningcss_command_checked = False
_lightningcss_missing_warned = False
_terser_missing_warned = False
_WORKSPACE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_TYPST_DECLARED_STRING_PATTERN_TEMPLATE = r'#let\s+{name}\s*=\s*"([^"]*)"'
_TYPST_DECLARED_CONTENT_PATTERN_TEMPLATE = r"#let\s+{name}\s*=\s*\[(.*?)\]"
_ASSET_HASH_LENGTH = 6
_RAW_COPY_ID_HASH_LENGTH = 10
WORKSPACE_PUBLIC_DIR_NAME = "public"
WEB_ASSETS_DIR_NAME = "assets"
TEMP_WORK_DIR_NAME = ".tmp"
_SVGO_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "svgo.config.mjs",
)
_SVGO_GLYPH_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "svgo.glyphs.config.mjs",
)
_GLOBAL_GLYPH_MAP_VERSION = 1
GLOBAL_GLYPH_ASSET_FILENAME = "glyphs.svg"
GLOBAL_GLYPH_MAP_FILENAME = "glyph-map.json"
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_DESCRIPTION_BLOCK_PATTERN = re.compile(
    r"<(blockquote|p|pre|figcaption|li)\b([^>]*)>(.*?)</\1>",
    flags=re.IGNORECASE | re.DOTALL,
)
_SENTENCE_PATTERN = re.compile(r".+?(?:[.!?](?=\s|$)|$)")
_SVG_THEME_FILL_CLASS_MAP: Dict[str, str] = {
    "#fff": "theme-paper-bg",
    "#ffffff": "theme-paper-bg",
    "#000": "t",
    "#000000": "t",
    "black": "t",
    "#141414": "t",
    "#646464": "theme-muted-text",
    "#aaa": "theme-footer-text",
    "#aaaaaa": "theme-footer-text",
    "#f5f5f5": "theme-code-bg",
    "#f8f8f8": "theme-surface-bg",
    "#74747c": "theme-code-comment",
    "#198810": "theme-code-green",
    "#1d6c76": "theme-code-dark-green",
    "#d73948": "theme-code-red",
    "#4b69c6": "theme-code-blue",
    "#8b41b1": "theme-code-violet",
    "#b60157": "theme-code-magenta",
}
_SVG_THEME_STROKE_CLASS_MAP: Dict[str, str] = {
    "#000": "theme-muted-stroke",
    "#000000": "theme-muted-stroke",
    "black": "theme-muted-stroke",
    "#141414": "t-stroke",
    "#646464": "theme-muted-stroke",
    "#787878": "theme-code-gutter",
}
_SVG_THEME_STYLE = """
<style id="driver-theme-style">
.theme-paper-bg { fill: var(--svg-paper-bg, #ffffff) !important; }
.t { fill: var(--svg-text, #141414) !important; }
.theme-muted-text { fill: var(--svg-muted-text, #646464) !important; }
.theme-footer-text { fill: var(--svg-footer-text, #aaaaaa) !important; }
.theme-code-bg { fill: var(--svg-code-bg, #f5f5f5) !important; }
.theme-surface-bg { fill: var(--svg-surface-bg, #f8f8f8) !important; }
.theme-code-comment { fill: var(--svg-code-comment, #74747c) !important; }
.theme-code-green { fill: var(--svg-code-green, #198810) !important; }
.theme-code-dark-green { fill: var(--svg-code-dark-green, #1d6c76) !important; }
.theme-code-red { fill: var(--svg-code-red, #d73948) !important; }
.theme-code-blue { fill: var(--svg-code-blue, #4b69c6) !important; }
.theme-code-violet { fill: var(--svg-code-violet, #8b41b1) !important; }
.theme-code-magenta { fill: var(--svg-code-magenta, #b60157) !important; }
.t-stroke { stroke: var(--svg-text, #141414) !important; }
.theme-muted-stroke { stroke: var(--svg-muted-stroke, #646464) !important; }
.theme-code-gutter { stroke: var(--svg-code-gutter, #787878) !important; }
a:focus,
a:focus-visible {
  outline: none;
}
a:focus-visible > path {
  fill: transparent !important;
  stroke: var(--svg-focus-ring, #4b69c6) !important;
  stroke-width: 1.2 !important;
  stroke-linejoin: round;
  vector-effect: non-scaling-stroke;
}
@media (forced-colors: active) {
  a:focus-visible > path {
    stroke: CanvasText !important;
  }
}
@media (prefers-color-scheme: dark) {
  :root {
    --svg-paper-bg: #161b22;
    --svg-text: #e8ecf2;
    --svg-muted-text: #a7b0bf;
    --svg-footer-text: #7f8897;
    --svg-code-bg: #222a34;
    --svg-surface-bg: #1b232d;
    --svg-code-comment: #8e97a6;
    --svg-code-green: #86df80;
    --svg-code-dark-green: #74cad3;
    --svg-code-red: #ff8d99;
    --svg-code-blue: #8ca8ff;
    --svg-code-violet: #c792ea;
    --svg-code-magenta: #e58bff;
    --svg-muted-stroke: #a7b0bf;
    --svg-code-gutter: #6f7783;
    --svg-focus-ring: #8ca8ff;
  }
}
</style>
""".strip()


@dataclass(frozen=True)
class DriverWebAssets:
    stylesheet_path: str
    clipboard_script_path: str
    theme_script_path: str
    inline_style: str
    inline_script: str


@dataclass(frozen=True)
class DriverAssetContext:
    web_assets: DriverWebAssets
    global_glyph_asset_path: str
    global_glyph_map_path: str


@dataclass(frozen=True)
class TypstInputs:
    svg: Dict[str, str]
    pdf: Dict[str, str]


def build_typst_inputs(
    shared_inputs: Optional[Dict[str, str]] = None,
    svg_inputs: Optional[Dict[str, str]] = None,
    pdf_inputs: Optional[Dict[str, str]] = None,
) -> TypstInputs:
    base_inputs = {"with_driver": "true"}
    if shared_inputs:
        base_inputs.update(shared_inputs)

    svg = dict(base_inputs)
    svg["export_format"] = "svg"
    if svg_inputs:
        svg.update(svg_inputs)

    pdf = dict(base_inputs)
    pdf["export_format"] = "pdf"
    if pdf_inputs:
        pdf.update(pdf_inputs)

    return TypstInputs(svg=svg, pdf=pdf)


def _append_svg_class(attrs: str, class_name: str) -> str:
    class_match = re.search(r'\sclass="([^"]*)"', attrs)
    if class_match:
        class_names = [name for name in class_match.group(1).split() if name]
        if class_name not in class_names:
            class_names.append(class_name)
        replacement = f' class="{" ".join(class_names)}"'
        return attrs[: class_match.start()] + replacement + attrs[class_match.end() :]
    if re.search(r"/\s*$", attrs):
        return re.sub(r"/\s*$", f' class="{class_name}" /', attrs)
    return f'{attrs} class="{class_name}"'


def _remove_svg_attr(attrs: str, attr_name: str) -> str:
    return re.sub(
        rf'\s{attr_name}="[^"]*"',
        "",
        attrs,
        flags=re.IGNORECASE,
    )


def _inject_svg_theme_classes(svg_data: str) -> str:
    def _rewrite_tag(match: re.Match) -> str:
        tag = match.group(1)
        attrs = match.group(2)
        if not attrs:
            return match.group(0)

        classes: List[str] = []
        attrs_to_remove: Set[str] = set()

        fill_match = re.search(r'\sfill="([^"]+)"', attrs, flags=re.IGNORECASE)
        if fill_match:
            fill_value = fill_match.group(1).strip().lower()
            if fill_value in _SVG_THEME_FILL_CLASS_MAP:
                classes.append(_SVG_THEME_FILL_CLASS_MAP[fill_value])
                attrs_to_remove.add("fill")

        stroke_match = re.search(r'\sstroke="([^"]+)"', attrs, flags=re.IGNORECASE)
        if stroke_match:
            stroke_value = stroke_match.group(1).strip().lower()
            if stroke_value in _SVG_THEME_STROKE_CLASS_MAP:
                classes.append(_SVG_THEME_STROKE_CLASS_MAP[stroke_value])
                attrs_to_remove.add("stroke")

        if not classes:
            return match.group(0)

        updated_attrs = attrs
        for attr_name in sorted(attrs_to_remove):
            updated_attrs = _remove_svg_attr(updated_attrs, attr_name)
        for class_name in classes:
            updated_attrs = _append_svg_class(updated_attrs, class_name)
        return f"<{tag}{updated_attrs}>"

    return re.sub(r"<([A-Za-z][\w:.-]*)([^>]*)>", _rewrite_tag, svg_data)


def _inject_svg_theme_style(svg_data: str) -> str:
    if 'id="driver-theme-style"' in svg_data:
        return svg_data
    return re.sub(
        r"(<svg\b[^>]*>)",
        rf"\1{_SVG_THEME_STYLE}",
        svg_data,
        count=1,
    )


def make_raw_copy_id(text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:_RAW_COPY_ID_HASH_LENGTH]
    return f"{digest}"


def build_page_head_title(
    page_title: str,
    site_title: str,
    page_subtitle: Optional[str] = None,
) -> str:
    title_parts = [page_title]
    if page_subtitle:
        title_parts.append(page_subtitle)
    if page_title != site_title:
        title_parts.append(site_title)
    return " - ".join(title_parts)


def _strip_html_text(fragment: str) -> str:
    text = _HTML_TAG_PATTERN.sub(" ", fragment)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_description_comparison_text(text: str) -> str:
    normalized = html.unescape(text)
    normalized = normalized.translate(
        str.maketrans(
            {
                "\u2018": "'",
                "\u2019": "'",
                "\u201c": '"',
                "\u201d": '"',
                "\u2026": "...",
            }
        )
    )
    return re.sub(r"\s+", " ", normalized).strip()


def extract_first_description_sentence(
    html_fragment: str,
    fallback_description: str,
    skip_texts: Optional[List[str]] = None,
    max_length: int = 220,
) -> str:
    normalized_skip_texts = {
        _normalize_description_comparison_text(text)
        for text in (skip_texts or [])
        if text and text.strip()
    }
    for block_match in _DESCRIPTION_BLOCK_PATTERN.finditer(html_fragment):
        block_tag = (block_match.group(1) or "").lower()
        block_attrs = block_match.group(2) or ""
        if block_tag == "p" and re.search(
            r'\bclass\s*=\s*"[^"]*\bsubtitle\b', block_attrs
        ):
            continue

        block_text = _strip_html_text(block_match.group(3))
        if not block_text:
            continue
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", block_text):
            continue
        if (
            _normalize_description_comparison_text(block_text)
            in normalized_skip_texts
        ):
            continue

        sentence_match = _SENTENCE_PATTERN.search(block_text)
        if not sentence_match:
            continue

        first_sentence = sentence_match.group(0).strip()
        if not first_sentence:
            continue
        if len(first_sentence) <= max_length:
            return first_sentence
        return first_sentence[: max_length - 1].rstrip() + "…"

    return fallback_description


def _resolve_typst_path() -> str:
    global _typst_path
    if _typst_path is None:
        _typst_path = shutil.which("typst") or shutil.which("typst.exe")
    if not _typst_path:
        print("Typst executable not found in PATH.")
        sys.exit(1)
    return _typst_path


def _resolve_typst_version() -> str:
    global _typst_version
    if _typst_version is not None:
        return _typst_version

    typst_path = _resolve_typst_path()
    result = subprocess.run(
        [typst_path, "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    version = result.stdout.strip()
    if not version:
        raise RuntimeError("Failed to resolve Typst version.")

    _typst_version = version
    return _typst_version


def _resolve_svgo_path() -> Optional[str]:
    global _svgo_path, _svgo_path_checked
    if not _svgo_path_checked:
        _svgo_path = shutil.which("svgo") or shutil.which("svgo.cmd")
        _svgo_path_checked = True
    return _svgo_path


def _resolve_lightningcss_command() -> Optional[List[str]]:
    global _lightningcss_command, _lightningcss_command_checked
    if _lightningcss_command_checked:
        return _lightningcss_command

    lightningcss_path = shutil.which("lightningcss") or shutil.which("lightningcss.cmd")
    if lightningcss_path:
        _lightningcss_command = [lightningcss_path]
    else:
        npx_path = shutil.which("npx") or shutil.which("npx.cmd")
        if npx_path:
            _lightningcss_command = [npx_path, "--yes", "lightningcss-cli"]

    _lightningcss_command_checked = True
    return _lightningcss_command


def _run_svgo(svg_path: str, preserve_ids: bool = False) -> None:
    global _svgo_missing_warned

    svgo_path = _resolve_svgo_path()
    if not svgo_path:
        if not _svgo_missing_warned:
            print("SVGO not found, skipping SVG optimization.", file=sys.stderr)
            _svgo_missing_warned = True
        return

    config_path = _SVGO_GLYPH_CONFIG_PATH if preserve_ids else _SVGO_CONFIG_PATH
    command = [
        svgo_path,
        svg_path,
        "-o",
        svg_path,
        "--multipass",
        "--precision",
        "2",
    ]
    if os.path.isfile(config_path):
        command.extend(["--config", config_path])

    try:
        subprocess.run(command, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(
            f"Aggressive SVGO failed for {svg_path}; retrying with defaults.",
            file=sys.stderr,
        )
        if e.stderr:
            print(e.stderr.decode("utf-8"), file=sys.stderr)

        fallback_command = [svgo_path, svg_path, "-o", svg_path]
        if preserve_ids and os.path.isfile(_SVGO_GLYPH_CONFIG_PATH):
            fallback_command.extend(["--config", _SVGO_GLYPH_CONFIG_PATH])

        try:
            subprocess.run(
                fallback_command,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as fallback_error:
            print(f"SVGO failed for {svg_path}", file=sys.stderr)
            if fallback_error.stderr:
                print(fallback_error.stderr.decode("utf-8"), file=sys.stderr)


def reset_directory(path: str) -> None:
    os.makedirs(path, exist_ok=True)
    if os.listdir(path):
        shutil.rmtree(path)
        os.makedirs(path, exist_ok=True)


def get_temp_root(build_base: str) -> str:
    temp_root = os.path.join(os.path.abspath(build_base), TEMP_WORK_DIR_NAME)
    os.makedirs(temp_root, exist_ok=True)
    return temp_root


def make_temp_dir(build_base: str, prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=get_temp_root(build_base))


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


def _build_asset_rel_path(asset_path: str) -> str:
    asset_parts = os.path.abspath(asset_path).split(os.sep)
    if WEB_ASSETS_DIR_NAME not in asset_parts:
        raise ValueError(
            f"Expected asset path inside '{WEB_ASSETS_DIR_NAME}/': {asset_path}"
        )
    asset_index = len(asset_parts) - 1 - asset_parts[::-1].index(WEB_ASSETS_DIR_NAME)
    rel_path = "/".join(part for part in asset_parts[asset_index + 1 :] if part)
    if not rel_path or rel_path == ".":
        raise ValueError(f"Invalid asset path: {asset_path}")
    if rel_path.startswith("../"):
        raise ValueError(f"Invalid asset path: {asset_path}")
    return rel_path


def build_root_asset_href(asset_path: str) -> str:
    rel_path = _build_asset_rel_path(asset_path)
    return f"/{WEB_ASSETS_DIR_NAME}/{rel_path}"


def build_local_asset_href(asset_path: str) -> str:
    rel_path = _build_asset_rel_path(asset_path)
    return f"./{WEB_ASSETS_DIR_NAME}/{rel_path}"


def build_asset_sibling_href(asset_path: str) -> str:
    rel_path = _build_asset_rel_path(asset_path)
    return f"./{rel_path}"


def _rebase_relative_href_for_destination(
    href: str,
    source_dir: str,
    dest_dir: str,
) -> str:
    if not href:
        return href

    parsed = urlparse(href)
    if parsed.scheme or href.startswith(("//", "/", "#")):
        return href

    normalized_source_dir = os.path.abspath(source_dir)
    normalized_dest_dir = os.path.abspath(dest_dir)
    if normalized_source_dir == normalized_dest_dir:
        return href

    joined_target = os.path.normpath(
        os.path.join(normalized_source_dir, parsed.path.replace("/", os.sep))
    )
    rebased_href = build_relative_href(normalized_dest_dir, joined_target)
    if parsed.query:
        rebased_href = f"{rebased_href}?{parsed.query}"
    if parsed.fragment:
        rebased_href = f"{rebased_href}#{parsed.fragment}"
    return rebased_href


def extract_declared_typst_string_from_source(source: str, name: str) -> Optional[str]:
    string_pattern = re.compile(
        _TYPST_DECLARED_STRING_PATTERN_TEMPLATE.format(name=re.escape(name))
    )
    match = string_pattern.search(source)
    if match:
        value = match.group(1).strip()
        if not value:
            return None
        return value

    content_pattern = re.compile(
        _TYPST_DECLARED_CONTENT_PATTERN_TEMPLATE.format(name=re.escape(name)),
        flags=re.DOTALL,
    )
    match = content_pattern.search(source)
    if not match:
        return None

    value = re.sub(r"\s+", " ", match.group(1)).strip()
    if not value:
        return None
    return value


def extract_required_declared_typst_string_from_source(source: str, name: str) -> str:
    value = extract_declared_typst_string_from_source(source, name)
    if value is None:
        raise RuntimeError(f"Missing required {name} declaration in Typst source.")
    return value


def extract_declared_typst_string(path: str, name: str) -> Optional[str]:
    with open(path, "r", encoding="utf-8") as f:
        return extract_declared_typst_string_from_source(f.read(), name)


def extract_required_declared_typst_string(path: str, name: str) -> str:
    value = extract_declared_typst_string(path, name)
    if value is None:
        raise RuntimeError(f"Missing required {name} declaration in '{path}'.")
    return value


def _remove_stale_hashed_assets(
    asset_dir: str,
    prefix: str,
    suffix: str,
    keep_filename: str,
) -> None:
    if not os.path.isdir(asset_dir):
        return

    expected_prefix = f"{prefix}."
    for filename in os.listdir(asset_dir):
        if filename == keep_filename:
            continue
        if not filename.startswith(expected_prefix) or not filename.endswith(suffix):
            continue

        stale_path = os.path.join(asset_dir, filename)
        if os.path.isfile(stale_path):
            try:
                os.remove(stale_path)
            except FileNotFoundError:
                continue


def _write_hashed_asset(
    asset_dir: str,
    prefix: str,
    suffix: str,
    content: str,
    remove_stale: bool = True,
) -> str:
    payload = content.encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:_ASSET_HASH_LENGTH]
    filename = f"{prefix}.{digest}{suffix}"
    asset_path = safe_join_child(asset_dir, filename)

    with open(asset_path, "w", encoding="utf-8") as f:
        f.write(content)

    if remove_stale:
        _remove_stale_hashed_assets(
            asset_dir=asset_dir,
            prefix=prefix,
            suffix=suffix,
            keep_filename=filename,
        )
    return asset_path


def _minify_js_source(source: str) -> str:
    global _terser_missing_warned

    terser_path = shutil.which("terser") or shutil.which("terser.cmd")
    if not terser_path:
        if not _terser_missing_warned:
            print(
                "Terser not found, skipping JavaScript minification. "
                "Install it with `npm install --global terser`.",
                file=sys.stderr,
            )
            _terser_missing_warned = True
        return source

    try:
        result = subprocess.run(
            [terser_path, "--compress", "--mangle", "--ecma", "2020"],
            check=True,
            input=source,
            text=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip() if e.stderr else ""
        if stderr:
            print(
                f"Terser minification failed, using original JavaScript: {stderr}",
                file=sys.stderr,
            )
        else:
            print(
                "Terser minification failed, using original JavaScript.",
                file=sys.stderr,
            )
        return source

    minified = result.stdout.strip()
    if not minified:
        print(
            "Terser minification produced empty output, using original JavaScript.",
            file=sys.stderr,
        )
        return source

    return minified


def _minify_css_source(source: str) -> str:
    global _lightningcss_missing_warned

    lightningcss_command = _resolve_lightningcss_command()
    if not lightningcss_command:
        if not _lightningcss_missing_warned:
            print(
                "Lightning CSS not found, skipping CSS minification. "
                "Install it with `npm install --global lightningcss-cli`.",
                file=sys.stderr,
            )
            _lightningcss_missing_warned = True
        return source

    try:
        result = subprocess.run(
            [*lightningcss_command, "--minify"],
            check=True,
            input=source,
            text=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip() if e.stderr else ""
        if stderr:
            print(
                f"Lightning CSS minification failed, using original CSS: {stderr}",
                file=sys.stderr,
            )
        else:
            print(
                "Lightning CSS minification failed, using original CSS.",
                file=sys.stderr,
            )
        return source

    minified = result.stdout.strip()
    if not minified:
        print(
            "Lightning CSS minification produced empty output, using original CSS.",
            file=sys.stderr,
        )
        return source

    return minified


_HTML_MINIFY_PRESERVE_PATTERN = re.compile(
    r"(<(?:script|style|pre)\b[^>]*>.*?</(?:script|style|pre)>)",
    re.DOTALL | re.IGNORECASE,
)


def _minify_html(content: str) -> str:
    segments = _HTML_MINIFY_PRESERVE_PATTERN.split(content)
    parts: List[str] = []
    for i, segment in enumerate(segments):
        if i % 2 == 1:
            parts.append(segment)
        else:
            segment = re.sub(r"<!--.*?-->", "", segment, flags=re.DOTALL)
            segment = re.sub(r">\s+<", "><", segment)
            segment = re.sub(r"[ \t]{2,}", " ", segment)
            segment = re.sub(r"[ \t]+\n", "\n", segment)
            segment = re.sub(r"\n{2,}", "\n", segment)
            parts.append(segment.strip())
    return "".join(parts).strip() + "\n"


def minify_html_file(path: str) -> None:
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    minified = _minify_html(content)
    if minified == content:
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write(minified)


def _remove_legacy_root_js_files(webroot_dir: str) -> int:
    if not os.path.isdir(webroot_dir):
        return 0

    removed_count = 0
    for filename in os.listdir(webroot_dir):
        if not re.fullmatch(r"(?:clipboard|theme)(?:\.[^.]+)?(?:\.min)?\.js", filename):
            continue
        target_path = os.path.join(webroot_dir, filename)
        if os.path.isfile(target_path):
            try:
                os.remove(target_path)
                removed_count += 1
            except FileNotFoundError:
                continue
    return removed_count


def build_driver_web_assets(driver_dir: str, webroot_dir: str) -> DriverWebAssets:
    if not os.path.isdir(driver_dir):
        raise FileNotFoundError(driver_dir)

    os.makedirs(webroot_dir, exist_ok=True)
    assets_dir = safe_join_child(webroot_dir, WEB_ASSETS_DIR_NAME)
    os.makedirs(assets_dir, exist_ok=True)

    stylesheet_src_path = os.path.join(driver_dir, "site.css")
    clipboard_src_path = os.path.join(driver_dir, "clipboard.js")
    theme_src_path = os.path.join(driver_dir, "theme.js")

    with open(stylesheet_src_path, "r", encoding="utf-8") as f:
        stylesheet_source = f.read().strip() + "\n"
    with open(clipboard_src_path, "r", encoding="utf-8") as f:
        clipboard_source = f.read()
    with open(theme_src_path, "r", encoding="utf-8") as f:
        theme_source = f.read()

    stylesheet_asset_path = _write_hashed_asset(
        asset_dir=assets_dir,
        prefix="site",
        suffix=".css",
        content=_minify_css_source(stylesheet_source),
    )
    clipboard_asset_path = _write_hashed_asset(
        asset_dir=assets_dir,
        prefix="clipboard",
        suffix=".min.js",
        content=_minify_js_source(clipboard_source),
    )
    theme_asset_path = _write_hashed_asset(
        asset_dir=assets_dir,
        prefix="theme",
        suffix=".min.js",
        content=_minify_js_source(theme_source),
    )

    inline_style_src_path = os.path.join(driver_dir, "inline-style.css")
    inline_script_src_path = os.path.join(driver_dir, "inline-script.js")

    with open(inline_style_src_path, "r", encoding="utf-8") as f:
        inline_style_source = f.read()
    with open(inline_script_src_path, "r", encoding="utf-8") as f:
        inline_script_source = f.read()

    web_assets = DriverWebAssets(
        stylesheet_path=stylesheet_asset_path,
        clipboard_script_path=clipboard_asset_path,
        theme_script_path=theme_asset_path,
        inline_style=_minify_css_source(inline_style_source),
        inline_script=_minify_js_source(inline_script_source),
    )

    _remove_legacy_root_js_files(webroot_dir)
    return web_assets


def run_typst_compile(
    source_bytes: bytes,
    output_path: str,
    export_format: str,
    inputs: Optional[Dict[str, str]] = None,
    creation_timestamp: Optional[str] = None,
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
    if creation_timestamp:
        command.extend(["--creation-timestamp", creation_timestamp])

    try:
        subprocess.run(
            command,
            check=True,
            input=source_bytes,
        )
    except subprocess.CalledProcessError as e:
        print(
            f"Typst compilation failed for {output_path} (exit code {e.returncode})",
            file=sys.stderr,
        )
        if e.stderr:
            print(e.stderr.decode("utf-8"), file=sys.stderr)
        elif e.output:
            print(e.output.decode("utf-8"), file=sys.stderr)
        raise RuntimeError(f"Typst compilation failed. Exit code {e.returncode}") from e


def _resolve_pdf_creation_timestamp(inputs: Optional[Dict[str, str]]) -> Optional[str]:
    if not inputs:
        return None

    raw_date: Optional[str]
    if "edited_date" in inputs:
        raw_date = inputs["edited_date"]
    elif "publish_date" in inputs:
        raw_date = inputs["publish_date"]
    else:
        raw_date = None
    if not raw_date:
        return None

    try:
        parsed_date = datetime.strptime(raw_date, "%Y-%m-%d")
    except ValueError:
        return None

    return str(int(parsed_date.replace(tzinfo=timezone.utc).timestamp()))


def _flatten_query_text(node: Any) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_flatten_query_text(item) for item in node)
    if isinstance(node, dict):
        func = node["func"] if "func" in node else None
        if func == "space":
            return " "
        if func == "linebreak":
            return "\n"
        if func == "smartquote":
            return '"' if ("double" in node and bool(node["double"])) else "'"

        parts: List[str] = []
        text = node["text"] if "text" in node else None
        if isinstance(text, str):
            parts.append(text)
        for key in ("body", "children", "child", "value", "values", "content"):
            if key in node:
                parts.append(_flatten_query_text(node[key]))
        if not parts:
            for key, value in node.items():
                if key in ("func", "text"):
                    continue
                if isinstance(value, (dict, list)):
                    parts.append(_flatten_query_text(value))
        return "".join(parts)
    return ""


def _query_typst_json_nodes(
    main_typ_path: str,
    query_root: str,
    selector: str,
    query_label: str,
    parse_label: str,
    inputs: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    abs_main_typ = os.path.abspath(main_typ_path)
    abs_query_root = os.path.abspath(query_root)
    query_input = os.path.relpath(abs_main_typ, start=abs_query_root).replace("\\", "/")

    command = [
        _resolve_typst_path(),
        "query",
        query_input,
        selector,
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
        stderr = e.stderr.strip() if e.stderr else ""
        if stderr:
            raise RuntimeError(
                f"Failed to query {query_label} from Typst source: {stderr}"
            ) from e
        raise RuntimeError(
            f"Failed to query {query_label} from Typst source: {e}"
        ) from e

    raw = result.stdout.strip()
    if not raw:
        raise RuntimeError(f"Typst query produced empty output for {query_label}.")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse {parse_label}: {e}") from e

    if not isinstance(data, list):
        raise RuntimeError(f"Invalid {parse_label}: expected list root.")

    nodes: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            raise RuntimeError(f"Invalid {parse_label}: expected object entries.")
        nodes.append(item)
    return nodes


def extract_typst_links(
    main_typ_path: str,
    query_root: str,
    inputs: Optional[Dict[str, str]] = None,
) -> List[Tuple[str, str]]:
    links: List[Tuple[str, str]] = []
    seen: Set[str] = set()
    for item in _query_typst_json_nodes(
        main_typ_path=main_typ_path,
        query_root=query_root,
        selector="link",
        query_label="links",
        parse_label="Typst query output",
        inputs=inputs,
    ):
        href = item["dest"]
        if not isinstance(href, str):
            raise RuntimeError(
                "Invalid Typst link query output: 'dest' must be string."
            )
        if not href or href in seen:
            continue

        label = re.sub(r"\s+", " ", _flatten_query_text(item["body"])).strip()
        if not label:
            label = href

        seen.add(href)
        links.append((href, label))

    return links


def _extract_typst_table_rows(
    table_payload: Dict[str, Any],
) -> List[List[Dict[str, Any]]]:
    columns_raw = table_payload["columns"]
    if isinstance(columns_raw, list):
        column_count = len(columns_raw)
    elif isinstance(columns_raw, int):
        column_count = columns_raw
    else:
        raise RuntimeError(
            "Invalid Typst table query output: 'columns' must be list or int."
        )
    if column_count <= 0:
        raise RuntimeError("Invalid Typst table query output: table must have columns.")

    children = table_payload["children"]
    if not isinstance(children, list):
        raise RuntimeError("Invalid Typst table query output: 'children' must be list.")

    cell_nodes: List[Dict[str, Any]] = []
    for child in children:
        if not isinstance(child, dict):
            raise RuntimeError(
                "Invalid Typst table query output: table child entry must be object."
            )
        if child.get("func") != "cell":
            continue

        body = child["body"]
        text = re.sub(r"\s+", " ", _flatten_query_text(body)).strip()
        is_inline_code = bool(
            isinstance(body, dict)
            and body.get("func") == "raw"
            and not bool(body.get("block", False))
        )

        colspan = child.get("colspan", 1)
        if not isinstance(colspan, int) or colspan <= 0:
            raise RuntimeError(
                "Invalid Typst table query output: 'colspan' must be positive int."
            )
        rowspan = child.get("rowspan", 1)
        if not isinstance(rowspan, int) or rowspan <= 0:
            raise RuntimeError(
                "Invalid Typst table query output: 'rowspan' must be positive int."
            )
        if colspan > column_count:
            raise RuntimeError(
                "Invalid Typst table query output: cell colspan exceeds column count."
            )

        cell_nodes.append(
            {
                "text": text,
                "is_inline_code": is_inline_code,
                "colspan": colspan,
                "rowspan": rowspan,
            }
        )

    rows: List[List[Dict[str, Any]]] = [[]]
    occupied: Dict[Tuple[int, int], bool] = {}
    row_index = 0
    col_index = 0

    def advance_to_free_slot(start_row: int, start_col: int) -> Tuple[int, int]:
        current_row = start_row
        current_col = start_col
        while True:
            while current_col < column_count and occupied.get(
                (current_row, current_col), False
            ):
                current_col += 1
            if current_col < column_count:
                return current_row, current_col
            current_row += 1
            current_col = 0
            while current_row >= len(rows):
                rows.append([])

    for cell in cell_nodes:
        row_index, col_index = advance_to_free_slot(row_index, col_index)
        while row_index >= len(rows):
            rows.append([])

        rowspan = int(cell["rowspan"])
        colspan = int(cell["colspan"])

        rows[row_index].append(cell)
        for row_offset in range(rowspan):
            target_row = row_index + row_offset
            while target_row >= len(rows):
                rows.append([])
            for col_offset in range(colspan):
                target_col = col_index + col_offset
                if target_col >= column_count:
                    raise RuntimeError(
                        "Invalid Typst table query output: cell span exceeds table width."
                    )
                slot_key = (target_row, target_col)
                if occupied.get(slot_key, False):
                    raise RuntimeError(
                        "Invalid Typst table query output: overlapping table spans."
                    )
                occupied[slot_key] = True

        col_index += colspan

    if occupied:
        row_count = max(row for row, _ in occupied.keys()) + 1
        while len(rows) < row_count:
            rows.append([])
        if len(rows) > row_count:
            rows = rows[:row_count]

    return rows


_ExtractResult = TypeVar("_ExtractResult")


def _extract_typst_from_content(
    source_content: Union[str, bytes],
    query_root: str,
    query_prefix: str,
    extractor: Callable[[str, str, Optional[Dict[str, str]]], List[_ExtractResult]],
    inputs: Optional[Dict[str, str]] = None,
) -> List[_ExtractResult]:
    temp_query_path = ""
    try:
        if isinstance(source_content, bytes):
            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=".typ",
                prefix=query_prefix,
                dir=query_root,
                delete=False,
            ) as temp_file:
                temp_file.write(source_content)
                temp_query_path = temp_file.name
        else:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".typ",
                prefix=query_prefix,
                dir=query_root,
                delete=False,
                encoding="utf-8",
            ) as temp_file:
                temp_file.write(source_content)
                temp_query_path = temp_file.name

        return extractor(temp_query_path, query_root, inputs)
    finally:
        if temp_query_path and os.path.exists(temp_query_path):
            os.remove(temp_query_path)


def extract_action_metadata(
    main_typ_path: str,
    query_root: str,
    inputs: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict[str, str]]:
    """Return {action_value: {label, role, tabindex}} from <driver-action> metadata."""
    result: Dict[str, Dict[str, str]] = {}
    for node in _query_typst_json_nodes(
        main_typ_path=main_typ_path,
        query_root=query_root,
        selector="<driver-action>",
        query_label="action metadata",
        parse_label="Typst action metadata query output",
        inputs=inputs,
    ):
        item = node.get("value")
        if not isinstance(item, dict):
            continue
        action_val = item.get("a")
        if not isinstance(action_val, str) or not action_val:
            continue
        result[action_val] = {
            "label": str(item.get("label") or ""),
            "role": str(item.get("role") or ""),
            "tabindex": str(item.get("tabindex") or ""),
        }
    return result


def extract_action_metadata_from_content(
    source_content: Union[str, bytes],
    query_root: str,
    inputs: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict[str, str]]:
    return _extract_typst_from_content(
        source_content=source_content,
        query_root=query_root,
        query_prefix=".action-query-",
        extractor=extract_action_metadata,
        inputs=inputs,
    )


def extract_doc_structure(
    main_typ_path: str,
    query_root: str,
    inputs: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Returns ordered list of metadata dicts from <driver-doc> query."""
    nodes = _query_typst_json_nodes(
        main_typ_path=main_typ_path,
        query_root=query_root,
        selector="<driver-doc>",
        query_label="document structure",
        parse_label="Typst document structure query output",
        inputs=inputs,
    )
    result: List[Dict[str, Any]] = []
    for node in nodes:
        value = node.get("value")
        if isinstance(value, dict):
            result.append(value)
    return result


def extract_doc_structure_from_content(
    source_content: Union[str, bytes],
    query_root: str,
    inputs: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Like extract_doc_structure but takes driver source bytes (pre-IMPORT_MAIN-substituted)."""
    return _extract_typst_from_content(
        source_content=source_content,
        query_root=query_root,
        query_prefix=".doc-query-",
        extractor=extract_doc_structure,
        inputs=inputs,
    )


def _collect_typ_files(paths: List[str]) -> List[Tuple[str, str]]:
    typ_files: Dict[str, str] = {}

    for path_index, path in enumerate(paths):
        if not path:
            continue
        abs_path = os.path.abspath(path)
        logical_prefix = f"{path_index}:"

        if os.path.isfile(abs_path) and abs_path.endswith(".typ"):
            logical_path = f"{logical_prefix}{os.path.basename(abs_path)}"
            typ_files.setdefault(logical_path, abs_path)
            continue

        if os.path.isdir(abs_path):
            for root, _, files in os.walk(abs_path):
                for name in files:
                    if not name.endswith(".typ"):
                        continue
                    file_path = os.path.abspath(os.path.join(root, name))
                    rel_path = os.path.relpath(file_path, start=abs_path).replace(
                        "\\", "/"
                    )
                    logical_path = f"{logical_prefix}{rel_path}"
                    typ_files.setdefault(logical_path, file_path)

    return sorted(typ_files.items(), key=lambda item: item[0])


def _update_hash_with_typ_files(hasher: "hashlib._Hash", paths: List[str]) -> None:
    typ_files = _collect_typ_files(paths)
    for logical_path, file_path in typ_files:
        hasher.update(logical_path.encode("utf-8"))
        with open(file_path, "rb") as f:
            hasher.update(f.read())


def sources_hash(paths: List[str], length: int = _ASSET_HASH_LENGTH) -> str:
    hasher = hashlib.sha256()
    _update_hash_with_typ_files(hasher, paths)
    return hasher.hexdigest()[:length]


def hash_text_with_sources(
    text: str,
    paths: List[str],
    length: int = _ASSET_HASH_LENGTH,
) -> str:
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
    return title, hidden_text


def _rewrite_html_asset_href(
    html_path: str, asset_path: str, tag_pattern: str
) -> bool:
    if not os.path.isfile(html_path):
        return False
    asset_name = os.path.basename(asset_path)
    if not asset_name:
        return False
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    href = build_relative_href(os.path.dirname(html_path), asset_path)
    name_parts = asset_name.split(".")
    if len(name_parts) >= 3:
        name_pattern = (
            re.escape(name_parts[0])
            + r"\.[^.]+\."
            + re.escape(".".join(name_parts[2:]))
        )
    else:
        name_pattern = re.escape(asset_name)
    updated_html = re.sub(
        tag_pattern.format(name_pattern),
        rf"\1{href}\2",
        html_content,
        count=1,
    )
    if updated_html == html_content:
        return False
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(updated_html)
    return True


def _extract_first_glyph_symbol_id(glyph_asset_path: str) -> Optional[str]:
    if not os.path.isfile(glyph_asset_path):
        return None

    try:
        with open(glyph_asset_path, "r", encoding="utf-8") as f:
            glyph_content = f.read()
    except (OSError, UnicodeDecodeError):
        return None

    symbol_match = _SVG_SYMBOL_PATTERN.search(glyph_content)
    if not symbol_match:
        return None

    symbol_attrs = symbol_match.group(1)
    symbol_id_match = _SVG_ID_ATTR_PATTERN.search(symbol_attrs)
    if not symbol_id_match:
        return None

    symbol_id = symbol_id_match.group(1).strip()
    if not symbol_id:
        return None
    return symbol_id


def _build_glyph_preload_svg(glyph_src: str, glyph_symbol_id: str) -> str:
    glyph_ref = f"{glyph_src}#{glyph_symbol_id}"
    return (
        '<svg data-glyph-preload="true" aria-hidden="true" width="0" height="0" '
        'style="position:absolute;opacity:0;pointer-events:none">'
        f'<use href="{html.escape(glyph_ref, quote=True)}"></use>'
        "</svg>"
    )


def rewrite_glyph_preload_href(html_path: str, glyph_asset_path: str) -> bool:
    if not os.path.isfile(html_path):
        return False

    glyph_name = os.path.basename(glyph_asset_path)
    if not glyph_name:
        return False

    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    glyph_src = build_root_asset_href(glyph_asset_path)
    glyph_symbol_id = _extract_first_glyph_symbol_id(glyph_asset_path)
    if glyph_symbol_id is None:
        return False
    glyph_ref = html.escape(f"{glyph_src}#{glyph_symbol_id}", quote=True)

    updated_html = _GLYPH_PRELOAD_USE_HREF_PATTERN.sub(
        lambda match: f"{match.group(1)}{glyph_ref}{match.group(2)}",
        html_content,
        count=1,
    )
    if updated_html == html_content:
        if _GLYPH_PRELOAD_SVG_PATTERN.search(html_content):
            return False
        body_match = _HTML_BODY_OPEN_TAG_PATTERN.search(html_content)
        if body_match is None:
            return False
        preload_svg = _build_glyph_preload_svg(glyph_src, glyph_symbol_id)
        insert_at = body_match.end()
        updated_html = (
            f"{html_content[:insert_at]}\n{preload_svg}\n{html_content[insert_at:]}"
        )

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


_SVG_DEFS_PATTERN = re.compile(r"<defs>(.*?)</defs>", flags=re.DOTALL)
_SVG_SYMBOL_PATTERN = re.compile(r"<symbol\b([^>]*)>(.*?)</symbol>", flags=re.DOTALL)
_SVG_ID_ATTR_PATTERN = re.compile(r'\s+id="([^"]+)"')
_SVG_WHITESPACE_PATTERN = re.compile(r"\s+")
_SVG_EXTERNAL_GLYPH_REF_PATTERN = re.compile(
    r"(?:xlink:)?href\s*=\s*['\"][^'\"]*glyphs(?:[-.][^'\"#?]*)?\.svg(?:\?[^'\"#]*)?(?:#[^'\"]+)?['\"]",
    flags=re.IGNORECASE,
)
_HTML_BODY_OPEN_TAG_PATTERN = re.compile(r"<body\b[^>]*>", flags=re.IGNORECASE)
_GLYPH_PRELOAD_SVG_PATTERN = re.compile(
    r"<svg\b(?=[^>]*\bdata-glyph-preload\s*=\s*['\"]true['\"])[^>]*>.*?</svg>",
    flags=re.IGNORECASE | re.DOTALL,
)
_GLYPH_PRELOAD_USE_HREF_PATTERN = re.compile(
    r"(<svg\b(?=[^>]*\bdata-glyph-preload\s*=\s*['\"]true['\"])[^>]*>.*?<use\b[^>]*\b(?:xlink:)?href\s*=\s*['\"])[^'\"]*(['\"])",
    flags=re.IGNORECASE | re.DOTALL,
)


def _sanitize_asset_prefix_component(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9-]+", "-", value.strip().lower())
    sanitized = re.sub(r"-+", "-", sanitized).strip("-")
    return sanitized


def _to_base36(value: int) -> str:
    if value <= 0:
        return "0"

    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    output: List[str] = []
    current = value
    while current:
        current, remainder = divmod(current, 36)
        output.append(digits[remainder])
    return "".join(reversed(output))


def _canonical_symbol_fingerprint(attrs_without_id: str, body: str) -> str:
    normalized_attrs = _SVG_WHITESPACE_PATTERN.sub(" ", attrs_without_id).strip()
    normalized_body = body.strip()
    if normalized_attrs:
        return f"<symbol {normalized_attrs}>{normalized_body}</symbol>"
    return f"<symbol>{normalized_body}</symbol>"


def _short_id_to_index(short_id: str) -> int:
    if not short_id.startswith("g"):
        return 0

    raw = short_id[1:]
    if not raw:
        return 0

    try:
        return int(raw, 36)
    except ValueError:
        return 0


def _load_global_glyph_registry(map_path: str) -> Dict[str, Any]:
    current_typst_version = _resolve_typst_version()
    default_registry: Dict[str, Any] = {
        "version": _GLOBAL_GLYPH_MAP_VERSION,
        "typst_version": current_typst_version,
        "next_short_index": 1,
        "symbols": {},
        "fingerprint_to_short": {},
        "typst_id_to_short": {},
    }

    if not os.path.isfile(map_path):
        return default_registry

    with open(map_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return {
        "version": data["version"],
        "typst_version": current_typst_version,
        "next_short_index": data["next_short_index"],
        "symbols": data["symbols"],
        "fingerprint_to_short": data["fingerprint_to_short"],
        "typst_id_to_short": data["typst_id_to_short"],
    }


def _allocate_next_short_id(registry: Dict[str, Any]) -> str:
    next_short_index = registry["next_short_index"]
    short_id = f"g{_to_base36(next_short_index)}"
    registry["next_short_index"] = next_short_index + 1
    return short_id


def _resolve_global_short_id(
    registry: Dict[str, Any],
    typst_id: str,
    fingerprint: str,
    attrs_without_id: str,
    body: str,
) -> str:
    symbols: Dict[str, Dict[str, str]] = registry["symbols"]
    typst_id_to_short: Dict[str, str] = registry["typst_id_to_short"]
    fingerprint_to_short: Dict[str, str] = registry["fingerprint_to_short"]

    typst_version = str(registry["typst_version"])
    scoped_typst_id = f"{typst_version}::{typst_id}"

    chosen_short_id: Optional[str] = None

    mapped_short_id: Optional[str]
    if scoped_typst_id in typst_id_to_short:
        mapped_short_id = typst_id_to_short[scoped_typst_id]
    elif typst_id in typst_id_to_short:
        mapped_short_id = typst_id_to_short[typst_id]
    else:
        mapped_short_id = None
    if mapped_short_id:
        mapped_symbol = symbols[mapped_short_id] if mapped_short_id in symbols else None
        if mapped_symbol and mapped_symbol["fingerprint"] == fingerprint:
            chosen_short_id = mapped_short_id

    if chosen_short_id is None:
        mapped_short_id = (
            fingerprint_to_short[fingerprint]
            if fingerprint in fingerprint_to_short
            else None
        )
        if mapped_short_id and mapped_short_id in symbols:
            chosen_short_id = mapped_short_id

    if chosen_short_id is None:
        chosen_short_id = _allocate_next_short_id(registry)

    existing_symbol = symbols[chosen_short_id] if chosen_short_id in symbols else None
    if existing_symbol is None:
        symbols[chosen_short_id] = {
            "fingerprint": fingerprint,
            "attrs": attrs_without_id,
            "body": body,
        }
    elif existing_symbol["fingerprint"] != fingerprint:
        chosen_short_id = _allocate_next_short_id(registry)
        symbols[chosen_short_id] = {
            "fingerprint": fingerprint,
            "attrs": attrs_without_id,
            "body": body,
        }

    typst_id_to_short[scoped_typst_id] = chosen_short_id
    fingerprint_to_short[fingerprint] = chosen_short_id

    return chosen_short_id


def _render_glyph_svg(symbols: Dict[str, Dict[str, str]]) -> str:
    ordered_short_ids = sorted(symbols.keys(), key=_short_id_to_index)
    glyph_symbols: List[str] = []
    for short_id in ordered_short_ids:
        symbol = symbols[short_id]
        attrs = symbol["attrs"]
        body = symbol["body"]
        glyph_symbols.append(f'<symbol id="{short_id}"{attrs}>{body}</symbol>')

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink">'
        f"<defs>{''.join(glyph_symbols)}</defs>"
        "</svg>"
    )


def _write_global_glyph_registry(map_path: str, registry: Dict[str, Any]) -> None:
    payload: Dict[str, Any] = {
        "version": _GLOBAL_GLYPH_MAP_VERSION,
        "typst_version": registry["typst_version"],
        "next_short_index": registry["next_short_index"],
        "symbols": registry["symbols"],
        "fingerprint_to_short": registry["fingerprint_to_short"],
        "typst_id_to_short": registry["typst_id_to_short"],
    }

    with open(map_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        f.write("\n")


def _extract_svg_symbols(
    svg_data: str,
) -> Optional[Tuple[str, List[Tuple[str, str, str]]]]:
    defs_match = _SVG_DEFS_PATTERN.search(svg_data)
    if not defs_match:
        return None

    defs_block = defs_match.group(0)
    defs_inner = defs_match.group(1)
    symbols: List[Tuple[str, str, str]] = []

    for symbol_match in _SVG_SYMBOL_PATTERN.finditer(defs_inner):
        attrs = symbol_match.group(1)
        body = symbol_match.group(2)

        id_match = _SVG_ID_ATTR_PATTERN.search(attrs)
        if not id_match:
            continue

        local_id = id_match.group(1)
        attrs_without_id = _SVG_ID_ATTR_PATTERN.sub("", attrs, count=1)
        symbols.append((local_id, attrs_without_id, body))

    return defs_block, symbols


def _extract_wrapped_global_short_id(symbol_body: str) -> Optional[str]:
    use_match = re.fullmatch(
        r'\s*<use\b[^>]*(?:xlink:)?href="([^"]+)"[^>]*/?>\s*(?:</use>)?\s*',
        symbol_body,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not use_match:
        return None

    href_value = use_match.group(1)
    if "#" not in href_value:
        return None

    href_path, short_id = href_value.rsplit("#", 1)
    if not short_id:
        return None

    if not href_path:
        return None

    href_path_without_query = href_path.split("?", 1)[0]
    href_basename = os.path.basename(href_path_without_query)
    if href_basename != GLOBAL_GLYPH_ASSET_FILENAME and not re.fullmatch(
        r"glyphs\.[0-9a-f]{6}\.svg",
        href_basename,
    ):
        return None

    return short_id


def _extract_and_rewrite_shared_svg_glyphs(
    svg_paths: List[str],
    dest_dir: str,
    glyph_scope_key: str,
    global_glyph_asset_path: Optional[str] = None,
    global_glyph_map_path: Optional[str] = None,
) -> Optional[str]:
    if not svg_paths:
        return None

    use_global_registry = bool(global_glyph_asset_path and global_glyph_map_path)
    registry: Optional[Dict[str, Any]] = None
    if use_global_registry:
        if global_glyph_map_path is None:
            raise RuntimeError("Global glyph map path is required.")
        registry = _load_global_glyph_registry(global_glyph_map_path)

    scope_component = _sanitize_asset_prefix_component(glyph_scope_key)
    if not scope_component:
        scope_component = "default"

    long_id_to_symbol: Dict[str, Tuple[str, str]] = {}
    page_symbol_maps: List[Tuple[str, str, str, List[Tuple[str, str, str]]]] = []

    for svg_path in svg_paths:
        with open(svg_path, "r", encoding="utf-8") as svg_file:
            svg_data = svg_file.read()

        extracted = _extract_svg_symbols(svg_data)
        if not extracted:
            continue

        defs_block, symbols = extracted
        if not symbols:
            continue

        local_symbol_map: List[Tuple[str, str, str]] = []
        for local_id, attrs_without_id, body in symbols:
            if use_global_registry and registry is not None:
                wrapped_short_id = _extract_wrapped_global_short_id(body)
                if wrapped_short_id:
                    existing_symbols: Dict[str, Dict[str, str]] = registry["symbols"]
                    if wrapped_short_id in existing_symbols:
                        local_symbol_map.append(
                            (local_id, attrs_without_id, wrapped_short_id)
                        )
                        continue

            symbol_fingerprint = _canonical_symbol_fingerprint(attrs_without_id, body)
            fingerprint_digest = hashlib.sha1(
                symbol_fingerprint.encode("utf-8")
            ).hexdigest()

            if use_global_registry and registry is not None:
                short_id = _resolve_global_short_id(
                    registry,
                    typst_id=local_id,
                    fingerprint=fingerprint_digest,
                    attrs_without_id=attrs_without_id,
                    body=body,
                )
                local_symbol_map.append((local_id, attrs_without_id, short_id))
                continue

            long_id = f"glyph-{scope_component}-{fingerprint_digest}"
            if long_id not in long_id_to_symbol:
                long_id_to_symbol[long_id] = (attrs_without_id, body)
            local_symbol_map.append((local_id, attrs_without_id, long_id))

        page_symbol_maps.append((svg_path, svg_data, defs_block, local_symbol_map))

    if not page_symbol_maps:
        return None

    short_id_map: Dict[str, str] = {}
    if use_global_registry and registry is not None:
        symbols = registry["symbols"]
        if not symbols:
            return None
        glyph_svg = _render_glyph_svg(symbols)
        if global_glyph_asset_path is None:
            raise RuntimeError("Global glyph asset path is required.")
        glyph_asset_seed_path = os.path.abspath(global_glyph_asset_path)
        glyph_asset_dir = os.path.dirname(glyph_asset_seed_path)
        glyph_asset_seed_name = os.path.basename(glyph_asset_seed_path)
        glyph_asset_prefix, glyph_asset_suffix = os.path.splitext(glyph_asset_seed_name)
        sanitized_prefix = _sanitize_asset_prefix_component(glyph_asset_prefix)
        if not sanitized_prefix:
            sanitized_prefix = "glyphs"
        if not glyph_asset_suffix:
            glyph_asset_suffix = ".svg"

        glyph_asset_path = _write_hashed_asset(
            asset_dir=glyph_asset_dir,
            prefix=sanitized_prefix,
            suffix=glyph_asset_suffix,
            content=glyph_svg,
            remove_stale=False,
        )
        if global_glyph_map_path is None:
            raise RuntimeError("Global glyph map path is required.")
        glyph_map_path = os.path.abspath(global_glyph_map_path)
        os.makedirs(os.path.dirname(glyph_map_path), exist_ok=True)
        _write_global_glyph_registry(glyph_map_path, registry)
    else:
        if not long_id_to_symbol:
            return None
        for index, long_id in enumerate(sorted(long_id_to_symbol.keys()), start=1):
            short_id_map[long_id] = f"g{_to_base36(index)}"

        glyph_symbols: List[str] = []
        for long_id in sorted(long_id_to_symbol.keys()):
            attrs_without_id, body = long_id_to_symbol[long_id]
            short_id = short_id_map[long_id]
            glyph_symbols.append(
                f'<symbol id="{short_id}"{attrs_without_id}>{body}</symbol>'
            )

        glyph_svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'xmlns:xlink="http://www.w3.org/1999/xlink">'
            f"<defs>{''.join(glyph_symbols)}</defs>"
            "</svg>"
        )

        assets_dir = safe_join_child(dest_dir, WEB_ASSETS_DIR_NAME)
        os.makedirs(assets_dir, exist_ok=True)
        glyph_prefix = f"glyphs-{scope_component}"
        glyph_asset_path = _write_hashed_asset(
            asset_dir=assets_dir,
            prefix=glyph_prefix,
            suffix=".svg",
            content=glyph_svg,
        )

    for svg_path, svg_data, defs_block, local_symbol_map in page_symbol_maps:
        glyph_href = (
            build_root_asset_href(glyph_asset_path)
            if use_global_registry
            else build_asset_sibling_href(glyph_asset_path)
        )
        wrapper_symbols: List[str] = []
        seen_local_ids: Set[str] = set()

        for local_id, attrs_without_id, long_id in local_symbol_map:
            if local_id in seen_local_ids:
                continue
            seen_local_ids.add(local_id)

            short_id = long_id if use_global_registry else short_id_map[long_id]
            wrapper_symbols.append(
                f'<symbol id="{local_id}"{attrs_without_id}'
                f'><use href="{glyph_href}#{short_id}"/></symbol>'
            )

        rewritten_defs = f"<defs>{''.join(wrapper_symbols)}</defs>"
        updated_svg_data = svg_data.replace(defs_block, rewritten_defs, 1)

        with open(svg_path, "w", encoding="utf-8") as svg_file:
            svg_file.write(updated_svg_data)

    return glyph_asset_path


def apply_global_glyph_mapping(root_dir: str, target_dirs: List[str]) -> Optional[str]:
    assets_dir = safe_join_child(root_dir, WEB_ASSETS_DIR_NAME)
    glyph_asset_path = os.path.join(assets_dir, GLOBAL_GLYPH_ASSET_FILENAME)
    glyph_map_path = os.path.join(assets_dir, GLOBAL_GLYPH_MAP_FILENAME)

    svg_paths: List[str] = []
    for directory in target_dirs:
        if not os.path.isdir(directory):
            continue
        for filename in sorted(os.listdir(directory)):
            if _is_generated_svg(filename, "page") or _is_generated_svg(
                filename, "meta-page"
            ):
                svg_paths.append(os.path.join(directory, filename))

    if not svg_paths:
        return None

    glyph_result = _extract_and_rewrite_shared_svg_glyphs(
        svg_paths,
        dest_dir=root_dir,
        glyph_scope_key="global",
        global_glyph_asset_path=glyph_asset_path,
        global_glyph_map_path=glyph_map_path,
    )

    for svg_path in svg_paths:
        _optimize_svg_with_normalized_href(svg_path)
    if glyph_result:
        _optimize_svg_with_normalized_href(glyph_result, preserve_ids=True)

    return glyph_result


def _is_root_asset_referenced(root_dir: str, asset_filename: str) -> bool:
    assets_dir = safe_join_child(root_dir, WEB_ASSETS_DIR_NAME)
    assets_dir_abs = os.path.abspath(assets_dir)
    needle = f"assets/{asset_filename}"

    for current_dir, _, files in os.walk(root_dir):
        for filename in files:
            if not filename.endswith((".html", ".svg")):
                continue

            file_path = os.path.join(current_dir, filename)
            file_abs = os.path.abspath(file_path)
            if file_abs.startswith(assets_dir_abs + os.sep):
                continue

            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            if needle in content:
                return True

    return False


def cleanup_legacy_glyph_assets(
    root_dir: str,
    target_dirs: List[str],
    clean_global_store: bool = False,
) -> int:
    cleaned_count = 0

    root_assets_dir = safe_join_child(root_dir, WEB_ASSETS_DIR_NAME)
    candidate_asset_dirs: Set[str] = set()
    candidate_asset_dirs.add(root_assets_dir)
    for directory in target_dirs:
        if not os.path.isdir(directory):
            continue
        candidate_asset_dirs.add(os.path.join(directory, WEB_ASSETS_DIR_NAME))

    for asset_dir in sorted(candidate_asset_dirs):
        if not os.path.isdir(asset_dir):
            continue

        normalized_asset_dir = os.path.abspath(asset_dir)
        is_root_assets_dir = normalized_asset_dir == os.path.abspath(root_assets_dir)

        for filename in os.listdir(asset_dir):
            if filename == GLOBAL_GLYPH_ASSET_FILENAME:
                if (
                    clean_global_store
                    and is_root_assets_dir
                    and not _is_root_asset_referenced(root_dir, filename)
                ):
                    target_path = os.path.join(asset_dir, filename)
                    if os.path.isfile(target_path):
                        os.remove(target_path)
                        cleaned_count += 1
                continue

            remove_legacy_post_glyph = filename.startswith(
                "glyphs-"
            ) and filename.endswith(".svg")
            remove_legacy_global_glyph = (
                clean_global_store
                and is_root_assets_dir
                and bool(re.fullmatch(r"glyphs\.[0-9a-f]{6}\.svg", filename))
            )
            if remove_legacy_global_glyph and _is_root_asset_referenced(
                root_dir, filename
            ):
                remove_legacy_global_glyph = False

            remove_legacy_global_map = (
                clean_global_store
                and is_root_assets_dir
                and bool(re.fullmatch(r"glyph-map\.[0-9a-f]{6}\.json", filename))
            )

            if not (
                remove_legacy_post_glyph
                or remove_legacy_global_glyph
                or remove_legacy_global_map
            ):
                continue

            target_path = os.path.join(asset_dir, filename)
            if not os.path.isfile(target_path):
                continue

            os.remove(target_path)
            cleaned_count += 1

        if normalized_asset_dir != os.path.abspath(root_assets_dir):
            try:
                if not os.listdir(asset_dir):
                    os.rmdir(asset_dir)
            except OSError:
                pass

    return cleaned_count


def _normalize_svg_href_attributes(svg_content: str) -> str:
    def _normalize_tag(match: re.Match) -> str:
        tag = match.group(0)
        has_xlink_href = bool(re.search(r"\bxlink:href\s*=", tag, flags=re.IGNORECASE))
        if not has_xlink_href:
            return tag

        has_plain_href = bool(re.search(r"(?<!:)\bhref\s*=", tag, flags=re.IGNORECASE))
        if has_plain_href:
            tag = re.sub(
                r"\s+xlink:href\s*=\s*(['\"])[^'\"]*\1",
                "",
                tag,
                flags=re.IGNORECASE,
            )

        return re.sub(r"\bxlink:href\b", "href", tag, flags=re.IGNORECASE)

    return re.sub(r"<[^>]+>", _normalize_tag, svg_content)


def _strip_typst_classes(svg_content: str) -> str:
    def _rewrite_class_attr(match: re.Match) -> str:
        quote = match.group("quote")
        class_value = match.group("value")
        class_names = [
            class_name
            for class_name in class_value.split()
            if class_name and not class_name.startswith("typst-")
        ]
        if not class_names:
            return ""
        return f" class={quote}{' '.join(class_names)}{quote}"

    return re.sub(
        r"\s+class\s*=\s*(?P<quote>['\"])(?P<value>[^'\"]*)(?P=quote)",
        _rewrite_class_attr,
        svg_content,
    )


def _prepare_anchor_hrefs_for_svgo(svg_content: str) -> str:
    inserted_xlink_href = False

    def _prepare_anchor_tag(match: re.Match) -> str:
        nonlocal inserted_xlink_href
        attrs = match.group(1)

        if re.search(r"\bxlink:href\s*=", attrs, flags=re.IGNORECASE):
            return match.group(0)

        href_match = re.search(r"(?<!:)\bhref\s*=", attrs, flags=re.IGNORECASE)
        if not href_match:
            return match.group(0)

        inserted_xlink_href = True
        prepared_attrs = re.sub(
            r"(?<!:)\bhref\s*=",
            "xlink:href=",
            attrs,
            count=1,
            flags=re.IGNORECASE,
        )
        return f"<a{prepared_attrs}>"

    prepared_svg = re.sub(r"<a([^>]*)>", _prepare_anchor_tag, svg_content)
    if not inserted_xlink_href:
        return prepared_svg

    if re.search(r"<svg\b[^>]*\bxmlns:xlink\s*=", prepared_svg, flags=re.IGNORECASE):
        return prepared_svg

    return re.sub(
        r"(<svg\b[^>]*)(>)",
        r'\1 xmlns:xlink="http://www.w3.org/1999/xlink"\2',
        prepared_svg,
        count=1,
        flags=re.IGNORECASE,
    )


def _extract_anchor_href(attrs: str) -> Optional[str]:
    href_match = re.search(
        r"\s+(?:xlink:)?href\s*=\s*['\"](?P<href>[^'\"]+)['\"]",
        attrs,
        flags=re.IGNORECASE,
    )
    if href_match is None:
        return None
    href = href_match.group("href").strip()
    return href if href else None


def _parse_action_payload(action_payload: str) -> Tuple[str, Dict[str, str]]:
    segments = [segment.strip() for segment in action_payload.split("|")]
    segments = [segment for segment in segments if segment]
    if not segments:
        return "", {}

    action_token = segments[0]
    metadata: Dict[str, str] = {}
    for segment in segments[1:]:
        separator_index = segment.find(":")
        if separator_index <= 0:
            continue
        key = segment[:separator_index].strip().lower()
        value = segment[separator_index + 1 :].strip()
        if not key or not value:
            continue
        metadata[key] = value
    return action_token, metadata


def _parse_svg_action_href(href: Optional[str]) -> Tuple[Optional[str], Dict[str, str]]:
    if href is None:
        return None, {}

    stripped_href = href.strip()
    if not stripped_href.startswith("#action="):
        return None, {}

    action_payload = stripped_href[len("#action=") :]
    try:
        action_payload = unquote(action_payload)
    except Exception:
        pass
    return _parse_action_payload(action_payload)


def _infer_svg_anchor_role(
    href: Optional[str],
    action_metadata: Optional[Dict[str, Dict[str, str]]] = None,
) -> Optional[str]:
    action_token, _ = _parse_svg_action_href(href)
    if action_token is None:
        return None
    meta = (action_metadata or {}).get(action_token, {})
    role = meta.get("role", "")
    if role:
        return role
    if action_token == "theme" or action_token.startswith("copy:"):
        return "button"
    return None


def _infer_svg_anchor_tabindex(
    href: Optional[str],
    action_metadata: Optional[Dict[str, Dict[str, str]]] = None,
) -> Optional[str]:
    action_token, _ = _parse_svg_action_href(href)
    if action_token is None:
        return None
    meta = (action_metadata or {}).get(action_token, {})
    tabindex = meta.get("tabindex", "")
    return tabindex if tabindex else None


_INDEX_HTML_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_DATE_PATH_SEGMENT_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INDEX_LABEL_LOWERCASE_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


def _humanize_index_target_segment(segment: str) -> Optional[str]:
    normalized = segment.strip()
    if not normalized or normalized in {".", ".."}:
        return None
    if _DATE_PATH_SEGMENT_PATTERN.fullmatch(normalized):
        return None
    if not _INDEX_HTML_SEGMENT_PATTERN.fullmatch(normalized):
        return None

    words = [part for part in re.split(r"[._-]+", normalized) if part]
    if not words:
        return None

    label_parts: List[str] = []
    for index, word in enumerate(words):
        if word.isupper() or word.isdigit():
            label_parts.append(word)
            continue
        if any(char.isdigit() for char in word):
            if word[0].isalpha():
                label_parts.append(word[0].upper() + word[1:])
            else:
                label_parts.append(word)
            continue

        lower_word = word.lower()
        if index > 0 and lower_word in _INDEX_LABEL_LOWERCASE_WORDS:
            label_parts.append(lower_word)
            continue

        label_parts.append(lower_word.capitalize())

    label = " ".join(label_parts).strip()
    return label if label else None


def _infer_index_href_label(href: str) -> Optional[str]:
    parsed_href = urlparse(href)
    path = parsed_href.path or href
    try:
        path = unquote(path)
    except Exception:
        pass

    normalized_path = path.replace("\\", "/").strip()
    if not normalized_path:
        return None

    segments = [
        segment for segment in normalized_path.split("/") if segment and segment != "."
    ]
    if not segments or segments[-1].lower() != "index.html":
        return None

    if len(segments) >= 2:
        target_label = _humanize_index_target_segment(segments[-2])
        if target_label is not None:
            return target_label
    return "Contents"


_HTML_TITLE_TAG_PATTERN = re.compile(
    r"<title\b[^>]*>(?P<title>.*?)</title>",
    flags=re.IGNORECASE | re.DOTALL,
)
_HTML_H1_TAG_PATTERN = re.compile(
    r"<h1\b[^>]*>(?P<title>.*?)</h1>",
    flags=re.IGNORECASE | re.DOTALL,
)
_HTML_TITLE_CACHE: Dict[str, Optional[str]] = {}


def _read_html_title(html_path: str) -> Optional[str]:
    cached = _HTML_TITLE_CACHE.get(html_path)
    if cached is not None or html_path in _HTML_TITLE_CACHE:
        return cached

    if not os.path.isfile(html_path):
        _HTML_TITLE_CACHE[html_path] = None
        return None

    with open(html_path, "r", encoding="utf-8") as html_file:
        html_data = html_file.read()

    h1_match = _HTML_H1_TAG_PATTERN.search(html_data)
    if h1_match is not None:
        title = html.unescape(" ".join(h1_match.group("title").split())).strip()
        _HTML_TITLE_CACHE[html_path] = title or None
        return _HTML_TITLE_CACHE[html_path]

    title_match = _HTML_TITLE_TAG_PATTERN.search(html_data)
    if title_match is None:
        _HTML_TITLE_CACHE[html_path] = None
        return None

    title = html.unescape(" ".join(title_match.group("title").split())).strip()
    _HTML_TITLE_CACHE[html_path] = title or None
    return _HTML_TITLE_CACHE[html_path]


def _resolve_post_index_title_from_href(
    href: str,
    svg_path: Optional[str],
) -> Optional[str]:
    if svg_path is None:
        return None

    parsed = urlparse(href)
    if parsed.scheme or parsed.netloc:
        return None

    raw_path = parsed.path or href
    if not raw_path:
        return None

    try:
        decoded_path = unquote(raw_path)
    except Exception:
        decoded_path = raw_path

    if not decoded_path.lower().endswith("index.html"):
        return None

    svg_dir = os.path.dirname(os.path.abspath(svg_path))
    target_path = os.path.normpath(os.path.join(svg_dir, decoded_path))
    normalized_target = target_path.replace(os.sep, "/")
    if "/posts/" not in normalized_target:
        return None

    return _read_html_title(target_path)


def _normalize_site_href_for_label(
    href: str,
    site_base_url: Optional[str],
) -> Optional[str]:
    if not site_base_url:
        return None

    parsed_href = urlparse(href)
    if parsed_href.scheme not in {"http", "https"} or not parsed_href.netloc:
        return None

    parsed_site = urlparse(site_base_url)
    site_hostname = parsed_site.hostname
    href_hostname = parsed_href.hostname
    if not site_hostname or not href_hostname:
        return None
    if site_hostname.lower() != href_hostname.lower():
        return None

    site_path = parsed_site.path or "/"
    href_path = parsed_href.path or "/"
    normalized_site_path = site_path.rstrip("/")
    normalized_href_path = href_path.rstrip("/")

    if normalized_site_path and normalized_site_path != normalized_href_path:
        site_prefix = f"{normalized_site_path}/"
        href_with_slash = f"{normalized_href_path}/" if normalized_href_path else "/"
        if not href_with_slash.startswith(site_prefix):
            return None
        relative_path = href_with_slash[len(site_prefix) :].rstrip("/")
    else:
        relative_path = ""

    if not relative_path:
        normalized_path = "index.html"
    elif relative_path.endswith(".html"):
        normalized_path = relative_path
    elif "." not in os.path.basename(relative_path):
        normalized_path = f"{relative_path}/index.html"
    else:
        normalized_path = relative_path

    if parsed_href.query:
        return f"{normalized_path}?{parsed_href.query}"
    return normalized_path


def _infer_svg_anchor_label(
    href: Optional[str],
    svg_path: Optional[str] = None,
    site_base_url: Optional[str] = None,
    action_metadata: Optional[Dict[str, Dict[str, str]]] = None,
) -> Optional[str]:
    if href is None:
        return None

    stripped_href = href.strip()
    if not stripped_href:
        return None

    action_token, _ = _parse_svg_action_href(href)
    if action_token is not None:
        meta = (action_metadata or {}).get(action_token, {})
        label = meta.get("label", "")
        if label:
            return label
        if action_token == "theme":
            return "Theme"
        if action_token.startswith("copy:"):
            return "Copy"
        return "Action"

    normalized_internal_href = _normalize_site_href_for_label(
        stripped_href,
        site_base_url=site_base_url,
    )
    href_for_inference = normalized_internal_href or stripped_href

    if stripped_href.startswith(("http://", "https://")):
        if normalized_internal_href is None:
            parsed = urlparse(stripped_href)
            if parsed.netloc:
                return f"External: {parsed.netloc}"
            return "External"

    post_title = _resolve_post_index_title_from_href(href_for_inference, svg_path)
    if post_title is not None:
        return post_title

    index_label = _infer_index_href_label(href_for_inference)
    if index_label is not None:
        return index_label

    href_lower = href_for_inference.lower()
    if href_lower.endswith("rss.xml"):
        return "RSS"
    if href_lower.endswith("meta.html"):
        return "Meta"
    if href_lower.endswith(".pdf"):
        return "PDF"
    if href_lower.endswith(".typ"):
        return "Source"

    return "Link"


def _inject_svg_anchor_accessibility(
    svg_data: str,
    svg_path: Optional[str] = None,
    site_base_url: Optional[str] = None,
    action_metadata: Optional[Dict[str, Dict[str, str]]] = None,
) -> str:
    def _rewrite_anchor(match: re.Match) -> str:
        attrs = match.group("attrs")
        body = match.group("body")
        href = _extract_anchor_href(attrs)
        label = _infer_svg_anchor_label(
            href,
            svg_path=svg_path,
            site_base_url=site_base_url,
            action_metadata=action_metadata,
        )
        if label is None:
            return match.group(0)

        rewritten_attrs = attrs
        role = _infer_svg_anchor_role(href, action_metadata=action_metadata)
        has_role = (
            re.search(r"\s+role\s*=\s*['\"][^'\"]+['\"]", attrs, flags=re.IGNORECASE)
            is not None
        )
        if role is not None and not has_role:
            rewritten_attrs += f' role="{html.escape(role, quote=True)}"'

        tabindex = _infer_svg_anchor_tabindex(href, action_metadata=action_metadata)
        has_tabindex = (
            re.search(
                r"\s+tabindex\s*=\s*['\"][^'\"]*['\"]",
                attrs,
                flags=re.IGNORECASE,
            )
            is not None
        )
        if tabindex is not None and not has_tabindex:
            rewritten_attrs += f' tabindex="{html.escape(tabindex, quote=True)}"'

        has_explicit_name = (
            re.search(r"\s+aria-label\s*=\s*['\"][^'\"]+['\"]", attrs, flags=re.IGNORECASE)
            is not None
            or re.search(
                r"\s+aria-labelledby\s*=\s*['\"][^'\"]+['\"]",
                attrs,
                flags=re.IGNORECASE,
            )
            is not None
        )
        if not has_explicit_name:
            rewritten_attrs += f' aria-label="{html.escape(label, quote=True)}"'

        rewritten_body = body
        has_title_node = re.search(r"<title\b[^>]*>", body, flags=re.IGNORECASE) is not None
        if not has_title_node:
            rewritten_body = f"<title>{html.escape(label)}</title>{body}"

        return f"<a{rewritten_attrs}>{rewritten_body}</a>"

    return re.sub(
        r"<a(?P<attrs>[^>]*)>(?P<body>.*?)</a>",
        _rewrite_anchor,
        svg_data,
        flags=re.DOTALL,
    )


def _normalize_svg_href_file(
    svg_path: str,
    site_base_url: Optional[str] = None,
    action_metadata: Optional[Dict[str, Dict[str, str]]] = None,
) -> None:
    if not os.path.isfile(svg_path):
        return

    with open(svg_path, "r", encoding="utf-8") as svg_file:
        svg_data = svg_file.read()

    normalized_svg_data = _normalize_svg_href_attributes(svg_data)
    normalized_svg_data = _strip_typst_classes(normalized_svg_data)
    normalized_svg_data = _inject_svg_anchor_accessibility(
        normalized_svg_data,
        svg_path=svg_path,
        site_base_url=site_base_url,
        action_metadata=action_metadata,
    )
    if normalized_svg_data == svg_data:
        return

    with open(svg_path, "w", encoding="utf-8") as svg_file:
        svg_file.write(normalized_svg_data)


def _prepare_anchor_hrefs_for_svgo_file(svg_path: str) -> None:
    if not os.path.isfile(svg_path):
        return

    with open(svg_path, "r", encoding="utf-8") as svg_file:
        svg_data = svg_file.read()

    prepared_svg_data = _prepare_anchor_hrefs_for_svgo(svg_data)
    if prepared_svg_data == svg_data:
        return

    with open(svg_path, "w", encoding="utf-8") as svg_file:
        svg_file.write(prepared_svg_data)


def _optimize_svg_with_normalized_href(
    svg_path: str,
    preserve_ids: bool = False,
    site_base_url: Optional[str] = None,
    action_metadata: Optional[Dict[str, Dict[str, str]]] = None,
) -> None:
    if not os.path.isfile(svg_path):
        return

    _prepare_anchor_hrefs_for_svgo_file(svg_path)
    _run_svgo(svg_path, preserve_ids=preserve_ids)
    _normalize_svg_href_file(svg_path, site_base_url=site_base_url, action_metadata=action_metadata)


def _convert_to_webp(src_bytes: bytes, dst_path: str) -> None:
    import io

    from PIL import Image  # type: ignore[import]

    with Image.open(io.BytesIO(src_bytes)) as img:
        img.save(dst_path, "webp", quality=85)


def _build_generated_driver_image_name(image_rel: str, asset_hash: str) -> str:
    src_hash = hashlib.sha1(image_rel.encode()).hexdigest()[:_ASSET_HASH_LENGTH]
    return f"image.{src_hash}.{asset_hash}.webp"


def _is_generated_driver_image_asset(filename: str) -> bool:
    parts = filename.split(".")
    if len(parts) < 3 or parts[-1] != "webp":
        return False
    digest = parts[-2]
    return (
        len(digest) == _ASSET_HASH_LENGTH
        and all(ch in "0123456789abcdef" for ch in digest)
    )


def _remove_stale_generated_driver_image_assets(
    asset_dir: str,
    keep_filenames: Set[str],
) -> None:
    if not os.path.isdir(asset_dir):
        return

    for filename in os.listdir(asset_dir):
        if filename in keep_filenames or not _is_generated_driver_image_asset(filename):
            continue

        target_path = os.path.join(asset_dir, filename)
        if os.path.isfile(target_path):
            try:
                os.remove(target_path)
            except FileNotFoundError:
                continue


def _replace_driver_image_anchors(
    svg_data: str,
    image_source_dir: str,
    svg_dest_dir: str,
    asset_hash: str,
    image_asset_names: Dict[str, str],
) -> str:
    def _rewrite(match: re.Match) -> str:
        attrs = match.group("attrs")
        body = match.group("body")

        href_match = re.search(r"(?:xlink:)?href\s*=\s*['\"]([^'\"]+)['\"]", attrs)
        if href_match is None:
            return match.group(0)
        href = href_match.group(1)

        parsed = urlparse(href)
        if parsed.scheme != "driver-image":
            return match.group(0)

        image_rel = unquote(parsed.netloc + parsed.path)
        alt_values = parse_qs(parsed.query).get("alt", [])
        alt = alt_values[0] if alt_values else None

        w_h = re.search(
            r'<rect\b[^>]*\bwidth=["\']([^"\']+)["\'][^>]*\bheight=["\']([^"\']+)["\']',
            body,
        )
        h_w = re.search(
            r'<rect\b[^>]*\bheight=["\']([^"\']+)["\'][^>]*\bwidth=["\']([^"\']+)["\']',
            body,
        )
        if w_h:
            width, height = w_h.group(1), w_h.group(2)
        elif h_w:
            width, height = h_w.group(2), h_w.group(1)
        else:
            return match.group(0)

        src_path = os.path.join(image_source_dir, image_rel)
        if not os.path.isfile(src_path):
            print(f"driver-image: source not found: {src_path!r}", file=sys.stderr)
            return match.group(0)

        webp_name = image_asset_names.get(image_rel)
        if webp_name is None:
            webp_name = _build_generated_driver_image_name(image_rel, asset_hash)
            image_asset_names[image_rel] = webp_name
        dst_path = os.path.join(svg_dest_dir, webp_name)
        if not os.path.exists(dst_path):
            with open(src_path, "rb") as f:
                _convert_to_webp(f.read(), dst_path)

        if alt:
            return (
                f'<image href="{webp_name}" width="{width}" height="{height}"'
                f' role="img" aria-label="{html.escape(alt, quote=True)}"/>'
            )
        return f'<image href="{webp_name}" width="{width}" height="{height}" role="presentation"/>'

    return re.sub(
        r"<a(?P<attrs>[^>]*)>(?P<body>.*?)</a>",
        _rewrite,
        svg_data,
        flags=re.DOTALL,
    )


def patch_svg_file(
    src_path: str,
    dst_path: str,
    svg_href_rewrites: Optional[Dict[str, str]],
    href_base_dir: Optional[str] = None,
    site_base_url: Optional[str] = None,
    image_source_dir: Optional[str] = None,
    asset_hash: Optional[str] = None,
    image_asset_names: Optional[Dict[str, str]] = None,
    action_metadata: Optional[Dict[str, Dict[str, str]]] = None,
) -> None:
    with open(src_path, "r", encoding="utf-8") as svg_file:
        svg_data = svg_file.read()

    svg_data = re.sub(
        r'(<svg[^>]*?)\swidth="[^"]+"', r'\1 width="100%"', svg_data, count=1
    )
    svg_data = re.sub(
        r'(<svg[^>]*?)\sheight="[^"]+"', r'\1 height="100%"', svg_data, count=1
    )

    def _rewrite_href(match: re.Match) -> str:
        attr = match.group("attr")
        quote = match.group("quote")
        value = match.group("value")
        safe_rewrites = svg_href_rewrites or {}
        rewritten = safe_rewrites.get(value, value)
        if href_base_dir is not None:
            rewritten = _rebase_relative_href_for_destination(
                href=rewritten,
                source_dir=href_base_dir,
                dest_dir=os.path.dirname(dst_path),
            )
        return f"{attr}={quote}{rewritten}{quote}"

    svg_data = re.sub(
        r"(?P<attr>(?:xlink:)?href)\s*=\s*(?P<quote>['\"])(?P<value>[^'\"]+)(?P=quote)",
        _rewrite_href,
        svg_data,
    )
    svg_data = _prepare_anchor_hrefs_for_svgo(svg_data)

    def _rewrite_anchor_tag(match: re.Match) -> str:
        attrs = match.group(1)
        javascript_parent_match = re.search(
            r"\s+(?:xlink:)?href\s*=\s*['\"]javascript:parent\.(?:copyCode|toggleColorTheme)\(",
            attrs,
        )
        action_hash_match = re.search(
            r"\s+(?:xlink:)?href\s*=\s*['\"]#action=[^'\"]*['\"]",
            attrs,
        )
        if javascript_parent_match or action_hash_match:
            attrs_without_target = re.sub(
                r"\s+target\s*=\s*['\"][^'\"]*['\"]",
                "",
                attrs,
            )
            return f"<a{attrs_without_target}>"

        if re.search(r"\s+target\s*=\s*['\"][^'\"]*['\"]", attrs):
            return f"<a{attrs}>"
        return f'<a target="_top"{attrs}>'

    svg_data = re.sub(r"<a([^>]*)>", _rewrite_anchor_tag, svg_data)
    svg_data = _inject_svg_anchor_accessibility(
        svg_data,
        svg_path=dst_path,
        site_base_url=site_base_url,
        action_metadata=action_metadata,
    )
    svg_data = _inject_svg_theme_classes(svg_data)
    svg_data = _inject_svg_theme_style(svg_data)

    if (
        image_source_dir is not None
        and asset_hash is not None
        and image_asset_names is not None
    ):
        svg_data = _replace_driver_image_anchors(
            svg_data,
            image_source_dir=image_source_dir,
            svg_dest_dir=os.path.dirname(dst_path),
            asset_hash=asset_hash,
            image_asset_names=image_asset_names,
        )

    with open(dst_path, "w", encoding="utf-8") as svg_file:
        svg_file.write(svg_data)


def _build_open_graph_metadata(
    title: str,
    description: str,
    og_type: str,
    og_url: Optional[str],
) -> str:
    if not og_type:
        raise RuntimeError("Open Graph type must not be empty.")

    metadata_lines = [
        f'<meta property="og:title" content="{html.escape(title, quote=True)}">',
        (
            '<meta property="og:description" content="'
            f'{html.escape(description, quote=True)}">'
        ),
        f'<meta property="og:type" content="{html.escape(og_type, quote=True)}">',
    ]
    if og_url:
        metadata_lines.append(
            f'<meta property="og:url" content="{html.escape(og_url, quote=True)}">'
        )
    return "\n    ".join(metadata_lines)


def build_html_from_svgs(
    template_path: str,
    output_dir: str,
    dest_dir: str,
    page_count: int,
    title_format: str,
    asset_context: "DriverAssetContext",
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
    asset_dest_dir: Optional[str] = None,
    rss_feed_path: Optional[str] = None,
    og_type: str = "website",
    og_url: Optional[str] = None,
    glyph_scope_key: Optional[str] = None,
    enable_shared_glyph_extraction: bool = True,
    image_source_dir: Optional[str] = None,
    asset_hash: Optional[str] = None,
    site_base_url: Optional[str] = None,
    action_metadata: Optional[Dict[str, Dict[str, str]]] = None,
) -> str:
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    index_path = os.path.join(dest_dir, html_filename)
    html_dir = os.path.dirname(index_path)
    page_asset_dir = asset_dest_dir or dest_dir
    page_links_list: List[str] = []
    page_render_items: List[Tuple[str, str]] = []
    patched_svg_paths: List[str] = []
    os.makedirs(dest_dir, exist_ok=True)
    os.makedirs(page_asset_dir, exist_ok=True)
    image_asset_names: Dict[str, str] = {}

    svg_files = sorted(
        f for f in os.listdir(output_dir) if _is_generated_svg(f, svg_name_prefix)
    )
    if page_count:
        svg_files = svg_files[:page_count]

    current_svg_set = set(svg_files)
    cleanup_dirs = [page_asset_dir]
    if os.path.abspath(page_asset_dir) != os.path.abspath(dest_dir):
        cleanup_dirs.append(dest_dir)
    for cleanup_dir in cleanup_dirs:
        if not os.path.isdir(cleanup_dir):
            continue
        for filename in os.listdir(cleanup_dir):
            if (
                _is_generated_svg(filename, svg_name_prefix)
                and filename not in current_svg_set
            ):
                os.remove(os.path.join(cleanup_dir, filename))

    for i, filename in enumerate(svg_files, start=1):
        src_path = os.path.join(output_dir, filename)
        dst_path = os.path.join(page_asset_dir, filename)

        patch_svg_file(
            src_path,
            dst_path,
            svg_href_rewrites,
            href_base_dir=html_dir,
            site_base_url=site_base_url,
            image_source_dir=image_source_dir,
            asset_hash=asset_hash,
            image_asset_names=image_asset_names,
            action_metadata=action_metadata,
        )
        patched_svg_paths.append(dst_path)

        page_title = title_format.replace("{i}", str(i))
        page_render_items.append((dst_path, page_title))

    if image_source_dir is not None and asset_hash is not None:
        _remove_stale_generated_driver_image_assets(
            page_asset_dir,
            keep_filenames=set(image_asset_names.values()),
        )

    glyph_asset_path: Optional[str] = None
    if enable_shared_glyph_extraction:
        glyph_scope = glyph_scope_key or svg_name_prefix
        glyph_asset_path = _extract_and_rewrite_shared_svg_glyphs(
            patched_svg_paths,
            dest_dir=page_asset_dir,
            glyph_scope_key=glyph_scope,
            global_glyph_asset_path=asset_context.global_glyph_asset_path,
            global_glyph_map_path=asset_context.global_glyph_map_path,
        )

    for svg_path in patched_svg_paths:
        _optimize_svg_with_normalized_href(
            svg_path,
            site_base_url=site_base_url,
            action_metadata=action_metadata,
        )
    if enable_shared_glyph_extraction and glyph_asset_path:
        _optimize_svg_with_normalized_href(
            glyph_asset_path,
            preserve_ids=True,
            site_base_url=site_base_url,
        )

    for svg_path, page_title in page_render_items:
        page_href = build_local_asset_href(svg_path)
        page_links_list.append(
            f'<object class="page" type="image/svg+xml" data="{html.escape(page_href, quote=True)}" '
            f'title="{page_title}"></object>'
        )

    page_links = "\n".join(page_links_list)
    index_content = template.replace("{{PAGES}}", page_links)
    index_content = index_content.replace(
        "{{INLINE_STYLE}}",
        f"<style>{asset_context.web_assets.inline_style}</style>" if asset_context.web_assets.inline_style else "",
    )
    index_content = index_content.replace(
        "{{INLINE_SCRIPT}}",
        f"<script>{asset_context.web_assets.inline_script}</script>" if asset_context.web_assets.inline_script else "",
    )

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
    index_content = index_content.replace(
        "{{DESCRIPTION}}", html.escape(meta_description)
    )
    index_content = index_content.replace(
        "{{OGP_METADATA}}",
        _build_open_graph_metadata(
            title=title,
            description=meta_description,
            og_type=og_type,
            og_url=og_url,
        ),
    )
    index_content = index_content.replace("{{TITLE}}", html.escape(title))
    index_content = index_content.replace("{{TEXT}}", hidden_text)
    index_content = index_content.replace("{{TOPBAR}}", top_bar_html)
    index_content = index_content.replace("{{REVISION}}", revision_html)

    stylesheet_src = build_root_asset_href(asset_context.web_assets.stylesheet_path)
    clipboard_src = build_root_asset_href(asset_context.web_assets.clipboard_script_path)
    theme_src = build_root_asset_href(asset_context.web_assets.theme_script_path)
    index_content = index_content.replace(
        "{{STYLESHEET_SRC}}", html.escape(stylesheet_src)
    )
    index_content = index_content.replace(
        "{{CLIPBOARD_SRC}}", html.escape(clipboard_src)
    )
    index_content = index_content.replace("{{THEME_SRC}}", html.escape(theme_src))
    rss_feed_link = ""
    if rss_feed_path:
        rss_feed_href = build_relative_href(
            html_dir,
            rss_feed_path,
        )
        rss_feed_link = (
            '<link rel="alternate" type="application/rss+xml" '
            f'title="RSS" href="{html.escape(rss_feed_href)}">'
        )
    index_content = index_content.replace("{{RSS_FEED_LINK}}", rss_feed_link)

    glyph_preload_html = ""
    warmup_glyph_asset_path = glyph_asset_path or asset_context.global_glyph_asset_path
    if warmup_glyph_asset_path:
        glyph_src = build_root_asset_href(warmup_glyph_asset_path)
        glyph_symbol_id = _extract_first_glyph_symbol_id(warmup_glyph_asset_path)
        if glyph_symbol_id is not None:
            glyph_preload_html = _build_glyph_preload_svg(glyph_src, glyph_symbol_id)
    index_content = index_content.replace("{{GLYPH_PRELOAD}}", glyph_preload_html)

    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_content)

    return index_path


def find_latest_revision(
    posts_dir: str, workspace_name: str, skip_latest: bool = False
) -> Tuple[Optional[str], Optional[str]]:
    revisions = list_workspace_revisions(posts_dir, workspace_name)
    if not revisions:
        return None, None

    revision_index = 1 if skip_latest else 0
    if revision_index >= len(revisions):
        return None, None

    selected = revisions[revision_index]
    return selected.date, f"../../{selected.date}/{selected.entry_name}/index.html"


def compile_and_build_html(
    source_bytes: bytes,
    output_dir: str,
    asset_hash: str,
    file_prefix: str,
    template_path: str,
    dest_dir: str,
    title_format: str,
    default_title: str,
    asset_context: "DriverAssetContext",
    description: Optional[str] = None,
    typst_inputs: Optional["TypstInputs"] = None,
    extract_title_from_pdf: bool = False,
    hidden_text_override: Optional[str] = None,
    svg_href_rewrites: Optional[Dict[str, str]] = None,
    svg_name_prefix: str = "page",
    html_filename: str = "index.html",
    asset_dest_dir: Optional[str] = None,
    rss_feed_path: Optional[str] = None,
    og_type: str = "website",
    og_url: Optional[str] = None,
    glyph_scope_key: Optional[str] = None,
    enable_shared_glyph_extraction: bool = True,
    image_source_dir: Optional[str] = None,
    site_base_url: Optional[str] = None,
) -> str:
    display_compiled_date = datetime.now().strftime("%Y-%m-%d")
    resolved_inputs_svg = dict(typst_inputs.svg) if typst_inputs is not None else {}
    resolved_inputs_pdf = dict(typst_inputs.pdf) if typst_inputs is not None else {}
    resolved_inputs_svg.setdefault("display_compiled_date", display_compiled_date)
    resolved_inputs_pdf.setdefault("display_compiled_date", display_compiled_date)

    svg_prefix = f"{svg_name_prefix}{{0p}}.{asset_hash}.svg"
    pdf_name = f"{file_prefix}.{asset_hash}.pdf"
    pdf_creation_timestamp = _resolve_pdf_creation_timestamp(resolved_inputs_pdf)

    run_typst_compile(
        source_bytes,
        os.path.join(output_dir, svg_prefix),
        export_format="svg",
        inputs=resolved_inputs_svg,
    )

    pdf_path = os.path.join(output_dir, pdf_name)
    run_typst_compile(
        source_bytes,
        pdf_path,
        export_format="pdf",
        inputs=resolved_inputs_pdf,
        creation_timestamp=pdf_creation_timestamp,
    )

    page_count = len(
        [f for f in os.listdir(output_dir) if _is_generated_svg(f, svg_name_prefix)]
    )

    action_meta = extract_action_metadata_from_content(
        source_bytes,
        query_root=os.getcwd(),
        inputs=resolved_inputs_svg,
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
        asset_dest_dir=asset_dest_dir,
        asset_context=asset_context,
        rss_feed_path=rss_feed_path,
        og_type=og_type,
        og_url=og_url,
        glyph_scope_key=glyph_scope_key or svg_name_prefix,
        enable_shared_glyph_extraction=enable_shared_glyph_extraction,
        image_source_dir=image_source_dir,
        asset_hash=asset_hash,
        site_base_url=site_base_url,
        action_metadata=action_meta,
    )
