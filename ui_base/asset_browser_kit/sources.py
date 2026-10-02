"""データソース。

UI は ItemSource のインターフェースだけを呼ぶ。load() はワーカースレッドで
実行されるので、中で Qt ウィジェットに触れないこと（QImage 等の非 GUI クラスは可）。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Callable, Iterable

from .model import BrowserItem, CategoryDef
from .utils import IMAGE_EXTS, config_dir, pretty_name, safe_name


class ItemSource:
    """データソースの基底クラス。最低限 categories() と load() を実装する。"""
    supports_root: bool = False         # True なら「パスを変更」ボタンを出す
    root: str = ""

    def categories(self) -> list[CategoryDef]:
        raise NotImplementedError

    def load(self, category: str, force: bool = False) -> list[BrowserItem]:
        """category のアイテム一覧を返す（ワーカースレッドで呼ばれる）。
        force=True は「更新」ボタン押下時（キャッシュを無視して再取得）。"""
        raise NotImplementedError

    def set_root(self, root: str) -> None:
        self.root = root

    def describe(self) -> str:
        """パスバーに表示する文字列。空なら非表示。"""
        return self.root


class StaticSource(ItemSource):
    """メモリ上のリストをそのまま出す（デモ・テスト・他システムからの受け渡し用）。"""

    def __init__(self, items: Iterable[BrowserItem],
                 categories: list[CategoryDef] | None = None, label: str = ""):
        self._items = list(items)
        if categories is None:
            keys = list(dict.fromkeys(i.category for i in self._items))
            categories = [CategoryDef(k) for k in keys]
        self._cats = categories
        self._label = label

    def categories(self):
        return self._cats

    def load(self, category, force=False):
        return sorted((i for i in self._items if i.category == category),
                      key=lambda i: i.name.lower())

    def describe(self):
        return self._label


class JsonCache:
    """カテゴリ単位の一覧キャッシュ。

    1) ライブラリ直下 <root>/<shared_dirname>/<category>.json（チーム共有）
    2) ユーザー設定領域（ライブラリが書き込み不可な場合のフォールバック）
    読み込み時は存在するもののうち最も新しいものを使う。
    """
    VERSION = 2

    def __init__(self, app_name: str = "AssetBrowser",
                 shared_dirname: str = ".asset_browser_cache",
                 use_shared: bool = True):
        self.app_name = app_name
        self.shared_dirname = shared_dirname
        self.use_shared = use_shared

    def _files(self, root: str, category: str) -> list[Path]:
        files = []
        if self.use_shared:
            files.append(Path(root) / self.shared_dirname / f"{safe_name(category)}.json")
        h = hashlib.md5(f"{root}|{category}".encode()).hexdigest()[:16]
        files.append(config_dir(self.app_name) / "cache" / f"cat_{h}.json")
        return files

    def read(self, root: str, category: str) -> list[BrowserItem] | None:
        best, best_mtime = None, -1.0
        for f in self._files(root, category):
            try:
                mt = f.stat().st_mtime
            except OSError:
                continue
            if mt > best_mtime:
                best, best_mtime = f, mt
        if best is None:
            return None
        try:
            data = json.loads(best.read_text("utf-8"))
            if data.get("version") != self.VERSION:
                return None
            return [BrowserItem.from_dict(r) for r in data.get("items", [])]
        except Exception:
            return None

    def write(self, root: str, category: str, items: list[BrowserItem]) -> None:
        blob = json.dumps({"version": self.VERSION,
                           "items": [i.to_dict() for i in items]}, ensure_ascii=False)
        for f in self._files(root, category):
            try:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(blob, "utf-8")
                return                  # 最初に書けた場所で十分
            except Exception:
                continue


NameFn = Callable[[str, CategoryDef], str]
MetaFn = Callable[[BrowserItem], dict]


class FolderSource(ItemSource):
    """フォルダ構成からアイテムを作る汎用ソース。

    <root>/<CategoryDef.folders...>/ 以下を走査する。

    item_kind="dir"  : サブフォルダ 1 つ = 1 アイテム（Megascans 型）
                       preview_pattern を指定すると中身を列挙せずにパスを組み立てる
                       （ネットワークドライブで速い）。未指定ならフォルダ内の画像を探す。
    item_kind="file" : file_exts に一致するファイル 1 つ = 1 アイテム
                       同名（または *_preview / *_thumb）の画像をサムネに使う。
                       file_exts を空にすると画像ファイル自体をアイテムにする。

    preview_pattern の書式フィールド: {id} {stem} {name}
    """
    supports_root = True

    def __init__(self, root: str, categories: list[CategoryDef], *,
                 item_kind: str = "dir",
                 file_exts: Iterable[str] = (),
                 preview_pattern: str | None = None,
                 id_fn: NameFn | None = None,
                 name_fn: NameFn | None = None,
                 meta_fn: MetaFn | None = None,
                 cache: JsonCache | None = None):
        if item_kind not in ("dir", "file"):
            raise ValueError("item_kind must be 'dir' or 'file'")
        self.root = self._clean(root)
        self._cats = list(categories)
        self.item_kind = item_kind
        exts = [e.lower() if e.startswith(".") else "." + e.lower() for e in file_exts]
        self.file_exts = sorted(exts, key=len, reverse=True)   # ".bgeo.sc" を ".sc" より先に
        self.preview_pattern = preview_pattern
        self.id_fn = id_fn
        self.name_fn = name_fn
        self.meta_fn = meta_fn
        self.cache = cache

    @staticmethod
    def _clean(root) -> str:
        return str(root or "").strip().strip('"')

    def set_root(self, root):
        self.root = self._clean(root)

    def categories(self):
        return self._cats

    def _cat(self, key: str) -> CategoryDef:
        for c in self._cats:
            if c.key == key:
                return c
        raise KeyError(key)

    # ---- load -------------------------------------------------------------
    def load(self, category, force=False):
        cat = self._cat(category)
        root = self.root
        if not root or not os.path.isdir(root):
            return []
        if self.cache is not None and not force:
            cached = self.cache.read(root, cat.key)
            if cached is not None:
                return cached
        dirs = [os.path.join(root, f) for f in cat.folders] if cat.folders else [root]
        items: list[BrowserItem] = []
        for d in dirs:
            if os.path.isdir(d):
                items += self._scan(d, cat)
        items.sort(key=lambda i: i.name.lower())
        if self.cache is not None:
            self.cache.write(root, cat.key, items)
        return items

    # ---- scan -------------------------------------------------------------
    def _scan(self, d: str, cat: CategoryDef) -> list[BrowserItem]:
        try:
            # os.scandir はエントリ種別を列挙時に得られるので追加 stat が少なく速い
            with os.scandir(d) as it:
                entries = [e for e in it if not e.name.startswith(".")]
        except OSError:
            return []
        if self.item_kind == "dir":
            out = []
            for e in entries:
                try:
                    if not e.is_dir():
                        continue
                except OSError:
                    continue
                out.append(self._make(e.name, e.path, cat, d, images=None))
            return out
        return self._scan_files(d, entries, cat)

    def _scan_files(self, d, entries, cat):
        images: dict[str, str] = {}
        files: list[tuple[str, str]] = []           # (path, stem)
        exts = self.file_exts or list(IMAGE_EXTS)
        for e in entries:
            try:
                if not e.is_file():
                    continue
            except OSError:
                continue
            low = e.name.lower()
            stem_l, ext = os.path.splitext(low)
            if ext in IMAGE_EXTS:
                images[stem_l] = e.path
            for x in exts:
                if low.endswith(x):
                    files.append((e.path, e.name[:-len(x)]))
                    break
        return [self._make(stem, path, cat, d, images=images) for path, stem in files]

    def _make(self, stem, path, cat, parent_dir, images) -> BrowserItem:
        iid = self.id_fn(stem, cat) if self.id_fn else stem
        name = self.name_fn(stem, cat) if self.name_fn else pretty_name(stem)
        item = BrowserItem(id=iid, name=name, category=cat.key, path=path)
        item.preview = self._preview(item, stem, path, parent_dir, images)
        if self.meta_fn is not None:
            try:
                item.meta.update(self.meta_fn(item) or {})
            except Exception:
                pass
        return item

    def _preview(self, item, stem, path, parent_dir, images):
        is_dir = images is None
        if self.preview_pattern:
            rel = self.preview_pattern.format(id=item.id, stem=stem, name=item.name)
            return os.path.join(path if is_dir else parent_dir, rel)
        if is_dir:
            return self._find_image_in(path)
        if os.path.splitext(path)[1].lower() in IMAGE_EXTS:
            return path                              # 画像そのものがアイテム
        s = stem.lower()
        for cand in (s, s + "_preview", s + "_thumb", s + ".preview", s + ".thumb"):
            if cand in images:
                return images[cand]
        return None

    @staticmethod
    def _find_image_in(d: str) -> str | None:
        try:
            with os.scandir(d) as it:
                imgs = sorted(e.path for e in it
                              if os.path.splitext(e.name)[1].lower() in IMAGE_EXTS)
        except OSError:
            return None
        for key in ("preview", "thumb", "icon"):
            for p in imgs:
                if key in os.path.basename(p).lower():
                    return p
        return imgs[0] if imgs else None
