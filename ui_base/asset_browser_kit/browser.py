"""AssetBrowser: 部品を組み合わせた完成形ウィジェット（QWidget）。

QMainWindow ではなく QWidget なので、スタンドアロンでも DCC のパネルでも
同じように使える。
"""
from __future__ import annotations

import itertools
import traceback
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QPixmap
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSlider, QToolButton, QVBoxLayout, QWidget)

from .favorites import FavoritesStore
from .icons import make_icon, resolve_icon
from .model import BrowserItem, CategoryDef, ItemAction
from .sources import ItemSource
from .theme import Texts, Theme, build_stylesheet
from .thumbnails import ThumbnailManager, make_placeholder, thumbnail_manager
from .utils import default_match, extract_keywords, tag_match
from .widgets import DetailDialog, FlowLayout, VirtualGrid, default_actions, default_mime


# --------------------------------------------------------------------------- #
#  バックグラウンド読み込み（共有プール。ウィジェット破棄後に戻ってきても安全）
# --------------------------------------------------------------------------- #
class _LoadSignals(QObject):
    done = Signal(int, int, object)        # token, generation, items
    failed = Signal(int, int, str)


class _LoadTask(QRunnable):
    def __init__(self, token, gen, source, category, force, sig):
        super().__init__()
        self.a = (token, gen, source, category, force, sig)

    def run(self):
        token, gen, source, category, force, sig = self.a
        try:
            sig.done.emit(token, gen, source.load(category, force))
        except Exception as exc:                # noqa: BLE001
            traceback.print_exc()
            sig.failed.emit(token, gen, str(exc))


_LOAD_POOL: QThreadPool | None = None
_LOAD_SIG: _LoadSignals | None = None
_TOKENS = itertools.count(1)


def _loader():
    global _LOAD_POOL, _LOAD_SIG
    if _LOAD_POOL is None:
        _LOAD_POOL = QThreadPool()
        _LOAD_POOL.setMaxThreadCount(2)
        _LOAD_SIG = _LoadSignals()
    return _LOAD_POOL, _LOAD_SIG


