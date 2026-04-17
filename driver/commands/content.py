import html
import json
import os
import re
import shutil
from argparse import Namespace
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .shared import (
    page_url,
    build_asset_ctx,
    refresh_glyphs,
    resolve_base_url,
)
from .post_entries import is_internal_post_entry
from .utils import (
    CompileBuildRequest,
    HtmlBuildConfig,
    MobileCompileConfig,
    compile_html,
    first_desc,
    hash_text_with_paths,
    make_inputs,
    minify_html,
    need_decl_str_from_source,
    reset_dir,
)


PostEntry = Dict[str, Any]
PostsByDate = Dict[str, List[PostEntry]]

_REVISION_SUFFIX_PATTERN = re.compile(r"-(\d+)$")
_SITE_TITLE = "Blog"
_ROOT_SHARED_FILENAMES = ("robots.txt", "favicon.ico")


def _append_revision_suffix(post_dir_name: str, title: str) -> str:
    rev_match = _REVISION_SUFFIX_PATTERN.search(post_dir_name)
    if not rev_match:
        return title
    return f"{title} Rev {rev_match.group(1)}"

def _collect_day_posts(date_dir: str, date_str: str) -> List[PostEntry]:
    day_posts: List[PostEntry] = []
    for post_dir_name in os.listdir(date_dir):
        if is_internal_post_entry(post_dir_name):
            continue
        post_path = os.path.join(date_dir, post_dir_name)
        if not os.path.isdir(post_path):
            continue

        post_json_path = os.path.join(post_path, "post.json")
        with open(post_json_path, "r", encoding="utf-8") as _f:
            post_data = json.load(_f)
        title = _append_revision_suffix(post_dir_name, post_data["title"])
        subtitle = post_data.get("subtitle")
        description = post_data.get("description", title)

        day_posts.append(
            {
                "name": title,
                "description": description,
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
            rel_link_clean = str(post["link"]).lstrip("./")
            sitemap_lines.append(
                f"  <url><loc>{html.escape(base_url + '/' + rel_link_clean, quote=False)}</loc></url>"
            )

    sitemap_lines.append("</urlset>")
    return sitemap_lines


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
        rel_link_clean = str(post["link"]).lstrip("./")
        post_url = f"{base_url}/{rel_link_clean}"
        item_description = str(post["description"])
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
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root_dir: str = args.root_dir
    os.makedirs(root_dir, exist_ok=True)

    copied_root_files: Dict[str, str] = {}
    for filename in _ROOT_SHARED_FILENAMES:
        dest_path = os.path.join(root_dir, filename)
        shutil.copy2(os.path.join(base_dir, filename), dest_path)
        copied_root_files[filename] = dest_path

    dest_base_dir = os.path.join(args.root_dir, "posts")
    if not os.path.exists(dest_base_dir):
        return

    posts_by_date = _collect_posts_by_date(dest_base_dir)
    template_path = os.path.join(base_dir, "content.template.typ")
    with open(template_path, "r", encoding="utf-8") as f:
        content_template = f.read()

    parsed_title = need_decl_str_from_source(
        content_template,
        "title",
    )
    parsed_subtitle = need_decl_str_from_source(
        content_template, "subtitle"
    )

    posts_typst_lines: List[str] = []
    for date_str, day_posts in posts_by_date.items():
        posts_typst_lines.append(f"== {date_str}")
        for post in day_posts:
            posts_typst_lines.append(f'- #link("{post["link"]}")[{post["name"]}]')
        posts_typst_lines.append("")

    content_source = content_template.replace("{{POSTS}}", "\n".join(posts_typst_lines))
    hidden_text = _build_hidden_text(parsed_title, parsed_subtitle, posts_by_date)
    page_title = parsed_title
    page_description = first_desc(hidden_text, parsed_subtitle)

    output_dir = os.path.join(args.build_base, "content")
    reset_dir(output_dir)

    template_typ_path = os.path.join(base_dir, "template.typ")
    asset_hash = hash_text_with_paths(
        content_source,
        [template_typ_path],
    )

    source_bytes = content_source.encode()
    html_template = os.path.join(base_dir, "index.template.html")
    typst_inputs = make_inputs(
        shared_inputs={"back_href": "./index.html"},
    )

    content_asset_dir = os.path.join(root_dir, "assets")
    asset_context = build_asset_ctx(base_dir, root_dir)
    base_url = resolve_base_url(args)
    og_url = page_url(
        base_url=base_url,
        root_dir=root_dir,
        dest_dir=root_dir,
        html_filename="index.html",
    )

    compile_html(
        CompileBuildRequest(
            source_bytes=source_bytes,
            output_dir=output_dir,
            asset_hash=asset_hash,
            file_prefix="content",
            typst_inputs=typst_inputs,
            mobile=MobileCompileConfig(),
            html=HtmlBuildConfig(
                template_path=html_template,
                dest_dir=root_dir,
                title_format="Blog Content Page {i}",
                default_title=page_title,
                asset_context=asset_context,
                description=page_description,
                hidden_text_override=hidden_text,
                asset_dest_dir=content_asset_dir,
                rss_feed_path=os.path.join(root_dir, "rss.xml"),
                og_type="website",
                og_url=og_url,
                site_base_url=base_url,
            ),
        )
    )

    glyph_target_dirs: List[str] = [root_dir, content_asset_dir]
    for date_str in sorted(os.listdir(dest_base_dir), reverse=True):
        date_dir = os.path.join(dest_base_dir, date_str)
        if not os.path.isdir(date_dir):
            continue
        for post_dir_name in os.listdir(date_dir):
            if is_internal_post_entry(post_dir_name):
                continue
            post_path = os.path.join(date_dir, post_dir_name)
            if not os.path.isdir(post_path):
                continue
            glyph_target_dirs.append(post_path)
            post_assets_dir = os.path.join(post_path, "assets")
            if os.path.isdir(post_assets_dir):
                glyph_target_dirs.append(post_assets_dir)
            source_dir = os.path.join(post_path, "source")
            if os.path.isdir(source_dir):
                glyph_target_dirs.append(source_dir)

    refresh_glyphs(
        root_dir=root_dir,
        target_dirs=glyph_target_dirs,
        clean_global_store=True,
    )
    minify_html(os.path.join(root_dir, "index.html"))

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
    for filename in _ROOT_SHARED_FILENAMES:
        print(f"{filename} generated at {copied_root_files[filename]}.")
    print(f"Sitemap generated at {sitemap_path}.")
    print(f"RSS feed generated at {rss_path}.")
