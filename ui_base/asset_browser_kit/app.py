"""スタンドアロン起動用ヘルパー（DCC 内では使わない）。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QLoggingCategory, Qt, qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

_IMG_NOISE = ("iCCP", "libpng warning", "sRGB profile", "known incorrect sRGB")


def install_quiet_image_logging():
    """プレビュー PNG の ICC プロファイル警告など、無害なノイズを抑制する。"""
    QLoggingCategory.setFilterRules("qt.gui.imageio.warning=false")

    def handler(mode, context, message):
        if any(s in message for s in _IMG_NOISE):
            return
        try:
            sys.stderr.write(message + "\n")
        except Exception:
            pass
    qInstallMessageHandler(handler)


class _Tee:
    def __init__(self, *streams):
        self._s = [s for s in streams if s is not None]

    def write(self, s):
        for st in self._s:
            try:
                st.write(s)
                st.flush()
            except Exception:
                pass

    def flush(self):
        for st in self._s:
            try:
                st.flush()
            except Exception:
                pass


def tee_to_logfile(path: str | Path) -> Path | None:
    """stdout/stderr をログファイルにも流す（pythonw などコンソール無し起動の診断用）。"""
    import faulthandler
    try:
        f = open(path, "w", encoding="utf-8", buffering=1)
    except Exception:
        return None
    sys.stdout = _Tee(sys.__stdout__, f)
    sys.stderr = _Tee(sys.__stderr__, f)
    faulthandler.enable(file=f)
    return Path(path)


def run_standalone(make_widget: Callable[[], QWidget], *, title: str = "Asset Browser",
                   app_name: str = "AssetBrowser", size=(1200, 800),
                   log_file: str | Path | None = None) -> int:
    """QApplication を用意してウィンドウに載せ、イベントループを回す。
    既に QApplication がある環境（DCC 内）ではウィンドウを出すだけで exec しない。"""
    if log_file:
        tee_to_logfile(log_file)
    install_quiet_image_logging()
    created = QApplication.instance() is None
    app = QApplication.instance() or QApplication(sys.argv)
    if created:
        app.setApplicationName(app_name)

    win = QMainWindow()
    win.setWindowTitle(title)
    win.setCentralWidget(make_widget())
    screen = app.primaryScreen()
    w, h = size
    if screen is not None:
        geo = screen.availableGeometry()
        w = min(w, max(800, geo.width() - 120))
        h = min(h, max(560, geo.height() - 120))
        win.resize(w, h)
        win.move(geo.center().x() - w // 2, geo.center().y() - h // 2)
    else:
        win.resize(w, h)
    win.setWindowState(Qt.WindowActive)
    win.show()
    win.raise_()
    win.activateWindow()
    if not created:
        app._asset_browser_window = win          # GC 防止
        return 0
    return app.exec()
