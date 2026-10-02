"""お気に入りの永続化（JSON）。メタ情報ごと保存するので再スキャン不要で一覧を出せる。"""
from __future__ import annotations

import json
from pathlib import Path

from .model import BrowserItem
from .utils import config_dir


class FavoritesStore:
    def __init__(self, app_name: str = "AssetBrowser", path: str | Path | None = None):
        self._file = Path(path) if path else config_dir(app_name) / "favorites.json"
        self._data: dict[str, dict] = {}
        try:
            if self._file.exists():
                raw = json.loads(self._file.read_text("utf-8"))
                if isinstance(raw, dict):
                    self._data = {k: v for k, v in raw.items() if isinstance(v, dict)}
        except Exception:
            self._data = {}

    def __len__(self):
        return len(self._data)

    def is_fav(self, item: BrowserItem) -> bool:
        return item.uid in self._data

    def set_fav(self, item: BrowserItem, fav: bool) -> None:
        if fav:
            self._data[item.uid] = item.to_dict()
        else:
            self._data.pop(item.uid, None)
        self._save()

    def items(self) -> list[BrowserItem]:
        out = [BrowserItem.from_dict(r) for r in self._data.values()]
        out.sort(key=lambda i: (i.category, i.name.lower()))
        return out

    def _save(self):
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(json.dumps(self._data, ensure_ascii=False), "utf-8")
        except Exception:
            pass
