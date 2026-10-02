"""サムネイルの非同期読み込み + LRU キャッシュ + プレースホルダー描画。"""
from __future__ import annotations

import hashlib
import random
from collections import OrderedDict

from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient)

from .model import BrowserItem


# --------------------------------------------------------------------------- #
#  非同期ローダー
# --------------------------------------------------------------------------- #
def compose_image(path: str, w: int, h: int, scale: float = 0.7,
                  bg: str = "#0a0a0a") -> QImage | None:
    """ワーカースレッドで実行可能。画像を切らずに scale 倍で中央に合成した
    w×h の QImage を返す（QPixmap はメインスレッド専用なので使わない）。"""
    src = QImage(path)
    if src.isNull():
        return None
    canvas = QImage(w, h, QImage.Format_RGB32)
    canvas.fill(QColor(bg))
    tw, th = max(1, int(w * scale)), max(1, int(h * scale))
    scaled = src.scaled(tw, th, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    p = QPainter(canvas)
    p.drawImage((w - scaled.width()) // 2, (h - scaled.height()) // 2, scaled)
    p.end()
    return canvas


class _LRU:
    def __init__(self, cap: int):
        self._d: "OrderedDict[str, QPixmap]" = OrderedDict()
        self.cap = cap

    def get(self, key):
        pm = self._d.get(key)
        if pm is not None:
            self._d.move_to_end(key)
        return pm

    def put(self, key, pm):
        self._d[key] = pm
        self._d.move_to_end(key)
        while len(self._d) > self.cap:
            self._d.popitem(last=False)


class _Signals(QObject):
    done = Signal(str, object)          # key, QImage | None


class _Task(QRunnable):
    def __init__(self, key, path, w, h, scale, bg, sig):
        super().__init__()
        self.a = (key, path, w, h, scale, bg, sig)

    def run(self):
        key, path, w, h, scale, bg, sig = self.a
        sig.done.emit(key, compose_image(path, w, h, scale, bg))


class ThumbnailManager(QObject):
    """読み込み・縮小・合成を QThreadPool で行い、結果を LRU にキャッシュして
    ready(key, QPixmap|None) で通知する。アプリ内で 1 つ共有する（thumbnail_manager()）。"""
    ready = Signal(str, object)

    def __init__(self, cap: int = 200, threads: int = 3):
        super().__init__()
        self.cache = _LRU(cap)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(threads)   # ネットワークに優しい並列度
        self._inflight: set[str] = set()
        self._sig = _Signals()
        self._sig.done.connect(self._on_done)

    @staticmethod
    def make_key(item: BrowserItem, w: int, h: int, scale: float) -> str:
        return f"{item.preview or item.uid}@{w}x{h}@{scale:g}"

    def request(self, key, path, w, h, scale=0.7, bg="#0a0a0a") -> QPixmap | None:
        """キャッシュ命中なら即 QPixmap を返す。無ければ読み込みを予約して None。"""
        pm = self.cache.get(key)
        if pm is not None:
            return pm
        if key not in self._inflight:
            self._inflight.add(key)
            self._pool.start(_Task(key, path, w, h, scale, bg, self._sig))
        return None

    def get_sync(self, key, path, w, h, scale=0.7, bg="#0a0a0a") -> QPixmap | None:
        """同期版（詳細ダイアログなど単発用）。"""
        pm = self.cache.get(key)
        if pm is None and path:
            img = compose_image(path, w, h, scale, bg)
            if img is not None:
                pm = QPixmap.fromImage(img)
                self.cache.put(key, pm)
        return pm

    def _on_done(self, key, image):
        self._inflight.discard(key)
        pm = QPixmap.fromImage(image) if image is not None else None
        if pm is not None:
            self.cache.put(key, pm)
        self.ready.emit(key, pm)


_MGR: ThumbnailManager | None = None


def thumbnail_manager() -> ThumbnailManager:
    global _MGR
    if _MGR is None:
        _MGR = ThumbnailManager()
    return _MGR


_BLANK: dict[tuple, QPixmap] = {}


def blank_pixmap(w: int, h: int, bg: str = "#0a0a0a") -> QPixmap:
    pm = _BLANK.get((w, h, bg))
    if pm is None:
        pm = QPixmap(w, h)
        pm.fill(QColor(bg))
        _BLANK[(w, h, bg)] = pm
    return pm


# --------------------------------------------------------------------------- #
#  プレースホルダー（サムネが無い / 読めないときの代替絵）
# --------------------------------------------------------------------------- #
PALETTES = {
    "sphere": [("#6b5c48", "#2f2820"), ("#8f8d88", "#4a4844"),
               ("#c2a878", "#7d6743"), ("#4c4327", "#221d10")],
    "rock":   [("#7c7368", "#3a352f"), ("#8a8378", "#443f38"),
               ("#5f6a44", "#2f351f"), ("#4a4644", "#221f1e")],
    "plant":  [("#4f9d3a", "#1e3d14"), ("#6fae42", "#274d18"),
               ("#3f8f34", "#153a12")],
    None:     [("#5a6270", "#2a2e36"), ("#6b6358", "#302c27"),
               ("#4f6a5c", "#22302a"), ("#6a5670", "#2e2532")],
}


def make_placeholder(item: BrowserItem, w: int, h: int, style: str | None = None,
                     bg: str = "#0a0a0a") -> QPixmap:
    pm = QPixmap(w, h)
    pm.fill(QColor(bg))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    side = min(w, h)
    p.translate((w - side) // 2, (h - side) // 2)
    seed = int(hashlib.md5(item.uid.encode()).hexdigest(), 16)
    opts = PALETTES.get(style, PALETTES[None])
    c1, c2 = opts[seed % len(opts)]
    rnd = random.Random(seed)
    {"sphere": _sphere, "rock": _rock, "plant": _plant}.get(style, _tile)(
        p, side, c1, c2, rnd, item)
    p.end()
    return pm


def _noise(p, size, rnd, n):
    p.setPen(Qt.NoPen)
    for _ in range(n):
        x, y = rnd.uniform(0, size), rnd.uniform(0, size)
        a = rnd.randint(0, 55)
        p.setBrush(QColor(255, 255, 255, a) if rnd.random() < .5 else QColor(0, 0, 0, a))
        d = rnd.uniform(1, 2.3)
        p.drawEllipse(QPointF(x, y), d, d)


def _tile(p, s, c1, c2, rnd, item):
    r = QRectF(s * .28, s * .22, s * .44, s * .44)
    g = QLinearGradient(r.topLeft(), r.bottomRight())
    g.setColorAt(0, QColor(c1))
    g.setColorAt(1, QColor(c2))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(g))
    p.drawRoundedRect(r, s * .06, s * .06)
    ch = (item.name or item.id or "?")[:1].upper()
    f = QFont()
    f.setPixelSize(max(8, int(s * .2)))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor(255, 255, 255, 190))
    p.drawText(r, Qt.AlignCenter, ch)


def _sphere(p, size, c1, c2, rnd, _item):
    r = size * 0.33
    cx = cy = size / 2
    g = QRadialGradient(cx - r * .35, cy - r * .45, r * 2.0)
    g.setColorAt(0.0, QColor(255, 255, 255, 120))
    g.setColorAt(0.28, QColor(c1))
    g.setColorAt(1.0, QColor(c2))
    path = QPainterPath()
    path.addEllipse(QPointF(cx, cy), r, r)
    p.setClipPath(path)
    p.fillRect(0, 0, size, size, QBrush(g))
    _noise(p, size, rnd, 800)
    p.setClipping(False)
    vg = QRadialGradient(cx, cy, r * 1.05)
    vg.setColorAt(0.62, QColor(0, 0, 0, 0))
    vg.setColorAt(1.0, QColor(0, 0, 0, 175))
    p.setPen(Qt.NoPen)
    p.setBrush(vg)
    p.drawEllipse(QPointF(cx, cy), r, r)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QColor(0, 0, 0, 90), 1))
    p.drawEllipse(QPointF(cx, cy), r, r)


