import hashlib
import html
import os
import re
from typing import Any, Dict, List, Optional, Tuple

_EMPTY_COND_SPAN_RE = re.compile(
    r'(<span data-cond-id="[^"]+"'
    r' data-cond-branch="[^"]+">)'
    r"\s*(</span>)"
)

from .utils import (
    _extract_typst_table_rows,
    _flatten_query_text,
    make_raw_copy_id,
)


def _embed_links_in_text(
    text: str,
    links: List[Tuple[str, str]],
) -> str:
    """Embed scoped links into an HTML text fragment."""
    for href, label in links:
        escaped_label = html.escape(label)
        if escaped_label not in text:
            continue
        safe_href = html.escape(href, quote=True)
        anchor = f'<a href="{safe_href}" tabindex="-1">{escaped_label}</a>'
        idx = text.find(escaped_label)
        if idx == -1:
            continue
        before = text[:idx]
        inside_anchor = (
            before.count("<a ") + before.count("<a>") > before.count("</a>")
        )
        if inside_anchor:
            continue
        text = text[:idx] + anchor + text[idx + len(escaped_label) :]
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


_UNICODE_TO_TYPST: Dict[str, str] = {
    "\u222b": "integral",
    "\u221e": "infinity",
    "\u2211": "sum",
    "\u220f": "product",
    "\u2192": "->",
    "\u2190": "<-",
    "\u21d2": "=>",
    "\u21d0": "<=",
    "\u2264": "<=",
    "\u2265": ">=",
    "\u2260": "!=",
    "\u2248": "approx",
    "\u00b1": "plus.minus",
    "\u2213": "minus.plus",
    "\u00d7": "times",
    "\u00f7": "div",
    "\u2218": "compose",
    "\u2229": "sect",
    "\u222a": "union",
    "\u2286": "subset.eq",
    "\u2287": "supset.eq",
    "\u2282": "subset",
    "\u2283": "supset",
    "\u2208": "in",
    "\u2209": "not in",
    "\u2200": "forall",
    "\u2203": "exists",
    "\u2205": "emptyset",
    "\u2026": "...",
    "\u22ef": "dots.c",
    "\u22ee": "dots.v",
    "\u22f0": "dots.up",
    "\u22f1": "dots.down",
    "\u2207": "nabla",
    "\u2202": "diff",
    "\u03b1": "alpha",
    "\u03b2": "beta",
    "\u03b3": "gamma",
    "\u03b4": "delta",
    "\u03b5": "epsilon",
    "\u03b6": "zeta",
    "\u03b7": "eta",
    "\u03b8": "theta",
    "\u03b9": "iota",
    "\u03ba": "kappa",
    "\u03bb": "lambda",
    "\u03bc": "mu",
    "\u03bd": "nu",
    "\u03be": "xi",
    "\u03c0": "pi",
    "\u03c1": "rho",
    "\u03c3": "sigma",
    "\u03c4": "tau",
    "\u03c5": "upsilon",
    "\u03c6": "phi",
    "\u03c7": "chi",
    "\u03c8": "psi",
    "\u03c9": "omega",
    "\u0393": "Gamma",
    "\u0394": "Delta",
    "\u0398": "Theta",
    "\u039b": "Lambda",
    "\u039e": "Xi",
    "\u03a0": "Pi",
    "\u03a3": "Sigma",
    "\u03a6": "Phi",
    "\u03a8": "Psi",
    "\u03a9": "Omega",
    "\u2102": "CC",
    "\u2115": "NN",
    "\u211a": "QQ",
    "\u211d": "RR",
    "\u2124": "ZZ",
}


