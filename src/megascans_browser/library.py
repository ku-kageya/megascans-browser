"""Megascans アセットの登録・取得をまとめた API。

スキャナーや UI はこのクラスを通して DB を操作し、SQL を直接書かない。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from megascans_browser.db import connect, init_db

# tags.kind に入る値 (db.py の CHECK 制約と同じ)
TAG_KINDS = ("tag", "color", "industry")


class AssetAlreadyExistsError(Exception):
    """同じ megascans_id のアセットが既に登録されている。"""


class AssetNotFoundError(Exception):
    """指定した megascans_id のアセットが登録されていない。"""


class _Unset:
    """update_asset() で「引数が指定されなかった」ことを表す目印。

    None は「値を消す」という意味で使うので、「変更しない」には別の目印が必要。
    """

    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()


@dataclass(frozen=True)
class AssetFile:
    """アセットに含まれるファイル1つ (テクスチャまたはメッシュ)。"""

    kind: str  # texture / mesh
    rel_path: str  # アセットフォルダからの相対パス
    map_type: str | None = None  # texture: Albedo / Normal ...
    lod: int | None = None  # mesh: 0, 1, 2 ...
    resolution: str | None = None  # 例: 4K


@dataclass(frozen=True)
class AssetRecord:
    """DB から読み出したアセット1件分。"""

    megascans_id: str
    name: str
    asset_type: str
    category: str
    folder_path: Path
    preview_path: Path | None
    average_color: str | None
    metadata: dict[str, Any]
    tags: tuple[str, ...]
    colors: tuple[str, ...]
    industries: tuple[str, ...]
    files: tuple[AssetFile, ...]
    created_at: str
    updated_at: str


class AssetLibrary:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = connect(db_path)
        init_db(self._conn)
        self._depth = 0  # transaction() の入れ子の深さ

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """ブロック内の書き込みを1つのトランザクションにまとめる。

        成功したら COMMIT、例外が出たら ROLLBACK する。入れ子にでき、内側は SAVEPOINT になる
        (内側で失敗したら内側の分だけ取り消す)。
        スキャンのように大量に書き込むときは外側で囲むと、COMMIT が1回で済んで速くなる。
        """

        outermost = self._depth == 0
        savepoint = f"sp{self._depth}"
        self._conn.execute("BEGIN" if outermost else f"SAVEPOINT {savepoint}")
        self._depth += 1
        try:
            yield
        except BaseException:
            if outermost:
                self._conn.rollback()
            else:
                self._conn.execute(f"ROLLBACK TO {savepoint}")
                self._conn.execute(f"RELEASE {savepoint}")
            raise
        else:
            if outermost:
                self._conn.commit()
            else:
                self._conn.execute(f"RELEASE {savepoint}")
        finally:
            self._depth -= 1

    # with AssetLibrary(...) as library: と書くと、ブロックを抜けるときに close() される。
    def __enter__(self) -> AssetLibrary:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def create_asset(
        self,
        megascans_id: str,
        name: str,
        category: str,
        folder_path: str | Path,
        *,
        preview_path: str | Path | None = None,
        average_color: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        tags: Iterable[str] = (),
        colors: Iterable[str] = (),
        industries: Iterable[str] = (),
        files: Iterable[AssetFile] = (),
        exist_ok: bool = False,
    ) -> AssetRecord:
        """アセットと、そのタグ・ファイルをまとめて登録する。

        asset_type は category の先頭から決める (surface/concrete/rough → surface)。
        既に登録済みの場合、exist_ok=True なら全項目を上書きし、False ならエラーにする。
        """

        if self._find_id(megascans_id) is not None:
            if not exist_ok:
                raise AssetAlreadyExistsError(megascans_id)
            # 再スキャン用: 省略された項目も「空」で上書きして、JSON の内容とそろえる
            return self.update_asset(
                megascans_id,
                name=name,
                category=category,
                folder_path=folder_path,
                preview_path=preview_path,
                average_color=average_color,
                metadata=metadata,
                tags=tags,
                colors=colors,
                industries=industries,
                files=files,
            )

        asset_type = category.split("/")[0]

        # 成功したら COMMIT、例外が出たら ROLLBACK する (transaction() を参照)。
        # 途中で失敗しても「アセットだけ登録されてタグがない」状態を残さない。
        with self.transaction():
            cur = self._conn.execute(
                """
                INSERT INTO assets (megascans_id, name, asset_type, category, folder_path,
                                    preview_path, average_color, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    megascans_id,
                    name,
                    asset_type,
                    category,
                    str(folder_path),
                    None if preview_path is None else str(preview_path),
                    average_color,
                    json.dumps(dict(metadata or {}), ensure_ascii=False),
                ),
            )
            asset_id = cur.lastrowid

            for kind, names in (("tag", tags), ("color", colors), ("industry", industries)):
                for tag_name in names:
                    self._add_tag(asset_id, kind, tag_name)
            self._add_files(asset_id, files)

        return self._load(asset_id)

    def get_asset(self, megascans_id: str) -> AssetRecord | None:
        """megascans_id で1件取得する。見つからなければ None。"""

        asset_id = self._find_id(megascans_id)
        return None if asset_id is None else self._load(asset_id)

    # --- 更新・削除 -----------------------------------------------------------

    def update_asset(
        self,
        megascans_id: str,
        *,
        name: str | _Unset = UNSET,
        category: str | _Unset = UNSET,
        folder_path: str | Path | _Unset = UNSET,
        preview_path: str | Path | None | _Unset = UNSET,
        average_color: str | None | _Unset = UNSET,
        metadata: Mapping[str, Any] | None | _Unset = UNSET,
        tags: Iterable[str] | _Unset = UNSET,
        colors: Iterable[str] | _Unset = UNSET,
        industries: Iterable[str] | _Unset = UNSET,
        files: Iterable[AssetFile] | _Unset = UNSET,
    ) -> AssetRecord:
        """指定した項目だけを更新する。省略した項目は変更しない。

        - preview_path / average_color に None を渡すと、値を消す
        - tags / colors / industries / files は、渡したもので丸ごと置き換える
        """

        # 変更する列と値を集める。列名はここに書いた固定の文字列だけなので、
        # f-string で SQL に埋め込んでも安全 (値は ? で渡す)。
        columns: dict[str, object] = {}
        if not isinstance(name, _Unset):
            columns["name"] = name
        if not isinstance(category, _Unset):
            columns["category"] = category
            columns["asset_type"] = category.split("/")[0]
        if not isinstance(folder_path, _Unset):
            columns["folder_path"] = str(folder_path)
        if not isinstance(preview_path, _Unset):
            columns["preview_path"] = None if preview_path is None else str(preview_path)
        if not isinstance(average_color, _Unset):
            columns["average_color"] = average_color
        if not isinstance(metadata, _Unset):
            columns["metadata"] = json.dumps(dict(metadata or {}), ensure_ascii=False)

        with self.transaction():
            asset_id = self._find_id(megascans_id)
            if asset_id is None:
                raise AssetNotFoundError(megascans_id)

            assignments = "".join(f"{column} = ?, " for column in columns)
            self._conn.execute(
                f"UPDATE assets SET {assignments}updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (*columns.values(), asset_id),
            )

            for kind, names in (("tag", tags), ("color", colors), ("industry", industries)):
                if isinstance(names, _Unset):
                    continue
                # その種類の付け外しだけを消して入れ直す (タグ自体は他のアセットと共有なので残す)
                self._conn.execute(
                    """
                    DELETE FROM asset_tags
                    WHERE asset_id = ? AND tag_id IN (SELECT id FROM tags WHERE kind = ?)
                    """,
                    (asset_id, kind),
                )
                for tag_name in names:
                    self._add_tag(asset_id, kind, tag_name)

            if not isinstance(files, _Unset):
                self._conn.execute("DELETE FROM asset_files WHERE asset_id = ?", (asset_id,))
                self._add_files(asset_id, files)

        return self._load(asset_id)

    def delete_asset(self, megascans_id: str) -> bool:
        """DB からアセットを削除する。削除できたら True、見つからなければ False。

        Megascans のファイルやフォルダは消さない (DB の登録だけを消す)。
        タグとファイルの行は ON DELETE CASCADE で一緒に消える。
        """

        with self.transaction():
            cur = self._conn.execute("DELETE FROM assets WHERE megascans_id = ?", (megascans_id,))
        return cur.rowcount > 0

    # --- 検索 -----------------------------------------------------------------

    def find_assets(
        self,
        *,
        name: str | None = None,
        asset_type: str | None = None,
        category: str | None = None,
        tags: Iterable[str] = (),
        colors: Iterable[str] = (),
        industries: Iterable[str] = (),
    ) -> list[AssetRecord]:
        """条件に合うアセットを名前順で返す。条件を指定しなければ全件。

        - 指定した条件はすべて満たすものだけ (AND)
        - name     : 部分一致 (大文字小文字は区別しない)
        - category : そのカテゴリと配下 (surface/concrete → surface/concrete/rough も含む)
        - tags / colors / industries : 指定したものを「全部」持つアセット
        """

        # 条件ごとに SQL の断片と値を追加していき、最後に AND でつなぐ
        conditions: list[str] = []
        params: list[object] = []

        if name:
            conditions.append(r"a.name LIKE ? ESCAPE '\'")
            params.append(f"%{_escape_like(name)}%")
        if asset_type:
            conditions.append("a.asset_type = ?")
            params.append(asset_type)
        if category:
            conditions.append(r"(a.category = ? OR a.category LIKE ? ESCAPE '\')")
            params += [category, _escape_like(category) + "/%"]

        for kind, values in (("tag", tags), ("color", colors), ("industry", industries)):
            # Gray と gray が両方渡されても1つとして数える (HAVING COUNT の数がずれないように)
            wanted = sorted({v.lower() for v in values})
            if not wanted:
                continue
            placeholders = ", ".join("?" for _ in wanted)
            conditions.append(
                f"""
                a.id IN (
                    SELECT at.asset_id
                    FROM asset_tags AS at
                    JOIN tags       AS t ON t.id = at.tag_id
                    WHERE t.kind = ? AND t.name IN ({placeholders})
                    GROUP BY at.asset_id
                    HAVING COUNT(*) = ?
                )
                """
            )
            params += [kind, *wanted, len(wanted)]

        sql = "SELECT a.id FROM assets AS a"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY a.name"

        ids = [row["id"] for row in self._conn.execute(sql, params)]
        return [self._load(asset_id) for asset_id in ids]

    def list_asset_ids(self) -> list[str]:
        """登録済みアセットの megascans_id を一覧する (タグやファイルは読まないので速い)。"""

        rows = self._conn.execute("SELECT megascans_id FROM assets ORDER BY megascans_id")
        return [row["megascans_id"] for row in rows]

    def list_categories(self) -> list[str]:
        """登録済みアセットのカテゴリを一覧する。"""

        rows = self._conn.execute("SELECT DISTINCT category FROM assets ORDER BY category")
        return [row["category"] for row in rows]

    def list_tags(self, kind: str = "tag") -> list[str]:
        """指定した種類 (tag / color / industry) の名前を一覧する。

        どのアセットにも付いていないタグは含めない。
        """

        if kind not in TAG_KINDS:
            raise ValueError(f"Unknown tag kind: {kind!r} (expected one of {TAG_KINDS})")

        rows = self._conn.execute(
            """
            SELECT DISTINCT t.name
            FROM tags AS t
            JOIN asset_tags AS at ON at.tag_id = t.id
            WHERE t.kind = ?
            ORDER BY t.name
            """,
            (kind,),
        )
        return [row["name"] for row in rows]

    # --- 内部用 ---------------------------------------------------------------

    def _find_id(self, megascans_id: str) -> int | None:
        row = self._conn.execute(
            "SELECT id FROM assets WHERE megascans_id = ?", (megascans_id,)
        ).fetchone()
        return None if row is None else row["id"]

    def _add_tag(self, asset_id: int, kind: str, name: str) -> None:
        # タグ自体は全アセットで共有する。既にあれば作らずに id だけ引く。
        self._conn.execute(
            "INSERT INTO tags (kind, name) VALUES (?, ?) ON CONFLICT DO NOTHING", (kind, name)
        )
        tag_id = self._conn.execute(
            "SELECT id FROM tags WHERE kind = ? AND name = ?", (kind, name)
        ).fetchone()["id"]
        # 同じタグが2回渡されても (green と Green など) エラーにしない
        self._conn.execute(
            "INSERT INTO asset_tags (asset_id, tag_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
            (asset_id, tag_id),
        )

    def _add_files(self, asset_id: int, files: Iterable[AssetFile]) -> None:
        self._conn.executemany(
            """
            INSERT INTO asset_files (asset_id, kind, map_type, lod, resolution, rel_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [(asset_id, f.kind, f.map_type, f.lod, f.resolution, f.rel_path) for f in files],
        )

    def _load(self, asset_id: int) -> AssetRecord:
        """assets.id から、タグとファイルも含めた AssetRecord を組み立てる。"""

        row = self._conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        tag_rows = self._conn.execute(
            """
            SELECT t.kind, t.name
            FROM asset_tags AS at
            JOIN tags       AS t ON t.id = at.tag_id
            WHERE at.asset_id = ?
            ORDER BY t.name
            """,
            (asset_id,),
        ).fetchall()
        file_rows = self._conn.execute(
            """
            SELECT kind, rel_path, map_type, lod, resolution
            FROM asset_files
            WHERE asset_id = ?
            ORDER BY rel_path
            """,
            (asset_id,),
        ).fetchall()

        def names_of(kind: str) -> tuple[str, ...]:
            return tuple(r["name"] for r in tag_rows if r["kind"] == kind)

        return AssetRecord(
            megascans_id=row["megascans_id"],
            name=row["name"],
            asset_type=row["asset_type"],
            category=row["category"],
            folder_path=Path(row["folder_path"]),
            preview_path=None if row["preview_path"] is None else Path(row["preview_path"]),
            average_color=row["average_color"],
            metadata=json.loads(row["metadata"]),
            tags=names_of("tag"),
            colors=names_of("color"),
            industries=names_of("industry"),
            files=tuple(
                AssetFile(
                    kind=r["kind"],
                    rel_path=r["rel_path"],
                    map_type=r["map_type"],
                    lod=r["lod"],
                    resolution=r["resolution"],
                )
                for r in file_rows
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _escape_like(text: str) -> str:
    r"""LIKE で特別な意味を持つ % と _ を、ただの文字として扱えるようにする。

    例: "50%" → "50\%" (ESCAPE '\' と組み合わせて使う)
    """

    return text.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
