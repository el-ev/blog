import hashlib
import html
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .utils import (
    _extract_typst_table_rows,
    _flatten_query_text,
    make_raw_copy_id,
)


def _embed_links_in_text_fragment(
    text: str,
    source_links: List[Tuple[str, str]],
) -> str:
    """Embed links into a text fragment, skipping occurrences already inside anchors."""
    for href, label in source_links:
        if not href:
            continue
        clean_label = label.strip()
        if not clean_label:
            continue
        escaped_label = html.escape(clean_label)
        if escaped_label not in text:
            continue
        safe_href = html.escape(href, quote=True)
        anchor = f'<a href="{safe_href}" tabindex="-1">{escaped_label}</a>'
        search_pos = 0
        while True:
            idx = text.find(escaped_label, search_pos)
            if idx == -1:
                break
            before = text[:idx]
            inside_anchor = (
                before.count("<a ") + before.count("<a>") > before.count("</a>")
            )
            if inside_anchor:
                search_pos = idx + len(escaped_label)
                continue
            text = text[:idx] + anchor + text[idx + len(escaped_label) :]
            break
    return text


def _render_table_html(table_rows: List[List[Dict[str, Any]]]) -> str:
    """Render extracted table rows as an HTML <table> string."""
    if not table_rows:
        return ""

    header_row = table_rows[0]
    has_header = len(table_rows) > 1 and bool(header_row)
    for cell in header_row:
        if int(cell["rowspan"]) != 1:
            has_header = False
            break

    html_parts: List[str] = ["<table>"]

    def build_row_html(
        row_cells: List[Dict[str, Any]], cell_tag: str, scope_attr: str = ""
    ) -> str:
        row_parts: List[str] = ["<tr>"]
        for cell in row_cells:
            raw_text = re.sub(r"\s+", " ", str(cell["text"])).strip()
            escaped_text = html.escape(raw_text)
            if bool(cell["is_inline_code"]):
                cell_copy_id = make_raw_copy_id(raw_text)
                content_html = f'<code id="raw-{cell_copy_id}">{escaped_text}</code>'
            else:
                content_html = escaped_text
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
    return "".join(html_parts)


def _format_numbering(n: int, fmt: str) -> str:
    """Format a counter value according to Typst's numbering string."""
    if fmt == "1":
        return str(n)
    if fmt == "a" and 1 <= n <= 26:
        return chr(ord("a") + n - 1)
    if fmt == "A" and 1 <= n <= 26:
        return chr(ord("A") + n - 1)
    return str(n)


def flatten_doc_node_to_html(node: Any) -> str:
    """Recursively convert a Typst JSON content node to an HTML string.

    Handles link → <a>, inline raw → <code>, block raw → <pre><code>,
    smartquote, space, linebreak, and styled/sequence wrappers.
    """
    if isinstance(node, str):
        return html.escape(node)
    if isinstance(node, list):
        return "".join(flatten_doc_node_to_html(item) for item in node)
    if isinstance(node, dict):
        func = node.get("func")
        if func == "space":
            return " "
        if func == "linebreak":
            return "<br>"
        if func == "smartquote":
            c = '"' if node.get("double") else "'"
            return html.escape(c)
        if func == "link":
            dest = node.get("dest", "")
            body_html = flatten_doc_node_to_html(node.get("body", ""))
            dest_escaped = html.escape(str(dest), quote=True)
            return f'<a href="{dest_escaped}" tabindex="-1">{body_html}</a>'
        if func == "raw":
            text = node.get("text", "")
            copy_id = make_raw_copy_id(text)
            if node.get("block"):
                return (
                    f'<pre id="raw-{copy_id}"><code>{html.escape(text)}</code></pre>'
                )
            return f'<code id="raw-{copy_id}">{html.escape(text)}</code>'
        parts: List[str] = []
        text_val = node.get("text")
        if isinstance(text_val, str):
            parts.append(html.escape(text_val))
        for key in ("body", "children", "child", "value", "values", "content"):
            if key in node:
                parts.append(flatten_doc_node_to_html(node[key]))
        if not parts:
            for key, value in node.items():
                if key in ("func", "text"):
                    continue
                if isinstance(value, (dict, list)):
                    parts.append(flatten_doc_node_to_html(value))
        return "".join(parts)
    return ""


