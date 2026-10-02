"""SQLite への接続とスキーマ定義。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# スキーマを変更したら上げる。DBファイル側の PRAGMA user_version と比較して判定する。
SCHEMA_VERSION = 1

SCHEMA_SQL = """
-- アセット本体。1行 = Megascans の1アセット。
CREATE TABLE assets (
    id            INTEGER PRIMARY KEY,           -- 内部用の連番 (サロゲートキー)
    megascans_id  TEXT    NOT NULL UNIQUE,       -- Megascans 側のID (例: xiwcfassc)
    name          TEXT    NOT NULL,
    asset_type    TEXT    NOT NULL,              -- 3d / 3dplant / surface ...
    category      TEXT    NOT NULL,              -- 例: surface/concrete/rough
    folder_path   TEXT    NOT NULL,              -- アセットフォルダの絶対パス
    preview_path  TEXT,                          -- サムネイル画像の絶対パス
    average_color TEXT,                          -- 例: #564E40
    metadata      TEXT    NOT NULL DEFAULT '{}'  -- 列にしない情報 (semanticTags, meta など)
                  CHECK (json_valid(metadata)),
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
) STRICT;

CREATE INDEX idx_assets_asset_type ON assets(asset_type);
CREATE INDEX idx_assets_category   ON assets(category);

-- タグのマスタ。kind で種類を分け、種類ごとに同じ名前は1行だけ (大文字小文字は区別しない)。
--   tag      : JSON の tags            (例: plant, concrete)
--   color    : semanticTags.color      (例: Green, Gray)
--   industry : semanticTags.industry   (例: VFX, games)
CREATE TABLE tags (
    id    INTEGER PRIMARY KEY,
    kind  TEXT    NOT NULL CHECK (kind IN ('tag', 'color', 'industry')),
    name  TEXT    NOT NULL COLLATE NOCASE,
    UNIQUE (kind, name)
) STRICT;

-- アセットとタグの多対多を表す中間テーブル。
CREATE TABLE asset_tags (
    asset_id  INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    tag_id    INTEGER NOT NULL REFERENCES tags(id)   ON DELETE CASCADE,
    PRIMARY KEY (asset_id, tag_id)
) STRICT;

-- 主キー (asset_id, tag_id) は「アセット → タグ」の検索にしか効かないので、
-- 「タグ → アセット」の検索用に逆順のインデックスを用意する。
CREATE INDEX idx_asset_tags_tag ON asset_tags(tag_id, asset_id);

-- アセットに含まれるファイル (テクスチャ・メッシュ)。アセット1 : ファイル多。
CREATE TABLE asset_files (
    id          INTEGER PRIMARY KEY,
    asset_id    INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    kind        TEXT    NOT NULL CHECK (kind IN ('texture', 'mesh')),
    map_type    TEXT,     -- texture: Albedo / Normal / Roughness ...
    lod         INTEGER,  -- mesh: 0, 1, 2 ...
    resolution  TEXT,     -- 例: 4K
    rel_path    TEXT    NOT NULL,  -- アセットフォルダからの相対パス
    UNIQUE (asset_id, rel_path)
) STRICT;
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    """DBに接続する。テストでは ":memory:" を渡すとメモリ上の使い捨てDBになる。"""

    conn = sqlite3.connect(db_path)
    # 行を row["name"] のように列名でアクセスできるようにする。
    conn.row_factory = sqlite3.Row
    # SQLite は外部キー制約がデフォルトで無効。接続ごとに有効化が必要。
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_schema_version(conn: sqlite3.Connection) -> int:
    """DBに記録したスキーマのバージョンを返す (新しいDBは 0)。

    init_db() がこの値を見て、テーブルを作るか・何もしないかを判断する。
    """

    return conn.execute("PRAGMA user_version").fetchone()[0]


def init_db(conn: sqlite3.Connection) -> None:
    """スキーマを作成する。作成済みなら何もしない。"""

    version = get_schema_version(conn)
    if version == SCHEMA_VERSION:
        return
    if version != 0:
        raise RuntimeError(f"Unsupported schema version {version} (expected {SCHEMA_VERSION})")

    # executescript() は Python 側のトランザクション管理の外で動くので、
    # BEGIN / COMMIT を自分で書いて「全部作るか、何も作らないか」にする。
    try:
        conn.executescript(
            f"BEGIN;\n{SCHEMA_SQL}\nPRAGMA user_version = {SCHEMA_VERSION};\nCOMMIT;"
        )
    except sqlite3.Error:
        if conn.in_transaction:
            conn.rollback()
        raise
