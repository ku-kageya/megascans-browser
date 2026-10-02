"""Houdini の Python Panel に埋め込む例（PySide6 を同梱する Houdini 向け）。

Windows > Python Panel Editor で新規パネルを作り、Script 欄に下記を貼る。
asset_browser_kit のあるフォルダを PYTHONPATH（HOUDINI_PATH/python3.Xlibs 等）に通しておく。
"""
import re

import hou

from asset_browser_kit import (AssetBrowser, CategoryDef, FolderSource, ItemAction,
                               JsonCache, Texts, copy_path_action, open_folder_action)

EXTS = (".bgeo.sc", ".bgeo", ".usd", ".usdc", ".abc", ".fbx", ".obj")


def import_to_obj(item):
    """/obj に Geometry ノードを作り File SOP で読み込む。"""
    name = re.sub(r"[^A-Za-z0-9_]", "_", item.name) or "prop"
    geo = hou.node("/obj").createNode("geo", node_name=name)
    f = geo.createNode("file")
    f.parm("file").set(item.path)
    f.setDisplayFlag(True)
    f.setRenderFlag(True)
    geo.setSelected(True, clear_all_selected=True)
    return "読み込みました"


def onCreateInterface():
    root = hou.text.expandString("$JOB/library")
    src = FolderSource(root, [CategoryDef("props", "Props", icon="box")],
                       item_kind="file", file_exts=EXTS, cache=JsonCache("PropLibrary"))
    actions = [ItemAction("Houdini に読み込む", import_to_obj, primary=True, close_after=True),
               open_folder_action(primary=False), copy_path_action()]
    return AssetBrowser(src, actions=actions, app_name="PropLibrary",
                        thumb_size=(200, 120), logo_text="",
                        texts=Texts(search_placeholder="プロップを検索…"))
