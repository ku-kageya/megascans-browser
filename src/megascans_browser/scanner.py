"""Megascans の Downloaded フォルダを読み、AssetLibrary に登録する。

Bridge が Downloaded 直下に作る索引 assetsData.json を読む。
アセットごとの <id>.json を1つずつ読むより、ネットワークドライブでもはるかに速い
(8,000件で約1秒 / 約4分)。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from megascans_browser.library import AssetLibrary

INDEX_FILE = "assetsData.json"

# metadata (JSON 列) に残す項目。検索には使わないが、UI で詳細を見せるときに使う。
METADATA_KEYS = ("semanticTags", "meta", "environment", "properties", "assetCategories")


@dataclass
class ScanResult:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    # 読めなかった索引の項目: (megascans_id か位置, 理由)
    errors: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class AssetEntry:
    """索引の1項目を、create_asset() に渡せる形に整えたもの。"""

    megascans_id: str
    name: str
    category: str
    folder_path: Path
    preview_path: Path | None
    average_color: str | None
    metadata: dict[str, Any]
    tags: tuple[str, ...]
    colors: tuple[str, ...]
    industries: tuple[str, ...]


def scan(library: AssetLibrary, root: str | Path) -> ScanResult:
    """root (Downloaded フォルダ) の索引を読み、DB を索引と同じ内容にする。

    - 索引にあるアセットは登録する (既にあれば全項目を上書き)
    - 索引から消えたアセットは DB から消す (ファイルには触らない)
    何度実行しても同じ結果になる。
    """

    root = Path(root)
    raw_entries = json.loads((root / INDEX_FILE).read_text(encoding="utf-8"))

    result = ScanResult()
    existing = set(library.list_asset_ids())
    seen: set[str] = set()

    # 全件を1つのトランザクションにまとめる。COMMIT が1回で済んで速く、
    # 途中で止まっても DB は前回スキャンの状態のまま残る。
    with library.transaction():
        for position, raw in enumerate(raw_entries):
            try:
                entry = parse_entry(raw, root)
            except (KeyError, TypeError, ValueError) as e:
                label = raw.get("id") if isinstance(raw, Mapping) else None
                result.errors.append((str(label or f"#{position}"), f"{type(e).__name__}: {e}"))
                continue

            library.create_asset(
                entry.megascans_id,
                entry.name,
                entry.category,
                entry.folder_path,
                preview_path=entry.preview_path,
                average_color=entry.average_color,
                metadata=entry.metadata,
                tags=entry.tags,
                colors=entry.colors,
                industries=entry.industries,
                exist_ok=True,
            )
            seen.add(entry.megascans_id)
            (result.updated if entry.megascans_id in existing else result.added).append(
                entry.megascans_id
            )

        # 読めなかった項目のアセットは、消さずに前回の内容を残す
        keep = seen | {label for label, _ in result.errors}
        for megascans_id in sorted(existing - keep):
            library.delete_asset(megascans_id)
            result.removed.append(megascans_id)

    return result


def parse_entry(raw: Mapping[str, Any], root: Path) -> AssetEntry:
    """索引の1項目を読む。必須の項目がなければ KeyError / ValueError。"""

    megascans_id = raw["id"].strip()
    name = raw["name"].strip()
    category = normalize_category(raw["categories"])
    if not megascans_id or not name or not category:
        raise ValueError("id, name, categories must not be empty")

    semantic = raw.get("semanticTags") or {}
    preview = raw.get("preview")

    return AssetEntry(
        megascans_id=megascans_id,
        name=name,
        category=category,
        # path / preview は Downloaded からの相対パスを要素に分けたリスト
        folder_path=root.joinpath(*raw["path"]),
        preview_path=root.joinpath(*preview) if preview else None,
        average_color=raw.get("averageColor") or None,
        metadata={key: raw[key] for key in METADATA_KEYS if raw.get(key) is not None},
        tags=clean_names(raw.get("tags")),
        colors=clean_names(semantic.get("color")),
        industries=clean_names(semantic.get("industry")),
    )


def normalize_category(parts: Iterable[str]) -> str:
    """["3d", "Nature", "Rock"] → "3d/nature/rock"

    索引には 3d/nature/rock と 3d/Nature/Rock が混在するので、小文字にそろえる。
    """

    return "/".join(p.strip().lower() for p in parts if p.strip())


def clean_names(names: Iterable[str] | None) -> tuple[str, ...]:
    """前後の空白を取り、空の値と (大文字小文字を無視した) 重複を除く。

    索引には " dark" や " " のような値が含まれている。
    """

    result: list[str] = []
    seen: set[str] = set()
    for name in names or ():
        if not isinstance(name, str):
            continue
        name = name.strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            result.append(name)
    return tuple(result)
