"""データモデル: 表示アイテム / カテゴリ定義 / アクション定義。

UI はこの 3 つだけを知っていればよく、データの出どころ（フォルダ走査・DB・
USD ステージ等）は ItemSource 側に閉じ込める。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class BrowserItem:
    """グリッドに並ぶ 1 アイテム。"""
    id: str
    name: str
    category: str                       # CategoryDef.key
    path: str = ""                      # 「フォルダーを開く」「パスをコピー」の対象
    preview: str | None = None          # サムネイル画像パス（無ければプレースホルダー）
    subtitle: str | None = None         # カード 2 行目。None なら id を表示
    meta: dict[str, str] = field(default_factory=dict)   # 詳細ダイアログの追加項目（挿入順）
    tags: list[str] = field(default_factory=list)        # 検索・キーワードチップ用
    data: Any = None                    # 任意のユーザーデータ（キャッシュ/お気に入りには保存されない）

    @property
    def uid(self) -> str:
        """カテゴリをまたいで一意なキー（お気に入り・サムネキャッシュで使用）。"""
        return f"{self.category}:{self.id}"

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "category": self.category,
                "path": self.path, "preview": self.preview,
                "subtitle": self.subtitle, "meta": dict(self.meta),
                "tags": list(self.tags)}

    @classmethod
    def from_dict(cls, d: dict) -> "BrowserItem":
        return cls(id=str(d.get("id", "")), name=str(d.get("name", "")),
                   category=str(d.get("category", "")), path=d.get("path") or "",
                   preview=d.get("preview"), subtitle=d.get("subtitle"),
                   meta=dict(d.get("meta") or {}), tags=list(d.get("tags") or []))


@dataclass
class CategoryDef:
    """左レールに並ぶカテゴリ。"""
    key: str
    label: str | None = None
    # QIcon / 組み込みアイコン名 ("cube" "plant" "surface" "folder" "image"
    # "grid" "box" "heart") / 画像ファイルパス / None(=folder)
    icon: Any = None
    # FolderSource 用: ルートからの相対フォルダ（複数可）。空ならルート直下を走査
    folders: list[str] = field(default_factory=list)
    # サムネが無いときの代替絵: "sphere" "rock" "plant" / None(=汎用タイル)
    placeholder: str | None = None

    def __post_init__(self):
        if not self.label:
            self.label = self.key


@dataclass
class ItemAction:
    """詳細ダイアログのボタン。

    callback(item) が文字列を返すと、ボタンにその文字を 1.5 秒表示する
    （「コピーしました」等のフィードバック用）。
    """
    label: str
    callback: Callable[[BrowserItem], Any]
    primary: bool = False               # True なら青い横長ボタン（先頭の 1 つだけ推奨）
    icon: Any = None                    # QIcon / QStyle.StandardPixmap / None
    close_after: bool = False           # 実行後にダイアログを閉じる
    enabled: Callable[[BrowserItem], bool] | None = None