def _serialize_math(node: Any) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_serialize_math(item) for item in node)
    if not isinstance(node, dict):
        return ""
    func = node.get("func")
    if func == "text":
        return node.get("text", "")
    if func == "symbol":
        sym = node.get("text", "")
        return _UNICODE_TO_TYPST.get(sym, sym)
    if func == "space":
        return " "
    if func == "linebreak":
        return " "
    if func == "sequence":
        return "".join(_serialize_math(c) for c in node.get("children", []))
    if func == "attach":
        base = _serialize_math(node.get("base", ""))
        sup = node.get("t")
        sub = node.get("b")
        result = base
        if sub is not None:
            s = _serialize_math(sub)
            result += f"_{s}" if len(s) == 1 else f"_({s})"
        if sup is not None:
            s = _serialize_math(sup)
            result += f"^{s}" if len(s) == 1 else f"^({s})"
        return result
    if func == "frac":
        num = _serialize_math(node.get("num", ""))
        denom = _serialize_math(node.get("denom", ""))
        return f"({num}) / ({denom})"
    if func == "root":
        radicand = _serialize_math(node.get("radicand", ""))
        index = node.get("index")
        if index is not None:
            return f"root({_serialize_math(index)}, {radicand})"
        return f"sqrt({radicand})"
    if func == "binom":
        upper = _serialize_math(node.get("upper", ""))
        lower = _serialize_math(node.get("lower", ""))
        return f"binom({upper}, {lower})"
    if func == "lr":
        return _serialize_math(node.get("body", ""))
    if func == "op":
        return _serialize_math(node.get("text", ""))
    if func == "styled":
        return _serialize_math(node.get("child", ""))
    if func == "h":
        return " "
    if func == "accent":
        base = _serialize_math(node.get("base", ""))
        accent_char = node.get("accent", {})
        if isinstance(accent_char, dict):
            accent_char = accent_char.get("text", "")
        return f"{base}\u0302" if accent_char == "\u0302" else f"accent({base})"
    if func == "vec" or func == "mat":
        children = node.get("children", [])
        items = ", ".join(_serialize_math(c) for c in children)
        return f"{func}({items})"
    parts: List[str] = []
    text_val = node.get("text")
    if isinstance(text_val, str):
        parts.append(text_val)
    for key in ("body", "children", "child", "value", "num", "denom"):
        if key in node:
            parts.append(_serialize_math(node[key]))
    return "".join(parts)


