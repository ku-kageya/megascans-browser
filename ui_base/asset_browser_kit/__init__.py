"""asset_browser_kit — PySide6 製の汎用アセットブラウザ UI。

    from asset_browser_kit import AssetBrowser, FolderSource, CategoryDef
    src = FolderSource("D:/lib", [CategoryDef("props", "Props", icon="box")])
    w = AssetBrowser(src)
"""
from .browser import AssetBrowser
from .favorites import FavoritesStore
from .icons import make_icon, resolve_icon
from .model import BrowserItem, CategoryDef, ItemAction
from .sources import FolderSource, ItemSource, JsonCache, StaticSource
from .theme import Texts, Theme, build_stylesheet
from .thumbnails import ThumbnailManager, make_placeholder, thumbnail_manager
from .utils import default_match, extract_keywords, pretty_name
from .widgets import (MIME_TYPE, DetailDialog, FlowLayout, ItemCard, VirtualGrid,
                      copy_path_action, default_actions, default_mime, item_from_mime,
                      open_folder_action)

__all__ = [
    "AssetBrowser", "BrowserItem", "CategoryDef", "ItemAction",
    "ItemSource", "FolderSource", "StaticSource", "JsonCache", "FavoritesStore",
    "Theme", "Texts", "build_stylesheet",
    "ThumbnailManager", "thumbnail_manager", "make_placeholder",
    "make_icon", "resolve_icon", "pretty_name", "extract_keywords", "default_match",
    "FlowLayout", "ItemCard", "VirtualGrid", "DetailDialog",
    "default_actions", "open_folder_action", "copy_path_action",
    "default_mime", "item_from_mime", "MIME_TYPE",
]
__version__ = "1.0.0"
