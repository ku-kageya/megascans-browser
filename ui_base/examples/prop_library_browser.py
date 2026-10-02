#!/usr/bin/env python3
"""ファイル単位のプロップライブラリ例（item_kind="file"）。

    <root>/<props|vegetation>/chair_a.bgeo.sc
                              chair_a.png        ← 同名画像をサムネに使う

    python prop_library_browser.py <ROOT>
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from asset_browser_kit import (AssetBrowser, CategoryDef, FolderSource, ItemAction,  # noqa: E402
                               JsonCache, copy_path_action, open_folder_action)
from asset_browser_kit.app import run_standalone  # noqa: E402

APP = "PropLibrary"
EXTS = (".bgeo.sc", ".bgeo", ".usd", ".usdc", ".usda", ".abc", ".fbx", ".obj")


def sidecar_meta(item):
    """chair_a.json があれば詳細ダイアログに表示する（ワーカースレッドで実行）。"""
    base, fmt = item.path, ""
    for ext in EXTS:
        if base.lower().endswith(ext):
            base, fmt = base[: -len(ext)], ext.lstrip(".")
            break
    meta = {"形式": fmt}
    j = base + ".json"
    if os.path.isfile(j):
        try:
            meta.update({str(k): str(v) for k, v in json.loads(open(j, encoding="utf-8").read()).items()})
        except Exception:
            pass
    return meta


def make_browser(root):
    src = FolderSource(root, [
        CategoryDef("props", "Props", icon="box", folders=["props"]),
        CategoryDef("vegetation", "Vegetation", icon="plant", folders=["vegetation"],
                    placeholder="plant"),
    ], item_kind="file", file_exts=EXTS, meta_fn=sidecar_meta, cache=JsonCache(APP))

    def log_item(item):
        print("selected:", item.uid, item.path)
        return "ログに出力しました"

    actions = [open_folder_action(), copy_path_action(),
               ItemAction("ログ", log_item)]          # 独自アクションの追加例
    w = AssetBrowser(src, actions=actions, app_name=APP, thumb_size=(260, 160), logo_text="P")
    w.item_activated.connect(lambda it: print("activated:", it.name))
    return w


if __name__ == "__main__":
    sys.exit(run_standalone(lambda: make_browser(sys.argv[1] if len(sys.argv) > 1 else ""),
                            title="Prop Library", app_name=APP))
