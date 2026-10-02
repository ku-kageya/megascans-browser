"""db.py (接続とスキーマ) のテスト。API を通さず SQL を直接書いて、DB 自体のルールを確かめる。"""

from __future__ import annotations

import sqlite3

import pytest

from megascans_browser.db import SCHEMA_VERSION, connect, get_schema_version, init_db


@pytest.fixture
def conn():
    conn = connect(":memory:")
    init_db(conn)
    yield conn
    conn.close()


def insert_asset(conn: sqlite3.Connection, megascans_id: str = "xiwcfassc", **overrides) -> int:
    values = {
        "megascans_id": megascans_id,
        "name": "Rough Concrete",
        "asset_type": "surface",
        "category": "surface/concrete/rough",
        "folder_path": "D:/Megascans/Downloaded/surface/rough_concrete_xiwcfassc",
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    cur = conn.execute(
        f"INSERT INTO assets ({columns}) VALUES ({placeholders})", tuple(values.values())
    )
    return cur.lastrowid


def insert_tag(conn: sqlite3.Connection, kind: str, name: str) -> int:
    return conn.execute("INSERT INTO tags (kind, name) VALUES (?, ?)", (kind, name)).lastrowid


# --- 接続 ---------------------------------------------------------------------


def test_connect_rows_are_accessible_by_column_name():
    conn = connect(":memory:")
    row = conn.execute("SELECT 1 AS answer").fetchone()
    assert row["answer"] == 1


def test_connect_enables_foreign_keys():
    conn = connect(":memory:")
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


# --- init_db とバージョン -----------------------------------------------------


def test_new_db_has_version_zero():
    conn = connect(":memory:")
    assert get_schema_version(conn) == 0


def test_init_db_creates_tables_and_sets_version(conn):
    tables = {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"assets", "tags", "asset_tags", "asset_files"} <= tables
    assert get_schema_version(conn) == SCHEMA_VERSION


def test_init_db_twice_does_nothing(conn):
    insert_asset(conn)
    init_db(conn)
    assert conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 1


def test_init_db_rejects_unknown_version():
    conn = connect(":memory:")
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(RuntimeError):
        init_db(conn)


def test_init_db_keeps_data_in_file(tmp_path):
    db_path = tmp_path / "library.db"
    conn = connect(db_path)
    init_db(conn)
    insert_asset(conn)
    conn.commit()
    conn.close()

    conn = connect(db_path)
    init_db(conn)
    assert conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 1
    conn.close()


def test_init_db_failure_leaves_nothing(monkeypatch):
    import megascans_browser.db as db

    # 途中でエラーになるスキーマ: 最初のテーブルだけ作られて残らないことを確かめる
    monkeypatch.setattr(db, "SCHEMA_SQL", "CREATE TABLE ok (id INTEGER); CREATE TABLE broken (;")
    conn = connect(":memory:")
    with pytest.raises(sqlite3.Error):
        db.init_db(conn)
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0
    assert get_schema_version(conn) == 0


# --- assets -------------------------------------------------------------------


def test_asset_defaults(conn):
    asset_id = insert_asset(conn)
    row = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
    assert row["metadata"] == "{}"
    assert row["preview_path"] is None
    assert row["created_at"] is not None
    assert row["updated_at"] is not None


def test_megascans_id_is_unique(conn):
    insert_asset(conn)
    with pytest.raises(sqlite3.IntegrityError):
        insert_asset(conn)


def test_required_columns_are_not_null(conn):
    with pytest.raises(sqlite3.IntegrityError):
        insert_asset(conn, name=None)


def test_metadata_must_be_valid_json(conn):
    with pytest.raises(sqlite3.IntegrityError):
        insert_asset(conn, metadata="{broken")


def test_strict_rejects_wrong_type(conn):
    asset_id = insert_asset(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO asset_files (asset_id, kind, lod, rel_path) VALUES (?, ?, ?, ?)",
            (asset_id, "mesh", "LOD0", "mesh_LOD0.fbx"),
        )


# --- tags / asset_tags --------------------------------------------------------


def test_tag_kind_is_checked(conn):
    with pytest.raises(sqlite3.IntegrityError):
        insert_tag(conn, "mood", "calm")


def test_tag_name_is_unique_ignoring_case(conn):
    insert_tag(conn, "color", "Gray")
    with pytest.raises(sqlite3.IntegrityError):
        insert_tag(conn, "color", "gray")


def test_same_name_allowed_in_different_kinds(conn):
    insert_tag(conn, "tag", "green")
    insert_tag(conn, "color", "green")
    assert conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0] == 2


def test_asset_tags_rejects_unknown_asset(conn):
    tag_id = insert_tag(conn, "tag", "concrete")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO asset_tags (asset_id, tag_id) VALUES (999, ?)", (tag_id,))


def test_asset_tags_primary_key_prevents_duplicates(conn):
    asset_id = insert_asset(conn)
    tag_id = insert_tag(conn, "tag", "concrete")
    conn.execute("INSERT INTO asset_tags VALUES (?, ?)", (asset_id, tag_id))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO asset_tags VALUES (?, ?)", (asset_id, tag_id))


def test_deleting_asset_cascades_to_tags_and_files(conn):
    asset_id = insert_asset(conn)
    tag_id = insert_tag(conn, "tag", "concrete")
    conn.execute("INSERT INTO asset_tags VALUES (?, ?)", (asset_id, tag_id))
    conn.execute(
        "INSERT INTO asset_files (asset_id, kind, rel_path) VALUES (?, 'texture', 'a.jpg')",
        (asset_id,),
    )

    conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,))

    assert conn.execute("SELECT COUNT(*) FROM asset_tags").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM asset_files").fetchone()[0] == 0
    # タグのマスタ自体は残る
    assert conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0] == 1


# --- asset_files --------------------------------------------------------------


def test_file_kind_is_checked(conn):
    asset_id = insert_asset(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO asset_files (asset_id, kind, rel_path) VALUES (?, 'video', 'a.mp4')",
            (asset_id,),
        )


def test_file_rel_path_is_unique_per_asset(conn):
    first = insert_asset(conn, "aaa")
    second = insert_asset(conn, "bbb")
    sql = "INSERT INTO asset_files (asset_id, kind, rel_path) VALUES (?, 'texture', 'a.jpg')"
    conn.execute(sql, (first,))
    conn.execute(sql, (second,))  # 別のアセットなら同じパスでよい
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, (first,))


# --- インデックス -------------------------------------------------------------


def query_plan(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> str:
    return " ".join(row["detail"] for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}", params))


def test_asset_type_search_uses_index(conn):
    plan = query_plan(conn, "SELECT id FROM assets WHERE asset_type = ?", ("surface",))
    assert "idx_assets_asset_type" in plan


def test_category_search_uses_index(conn):
    plan = query_plan(conn, "SELECT id FROM assets WHERE category = ?", ("surface/concrete",))
    assert "idx_assets_category" in plan


def test_tag_to_asset_search_uses_reverse_index(conn):
    plan = query_plan(conn, "SELECT asset_id FROM asset_tags WHERE tag_id = ?", (1,))
    assert "idx_asset_tags_tag" in plan
