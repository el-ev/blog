import os
import re
import html
import json
from argparse import Namespace
from typing import Any, Dict, List, Tuple

from .utils import (
    reset_directory,
    compile_and_build_html,
    copy_driver_web_js,
    hash_text_with_sources,
)


PostEntry = Dict[str, Any]
PostsByDate = Dict[str, List[PostEntry]]

_TITLE_PATTERN = re.compile(r'#let\s+title\s*=\s*"([^"]+)"')
_SUBTITLE_PATTERN = re.compile(r'#let\s+subtitle\s*=\s*"([^"]+)"')
_REVISION_SUFFIX_PATTERN = re.compile(r"-(\d+)$")


def _extract_post_title(main_typ_path: str, fallback: str) -> str:
    if not os.path.exists(main_typ_path):
        return fallback

    try:
        with open(main_typ_path, "r", encoding="utf-8") as f:
            content = f.read()
        match = _TITLE_PATTERN.search(content)
        if match:
            return match.group(1)
    except Exception:
        pass
    return fallback


def _append_revision_suffix(post_dir_name: str, title: str) -> str:
    rev_match = _REVISION_SUFFIX_PATTERN.search(post_dir_name)
    if not rev_match:
        return title
    return f"{title} Rev {rev_match.group(1)}"


def _collect_day_posts(date_dir: str, date_str: str) -> List[PostEntry]:
    day_posts: List[PostEntry] = []
    for post_dir_name in os.listdir(date_dir):
        post_path = os.path.join(date_dir, post_dir_name)
        if not os.path.isdir(post_path):
            continue

        title = _extract_post_title(
            os.path.join(post_path, "source", "main.typ"),
            fallback=post_dir_name,
        )
        title = _append_revision_suffix(post_dir_name, title)

        day_posts.append(
            {
                "name": title,
                "link": f"./posts/{date_str}/{post_dir_name}/index.html",
                "time": os.path.getmtime(post_path),
            }
        )
    day_posts.sort(key=lambda post: post["time"], reverse=True)
    return day_posts


def _collect_posts_by_date(posts_dir: str) -> PostsByDate:
    posts_by_date: PostsByDate = {}
    for date_str in sorted(os.listdir(posts_dir), reverse=True):
        date_dir = os.path.join(posts_dir, date_str)
        if not os.path.isdir(date_dir):
            continue
        day_posts = _collect_day_posts(date_dir, date_str)
        if day_posts:
            posts_by_date[date_str] = day_posts
    return posts_by_date


def _extract_template_headers(content_template: str) -> Tuple[str, str]:
    parsed_title = "Blog"
    parsed_subtitle = ""
    title_match = _TITLE_PATTERN.search(content_template)
    subtitle_match = _SUBTITLE_PATTERN.search(content_template)
    if title_match:
        parsed_title = title_match.group(1)
    if subtitle_match:
        parsed_subtitle = subtitle_match.group(1)
    return parsed_title, parsed_subtitle


def _build_posts_typst(posts_by_date: PostsByDate) -> str:
    lines: List[str] = []
    for date_str, day_posts in posts_by_date.items():
        lines.append(f"== {date_str}")
        for post in day_posts:
            lines.append(f'- #link("{post["link"]}")[{post["name"]}]')
        lines.append("")
    return "\n".join(lines)


def _build_hidden_text(
    parsed_title: str,
    parsed_subtitle: str,
    posts_by_date: PostsByDate,
) -> str:
    sections: List[str] = [f"<h1>{html.escape(parsed_title)}</h1>"]
    if parsed_subtitle:
        sections.append(f"<p>{html.escape(parsed_subtitle)}</p>")
    sections.append("<h1>Content</h1>")

    for date_str, day_posts in posts_by_date.items():
        sections.append(f"<h2>{html.escape(date_str)}</h2>")
        sections.append("<ul>")
        for post in day_posts:
            href = html.escape(post["link"])
            label = html.escape(post["name"])
            sections.append(f'<li><a href="{href}">{label}</a></li>')
        sections.append("</ul>")
    return "\n".join(sections)


def _load_config_data(config_path: str) -> Dict[str, Any]:
    if not config_path or not os.path.isfile(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to read config file '{config_path}': {e}")
        return {}


def _resolve_base_url(args: Namespace, config_data: Dict[str, Any]) -> str:
    base_url_raw = getattr(args, "base_url", None) or config_data.get("base_url")
    base_url = str(base_url_raw) if base_url_raw else "https://owo.li/blog/"
    return base_url.rstrip("/")


def _build_sitemap_lines(base_url: str, posts_by_date: PostsByDate) -> List[str]:
    sitemap_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        f'  <url><loc>{html.escape(base_url + "/", quote=False)}</loc></url>',
    ]

    for day_posts in posts_by_date.values():
        for post in day_posts:
            rel_link = post["link"].lstrip("./")
            rel_link_clean = rel_link
            if rel_link_clean.endswith("index.html"):
                rel_link_clean = rel_link_clean[:-10]
            sitemap_lines.append(
                f'  <url><loc>{html.escape(base_url + "/" + rel_link_clean, quote=False)}</loc></url>'
            )

    sitemap_lines.append("</urlset>")
    return sitemap_lines


def update_content(args: Namespace) -> None:
    dest_base_dir = os.path.join(args.root_dir, "posts")
    if not os.path.exists(dest_base_dir):
        return

    posts_by_date = _collect_posts_by_date(dest_base_dir)

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    content_template_path = os.path.join(base_dir, "content.template.typ")

    with open(content_template_path, "r", encoding="utf-8") as f:
        content_template = f.read()

    parsed_title, parsed_subtitle = _extract_template_headers(content_template)
    content_source = content_template.replace("{{POSTS}}", _build_posts_typst(posts_by_date))
    hidden_text = _build_hidden_text(parsed_title, parsed_subtitle, posts_by_date)

    build_base: str = args.build_base
    output_dir = os.path.join(build_base, "content")
    reset_directory(output_dir)

    template_typ_path = os.path.join(base_dir, "template.typ")
    asset_hash = hash_text_with_sources(
        content_source,
        [template_typ_path],
    )

    content_source_bytes = content_source.encode()
    template_path = os.path.join(base_dir, "index.template.html")

    root_dir: str = args.root_dir
    os.makedirs(root_dir, exist_ok=True)
    copied_driver_js = copy_driver_web_js(base_dir, root_dir)
    if copied_driver_js:
        print(f"Copied {copied_driver_js} driver JS file(s) to '{root_dir}'.")

    compile_and_build_html(
        source_bytes=content_source_bytes,
        output_dir=output_dir,
        asset_hash=asset_hash,
        file_prefix="content",
        template_path=template_path,
        dest_dir=root_dir,
        title_format="Blog Content Page {i}",
        default_title=parsed_title,
        description=parsed_subtitle,
        extract_title_from_pdf=False,
        hidden_text_override=hidden_text,
        clipboard_asset_path=os.path.join(root_dir, "clipboard.min.js"),
    )

    config_path: str = getattr(args, "config", "")
    config_data = _load_config_data(config_path)
    base_url = _resolve_base_url(args, config_data)
    sitemap_lines = _build_sitemap_lines(base_url, posts_by_date)

    sitemap_path = os.path.join(root_dir, "sitemap.xml")
    with open(sitemap_path, "w", encoding="utf-8") as f:
        f.write("\n".join(sitemap_lines))

    print(f"Content page updated in {root_dir}.")
    print(f"Sitemap generated at {sitemap_path}.")
