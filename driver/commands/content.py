import html
import os
import re
from argparse import Namespace
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .shared import (
    build_public_page_url,
    build_driver_asset_context,
    refresh_glyph_assets,
    resolve_base_url,
)
from .utils import (
    reset_directory,
    compile_and_build_html,
    extract_declared_typst_string,
    extract_declared_typst_string_from_source,
    hash_text_with_sources,
)


PostEntry = Dict[str, Any]
PostsByDate = Dict[str, List[PostEntry]]

_REVISION_SUFFIX_PATTERN = re.compile(r"-(\d+)$")


def _extract_post_title(main_typ_path: str, fallback: str) -> str:
    return extract_declared_typst_string(main_typ_path, "title") or fallback


def _extract_post_subtitle(main_typ_path: str) -> Optional[str]:
    return extract_declared_typst_string(main_typ_path, "subtitle")


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

        main_typ_path = os.path.join(post_path, "source", "main.typ")
        title = _extract_post_title(
            main_typ_path,
            fallback=post_dir_name,
        )
        title = _append_revision_suffix(post_dir_name, title)
        subtitle = _extract_post_subtitle(main_typ_path)

        day_posts.append(
            {
                "name": title,
                "subtitle": subtitle,
                "link": f"./posts/{date_str}/{post_dir_name}/index.html",
                "time": os.path.getmtime(post_path),
                "date": date_str,
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
            sections.append(
                f'<li><a href="{href}" tabindex="-1">{label}</a></li>'
            )
        sections.append("</ul>")

    return "\n".join(sections)


def _build_sitemap_lines(base_url: str, posts_by_date: PostsByDate) -> List[str]:
    sitemap_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        f"  <url><loc>{html.escape(base_url + '/', quote=False)}</loc></url>",
    ]

    for day_posts in posts_by_date.values():
        for post in day_posts:
            rel_link = post["link"].lstrip("./")
            rel_link_clean = rel_link
            if rel_link_clean.endswith("index.html"):
                rel_link_clean = rel_link_clean[:-10]
            sitemap_lines.append(
                f"  <url><loc>{html.escape(base_url + '/' + rel_link_clean, quote=False)}</loc></url>"
            )

    sitemap_lines.append("</urlset>")
    return sitemap_lines


def _build_post_permalink(base_url: str, post_link: str) -> str:
    rel_link_clean = post_link.lstrip("./")
    if rel_link_clean.endswith("index.html"):
        rel_link_clean = rel_link_clean[:-10]
    return f"{base_url}/{rel_link_clean}"


def _format_rss_pub_date(date_str: str) -> str:
    parsed = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return parsed.strftime("%a, %d %b %Y %H:%M:%S +0000")


def _build_rss_lines(
    base_url: str,
    site_title: str,
    site_description: str,
    posts_by_date: PostsByDate,
) -> List[str]:
    feed_url = f"{base_url}/rss.xml"
    rss_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "  <channel>",
        f"    <title>{html.escape(site_title, quote=False)}</title>",
        f"    <link>{html.escape(base_url + '/', quote=False)}</link>",
        f"    <description>{html.escape(site_description, quote=False)}</description>",
        "    <language>en-us</language>",
        f'    <atom:link href="{html.escape(feed_url)}" rel="self" type="application/rss+xml" />',
    ]

    all_posts: List[PostEntry] = []
    for day_posts in posts_by_date.values():
        all_posts.extend(day_posts)

    if all_posts:
        rss_lines.append(
            f"    <lastBuildDate>{_format_rss_pub_date(str(all_posts[0]['date']))}</lastBuildDate>"
        )
    else:
        rss_lines.append(
            "    <lastBuildDate>"
            f"{datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S +0000')}"
            "</lastBuildDate>"
        )

    for post in all_posts:
        post_url = _build_post_permalink(base_url, str(post["link"]))
        item_description = str(
            post["subtitle"] if post["subtitle"] is not None else post["name"]
        )
        rss_lines.extend(
            [
                "    <item>",
                f"      <title>{html.escape(str(post['name']), quote=False)}</title>",
                f"      <link>{html.escape(post_url, quote=False)}</link>",
                f'      <guid isPermaLink="true">{html.escape(post_url, quote=False)}</guid>',
                f"      <pubDate>{_format_rss_pub_date(str(post['date']))}</pubDate>",
                "      <description>"
                f"{html.escape(item_description, quote=False)}</description>",
                "    </item>",
            ]
        )

    rss_lines.extend(["  </channel>", "</rss>"])
    return rss_lines