def build_hidden_text(
    doc_elements: List[Dict[str, Any]],
    post_title: str,
    post_subtitle: Optional[str],
    asset_hash: str,
    nav_links: Optional[List[Tuple[str, str]]] = None,
    source_links: Optional[List[Tuple[str, str]]] = None,
) -> str:
    """Build sr-only HTML from an ordered list of <driver-doc> metadata elements."""
    parts: List[str] = []
    parts.append(f"<h1>{html.escape(post_title)}</h1>")
    if post_subtitle:
        parts.append(f'<p class="subtitle">{html.escape(post_subtitle)}</p>')

    # page_header emits subtitle PAR (if present) and date PAR.
    # The title is inside block() so it does NOT produce a par metadata node.
    skip_count = 1 + (1 if post_subtitle else 0)
    skipped_pars = 0

    # State: grouping consecutive list items
    list_tag: Optional[str] = None  # "ul" or "ol"
    list_items: List[str] = []

    # State: table-figure caption pending until table body arrives
    pending_table_cap: Optional[Dict[str, Any]] = None

    # Per-kind figure counters (for caption labels like "Figure 1:")
    fig_counts: Dict[str, int] = {}

    def flush_list() -> None:
        if not list_items:
            return
        tag = list_tag or "ul"
        parts.append(f"<{tag}>")
        parts.extend(list_items)
        parts.append(f"</{tag}>")
        list_items.clear()

    def build_fig_label(cap: Dict[str, Any], default_kind: str) -> str:
        kind = cap.get("kind", default_kind)
        fig_counts[kind] = fig_counts.get(kind, 0) + 1
        n = fig_counts[kind]
        supplement = cap.get("supplement")
        sup_text = (
            re.sub(r"\s+", " ", _flatten_query_text(supplement)).strip()
            if supplement
            else "Figure"
        )
        fmt = cap.get("numbering") or "1"
        sep = cap.get("separator")
        sep_text = (
            re.sub(r"\s+", " ", _flatten_query_text(sep)).strip() if sep else ":"
        )
        num_str = _format_numbering(n, fmt)
        return f"{sup_text}\u00a0{num_str}{sep_text}"

    for elem in doc_elements:
        t = elem.get("t")

        # Skip initial page_header PARs (subtitle + date)
        if t == "par" and skipped_pars < skip_count:
            skipped_pars += 1
            continue

        # Inline raws are already embedded in their parent element
        if t == "raw" and not elem.get("bl"):
            continue

        # Any non-list element flushes the pending list buffer
        if t not in ("li", "eli"):
            flush_list()
            list_tag = None

        if t == "h":
            # Offset Typst heading levels by 1 (title is <h1>, sections are <h2>+)
            level = min(elem.get("l", 1) + 1, 6)
            body_html = flatten_doc_node_to_html(elem.get("b", ""))
            parts.append(f"<h{level}>{body_html}</h{level}>")

        elif t == "par":
            body_html = flatten_doc_node_to_html(elem.get("b", "")).strip()
            if body_html:
                if source_links:
                    body_html = _embed_links_in_text_fragment(body_html, source_links)
                parts.append(f"<p>{body_html}</p>")

        elif t == "raw":  # block raw (bl=True checked above)
            if parts:
                parts.append("<p></p>")
            raw_text = elem.get("x", "")
            copy_id = make_raw_copy_id(raw_text)
            parts.append(
                f'<pre id="raw-{copy_id}"><code>{html.escape(raw_text)}</code></pre>'
            )

        elif t == "info":
            body_html = flatten_doc_node_to_html(elem.get("b", ""))
            body_html = re.sub(r"\s+", " ", body_html).strip()
            parts.append(
                f'<blockquote class="info-block"><p>{body_html}</p></blockquote>'
            )

        elif t == "li":
            if list_tag != "ul":
                flush_list()
                list_tag = "ul"
            body_html = flatten_doc_node_to_html(elem.get("b", "")).strip()
            if source_links:
                body_html = _embed_links_in_text_fragment(body_html, source_links)
            list_items.append(f"<li>{body_html}</li>")

        elif t == "eli":
            if list_tag != "ol":
                flush_list()
                list_tag = "ol"
            body_html = flatten_doc_node_to_html(elem.get("b", "")).strip()
            if source_links:
                body_html = _embed_links_in_text_fragment(body_html, source_links)
            list_items.append(f"<li>{body_html}</li>")

        elif t == "dt":
            term_html = flatten_doc_node_to_html(elem.get("term", "")).strip()
            desc_html = flatten_doc_node_to_html(elem.get("b", "")).strip()
            parts.append(f"<dl><dt>{term_html}</dt><dd>{desc_html}</dd></dl>")

        elif t == "blockquote":
            body_html = flatten_doc_node_to_html(elem.get("b", "")).strip()
            parts.append(f"<blockquote><p>{body_html}</p></blockquote>")

        elif t == "eq":
            alt = elem.get("alt")
            if isinstance(alt, str) and alt.strip():
                eq_text = html.escape(alt.strip())
            else:
                eq_text = html.escape(
                    re.sub(r"\s+", " ", _flatten_query_text(elem.get("b", ""))).strip()
                )
            parts.append(f"<p><code>{eq_text}</code></p>")

        elif t == "fig":
            body = elem.get("b", {})
            if isinstance(body, dict) and body.get("func") == "image":
                source = body.get("source", "")
                alt_raw = body.get("alt")
                alt = ""
                if isinstance(alt_raw, str):
                    alt = alt_raw.strip()
                elif alt_raw is not None:
                    alt = re.sub(r"\s+", " ", _flatten_query_text(alt_raw)).strip()
                cap_node = elem.get("cap")
                caption = ""
                if isinstance(cap_node, dict):
                    label = build_fig_label(cap_node, "image")
                    body_text = flatten_doc_node_to_html(cap_node.get("body", ""))
                    caption = re.sub(r"\s+", " ", f"{label} {body_text}").strip()
                src_hash = hashlib.sha1(source.encode()).hexdigest()[:6]
                img_src = html.escape(
                    f"assets/image.{src_hash}.{asset_hash}.webp", quote=True
                )
                alt_attr = (
                    f' alt="{html.escape(alt, quote=True)}"'
                    if alt
                    else ' role="presentation"'
                )
                img_tag = f'<img src="{img_src}"{alt_attr}>'
                parts.append(
                    f"<figure><p>{img_tag}</p>"
                    f"<figcaption>{caption}</figcaption>"
                    f"</figure>"
                )

        elif t == "fig-cap":
            pending_table_cap = elem.get("cap")

        elif t == "table":
            table_node = elem.get("b")
            cap = pending_table_cap
            pending_table_cap = None
            if isinstance(table_node, dict):
                try:
                    rows = _extract_typst_table_rows(table_node)
                    table_html = _render_table_html(rows)
                    if table_html:
                        if cap is not None and isinstance(cap, dict):
                            label = build_fig_label(cap, "table")
                            body_text = flatten_doc_node_to_html(cap.get("body", ""))
                            caption = re.sub(
                                r"\s+", " ", f"{label} {body_text}"
                            ).strip()
                            parts.append(
                                f"<figure>{table_html}"
                                f"<figcaption>{caption}</figcaption>"
                                f"</figure>"
                            )
                        else:
                            parts.append(table_html)
                except Exception:
                    pass

    # Flush any list still in progress at end of document
    flush_list()

    result = "\n".join(parts)

    if nav_links:
        nav_items = "".join(
            f'<li><a href="{html.escape(href, quote=True)}" tabindex="-1">'
            f"{html.escape(label)}</a></li>"
            for href, label in nav_links
        )
        result += f'\n<nav aria-label="Post navigation"><ul>{nav_items}</ul></nav>'

    return result


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