def _rock(p, s, c1, c2, rnd, _item):
    pts = [(.36, .29), (.64, .26), (.79, .48), (.75, .75), (.48, .81), (.24, .66), (.20, .46)]
    poly = QPolygonF([QPointF(x * s, y * s) for x, y in pts])
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, 120))
    p.drawEllipse(QRectF(s * .22, s * .80, s * .56, s * .10))
    path = QPainterPath()
    path.addPolygon(poly)
    path.closeSubpath()
    g = QRadialGradient(s * .42, s * .34, s * .62)
    g.setColorAt(0.0, QColor(255, 255, 255, 95))
    g.setColorAt(0.30, QColor(c1))
    g.setColorAt(1.0, QColor(c2))
    p.setClipPath(path)
    p.fillRect(0, 0, s, s, QBrush(g))
    _noise(p, s, rnd, 650)
    p.setClipping(False)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QColor(0, 0, 0, 80), 1))
    p.drawPolygon(poly)


def _plant(p, s, c1, c2, rnd, _item):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, 110))
    p.drawEllipse(QRectF(s * .28, s * .82, s * .44, s * .08))
    n = 7
    for i in range(n):
        t = i / (n - 1) - .5
        bx = s * .5 + t * s * .30
        top_y = s * .30 + abs(t) * s * .22
        sway = t * s * .24
        pen = QPen(QColor(c1 if i % 2 else c2), max(3.0, 9 - abs(t) * 8))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        path = QPainterPath()
        path.moveTo(bx, s * .86)
        path.quadTo(bx + sway * .4, s * .58, bx + sway, top_y)
        p.drawPath(path)
    p.setPen(Qt.NoPen)
    vg = QRadialGradient(s / 2, s * .46, s * .62)
    vg.setColorAt(0.62, QColor(0, 0, 0, 0))
    vg.setColorAt(1.0, QColor(0, 0, 0, 150))
    p.setBrush(vg)
    p.drawRect(0, 0, s, s)
