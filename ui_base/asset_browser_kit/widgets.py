"""再利用可能な部品: FlowLayout / ItemCard / VirtualGrid / DetailDialog。

どれも BrowserItem だけを扱い、データの出どころは知らない。
AssetBrowser を使わずに部品単体で組み込むこともできる。
"""
from __future__ import annotations

import bisect
import json
import os
import traceback
from typing import Callable

from PySide6.QtCore import QMimeData, QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QDrag, QFontMetrics, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QBoxLayout, QDialog, QFrame, QHBoxLayout,
                               QLabel, QLayout, QPushButton, QScrollArea, QStyle,
                               QToolButton, QVBoxLayout, QWidget)

from .model import BrowserItem, ItemAction
from .theme import Texts
from .thumbnails import ThumbnailManager, blank_pixmap, thumbnail_manager

MIME_TYPE = "application/x-asset-browser-item"


def set_prop(w: QWidget, name: str, value) -> None:
    """動的プロパティを変えて QSS を再評価する（[fav="true"] 等のセレクタ用）。"""
    w.setProperty(name, value)
    w.style().unpolish(w)
    w.style().polish(w)


def default_mime(item: BrowserItem) -> QMimeData:
    """ドラッグ時の既定 MIME。ファイル URL / テキスト / アイテム JSON を載せる。"""
    md = QMimeData()
    if item.path:
        md.setUrls([QUrl.fromLocalFile(item.path)])
        md.setText(item.path)
    md.setData(MIME_TYPE, json.dumps(item.to_dict(), ensure_ascii=False).encode("utf-8"))
    return md


def item_from_mime(md: QMimeData) -> BrowserItem | None:
    """ドロップ先で MIME からアイテムを復元する。"""
    if not md.hasFormat(MIME_TYPE):
        return None
    try:
        return BrowserItem.from_dict(json.loads(bytes(md.data(MIME_TYPE)).decode("utf-8")))
    except Exception:
        return None


# --------------------------------------------------------------------------- #
#  既定アクション
# --------------------------------------------------------------------------- #
def open_folder_action(texts: Texts | None = None, primary: bool = True) -> ItemAction:
    t = texts or Texts()

    def run(item: BrowserItem):
        p = item.path
        if p and os.path.isfile(p):
            p = os.path.dirname(p)
        if p and os.path.isdir(p):
            QDesktopServices.openUrl(QUrl.fromLocalFile(p))
            return t.opened
        return t.not_found
    return ItemAction(t.open_folder, run, primary=primary, icon=QStyle.SP_DirOpenIcon)


def copy_path_action(texts: Texts | None = None) -> ItemAction:
    t = texts or Texts()

    def run(item: BrowserItem):
        QGuiApplication.clipboard().setText(item.path)
        return t.copied
    return ItemAction(t.copy_path, run)


def default_actions(texts: Texts | None = None) -> list[ItemAction]:
    return [open_folder_action(texts), copy_path_action(texts)]


