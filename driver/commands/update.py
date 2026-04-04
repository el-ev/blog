import os
import re
import hashlib
import html
import json
from argparse import Namespace
from typing import Dict, List, Any

from .utils import (
    reset_directory,
    compile_and_build_html,
)


def update_content(args: Namespace) -> None:
    dest_base_dir = os.path.join(args.root_dir, "posts")
    if not os.path.exists(dest_base_dir):
        return

    posts_by_date: Dict[str, List[Dict[str, Any]]] = {}
    for date_str in sorted(os.listdir(dest_base_dir), reverse=True):
        date_dir = os.path.join(dest_base_dir, date_str)
        if not os.path.isdir(date_dir):
            continue

        day_posts: List[Dict[str, Any]] = []
        for post_dir_name in os.listdir(date_dir):
            post_path = os.path.join(date_dir, post_dir_name)
            if not os.path.isdir(post_path):
                continue

            title = post_dir_name
            main_typ_path = os.path.join(post_path, "source", "main.typ")
            if os.path.exists(main_typ_path):
                try:
                    with open(main_typ_path, "r", encoding="utf-8") as f:
                        match = re.search(r'#let\s+title\s*=\s*"([^"]+)"', f.read())
                        if match:
                            title = match.group(1)
                except Exception:
                    pass

            rev_match = re.search(r'-(\d+)$', post_dir_name)
            if rev_match:
                title += f" Rev {rev_match.group(1)}"

            day_posts.append({
                "name": title,
                "link": f"./posts/{date_str}/{post_dir_name}/index.html",
                "time": os.path.getmtime(post_path)
            })

        day_posts.sort(key=lambda x: x["time"], reverse=True)
        if day_posts:
            posts_by_date[date_str] = day_posts

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    content_template_path = os.path.join(base_dir, "content.template.typ")
    
    with open(content_template_path, "r", encoding="utf-8") as f:
        content_template = f.read()

    posts_typst: List[str] = []
    for date_str, day_posts in posts_by_date.items():
        posts_typst.append(f"== {date_str}")
        for p in day_posts:
            posts_typst.append(f'- #link("{p["link"]}")[{p["name"]}]')
        posts_typst.append("")

    content_source = content_template.replace("{{POSTS}}", "\n".join(posts_typst))

    hidden_sections: List[str] = ["<h1>Content</h1>"]
    for date_str, day_posts in posts_by_date.items():
        hidden_sections.append(f"<h2>{html.escape(date_str)}</h2>")
        hidden_sections.append("<ul>")
        for post in day_posts:
            href = html.escape(post["link"])
            label = html.escape(post["name"])
            hidden_sections.append(f'<li><a href="{href}">{label}</a></li>')
        hidden_sections.append("</ul>")
    hidden_text = "\n".join(hidden_sections)

    build_base: str = args.build_base
    output_dir = os.path.join(build_base, "content")
    reset_directory(output_dir)

    asset_hash = hashlib.sha256(content_source.encode("utf-8")).hexdigest()[:6]

    content_source_bytes = content_source.encode()
    template_path = os.path.join(base_dir, "index.template.html")

    root_dir: str = args.root_dir
    os.makedirs(root_dir, exist_ok=True)

    compile_and_build_html(
        source_bytes=content_source_bytes,
        output_dir=output_dir,
        asset_hash=asset_hash,
        file_prefix="content",
        template_path=template_path,
        dest_dir=root_dir,
        title_format="Blog Content Page {i}",
        default_title="Blog Content",
        extract_title_from_pdf=False,
        hidden_text_override=hidden_text,
    )
    
    config_data: Dict[str, Any] = {}
    config_path: str = getattr(args, 'config', '')
    if config_path and os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
        except Exception as e:
            print(f"Failed to read config file '{config_path}': {e}")
            
    base_url_raw = getattr(args, 'base_url', None) or config_data.get("base_url")
    base_url: str = str(base_url_raw) if base_url_raw else "https://owo.li/blog/"
    base_url = base_url.rstrip("/")

    # Generate Sitemap
    sitemap_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    ]

    # Add root index
    sitemap_lines.append(f'  <url><loc>{base_url}/</loc></url>')

    # Add all discovered posts
    for date_str, day_posts in posts_by_date.items():
        for post in day_posts:
            # post["link"] is like "./posts/2026-04-04/test/index.html"
            rel_link = post["link"].lstrip("./")
            # If it ends with index.html, we can just link to the directory
            rel_link_clean = rel_link
            if rel_link_clean.endswith("index.html"):
                rel_link_clean = rel_link_clean[:-10]
            sitemap_lines.append(f'  <url><loc>{base_url}/{rel_link_clean}</loc></url>')

    sitemap_lines.append("</urlset>")

    sitemap_path = os.path.join(root_dir, "sitemap.xml")
    with open(sitemap_path, "w", encoding="utf-8") as f:
        f.write("\n".join(sitemap_lines))

    print(f"Content page updated in {root_dir}.")
    print(f"Sitemap generated at {sitemap_path}.")