def update_content(args: Namespace) -> None:
    dest_base_dir = os.path.join(args.root_dir, "posts")
    if not os.path.exists(dest_base_dir):
        return

    posts_by_date = _collect_posts_by_date(dest_base_dir)

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    content_template_path = os.path.join(base_dir, "content.template.typ")
    with open(content_template_path, "r", encoding="utf-8") as f:
        content_template = f.read()

    parsed_title = extract_declared_typst_string_from_source(content_template, "title")
    if parsed_title is None:
        raise RuntimeError("Missing required title declaration in content template.")

    parsed_subtitle = extract_declared_typst_string_from_source(
        content_template, "subtitle"
    )
    if parsed_subtitle is None:
        raise RuntimeError("Missing required subtitle declaration in content template.")

    posts_typst_lines: List[str] = []
    for date_str, day_posts in posts_by_date.items():
        posts_typst_lines.append(f"== {date_str}")
        for post in day_posts:
            posts_typst_lines.append(f'- #link("{post["link"]}")[{post["name"]}]')
        posts_typst_lines.append("")

    content_source = content_template.replace("{{POSTS}}", "\n".join(posts_typst_lines))
    hidden_text = _build_hidden_text(parsed_title, parsed_subtitle, posts_by_date)

    output_dir = os.path.join(args.build_base, "content")
    reset_directory(output_dir)

    template_typ_path = os.path.join(base_dir, "template.typ")
    asset_hash = hash_text_with_sources(
        content_source,
        [template_typ_path],
    )

    content_source_bytes = content_source.encode()
    template_path = os.path.join(base_dir, "index.template.html")
    input_values_svg: Dict[str, str] = {
        "with_driver": "true",
        "export_format": "svg",
        "back_href": "./index.html",
    }
    input_values_pdf: Dict[str, str] = {
        "with_driver": "true",
        "export_format": "pdf",
        "back_href": "./index.html",
    }

    root_dir: str = args.root_dir
    os.makedirs(root_dir, exist_ok=True)
    asset_context = build_driver_asset_context(base_dir, root_dir)
    base_url = resolve_base_url(args)
    og_url = build_public_page_url(
        base_url=base_url,
        root_dir=root_dir,
        dest_dir=root_dir,
        html_filename="index.html",
    )

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
        inputs_svg=input_values_svg,
        inputs_pdf=input_values_pdf,
        extract_title_from_pdf=False,
        hidden_text_override=hidden_text,
        stylesheet_asset_path=asset_context.web_assets.stylesheet_path,
        clipboard_asset_path=asset_context.web_assets.clipboard_script_path,
        theme_asset_path=asset_context.web_assets.theme_script_path,
        rss_feed_path=os.path.join(root_dir, "rss.xml"),
        og_type="website",
        og_url=og_url,
        global_glyph_asset_path=asset_context.global_glyph_asset_path,
        global_glyph_map_path=asset_context.global_glyph_map_path,
    )

    glyph_target_dirs: List[str] = [root_dir]
    for date_str in sorted(os.listdir(dest_base_dir), reverse=True):
        date_dir = os.path.join(dest_base_dir, date_str)
        if not os.path.isdir(date_dir):
            continue
        for post_dir_name in os.listdir(date_dir):
            post_path = os.path.join(date_dir, post_dir_name)
            if not os.path.isdir(post_path):
                continue
            glyph_target_dirs.append(post_path)
            source_dir = os.path.join(post_path, "source")
            if os.path.isdir(source_dir):
                glyph_target_dirs.append(source_dir)

    refresh_glyph_assets(
        root_dir=root_dir,
        target_dirs=glyph_target_dirs,
        clean_global_store=True,
    )

    sitemap_lines = _build_sitemap_lines(base_url, posts_by_date)
    rss_lines = _build_rss_lines(
        base_url=base_url,
        site_title=parsed_title,
        site_description=parsed_subtitle,
        posts_by_date=posts_by_date,
    )

    sitemap_path = os.path.join(root_dir, "sitemap.xml")
    with open(sitemap_path, "w", encoding="utf-8") as f:
        f.write("\n".join(sitemap_lines))
    rss_path = os.path.join(root_dir, "rss.xml")
    with open(rss_path, "w", encoding="utf-8") as f:
        f.write("\n".join(rss_lines))

    print(f"Content page updated in {root_dir}.")
    print(f"Sitemap generated at {sitemap_path}.")
    print(f"RSS feed generated at {rss_path}.")
