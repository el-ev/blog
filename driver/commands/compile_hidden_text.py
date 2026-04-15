import html
import os
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from .utils import extract_pdf_text

_HIDDEN_PLACEHOLDER_PREFIX = "__HIDDEN_HTML_"
_ORDERED_LIST_ITEM_PATTERN = re.compile(r"(?:^|\s)(\d+)\.\s+")


def _index_in_hidden_placeholder(text: str, idx: int) -> bool:
    start = text.rfind(_HIDDEN_PLACEHOLDER_PREFIX, 0, idx + 1)
    if start < 0:
        return False
    end = text.find("__", start + len(_HIDDEN_PLACEHOLDER_PREFIX))
    if end < 0:
        return False
    return start <= idx < end + 2


def _replace_first_with_options(
    text: str,
    old: str,
    new: str,
    independent_only: bool = False,
    search_start: int = 0,
) -> Tuple[str, bool, int]:
    if not old:
        return text, False, -1

    next_search_start = max(search_start, 0)
    while True:
        idx = text.find(old, next_search_start)
        if idx < 0:
            return text, False, -1
        if not _index_in_hidden_placeholder(text, idx) and (
            not independent_only
            or _is_independent_text_match(text, idx, idx + len(old))
        ):
            return text[:idx] + new + text[idx + len(old) :], True, idx
        next_search_start = idx + 1


def _is_independent_text_match(text: str, start: int, end: int) -> bool:
    def is_word_char(char: str) -> bool:
        return char.isalnum() or char == "_"

    if start > 0 and is_word_char(text[start - 1]):
        return False
    if end < len(text) and is_word_char(text[end]):
        return False
    return True


def _count_non_placeholder_occurrences(
    text: str,
    needle: str,
    independent_only: bool = False,
) -> int:
    if not needle:
        return 0

    count = 0
    search_start = 0
    while True:
        idx = text.find(needle, search_start)
        if idx < 0:
            return count
        if not _index_in_hidden_placeholder(text, idx) and (
            not independent_only
            or _is_independent_text_match(text, idx, idx + len(needle))
        ):
            count += 1
        search_start = idx + 1


def _make_hidden_placeholder(index: int) -> str:
    return f"__HIDDEN_HTML_{index}__"


def _embed_links_in_hidden_text(
    inner_hidden: str,
    merged_links: List[Tuple[str, str]],
    placeholder_html: List[Tuple[str, str]],
) -> Tuple[str, List[Tuple[str, str]]]:
    text = inner_hidden
    remaining_links: List[Tuple[str, str]] = []
    cursor = 0

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
            anchor = (
                f'<a href="{safe_href}" tabindex="-1">{escaped_candidate}</a>'
            )
            placeholder = _make_hidden_placeholder(len(placeholder_html))
            text, replaced, replaced_at = _replace_first_with_options(
                text,
                escaped_candidate,
                placeholder,
                search_start=cursor,
            )
            if replaced:
                placeholder_html.append((placeholder, anchor))
                cursor = replaced_at + len(placeholder)
                placed = True
                break

        if not placed:
            remaining_links.append((href, label or href))

    return text, remaining_links


