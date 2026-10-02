"""レール用の線画アイコン（QPainter で描画。外部画像不要）。"""
from __future__ import annotations

import math
import os

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

BUILTIN_ICONS = ("cube", "box", "plant", "surface", "heart", "folder", "image", "grid")


def make_icon(kind: str, color: str = "#c6c6c6", size: int = 26) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(color), 2.0)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    s = size
    c = s / 2
    P = lambda x, y: QPointF(s * x, s * y)  # noqa: E731
    if kind in ("cube", "box"):
        r = s * 0.36
        pts = [QPointF(c + r * math.cos(math.radians(a)), c + r * math.sin(math.radians(a)))
               for a in (-90, -30, 30, 90, 150, 210)]
        p.drawPolygon(QPolygonF(pts))
        for i in (0, 2, 4):
            p.drawLine(QPointF(c, c), pts[i])
    elif kind == "plant":
        path = QPainterPath()
        path.moveTo(c, s * .85)
        path.cubicTo(s * .15, s * .62, s * .24, s * .22, c, s * .16)
        path.cubicTo(s * .76, s * .22, s * .85, s * .62, c, s * .85)
        p.drawPath(path)
        p.drawLine(QPointF(c, s * .85), QPointF(c, s * .28))
    elif kind == "surface":
        p.drawPolygon(QPolygonF([P(.2, .5), P(.5, .34), P(.8, .5), P(.5, .66)]))
        p.drawLine(P(.35, .5), P(.65, .5))
    elif kind == "heart":
        path = QPainterPath()
        path.moveTo(c, s * .80)
        path.cubicTo(s * .05, s * .44, s * .22, s * .14, c, s * .36)
        path.cubicTo(s * .78, s * .14, s * .95, s * .44, c, s * .80)
        p.drawPath(path)
    elif kind == "image":
        p.drawRoundedRect(QRectF(s * .18, s * .24, s * .64, s * .52), 2, 2)
        p.drawPolyline(QPolygonF([P(.24, .70), P(.44, .48), P(.58, .62),
                                  P(.66, .54), P(.78, .70)]))
        p.drawEllipse(P(.66, .37), s * .05, s * .05)
    elif kind == "grid":
        for x in (.2, .54):
            for y in (.2, .54):
                p.drawRoundedRect(QRectF(s * x, s * y, s * .26, s * .26), 2, 2)
    else:  # folder
        p.drawPolygon(QPolygonF([P(.16, .28), P(.40, .28), P(.48, .37), P(.84, .37),
                                 P(.84, .76), P(.16, .76)]))
    p.end()
    return QIcon(pm)


def resolve_icon(icon, color: str = "#c6c6c6", size: int = 26) -> QIcon:
    """QIcon / 組み込み名 / 画像パス / None を QIcon に揃える。"""
    if isinstance(icon, QIcon):
        return icon
    if isinstance(icon, str):
        if icon in BUILTIN_ICONS:
            return make_icon(icon, color, size)
        if os.path.exists(icon):
            return QIcon(icon)
    return make_icon("folder", color, size)