def _flatten_text_skip_conds(node: Any) -> str:
    """Like _flatten_query_text but skips link nodes whose dest starts with #cond=."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_flatten_text_skip_conds(item) for item in node)
    if isinstance(node, dict):
        func = node.get("func")
        if func == "space":
            return " "
        if func == "linebreak":
            return "\n"
        if func == "link":
            dest = node.get("dest", "")
            if isinstance(dest, str) and dest.startswith("#cond="):
                return ""
            return _flatten_text_skip_conds(node.get("body", ""))
        parts: list = []
        text = node.get("text")
        if isinstance(text, str):
            parts.append(text)
        for key in ("body", "children", "child", "value", "values", "content"):
            if key in node:
                parts.append(_flatten_text_skip_conds(node[key]))
        if not parts:
            for key, value in node.items():
                if key in ("func", "text"):
                    continue
                if isinstance(value, (dict, list)):
                    parts.append(_flatten_text_skip_conds(value))
        return "".join(parts)
    return ""


def _collect_emphasis_text(
    emphasis_elems: List[Dict[str, Any]],
) -> Dict[str, str]:
    """Build a map from flattened text → HTML tag for strong/emph elements."""
    result: Dict[str, str] = {}
    for elem in emphasis_elems:
        t = elem.get("t")
        tag = "strong" if t == "b" else "em" if t == "i" else None
        if not tag:
            continue
        text = _flatten_query_text(elem.get("b", "")).strip()
        if text:
            result[text] = tag
    return result


def flatten_doc_node_to_html(
    node: Any,
    emphasis_map: Optional[Dict[str, str]] = None,
) -> str:
    """Recursively convert a Typst JSON content node to an HTML string.

    Handles link → <a>, inline raw → <code>, block raw → <pre><code>,
    smartquote, space, linebreak, styled (strong/emph), and sequence wrappers.
    """
    if isinstance(node, str):
        return html.escape(node)
    if isinstance(node, list):
        return "".join(flatten_doc_node_to_html(item, emphasis_map) for item in node)
    if isinstance(node, dict):
        func = node.get("func")
        if func == "space":
            return " "
        if func == "linebreak":
            return "<br>"
        if func == "smartquote":
            c = '"' if node.get("double") else "'"
            return html.escape(c)
        if func == "styled" and emphasis_map:
            inner = flatten_doc_node_to_html(node.get("child", ""), emphasis_map)
            inner_text = _flatten_query_text(node.get("child", "")).strip()
            tag = emphasis_map.get(inner_text)
            if tag:
                return f"<{tag}>{inner}</{tag}>"
            return inner
        if func == "link":
            dest = node.get("dest", "")
            body_html = flatten_doc_node_to_html(node.get("body", ""), emphasis_map)
            if isinstance(dest, str) and dest.startswith("#cond="):
                m = re.match(r"#cond=(.+):([01])$", dest)
                if m:
                    cond_id = m.group(1)
                    branch = m.group(2)
                    if cond_id.startswith("checkbox:") or cond_id.startswith("radio:"):
                        return ""
                    cond_id = html.escape(cond_id, quote=True)
                    hide = ' style="display:none"' if branch == "1" else ""
                    return (
                        f'<span data-cond-id="{cond_id}"'
                        f' data-cond-branch="{branch}"{hide}>'
                        f"{body_html}</span>"
                    )
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
                parts.append(flatten_doc_node_to_html(node[key], emphasis_map))
        if not parts:
            for key, value in node.items():
                if key in ("func", "text"):
                    continue
                if isinstance(value, (dict, list)):
                    parts.append(flatten_doc_node_to_html(value, emphasis_map))
        return "".join(parts)
    return ""


def _is_inline_metadata(node: Dict[str, Any]) -> bool:
    t = node.get("t", "")
    if t in ("b", "i", "lnk", "eq-il"):
        return True
    if t == "raw" and not node.get("bl"):
        return True
    return False


def _group_list_items(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    i = 0
    while i < len(nodes):
        t = nodes[i].get("t")
        if t in ("li", "eli"):
            tag = "ul" if t == "li" else "ol"
            items: List[Dict[str, Any]] = []
            while i < len(nodes):
                cur_t = nodes[i].get("t")
                if cur_t == t:
                    item = nodes[i]
                    if "children" in item:
                        item["children"] = _group_list_items(item["children"])
                    items.append(item)
                    i += 1
                elif _is_inline_metadata(nodes[i]):
                    i += 1
                else:
                    break
            result.append({"t": tag, "children": items})
        else:
            if "children" in nodes[i]:
                nodes[i]["children"] = _group_list_items(nodes[i]["children"])
            result.append(nodes[i])
            i += 1
    return result


def _build_node_tree(flat_elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    root: List[Dict[str, Any]] = []
    stack: List[List[Dict[str, Any]]] = [root]
    for i, elem in enumerate(flat_elements):
        t = elem.get("t", "")
        elem["_idx"] = i
        if t.endswith("/o"):
            node = {k: v for k, v in elem.items() if k != "t"}
            node["t"] = t[:-2]
            node["children"] = []
            stack[-1].append(node)
            stack.append(node["children"])
        elif t.endswith("/c"):
            if len(stack) > 1:
                stack.pop()
        else:
            stack[-1].append(elem)
    return _group_list_items(root)


def build_hidden_text(
    doc_elements: List[Dict[str, Any]],
    post_title: str,
    post_subtitle: Optional[str],
    asset_hash: str,
    nav_links: Optional[List[Tuple[str, str]]] = None,
) -> str:
    """Build sr-only HTML from <driver-doc> metadata elements."""
    header: List[str] = [f"<h1>{html.escape(post_title)}</h1>"]
    if post_subtitle:
        header.append(f'<p class="subtitle">{html.escape(post_subtitle)}</p>')

    skip_count = 1 + (1 if post_subtitle else 0)
    fig_counts: Dict[str, int] = {}

    # --- pre-passes on the flat stream (before tree building) ---

    elem_links: Dict[int, List[Tuple[str, str]]] = {}
    ghost_texts: set = set()
    last_text_idx: Optional[int] = None
    for i, elem in enumerate(doc_elements):
        t = elem.get("t", "")
        if t == "lnk":
            href = elem.get("href", "")
            if href.startswith("#cond=") or href.startswith("#action="):
                text = re.sub(
                    r"\s+", " ", _flatten_query_text(elem.get("b", ""))
                ).strip()
                if text:
                    ghost_texts.add(text)
            if not href or href.startswith("#action=") or href.startswith("#cond="):
                continue
            label = re.sub(
                r"\s+", " ", _flatten_query_text(elem.get("b", ""))
            ).strip()
            if not label:
                continue
            if last_text_idx is not None:
                elem_links.setdefault(last_text_idx, []).append((href, label))
        elif t in ("par", "h", "info", "dt", "li", "eli"):
            last_text_idx = i
        elif t not in ("b", "i", "raw", "eq-il"):
            last_text_idx = None

    emphasis_map = _collect_emphasis_text(
        [e for e in doc_elements if e.get("t") in ("b", "i")]
    )

    tree = _build_node_tree(doc_elements)

    def fig_label(cap: Dict[str, Any], default_kind: str) -> str:
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
        return f"{sup_text}\u00a0{_format_numbering(n, fmt)}{sep_text}"

    def _links_for(node: Dict[str, Any]) -> Optional[List[Tuple[str, str]]]:
        idx = node.get("_idx")
        return elem_links.get(idx) if idx is not None else None

    def render(nodes: List[Dict[str, Any]], skip_pars: int = 0) -> List[str]:
        parts: List[str] = []
        skipped_pars = 0
        trailing_residual: Optional[str] = None

        for node in nodes:
            t = node.get("t")

            if t == "lnk":
                href = node.get("href", "")
                frag = None
                if href.startswith("#action=input:"):
                    input_id = href[len("#action=input:"):]
                    placeholder = re.sub(
                        r"\s+", " ", _flatten_query_text(node.get("b", ""))
                    ).strip()
                    esc_id = html.escape(input_id, quote=True)
                    esc_ph = html.escape(placeholder, quote=True)
                    frag = (
                        f' <input class="sr-only-input"'
                        f' data-input-id="{esc_id}"'
                        f' aria-label="{esc_ph}">'
                    )
                elif href.startswith("#action=form-action:"):
                    action_id = href[len("#action=form-action:"):]
                    label = re.sub(
                        r"\s+", " ", _flatten_query_text(node.get("b", ""))
                    ).strip()
                    esc_id = html.escape(action_id, quote=True)
                    frag = (
                        f' <button class="sr-only-action"'
                        f' data-action-id="{esc_id}">'
                        f"{html.escape(label)}</button>"
                    )
                elif href.startswith("#action=checkbox:"):
                    cb_id = href[len("#action=checkbox:"):]
                    cb_label = re.sub(
                        r"\s+", " ", _flatten_text_skip_conds(node.get("b", ""))
                    ).strip()
                    esc_id = html.escape(cb_id, quote=True)
                    esc_label = html.escape(cb_label or cb_id, quote=True)
                    label_suffix = f" {html.escape(cb_label)}" if cb_label else ""
                    frag = (
                        f' <input type="checkbox" class="sr-only-checkbox"'
                        f' data-checkbox-id="{esc_id}"'
                        f' aria-label="{esc_label}">'
                        f"{label_suffix}"
                    )
                elif href.startswith("#action=radio:"):
                    rest = href[len("#action=radio:"):]
                    colon_idx = rest.find(":")
                    if colon_idx > 0:
                        r_group = rest[:colon_idx]
                        r_value = rest[colon_idx + 1:]
                        r_label = re.sub(
                            r"\s+", " ", _flatten_text_skip_conds(node.get("b", ""))
                        ).strip()
                        esc_group = html.escape(r_group, quote=True)
                        esc_value = html.escape(r_value, quote=True)
                        esc_label = html.escape(r_label or f"{r_group}: {r_value}", quote=True)
                        label_suffix = f" {html.escape(r_label)}" if r_label else ""
                        frag = (
                            f' <input type="radio" class="sr-only-radio"'
                            f' name="{esc_group}" value="{esc_value}"'
                            f' data-radio-group="{esc_group}"'
                            f' aria-label="{esc_label}">'
                            f"{label_suffix}"
                        )
                if frag is not None:
                    is_standalone = href.startswith("#action=checkbox:") or href.startswith("#action=radio:")
                    if is_standalone:
                        parts.append(frag.strip())
                    else:
                        suffix = trailing_residual or ""
                        trailing_residual = None
                        if parts and parts[-1].endswith("</p>"):
                            parts[-1] = parts[-1][:-4] + frag + suffix + "</p>"
                        else:
                            parts.append(frag.strip() + suffix)
                continue

            if t == "par" and skip_pars > 0 and skipped_pars < skip_pars:
                skipped_pars += 1
                continue

            if t == "raw" and not node.get("bl"):
                raw_text = node.get("x", "")
                if raw_text:
                    copy_id = make_raw_copy_id(raw_text)
                    parts.append(
                        f'<code id="raw-{copy_id}">'
                        f"{html.escape(raw_text)}</code>"
                    )
                continue
            if t in ("b", "i"):
                continue

            if t in ("ul", "ol"):
                item_tag = "li" if t == "ul" else "eli"
                items: List[str] = []
                for child in node.get("children", []):
                    if child.get("t") != item_tag:
                        continue
                    children = child.get("children", [])
                    if children:
                        inner = render(children)
                        if (
                            len(inner) == 1
                            and inner[0].startswith("<p>")
                            and inner[0].endswith("</p>")
                        ):
                            items.append(f"<li>{inner[0][3:-4]}</li>")
                        else:
                            items.append(f"<li>{''.join(inner)}</li>")
                    else:
                        body_html = flatten_doc_node_to_html(
                            child.get("b", ""), emphasis_map
                        ).strip()
                        links = _links_for(child)
                        if links:
                            body_html = _embed_links_in_text(
                                body_html, links
                            )
                        items.append(f"<li>{body_html}</li>")
                if items:
                    parts.append(f"<{t}>{''.join(items)}</{t}>")

            elif t == "blockquote":
                inner = render(node.get("children", []))
                if not inner:
                    body_html = flatten_doc_node_to_html(
                        node.get("b", ""), emphasis_map
                    ).strip()
                    if body_html:
                        inner = [f"<p>{body_html}</p>"]
                attr = node.get("attr")
                attr_html = ""
                if attr is not None:
                    attr_text = flatten_doc_node_to_html(attr).strip()
                    if attr_text:
                        attr_html = f"<footer>{attr_text}</footer>"
                parts.append(
                    f"<blockquote>{''.join(inner)}{attr_html}</blockquote>"
                )

            elif t == "fig-t":
                cap = node.get("cap")
                table_child = next(
                    (c for c in node.get("children", []) if c.get("t") == "table"),
                    None,
                )
                if table_child is not None:
                    table_node = table_child.get("b")
                    if isinstance(table_node, dict):
                        try:
                            rows = _extract_typst_table_rows(table_node)
                            table_html = _render_table_html(rows)
                            if table_html:
                                if cap is not None and isinstance(cap, dict):
                                    label = fig_label(cap, "table")
                                    body_text = flatten_doc_node_to_html(
                                        cap.get("body", "")
                                    )
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

            elif t == "table":
                table_node = node.get("b")
                if isinstance(table_node, dict):
                    try:
                        rows = _extract_typst_table_rows(table_node)
                        table_html = _render_table_html(rows)
                        if table_html:
                            parts.append(table_html)
                    except Exception:
                        pass

            elif t == "h":
                level = min(node.get("l", 1) + 1, 6)
                body_html = flatten_doc_node_to_html(
                    node.get("b", ""), emphasis_map
                )
                links = _links_for(node)
                if links:
                    body_html = _embed_links_in_text(body_html, links)
                parts.append(f"<h{level}>{body_html}</h{level}>")

            elif t == "par":
                body_html = flatten_doc_node_to_html(
                    node.get("b", ""), emphasis_map
                ).strip()
                if not body_html:
                    continue
                if ghost_texts and "data-cond-id=" not in body_html:
                    raw_text = re.sub(
                        r"\s+", " ", _flatten_query_text(node.get("b", ""))
                    ).strip()
                    residual = raw_text
                    for gt in ghost_texts:
                        residual = residual.replace(gt, "")
                    residual = residual.strip()
                    if not residual:
                        continue
                    if residual != raw_text:
                        trailing_residual = html.escape(residual)
                        continue
                links = _links_for(node)
                if links:
                    body_html = _embed_links_in_text(body_html, links)
                if "data-cond-id=" in body_html and parts:
                    m = _EMPTY_COND_SPAN_RE.search(parts[-1])
                    if m:
                        parts[-1] = (
                            parts[-1][: m.end(1)]
                            + body_html
                            + parts[-1][m.start(2) :]
                        )
                        continue
                parts.append(f"<p>{body_html}</p>")

            elif t == "raw":
                raw_text = node.get("x", "")
                copy_id = make_raw_copy_id(raw_text)
                parts.append(
                    f'<pre id="raw-{copy_id}">'
                    f"<code>{html.escape(raw_text)}</code></pre>"
                )

            elif t == "info":
                body_html = flatten_doc_node_to_html(
                    node.get("b", ""), emphasis_map
                )
                body_html = re.sub(r"\s+", " ", body_html).strip()
                links = _links_for(node)
                if links:
                    body_html = _embed_links_in_text(body_html, links)
                parts.append(f"<aside><p>{body_html}</p></aside>")

            elif t == "dt":
                term_html = flatten_doc_node_to_html(
                    node.get("term", ""), emphasis_map
                ).strip()
                desc_html = flatten_doc_node_to_html(
                    node.get("b", ""), emphasis_map
                ).strip()
                links = _links_for(node)
                if links:
                    term_html = _embed_links_in_text(term_html, links)
                    desc_html = _embed_links_in_text(desc_html, links)
                parts.append(
                    f"<dl><dt>{term_html}</dt><dd>{desc_html}</dd></dl>"
                )

            elif t in ("eq", "eq-il"):
                alt = node.get("alt")
                if isinstance(alt, str) and alt.strip():
                    eq_text = html.escape(alt.strip())
                else:
                    eq_text = html.escape(
                        re.sub(
                            r"\s+", " ", _serialize_math(node.get("b", ""))
                        ).strip()
                    )
                if t == "eq-il":
                    code_frag = f"<code>${eq_text}$</code>"
                    if (
                        parts
                        and parts[-1].startswith("<p>")
                        and parts[-1].endswith("</p>")
                    ):
                        parts[-1] = (
                            parts[-1][:-4] + " " + code_frag + "</p>"
                        )
                    else:
                        parts.append(code_frag)
                else:
                    parts.append(f"<p><code>$ {eq_text} $</code></p>")

            elif t == "fig":
                body = node.get("b", {})
                if isinstance(body, dict) and body.get("func") == "image":
                    source = body.get("source", "")
                    alt_raw = body.get("alt")
                    alt = ""
                    if isinstance(alt_raw, str):
                        alt = alt_raw.strip()
                    elif alt_raw is not None:
                        alt = re.sub(
                            r"\s+", " ", _flatten_query_text(alt_raw)
                        ).strip()
                    cap_node = node.get("cap")
                    caption = ""
                    if isinstance(cap_node, dict):
                        label = fig_label(cap_node, "image")
                        body_text = flatten_doc_node_to_html(
                            cap_node.get("body", "")
                        )
                        caption = re.sub(
                            r"\s+", " ", f"{label} {body_text}"
                        ).strip()
                    src_hash = hashlib.sha1(source.encode()).hexdigest()[:6]
                    img_src = html.escape(
                        f"assets/image.{src_hash}.{asset_hash}.webp",
                        quote=True,
                    )
                    alt_attr = (
                        f' alt="{html.escape(alt, quote=True)}"'
                        if alt
                        else ' role="presentation"'
                    )
                    parts.append(
                        f"<figure><p><img"
                        f' src="{img_src}"{alt_attr}></p>'
                        f"<figcaption>{caption}</figcaption>"
                        f"</figure>"
                    )

        return parts

    body_parts = render(tree, skip_pars=skip_count)
    body_parts = [p for p in body_parts if p != "<p></p>"]
    all_parts = header + body_parts
    result = "\n".join(all_parts)

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