def _embed_raws_in_hidden_text(
    inner_hidden: str,
    source_raws: List[Tuple[str, bool]],
    placeholder_start_index: int = 0,
) -> Tuple[str, List[str], List[str], List[Tuple[str, str]], Set[str]]:
    text = inner_hidden
    remaining_inline_raws: List[str] = []
    remaining_block_raws: List[str] = []
    placeholder_html: List[Tuple[str, str]] = []
    block_placeholders: Set[str] = set()
    remaining_query_counts: Dict[str, int] = defaultdict(int)

    for raw_text, _ in source_raws:
        normalized_raw = raw_text.replace("\r\n", "\n").replace("\r", "\n")
        if not normalized_raw.strip():
            continue
        stripped_raw = normalized_raw.strip("\n")
        candidate_texts = [normalized_raw]
        if stripped_raw and stripped_raw != normalized_raw:
            candidate_texts.append(stripped_raw)
        for candidate_text in candidate_texts:
            escaped_candidate = html.escape(candidate_text)
            if not escaped_candidate:
                continue
            remaining_query_counts[escaped_candidate] += 1

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

            expected_count = remaining_query_counts[escaped_candidate]
            if expected_count <= 0:
                continue

            occurrence_count = _count_non_placeholder_occurrences(
                text,
                escaped_candidate,
                independent_only=True,
            )
            if occurrence_count != expected_count:
                continue

            placeholder = _make_hidden_placeholder(
                placeholder_start_index + len(placeholder_html)
            )
            wrapped_candidate = (
                f"<pre><code>{escaped_candidate}</code></pre>"
                if is_block
                else f"<code>{escaped_candidate}</code>"
            )
            text, replaced, _ = _replace_first_with_options(
                text,
                escaped_candidate,
                placeholder,
                independent_only=True,
            )
            if replaced:
                placeholder_html.append((placeholder, wrapped_candidate))
                if is_block:
                    block_placeholders.add(placeholder)
                remaining_query_counts[escaped_candidate] = expected_count - 1
                placed = True
                break

        if not placed:
            if is_block:
                remaining_block_raws.append(normalized_raw)
            else:
                remaining_inline_raws.append(normalized_raw)

    return (
        text,
        remaining_inline_raws,
        remaining_block_raws,
        placeholder_html,
        block_placeholders,
    )


def _ends_paragraph(line: str) -> bool:
    return line.endswith((".", "!", "?", ":", ";", ".)", '."'))