# --------------------------------------------------------------------------- #
#  AssetBrowser
# --------------------------------------------------------------------------- #
class AssetBrowser(QWidget):
    """汎用アセットブラウザ。

    Signals:
        item_activated(item)          カードがクリックされた
        favorite_changed(item, bool)  お気に入りが変わった
        items_loaded(list)            カテゴリの読み込みが完了した
        category_changed(str)         カテゴリ（"__favorites__" 含む）が切り替わった
    """
    item_activated = Signal(object)
    favorite_changed = Signal(object, bool)
    items_loaded = Signal(list)
    category_changed = Signal(str)

    FAVORITES = "__favorites__"

    def __init__(self, source: ItemSource, *,
                 actions: list[ItemAction] | None = None,
                 favorites: FavoritesStore | bool = True,
                 app_name: str = "AssetBrowser",
                 theme: Theme | None = None,
                 texts: Texts | None = None,
                 thumb_size: tuple[int, int] = (320, 180),
                 thumb_scale: float = 0.7,
                 zoom: bool | tuple[int, int] = True,
                 keywords: bool | Callable[[list[BrowserItem]], list[str]] = True,
                 match_fn: Callable[[BrowserItem, str], bool] = default_match,
                 drag: bool | Callable[[BrowserItem], object] = True,
                 detail_dialog: bool = True,
                 show_badge: bool = True,
                 logo_text: str = "A",
                 autoload: bool = True,
                 parent=None):
        super().__init__(parent)
        self.source = source
        self.theme = theme or Theme()
        self.texts = texts or Texts()
        self.actions = default_actions(self.texts) if actions is None else list(actions)
        if favorites is True:
            favorites = FavoritesStore(app_name)
        # FavoritesStore は __len__ を持つので truthiness で判定しないこと
        self.favorites: FavoritesStore | None = (
            None if favorites is False or favorites is None else favorites)
        self.match_fn = match_fn
        self.keyword_fn = (extract_keywords if keywords is True
                           else keywords if callable(keywords) else None)
        self.detail_dialog = detail_dialog
        self.thumb_scale = thumb_scale

        self._cats: list[CategoryDef] = list(source.categories())
        self._cat_map = {c.key: c for c in self._cats}
        self.items: list[BrowserItem] = []
        self.mode = "category"
        self.category = self._cats[0].key if self._cats else ""
        self.query = ""
        self.tag = ""
        self._gen = 0
        self._token = next(_TOKENS)
        self._cat_btns: dict[str, QToolButton] = {}
        self._tag_btns: dict[str, QPushButton] = {}
        self._qss = build_stylesheet(self.theme)

        self.setObjectName("AssetBrowser")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(self._qss)            # ← アプリ全体ではなくこのウィジェットだけ

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.rail = self._build_rail(logo_text)
        lay.addWidget(self.rail)
        mime = drag if callable(drag) else (default_mime if drag else None)
        lay.addWidget(self._build_content(thumb_size, zoom, show_badge, mime), 1)

        _, sig = _loader()
        sig.done.connect(self._on_loaded)
        sig.failed.connect(self._on_failed)

        self._show_message(self.texts.loading)
        if autoload:
            QTimer.singleShot(0, self.start)     # ウィンドウ表示後に読み込み開始

    # ================================================================== #
    #  公開 API
    # ================================================================== #
    def start(self):
        if self._cats:
            self.set_category(self.category)
        else:
            self._apply([])

    def set_category(self, key: str):
        self.mode, self.category, self.tag = "category", key, ""
        self._sync_rail()
        self.category_changed.emit(key)
        self.reload()

    def show_favorites(self):
        if self.favorites is None:
            return
        self.mode, self.tag = "favorites", ""
        self._sync_rail()
        self.category_changed.emit(self.FAVORITES)
        self.reload()

    def reload(self, force: bool = False):
        """現在のカテゴリを読み直す。force=True でキャッシュを無視して再走査。"""
        self._show_message(self.texts.loading)
        if self.mode == "favorites":
            self._apply(self.favorites.items())
            return
        self._gen += 1
        pool, sig = _loader()
        pool.start(_LoadTask(self._token, self._gen, self.source, self.category, force, sig))

    def set_root(self, root: str):
        self.source.set_root(root)
        self.reload()

    def set_items(self, items: list[BrowserItem]):
        """外部から直接アイテムを流し込む（ソースを介さない更新用）。"""
        self._gen += 1
        self._apply(list(items))

    def visible_items(self) -> list[BrowserItem]:
        items = self.items
        if self.tag:
            items = [i for i in items if tag_match(i, self.tag)]
        if self.query:
            items = [i for i in items if self.match_fn(i, self.query)]
        return items

    def category_label(self, key: str) -> str:
        c = self._cat_map.get(key)
        return c.label if c else key

    def placeholder(self, item: BrowserItem, w: int, h: int) -> QPixmap:
        c = self._cat_map.get(item.category)
        return make_placeholder(item, w, h, c.placeholder if c else None, self.theme.thumb_bg)

    # ================================================================== #
    #  UI 構築
    # ================================================================== #
    def _build_rail(self, logo_text) -> QWidget:
        rail = QFrame()
        rail.setObjectName("abRail")
        rail.setFixedWidth(90)
        v = QVBoxLayout(rail)
        v.setContentsMargins(6, 12, 6, 12)
        v.setSpacing(6)
        if logo_text:
            logo = QLabel(logo_text)
            logo.setObjectName("abLogo")
            logo.setAlignment(Qt.AlignCenter)
            logo.setFixedSize(40, 40)
            v.addWidget(logo, 0, Qt.AlignHCenter)
            v.addSpacing(10)
        for c in self._cats:
            btn = self._rail_button(c.label, resolve_icon(c.icon, self.theme.icon))
            btn.clicked.connect(lambda _=False, k=c.key: self.set_category(k))
            self._cat_btns[c.key] = btn
            v.addWidget(btn, 0, Qt.AlignHCenter)
        self.btn_fav = None
        if self.favorites is not None:
            sep = QFrame()
            sep.setObjectName("abRailSep")
            sep.setFixedHeight(1)
            v.addSpacing(6)
            v.addWidget(sep)
            v.addSpacing(6)
            self.btn_fav = self._rail_button(self.texts.favorites,
                                             make_icon("heart", self.theme.icon))
            self.btn_fav.clicked.connect(lambda: self.show_favorites())
            v.addWidget(self.btn_fav, 0, Qt.AlignHCenter)
        v.addStretch(1)
        # カテゴリ 1 つ & お気に入り無しならレール不要
        rail.setVisible(len(self._cats) > 1 or self.favorites is not None)
        return rail

    @staticmethod
    def _rail_button(caption, icon) -> QToolButton:
        b = QToolButton()
        b.setObjectName("abCat")
        b.setCheckable(True)
        b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        b.setIcon(icon)
        b.setIconSize(QSize(26, 26))
        b.setText(caption)
        b.setToolTip(caption)
        b.setFixedSize(78, 58)
        b.setCursor(Qt.PointingHandCursor)
        return b

    def _build_content(self, thumb_size, zoom, show_badge, mime) -> QWidget:
        panel = QWidget()
        panel.setObjectName("abContent")
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        top = QWidget()
        tl = QHBoxLayout(top)
        tl.setContentsMargins(20, 16, 20, 0)
        self.search = QLineEdit()
        self.search.setObjectName("abSearch")
        self.search.setPlaceholderText(self.texts.search_placeholder)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search)
        tl.addWidget(self.search)
        v.addWidget(top)

        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(20, 16, 20, 8)
        bl.setSpacing(8)
        self.title = QLabel()
        self.title.setObjectName("abTitle")
        self.path_lbl = QLabel()
        self.path_lbl.setObjectName("abPath")
        self.count_lbl = QLabel()
        self.count_lbl.setObjectName("abCount")
        bl.addWidget(self.title)
        bl.addStretch(1)
        bl.addWidget(self.path_lbl)
        bl.addWidget(self.count_lbl)

        self.zoom = None
        if zoom:
            lo, hi = zoom if isinstance(zoom, tuple) else (120, max(512, thumb_size[0]))
            self._aspect = thumb_size[1] / thumb_size[0]
            self.zoom = QSlider(Qt.Horizontal)
            self.zoom.setObjectName("abZoom")
            self.zoom.setRange(lo, hi)
            self.zoom.setValue(thumb_size[0])
            self.zoom.setFixedWidth(100)
            self.zoom.setToolTip(self.texts.zoom_tip)
            self._zoom_timer = QTimer(self, singleShot=True, interval=120)
            self._zoom_timer.timeout.connect(self._apply_zoom)
            self.zoom.valueChanged.connect(lambda _: self._zoom_timer.start())
            bl.addWidget(self.zoom)

        refresh = QPushButton(self.texts.refresh)
        refresh.setObjectName("abGhostSm")
        refresh.setToolTip(self.texts.refresh_tip)
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.clicked.connect(self._refresh)
        bl.addWidget(refresh)
        if self.source.supports_root:
            change = QPushButton(self.texts.change_root)
            change.setObjectName("abGhostSm")
            change.setCursor(Qt.PointingHandCursor)
            change.clicked.connect(self._change_root)
            bl.addWidget(change)
        v.addWidget(bar)

        self.tagbar = QWidget()
        self.tagbar.setObjectName("abTagbar")
        self.tagflow = FlowLayout(self.tagbar, spacing=8)
        self.tagflow.setContentsMargins(20, 0, 20, 8)
        self.tagbar.hide()
        v.addWidget(self.tagbar)

        fav = self.favorites
        self.grid = VirtualGrid(
            thumb_size=thumb_size,
            is_fav=(fav.is_fav if fav else (lambda i: False)),
            label_fn=self.category_label,
            category_order=[c.key for c in self._cats],
            placeholder_fn=self.placeholder,
            show_fav=fav is not None, show_badge=show_badge,
            thumb_scale=self.thumb_scale, thumb_bg=self.theme.thumb_bg,
            mime_provider=mime)
        self.grid.open_requested.connect(self._on_open)
        self.grid.fav_changed.connect(self._on_card_fav)
        v.addWidget(self.grid, 1)

        self.empty = QLabel()
        self.empty.setObjectName("abEmpty")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.hide()
        v.addWidget(self.empty, 1)
        return panel

    # ================================================================== #
    #  データ反映
    # ================================================================== #
    def _on_loaded(self, token, gen, items):
        if token != self._token or gen != self._gen:   # 他インスタンス / 古い読み込み
            return
        self._apply(items)

    def _on_failed(self, token, gen, msg):
        if token != self._token or gen != self._gen:
            return
        self.items = []
        self._build_tagbar()
        self._show_message(self.texts.load_error.format(error=msg))

    def _apply(self, items):
        self.items = list(items)
        self._build_tagbar()
        self.rebuild()
        self.items_loaded.emit(self.items)

    def _build_tagbar(self):
        self.tagflow.clear()
        self._tag_btns = {}
        kws = self.keyword_fn(self.items) if self.keyword_fn else []
        if self.tag and self.tag not in kws:
            self.tag = ""
        self.tagbar.setVisible(bool(kws))
        for kw in kws:
            b = QPushButton(kw)
            b.setObjectName("abChip")
            b.setCheckable(True)
            b.setChecked(kw == self.tag)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=kw: self._toggle_tag(k))
            self.tagflow.addWidget(b)
            self._tag_btns[kw] = b

    def rebuild(self):
        items = self.visible_items()
        t = self.texts
        self.title.setText(t.favorites_title if self.mode == "favorites"
                           else self.category_label(self.category))
        desc = self.source.describe() or ""
        self.path_lbl.setVisible(bool(desc))
        self.path_lbl.setText("\U0001F4C1  " + QFontMetrics(self.path_lbl.font())
                              .elidedText(desc, Qt.ElideMiddle, 360))
        self.path_lbl.setToolTip(desc)
        self.count_lbl.setText(t.count.format(n=len(items)))
        if not items:
            self.grid.set_items([])
            self._show_message(self._empty_msg())
            return
        self.empty.hide()
        self.grid.show()
        self.grid.set_items(items, show_headers=(self.mode == "favorites"))

    def _show_message(self, text):
        self.grid.hide()
        self.empty.setText(text)
        self.empty.show()

    def _empty_msg(self):
        t = self.texts
        if self.tag or self.query:
            cond = " / ".join(x for x in (self.tag, self.query) if x)
            return t.empty_filter.format(cond=cond)
        if self.mode == "favorites":
            return t.empty_favorites
        return t.empty_category.format(category=self.category_label(self.category))

    # ================================================================== #
    #  イベント
    # ================================================================== #
    def _sync_rail(self):
        for k, b in self._cat_btns.items():
            b.setChecked(self.mode == "category" and self.category == k)
        if self.btn_fav is not None:
            self.btn_fav.setChecked(self.mode == "favorites")

    def _toggle_tag(self, kw):
        self.tag = "" if self.tag == kw else kw
        for k, b in self._tag_btns.items():
            b.setChecked(k == self.tag)
        self.rebuild()

    def _on_search(self, text):
        self.query = text.strip()
        self.rebuild()

    def _refresh(self):
        self.reload(force=(self.mode == "category"))

    def _change_root(self):
        from pathlib import Path
        d = QFileDialog.getExistingDirectory(self, self.texts.choose_root,
                                             self.source.root or str(Path.home()))
        if d:
            self.set_root(d)

    def _apply_zoom(self):
        w = self.zoom.value()
        self.grid.set_thumb_size(w, max(1, int(round(w * self._aspect))))

    def _preview_pixmap(self, item):
        def make(w, h):
            mgr = thumbnail_manager()
            key = ThumbnailManager.make_key(item, w, h, self.thumb_scale)
            pm = mgr.get_sync(key, item.preview, w, h, self.thumb_scale,
                              self.theme.thumb_bg) if item.preview else None
            return pm or self.placeholder(item, w, h)
        return make

    def _on_open(self, item):
        self.item_activated.emit(item)
        if not self.detail_dialog:
            return
        fav = self.favorites
        dlg = DetailDialog(item, preview=self._preview_pixmap(item),
                           category_label=self.category_label(item.category),
                           actions=self.actions,
                           is_fav=fav.is_fav(item) if fav else None,
                           texts=self.texts, stylesheet=self._qss, parent=self)
        dlg.fav_changed.connect(self._set_fav)
        dlg.exec()
        dlg.deleteLater()
        if self.mode == "favorites":
            self._apply(fav.items())
        else:
            self.grid.refresh_favorites()

    def _set_fav(self, item, fav):
        self.favorites.set_fav(item, fav)
        self.favorite_changed.emit(item, fav)

    def _on_card_fav(self, item, fav):
        self._set_fav(item, fav)
        if self.mode == "favorites":
            self._apply(self.favorites.items())