# --------------------------------------------------------------------------- #
#  FlowLayout（折り返し配置）
# --------------------------------------------------------------------------- #
class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=14):
        super().__init__(parent)
        self._items: list = []
        self._space = spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._layout(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def clear(self):
        while self.count():
            w = self.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()

    def _layout(self, rect, test):
        m = self.contentsMargins()
        x, y = rect.x() + m.left(), rect.y() + m.top()
        right = rect.right() - m.right()
        line_h = 0
        for it in self._items:
            hint = it.sizeHint()
            if x + hint.width() > right and line_h > 0:
                x = rect.x() + m.left()
                y += line_h + self._space
                line_h = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._space
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()


# --------------------------------------------------------------------------- #
#  カード
# --------------------------------------------------------------------------- #
class ItemCard(QFrame):
    open_requested = Signal(object)
    fav_changed = Signal(object, bool)
    META_H = 62                         # 名前 / サブタイトル帯の高さ

    def __init__(self, thumb_w: int, thumb_h: int, *, show_fav=True, show_badge=True,
                 thumb_bg="#0a0a0a", parent=None):
        super().__init__(parent)
        self.item: BrowserItem | None = None
        self.thumb_key = ""
        self.loaded = False
        self.mime_provider: Callable[[BrowserItem], QMimeData | None] | None = None
        self._tw, self._th, self._bg = thumb_w, thumb_h, thumb_bg
        self._press: QPoint | None = None
        self.setObjectName("abCard")
        self.setFixedSize(thumb_w + 2, thumb_h + self.META_H)
        self.setCursor(Qt.PointingHandCursor)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        wrap = QWidget()
        wrap.setObjectName("abThumbWrap")
        wrap.setFixedSize(thumb_w, thumb_h)
        self._img = QLabel(wrap)
        self._img.setGeometry(0, 0, thumb_w, thumb_h)
        self._img.setPixmap(blank_pixmap(thumb_w, thumb_h, thumb_bg))
        self._badge = QLabel("", wrap)
        self._badge.setObjectName("abBadge")
        self._badge.move(8, 8)
        self._badge.setVisible(show_badge)
        self.heart = QToolButton(wrap)
        self.heart.setObjectName("abHeart")
        self.heart.setCheckable(True)
        self.heart.setFixedSize(28, 28)
        self.heart.move(thumb_w - 36, 8)
        self.heart.setCursor(Qt.PointingHandCursor)
        self.heart.clicked.connect(self._toggle)
        self.heart.setVisible(show_fav)
        lay.addWidget(wrap)

        meta = QWidget()
        ml = QVBoxLayout(meta)
        ml.setContentsMargins(12, 8, 12, 11)
        ml.setSpacing(2)
        self._name = QLabel()
        self._name.setObjectName("abName")
        self._sub = QLabel()
        self._sub.setObjectName("abSub")
        ml.addWidget(self._name)
        ml.addWidget(self._sub)
        lay.addWidget(meta)

    # ---- データ差し替え（使い回し用） ----
    def bind(self, item: BrowserItem, is_fav: bool, badge: str, thumb_key: str):
        self.item = item
        self.loaded = False
        self.thumb_key = thumb_key
        self._img.setPixmap(blank_pixmap(self._tw, self._th, self._bg))
        self._badge.setText(badge)
        self._badge.adjustSize()
        fm = QFontMetrics(self._name.font())
        self._name.setText(fm.elidedText(item.name, Qt.ElideRight, self._tw - 24))
        self._name.setToolTip(item.name)
        sub = item.subtitle if item.subtitle is not None else item.id
        self._sub.setText(QFontMetrics(self._sub.font()).elidedText(sub, Qt.ElideRight, self._tw - 24))
        self.set_fav_state(is_fav)

    def set_pixmap(self, pm: QPixmap):
        self._img.setPixmap(pm)
        self.loaded = True

    def set_fav_state(self, fav: bool):
        self.heart.blockSignals(True)
        self.heart.setChecked(fav)
        self.heart.blockSignals(False)
        self._sync()

    def _sync(self):
        fav = self.heart.isChecked()
        self.heart.setText("\u2665" if fav else "\u2661")
        set_prop(self.heart, "fav", fav)

    def _toggle(self):
        self._sync()
        if self.item is not None:
            self.fav_changed.emit(self.item, self.heart.isChecked())

    # ---- クリック / ドラッグ ----
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if (self._press is not None and self.mime_provider is not None
                and self.item is not None and e.buttons() & Qt.LeftButton):
            if (e.position().toPoint() - self._press).manhattanLength() >= \
                    QApplication.startDragDistance():
                self._press = None
                self._start_drag()
                return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if (e.button() == Qt.LeftButton and self._press is not None
                and self.item is not None and self.rect().contains(e.position().toPoint())):
            self._press = None
            item = self.item
            # モーダルをイベントハンドラ内で開かないよう次のループで通知
            QTimer.singleShot(0, lambda: self.open_requested.emit(item))
            return
        self._press = None
        super().mouseReleaseEvent(e)

    def _start_drag(self):
        md = self.mime_provider(self.item)
        if md is None:
            return
        drag = QDrag(self)
        drag.setMimeData(md)
        pm = self._img.pixmap()
        if pm is not None and not pm.isNull():
            drag.setPixmap(pm.scaledToWidth(min(160, pm.width()), Qt.SmoothTransformation))
        drag.exec(Qt.CopyAction)


# --------------------------------------------------------------------------- #
#  仮想グリッド（画面内のカードだけ生成し、スクロールで使い回す）
# --------------------------------------------------------------------------- #
class VirtualGrid(QScrollArea):
    """カテゴリ見出し付きグリッド。数千件でもカード生成は画面内の分だけ。"""
    open_requested = Signal(object)
    fav_changed = Signal(object, bool)
    GAP = 16
    MARGIN = 20
    HEADER_H = 46
    SECTION_GAP = 12
    BUFFER = 160                        # 上下の先読み(px)

    def __init__(self, *, thumb_size=(320, 180),
                 is_fav: Callable[[BrowserItem], bool] = lambda i: False,
                 label_fn: Callable[[str], str] = lambda k: k,
                 category_order: list[str] | None = None,
                 placeholder_fn: Callable[[BrowserItem, int, int], QPixmap] | None = None,
                 show_fav=True, show_badge=True, thumb_scale=0.7, thumb_bg="#0a0a0a",
                 mime_provider=None, manager: ThumbnailManager | None = None, parent=None):
        super().__init__(parent)
        self.is_fav = is_fav
        self.label_fn = label_fn
        self.category_order = list(category_order or [])
        self.placeholder_fn = placeholder_fn
        self.show_fav, self.show_badge = show_fav, show_badge
        self.thumb_scale, self.thumb_bg = thumb_scale, thumb_bg
        self.mime_provider = mime_provider
        self._tw, self._th = thumb_size
        self._items: list[BrowserItem] = []
        self._show_headers = True
        self._pool: list[ItemCard] = []
        self._active: dict[int, ItemCard] = {}
        self._cols = 1
        self._card_x: list[int] = []
        self._card_y: list[int] = []
        self._ys_sorted: list[int] = []
        self._order: list[int] = []
        self._headers: list[tuple[str, int, int]] = []
        self._header_widgets: list[QLabel] = []

        self._mgr = manager or thumbnail_manager()
        self._mgr.ready.connect(self._on_thumb)

        self.setObjectName("abScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._content = QWidget()
        self._content.setObjectName("abHolder")
        self.setWidget(self._content)
        self.verticalScrollBar().valueChanged.connect(self._update_visible)

    # ---- 公開 API ----
    @property
    def card_w(self):
        return self._tw + 2

    @property
    def card_h(self):
        return self._th + ItemCard.META_H

    def thumb_size(self) -> tuple[int, int]:
        return self._tw, self._th

    def set_items(self, items: list[BrowserItem], show_headers: bool = True):
        self._items = list(items)
        self._show_headers = show_headers
        self._recycle_all()
        self.verticalScrollBar().setValue(0)
        self._relayout()

    def set_thumb_size(self, w: int, h: int):
        if (w, h) == (self._tw, self._th):
            return
        self._tw, self._th = w, h
        for c in list(self._active.values()) + self._pool:   # サイズ違いのカードは破棄
            c.deleteLater()
        self._active, self._pool = {}, []
        self._relayout()

    def refresh_favorites(self):
        for idx, card in self._active.items():
            card.set_fav_state(self.is_fav(self._items[idx]))

    # ---- 内部 ----
    def _recycle_all(self):
        for c in self._active.values():
            c.hide()
        self._pool.extend(self._active.values())
        self._active = {}

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout()

    def _columns(self) -> int:
        avail = self.viewport().width() - 2 * self.MARGIN
        return max(1, (avail + self.GAP) // (self.card_w + self.GAP))

    def _block(self) -> tuple[int, int]:
        block = self._cols * self.card_w + (self._cols - 1) * self.GAP
        return max(self.MARGIN, (self.viewport().width() - block) // 2), block

    def _relayout(self):
        self._cols = self._columns()
        n = len(self._items)
        self._card_x, self._card_y = [0] * n, [0] * n
        self._order, self._headers = [], []

        groups: dict[str, list[int]] = {}
        for i, it in enumerate(self._items):
            groups.setdefault(it.category, []).append(i)
        cats = [c for c in self.category_order if c in groups]
        cats += [c for c in sorted(groups) if c not in self.category_order]

        x0, _ = self._block()
        step_x, step_y = self.card_w + self.GAP, self.card_h + self.GAP
        use_headers = self._show_headers and len(cats) > 1
        y = self.MARGIN
        for ci, cat in enumerate(cats):
            idxs = groups[cat]
            if ci > 0:
                y += self.SECTION_GAP
            if use_headers:
                self._headers.append((self.label_fn(cat), y, len(idxs)))
                y += self.HEADER_H
            for k, idx in enumerate(idxs):
                col = k % self._cols
                if col == 0 and k > 0:
                    y += step_y
                self._card_x[idx] = x0 + col * step_x
                self._card_y[idx] = y
                self._order.append(idx)
            if idxs:
                y += step_y
        total = y - self.GAP + self.MARGIN
        self._ys_sorted = [self._card_y[i] for i in self._order]
        self._content.setFixedHeight(max(total, self.viewport().height()))
        self._build_headers()
        self._recycle_all()
        self._update_visible()

    def _build_headers(self):
        for w in self._header_widgets:
            w.deleteLater()
        self._header_widgets = []
        x0, block = self._block()
        for label, y, count in self._headers:
            h = QLabel(f"{label}   {count}", self._content)
            h.setObjectName("abGroupHeader")
            h.setGeometry(x0, y, block, self.HEADER_H)
            h.show()
            self._header_widgets.append(h)

    def _visible_indices(self):
        if not self._order:
            return []
        top = self.verticalScrollBar().value()
        bottom = top + self.viewport().height()
        lo = bisect.bisect_left(self._ys_sorted, top - self.BUFFER - self.card_h)
        hi = bisect.bisect_right(self._ys_sorted, bottom + self.BUFFER)
        return self._order[lo:hi]

    def _acquire(self) -> ItemCard:
        if self._pool:
            return self._pool.pop()
        card = ItemCard(self._tw, self._th, show_fav=self.show_fav,
                        show_badge=self.show_badge, thumb_bg=self.thumb_bg,
                        parent=self._content)
        card.mime_provider = self.mime_provider
        card.open_requested.connect(self.open_requested)
        card.fav_changed.connect(self.fav_changed)
        return card

    def _update_visible(self, *_):
        if not self._order:
            self._recycle_all()
            return
        needed = set(self._visible_indices())
        for idx in list(self._active):
            if idx not in needed:
                card = self._active.pop(idx)
                card.hide()
                self._pool.append(card)
        for idx in needed:
            x, y = self._card_x[idx], self._card_y[idx]
            card = self._active.get(idx)
            if card is None:
                card = self._acquire()
                self._active[idx] = card
                it = self._items[idx]
                key = ThumbnailManager.make_key(it, self._tw, self._th, self.thumb_scale)
                card.bind(it, self.is_fav(it), self.label_fn(it.category), key)
                card.move(x, y)
                card.show()
                self._request_thumb(card)
            else:
                card.move(x, y)

    def _placeholder(self, item):
        if self.placeholder_fn is not None:
            return self.placeholder_fn(item, self._tw, self._th)
        return blank_pixmap(self._tw, self._th, self.thumb_bg)

    def _request_thumb(self, card: ItemCard):
        it = card.item
        if it is None:
            return
        cached = self._mgr.cache.get(card.thumb_key)
        if cached is not None:
            card.set_pixmap(cached)
            return
        if not it.preview:
            pm = self._placeholder(it)
            self._mgr.cache.put(card.thumb_key, pm)
            card.set_pixmap(pm)
            return
        pm = self._mgr.request(card.thumb_key, it.preview, self._tw, self._th,
                               self.thumb_scale, self.thumb_bg)
        if pm is not None:
            card.set_pixmap(pm)

    def _on_thumb(self, key, pm):
        for card in self._active.values():
            if card.thumb_key == key and not card.loaded and card.item is not None:
                if pm is None:                  # 読めなかった → プレースホルダー
                    pm = self._placeholder(card.item)
                    self._mgr.cache.put(key, pm)
                card.set_pixmap(pm)
                break


# --------------------------------------------------------------------------- #
#  詳細モーダル
# --------------------------------------------------------------------------- #
class DetailDialog(QDialog):
    """親ウィジェットを半透明で覆い、中央にシートを出すモーダル。
    親が狭い（Houdini のペイン等）ときは縦並びレイアウトに切り替わる。"""
    fav_changed = Signal(object, bool)

    def __init__(self, item: BrowserItem, *, preview: QPixmap | Callable[[int, int], QPixmap],
                 category_label: str = "", actions: list[ItemAction] | None = None,
                 is_fav: bool | None = None, texts: Texts | None = None,
                 stylesheet: str = "", parent=None):
        super().__init__(parent)
        self.item = item
        self.texts = t = texts or Texts()
        self.setObjectName("abDetail")
        self.setModal(True)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        if stylesheet:
            self.setStyleSheet(stylesheet)

        avail = parent.size() if parent is not None else QSize(1000, 640)
        narrow = avail.width() < 680
        sw = min(860, max(300, avail.width() - 40))
        sh = min(640 if narrow else 470, max(320, avail.height() - 40))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.sheet = sheet = QFrame()
        sheet.setObjectName("abSheet")
        sheet.setFixedSize(sw, sh)
        outer.addWidget(sheet, 0, Qt.AlignCenter)
        box = QBoxLayout(QBoxLayout.TopToBottom if narrow else QBoxLayout.LeftToRight, sheet)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)

        pv = QLabel()
        pv.setAlignment(Qt.AlignCenter)
        if narrow:
            pv.setObjectName("abPreviewTop")
            ph = int(sh * 0.40)
            pv.setFixedHeight(ph)
            pw_, ph_ = sw - 30, ph - 20
            detail_w = sw
        else:
            pv.setObjectName("abPreview")
            pv.setFixedWidth(sw // 2)
            pw_ = sw // 2 - 30
            ph_ = int(pw_ * 0.75)
            detail_w = sw - sw // 2
        pv.setPixmap(preview(pw_, ph_) if callable(preview) else preview)
        box.addWidget(pv)

        body = QWidget()
        body.setObjectName("abDetailBody")
        rl = QVBoxLayout(body)
        rl.setContentsMargins(28, 26, 28, 24)
        rl.setSpacing(0)
        dt = QLabel((category_label or item.category).upper())
        dt.setObjectName("abDType")
        rl.addWidget(dt)
        dn = QLabel(item.name)
        dn.setObjectName("abDName")
        dn.setWordWrap(True)
        rl.addWidget(dn)
        rl.addSpacing(14)

        specs = [(t.spec_category, category_label or item.category, False)]
        specs += [(k, str(v), False) for k, v in item.meta.items()]
        specs += [(t.spec_id, item.id, True), (t.spec_path, item.path, True)]
        specs = [s for s in specs if s[1]]
        spec_w = QWidget()
        spec_w.setObjectName("abSpecs")
        sl = QVBoxLayout(spec_w)
        sl.setContentsMargins(0, 0, 14, 0)        # 縦スクロールバーと値が重ならないように
        sl.setSpacing(0)
        vmax = max(140, detail_w - 56 - 110)
        for i, (k, v, mono) in enumerate(specs):
            if i == 0:
                sl.addWidget(self._line())
            sl.addWidget(self._spec(k, v, mono, vmax))
            sl.addWidget(self._line())
        sl.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName("abSpecScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(spec_w)
        rl.addWidget(scroll, 1)
        rl.addSpacing(12)

        row = QHBoxLayout()
        row.setSpacing(10)
        for act in actions or []:
            btn = QPushButton(act.label)
            btn.setObjectName("abPrimary" if act.primary else "abGhost")
            btn.setCursor(Qt.PointingHandCursor)
            if act.icon is not None:
                btn.setIcon(act.icon if isinstance(act.icon, QIcon)
                            else self.style().standardIcon(act.icon))
            if act.enabled is not None:
                btn.setEnabled(bool(act.enabled(item)))
            btn.clicked.connect(lambda _=False, a=act, b=btn: self._run(a, b))
            row.addWidget(btn, 1 if act.primary else 0)
        if is_fav is not None:
            self.fav_btn = QToolButton()
            self.fav_btn.setObjectName("abFavBtn")
            self.fav_btn.setCheckable(True)
            self.fav_btn.setChecked(is_fav)
            self.fav_btn.setFixedSize(42, 42)
            self.fav_btn.setCursor(Qt.PointingHandCursor)
            self.fav_btn.clicked.connect(self._toggle_fav)
            self._sync_fav()
            if not any(a.primary for a in actions or []):
                row.addStretch(1)
            row.addWidget(self.fav_btn)
        rl.addLayout(row)
        box.addWidget(body, 1)

        close = QToolButton(sheet)
        close.setObjectName("abClose")
        close.setText("\u00d7")
        close.setFixedSize(34, 34)
        close.move(sw - 18 - 34, 14)
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.reject)
        close.raise_()

    # ---- parts ----
    @staticmethod
    def _spec(k, v, mono, vmax):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 11, 0, 11)
        kl = QLabel(k)
        kl.setObjectName("abK")
        vl = QLabel(v)
        vl.setObjectName("abVMono" if mono else "abV")
        vl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        vl.setWordWrap(True)
        vl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        vl.setMaximumWidth(vmax)
        h.addWidget(kl, 0, Qt.AlignTop)
        h.addStretch(1)
        h.addWidget(vl)
        return w

    @staticmethod
    def _line():
        f = QFrame()
        f.setObjectName("abLine")
        f.setFixedHeight(1)
        return f

    # ---- behaviour ----
    def _sync_fav(self):
        fav = self.fav_btn.isChecked()
        self.fav_btn.setText("\u2665" if fav else "\u2661")
        set_prop(self.fav_btn, "fav", fav)

    def _toggle_fav(self):
        self._sync_fav()
        self.fav_changed.emit(self.item, self.fav_btn.isChecked())

    def _run(self, act: ItemAction, btn: QPushButton):
        try:
            res = act.callback(self.item)
        except Exception as exc:                # noqa: BLE001
            traceback.print_exc()
            res = f"Error: {exc}"
        if isinstance(res, str) and res:
            self._flash(btn, res, act.label)
        if act.close_after:
            self.accept()

    @staticmethod
    def _flash(btn, text, revert):
        btn.setText(text)

        def back():
            try:
                btn.setText(revert)
            except RuntimeError:                # ダイアログが既に破棄
                pass
        QTimer.singleShot(1500, back)

    def showEvent(self, e):
        super().showEvent(e)
        p = self.parentWidget()
        if p is not None:                       # 親ウィジェットの領域を覆う
            self.setGeometry(QRect(p.mapToGlobal(QPoint(0, 0)), p.size()))

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 140))

    def mousePressEvent(self, e):
        if not self.sheet.geometry().contains(e.position().toPoint()):
            self.reject()                       # シート外クリックで閉じる
        else:
            super().mousePressEvent(e)