def _is_hidden_date_line(line: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", line))


def _is_hidden_metadata_line(line: str) -> bool:
    return line.startswith("Edited on ") or line.startswith("Last revision on ")


def _should_skip_hidden_line(line: str) -> bool:
    return bool(
        line.startswith("Compiled on ")
        or line.startswith("Compiled at ")
        or re.fullmatch(r"\d+", line)
    )


def _restore_hidden_placeholders(
    text: str,
    placeholder_html: List[Tuple[str, str]],
) -> str:
    restored = text
    for placeholder, html_fragment in placeholder_html:
        restored = restored.replace(placeholder, html_fragment)
    return restored


def _normalize_text_for_match(text: str) -> str:
    normalized = html.unescape(text)
    normalized = (
        normalized.replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
    )
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def _line_matches_source_text(line: str, source_text: str) -> bool:
    if not source_text:
        return False
    return _normalize_text_for_match(line) == _normalize_text_for_match(source_text)


def _split_heading_prefix(line: str, heading_text: str) -> Optional[str]:
    stripped_line = re.sub(r"\s+", " ", line).strip()
    stripped_heading = re.sub(r"\s+", " ", heading_text).strip()
    if not stripped_line or not stripped_heading:
        return None
    if stripped_line == stripped_heading:
        return ""
    prefix = f"{stripped_heading} "
    if stripped_line.startswith(prefix):
        return stripped_line[len(prefix) :].strip()
    return None


def _inject_heading_placeholders(
    inner_hidden: str,
    source_headings: List[Tuple[int, str]],
    placeholder_html: List[Tuple[str, str]],
) -> Tuple[str, Set[str]]:
    normalized = inner_hidden.replace("\r\n", "\n").replace("\r", "\n")
    pending_headings: List[Tuple[int, str]] = []
    for level, text in source_headings:
        clean = re.sub(r"\s+", " ", text).strip()
        if clean:
            pending_headings.append((level, html.escape(clean)))

    heading_placeholders: Set[str] = set()
    if not pending_headings:
        return normalized, heading_placeholders

    output_lines: List[str] = []
    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if not line:
            output_lines.append("")
            continue

        current_line = re.sub(r"\s+", " ", line).strip()
        while pending_headings:
            level, heading_text = pending_headings[0]
            remainder = _split_heading_prefix(current_line, heading_text)
            if remainder is None:
                break
            heading_level = min(max(level, 2), 6)
            placeholder = _make_hidden_placeholder(len(placeholder_html))
            placeholder_html.append(
                (
                    placeholder,
                    f"<h{heading_level}>{heading_text}</h{heading_level}>",
                )
            )
            heading_placeholders.add(placeholder)
            output_lines.append(placeholder)
            pending_headings.pop(0)
            current_line = remainder
            if not current_line:
                break

        if current_line:
            output_lines.append(current_line)

    return "\n".join(output_lines), heading_placeholders


def _replace_table_text_with_placeholder(
    text: str,
    tokens: List[str],
    placeholder: str,
) -> Tuple[str, bool]:
    cleaned_tokens = [token for token in tokens if token]
    if not cleaned_tokens:
        return text, False

    pattern = re.compile(r"\s+".join(re.escape(token) for token in cleaned_tokens))
    search_start = 0
    while True:
        match = pattern.search(text, pos=search_start)
        if not match:
            return text, False
        if not _index_in_hidden_placeholder(text, match.start()):
            return text[: match.start()] + placeholder + text[match.end() :], True
        search_start = match.start() + 1


def _render_table_html(table_rows: List[List[Dict[str, Any]]]) -> Tuple[str, List[str]]:
    if not table_rows:
        return "", []

    header_row = table_rows[0]
    has_header = len(table_rows) > 1 and bool(header_row)
    for cell in header_row:
        if int(cell["rowspan"]) != 1:
            has_header = False
            break

    html_parts: List[str] = ["<table>"]
    match_tokens: List[str] = []

    def build_row_html(
        row_cells: List[Dict[str, Any]], cell_tag: str, scope_attr: str = ""
    ) -> str:
        row_parts: List[str] = ["<tr>"]
        for cell in row_cells:
            raw_text = re.sub(r"\s+", " ", str(cell["text"])).strip()
            escaped_text = html.escape(raw_text)
            if escaped_text:
                match_tokens.append(escaped_text)
            content_html = (
                f"<code>{escaped_text}</code>"
                if bool(cell["is_inline_code"])
                else escaped_text
            )

            attrs: List[str] = []
            colspan = int(cell["colspan"])
            rowspan = int(cell["rowspan"])
            if colspan > 1:
                attrs.append(f'colspan="{colspan}"')
            if rowspan > 1:
                attrs.append(f'rowspan="{rowspan}"')
            if scope_attr:
                attrs.append(scope_attr)
            attrs_html = f" {' '.join(attrs)}" if attrs else ""
            row_parts.append(f"<{cell_tag}{attrs_html}>{content_html}</{cell_tag}>")
        row_parts.append("</tr>")
        return "".join(row_parts)

    if has_header:
        html_parts.append("<thead>")
        html_parts.append(build_row_html(header_row, "th", 'scope="col"'))
        html_parts.append("</thead>")
        body_rows = table_rows[1:]
    else:
        body_rows = table_rows

    html_parts.append("<tbody>")
    for row in body_rows:
        html_parts.append(build_row_html(row, "td"))
    html_parts.append("</tbody>")
    html_parts.append("</table>")
    return "".join(html_parts), match_tokens


def _inject_table_placeholders(
    inner_hidden: str,
    source_tables: List[Dict[str, Any]],
    placeholder_html: List[Tuple[str, str]],
) -> Tuple[str, Set[str]]:
    text = inner_hidden
    table_placeholders: Set[str] = set()

    for table in source_tables:
        rows = table["rows"]
        if not isinstance(rows, list):
            raise RuntimeError("Invalid Typst table extraction: rows must be list.")
        table_html, match_tokens = _render_table_html(rows)
        if not table_html or not match_tokens:
            continue

        placeholder = _make_hidden_placeholder(len(placeholder_html))
        text, replaced = _replace_table_text_with_placeholder(
            text,
            match_tokens,
            placeholder,
        )
        if not replaced:
            continue
        placeholder_html.append((placeholder, table_html))
        table_placeholders.add(placeholder)

    return text, table_placeholders


def _extract_ordered_items(line: str) -> List[str]:
    stripped = line.strip()
    if not stripped:
        return []

    matches = list(_ORDERED_LIST_ITEM_PATTERN.finditer(stripped))
    if not matches:
        return []
    leading_text = stripped[: matches[0].start()].strip()
    if leading_text:
        return []

    items: List[str] = []
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(stripped)
        item = stripped[start:end].strip()
        if item:
            items.append(item)
    return items


def _extract_bullet_items(line: str) -> List[str]:
    stripped = line.strip()
    if not stripped:
        return []
    if stripped.startswith("•"):
        return [item.strip() for item in stripped.split("•") if item.strip()]
    if stripped.startswith("- "):
        item = stripped[2:].strip()
        return [item] if item else []
    return []


def _paragraphize_hidden_text(
    inner_hidden: str,
    placeholder_html: List[Tuple[str, str]],
    block_placeholders: Set[str],
    post_subtitle: Optional[str],
) -> str:
    normalized = inner_hidden.replace("\r\n", "\n").replace("\r", "\n")
    parts: List[str] = []
    current_lines: List[str] = []
    open_list_tag: Optional[str] = None
    title_emitted = False
    subtitle_emitted = False
    date_emitted = False

    def flush_current() -> None:
        if not current_lines:
            return
        paragraph = re.sub(r"\s+", " ", " ".join(current_lines)).strip()
        parts.append(f"<p>{paragraph}</p>")
        current_lines.clear()

    def close_list() -> None:
        nonlocal open_list_tag
        if not open_list_tag:
            return
        parts.append(f"</{open_list_tag}>")
        open_list_tag = None

    def open_list(tag: str) -> None:
        nonlocal open_list_tag
        if open_list_tag == tag:
            return
        close_list()
        parts.append(f"<{tag}>")
        open_list_tag = tag

    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if not line:
            flush_current()
            close_list()
            continue

        if line in block_placeholders:
            flush_current()
            close_list()
            parts.append(line)
            continue

        if _should_skip_hidden_line(line):
            flush_current()
            close_list()
            continue

        if not title_emitted:
            flush_current()
            close_list()
            parts.append(f"<h1>{line}</h1>")
            title_emitted = True
            continue

        if (
            post_subtitle
            and not subtitle_emitted
            and _line_matches_source_text(line, post_subtitle)
        ):
            flush_current()
            close_list()
            parts.append(f"<p>{line}</p>")
            subtitle_emitted = True
            continue

        if _is_hidden_date_line(line) and not date_emitted:
            flush_current()
            close_list()
            parts.append(f'<p><time datetime="{line}">{line}</time></p>')
            date_emitted = True
            continue

        if _is_hidden_metadata_line(line):
            flush_current()
            close_list()
            parts.append(f"<p>{line}</p>")
            continue

        ordered_items = _extract_ordered_items(line)
        if ordered_items:
            flush_current()
            open_list("ol")
            for item in ordered_items:
                parts.append(f"<li>{item}</li>")
            continue

        bullet_items = _extract_bullet_items(line)
        if bullet_items:
            flush_current()
            open_list("ul")
            for item in bullet_items:
                parts.append(f"<li>{item}</li>")
            continue

        close_list()
        current_lines.append(line)
        if _ends_paragraph(line):
            flush_current()

    flush_current()
    close_list()
    return _restore_hidden_placeholders("\n".join(parts), placeholder_html)




def _extract_inner_hidden_text(extracted_hidden: str) -> str:
    if not extracted_hidden:
        return ""
    prefix = '<div class="sr-only">\n'
    suffix = "\n</div>"
    if extracted_hidden.startswith(prefix) and extracted_hidden.endswith(suffix):
        return extracted_hidden[len(prefix) : -len(suffix)]
    return extracted_hidden


def replace_hidden_block(
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


def build_final_hidden_text(
    post_pdf_path: str,
    source_links: List[Tuple[str, str]],
    source_raws: List[Tuple[str, bool]],
    source_headings: List[Tuple[int, str]],
    source_tables: List[Dict[str, Any]],
    post_subtitle: Optional[str],
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
    inner_hidden, heading_placeholders = _inject_heading_placeholders(
        inner_hidden,
        source_headings,
        placeholder_html,
    )
    inner_hidden, table_placeholders = _inject_table_placeholders(
        inner_hidden,
        source_tables,
        placeholder_html,
    )
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
        placeholder_start_index=len(placeholder_html),
    )
    placeholder_html.extend(raw_placeholder_html)
    paragraphized_hidden_text = _paragraphize_hidden_text(
        embedded_hidden_text,
        placeholder_html,
        block_placeholders | heading_placeholders | table_placeholders,
        post_subtitle,
    )
    return paragraphized_hidden_text
