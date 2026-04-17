import json
import os
from typing import Any, Dict, List, Optional

from .utils import (
    DriverAssetContext,
    DriverWebAssets,
    WEB_ASSETS_DIR_NAME,
    GLOBAL_GLYPH_ASSET_FILENAME,
    GLOBAL_GLYPH_MAP_FILENAME,
    apply_glyph_map,
    build_web_assets,
    clean_glyph_assets,
    rewrite_glyph_preload,
)


def build_asset_ctx(driver_dir: str, root_dir: str) -> DriverAssetContext:
    web_assets = build_web_assets(driver_dir, root_dir)
    assets_dir = os.path.join(root_dir, WEB_ASSETS_DIR_NAME)
    return DriverAssetContext(
        web_assets=web_assets,
        global_glyph_asset_path=os.path.join(assets_dir, GLOBAL_GLYPH_ASSET_FILENAME),
        global_glyph_map_path=os.path.join(assets_dir, GLOBAL_GLYPH_MAP_FILENAME),
    )


def refresh_glyphs(
    root_dir: str,
    target_dirs: List[str],
    clean_global_store: bool = False,
) -> None:
    glyph_asset_path = apply_glyph_map(
        root_dir=root_dir,
        target_dirs=target_dirs,
    )

    if glyph_asset_path:
        html_paths = {
            os.path.join(root_dir, "index.html"),
        }

        for directory in target_dirs:
            if not os.path.isdir(directory):
                continue
            for filename in os.listdir(directory):
                if not filename.endswith(".html"):
                    continue
                html_paths.add(os.path.join(directory, filename))

        for html_path in sorted(html_paths):
            rewrite_glyph_preload(html_path, glyph_asset_path)

    clean_glyph_assets(
        root_dir=root_dir,
        target_dirs=target_dirs,
        clean_global_store=clean_global_store,
    )


def load_config_data(config_path: str) -> Dict[str, Any]:
    if not config_path or not os.path.isfile(config_path):
        return {}

    with open(config_path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    if not isinstance(loaded, dict):
        raise RuntimeError(
            f"Invalid config file '{config_path}': expected JSON object."
        )
    return loaded


def resolve_base_url(args: Any, required: bool = True) -> Optional[str]:
    config_path = getattr(args, "config", "")
    config_data = load_config_data(config_path)
    base_url_arg = getattr(args, "base_url", None)
    if base_url_arg:
        base_url_raw = base_url_arg
    elif "base_url" in config_data:
        base_url_raw = config_data["base_url"]
    else:
        if required:
            raise RuntimeError(
                "Missing base_url. Provide --base-url or set base_url in config JSON."
            )
        return None
    return str(base_url_raw).rstrip("/")


def page_url(
    base_url: str,
    root_dir: str,
    dest_dir: str,
    html_filename: str = "index.html",
) -> Optional[str]:
    root_abs = os.path.abspath(root_dir)
    dest_abs = os.path.abspath(dest_dir)
    try:
        if os.path.commonpath([root_abs, dest_abs]) != root_abs:
            return None
    except ValueError:
        return None

    rel_dir = os.path.relpath(dest_abs, start=root_abs).replace("\\", "/")
    if rel_dir == ".":
        return f"{base_url}/{html_filename}"
    return f"{base_url}/{rel_dir}/{html_filename}"
