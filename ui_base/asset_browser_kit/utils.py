"""Qt に依存しない小物ユーティリティ。"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Iterable

from .model import BrowserItem

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")
_SPLIT = re.compile(r"[\s_\-.]+")


def config_dir(app_name: str) -> Path:
    """ユーザー設定の保存先。

    QApplication の applicationName に依存しない GenericConfigLocation/<app_name>
    を使うので、Houdini / Maya などに埋め込んでもホストの設定領域を汚さない。
    """
    base = ""
    try:
        from PySide6.QtCore import QStandardPaths
        base = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.GenericConfigLocation)
    except Exception:
        pass
    d = Path(base) / app_name if base else Path.home() / f".{app_name}"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        d = Path.home()
    return d


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s)


def pretty_name(stem: str, *, strip_prefixes: Iterable[str] = (),
                drop_last_token: bool = False) -> str:
    """フォルダ名/ファイル名から表示名を作る。

    pretty_name("rock_smooth_oksjb0", drop_last_token=True)  -> "Rock Smooth"
    pretty_name("3dplant_climber_xfq", strip_prefixes=["3dplant"],
                drop_last_token=True)                        -> "Climber"
    """
    parts = [p for p in _SPLIT.split(stem) if p]
    if drop_last_token and parts:
        parts = parts[:-1]
    prefixes = {p.lower() for p in strip_prefixes}
    if parts and parts[0].lower() in prefixes:
        parts = parts[1:]
    name = " ".join(parts).strip()
    return name.title() if name else stem


def extract_keywords(items: list[BrowserItem], top: int = 18,
                     stop: Iterable[str] = ("the", "and", "with", "for")) -> list[str]:
    """アイテム名とタグから頻出キーワードを抽出（キーワードチップ用）。"""
    stop = set(stop)
    cnt: Counter = Counter()
    for it in items:
        toks = _SPLIT.split(it.name.lower()) + [t.lower() for t in it.tags]
        for tok in toks:
            tok = tok.strip()
            if len(tok) >= 3 and not tok.isdigit() and tok not in stop:
                cnt[tok] += 1
    common = [w for w, c in cnt.most_common() if c >= 2]
    if len(common) < top:
        common += [w for w, c in cnt.most_common() if c < 2 and w not in common]
    return common[:top]


def default_match(item: BrowserItem, query: str) -> bool:
    """検索ボックスの既定マッチ。名前 / ID / サブタイトル / タグの部分一致。"""
    q = query.lower()
    if q in item.name.lower() or q in item.id.lower():
        return True
    if item.subtitle and q in item.subtitle.lower():
        return True
    return any(q in t.lower() for t in item.tags)


def tag_match(item: BrowserItem, tag: str) -> bool:
    """キーワードチップの既定マッチ。"""
    return tag in item.name.lower() or any(tag == t.lower() for t in item.tags)
