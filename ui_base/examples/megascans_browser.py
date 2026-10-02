#!/usr/bin/env python3
"""元の asset_browser.py と同等の Megascans 用ブラウザを、キットで組み直した例。

    python megascans_browser.py [LIBRARY_ROOT]

<root>/<3d|3dplant|surface>/<asset_folder>/<id>_Preview.png を想定。
ルートが無ければデモデータで起動する。
"""
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from asset_browser_kit import (AssetBrowser, BrowserItem, CategoryDef, FolderSource,  # noqa: E402
                               JsonCache, StaticSource, Texts, pretty_name)
from asset_browser_kit.app import run_standalone  # noqa: E402

APP = "AssetBrowser"
CATEGORIES = [
    CategoryDef("3D Asset", icon="cube", folders=["3d"], placeholder="rock"),
    CategoryDef("3D Plant", icon="plant", folders=["3dplant"], placeholder="plant"),
    CategoryDef("Surface", icon="surface", folders=["surface"], placeholder="sphere"),
]


def megascans_id(stem, cat):
    return re.split(r"[_\-]+", stem)[-1]          # 末尾トークン = アセット ID


def megascans_name(stem, cat):
    # 3dplant_climber_xfqicgrqx -> Climber
    return pretty_name(stem, strip_prefixes=("3d", "3dplant", "surface"), drop_last_token=True)


def demo_source():
    raw = [
        ("Rocky Ground", "sk2xdgp", "Surface", "4K", "Albedo / Normal / Roughness"),
        ("Nordic Beach Rock", "vd5abfp", "3D Asset", "8K", "FBX / OBJ"),
        ("Wild Grass", "tf3keasq", "3D Plant", "2K", "FBX / Atlas"),
        ("Forest Floor", "ub1nqcpx", "Surface", "4K", "Albedo / Normal / Height"),
        ("Mossy Boulder", "we8pqcpz", "3D Asset", "8K", "FBX / OBJ"),
        ("Broadleaf Plant", "pl4gwasd", "3D Plant", "2K", "FBX / Atlas"),
        ("Sand Dunes", "sd9xkvpm", "Surface", "8K", "Albedo / Normal / Roughness"),
        ("Cliff Face", "ci2mabpk", "3D Asset", "8K", "FBX / OBJ"),
        ("Fern Cluster", "fn7reasw", "3D Plant", "2K", "FBX / Atlas"),
        ("Concrete Wall", "co3jkvpn", "Surface", "4K", "Albedo / Normal / Height"),
        ("Dead Tree Trunk", "dt6mabpj", "3D Asset", "4K", "FBX / OBJ"),
        ("Granite Rock", "gr1pxvpl", "Surface", "4K", "Albedo / Normal / Roughness"),
        ("River Pebbles", "rp8kdgpr", "Surface", "4K", "Albedo / Normal / Height"),
        ("Alpine Shrub", "as2gweas", "3D Plant", "2K", "FBX / Atlas"),
        ("Volcanic Rock", "vr4mabpt", "3D Asset", "4K", "FBX / OBJ"),
    ]
    items = [BrowserItem(id=i, name=n, category=c, path=f"D:/Megascans/Downloaded/{i}",
                         meta={"解像度": r, "フォーマット": f})
             for n, i, c, r, f in raw]
    return StaticSource(items, CATEGORIES, label="D:/Megascans/Downloaded  (デモデータ)")


def make_browser(root: str):
    if root and os.path.isdir(root):
        src = FolderSource(root, CATEGORIES, item_kind="dir",
                           preview_pattern="{id}_Preview.png",   # フォルダ内を列挙しない
                           id_fn=megascans_id, name_fn=megascans_name,
                           cache=JsonCache(APP))                  # 2 回目以降は即表示
    else:
        if root:
            print(f"path not found: {root!r} — showing demo data")
        src = demo_source()
    return AssetBrowser(src, app_name=APP, thumb_size=(512, 256),
                        texts=Texts(search_placeholder="\U0001F50D  アセットを検索…"))


if __name__ == "__main__":
    root = sys.argv[1].strip().strip('"') if len(sys.argv) > 1 else ""
    sys.exit(run_standalone(lambda: make_browser(root), title="Asset Browser", app_name=APP,
                            log_file=Path(tempfile.gettempdir()) / "asset_browser.log"))
