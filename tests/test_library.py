"""AssetLibrary (API 層) のテスト。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from megascans_browser.library import (
    UNSET,
    AssetAlreadyExistsError,
    AssetFile,
    AssetLibrary,
    AssetNotFoundError,
)

# Megascans の JSON に近い形のサンプル (名前・カテゴリ・タグ・色・業界)
SAMPLES = [
    {
        "megascans_id": "xiwcfassc",
        "name": "Rough Concrete",
        "category": "surface/concrete/rough",
        "tags": ["concrete", "rough", "wall"],
        "colors": ["Gray"],
        "industries": ["VFX", "games"],
    },
    {
        "megascans_id": "ukopbhbqx",
        "name": "Smooth Concrete",
        "category": "surface/concrete/smooth",
        "tags": ["concrete", "smooth"],
        "colors": ["Gray", "Beige"],
        "industries": ["architecture"],
    },
    {
        "megascans_id": "vgvmcgf",
        "name": "Fern",
        "category": "3dplant/fern",
        "tags": ["plant", "fern", "green"],
        "colors": ["Green"],
        "industries": ["VFX", "games"],
    },
    {
        "megascans_id": "rkszw",
        "name": "Mossy Rock",
        "category": "3d/rock/mossy",
        "tags": ["rock", "moss"],
        "colors": ["Green", "Gray"],
        "industries": ["games"],
    },
]

FILES = (
    AssetFile(kind="texture", rel_path="Albedo_4K.jpg", map_type="Albedo", resolution="4K"),
    AssetFile(kind="mesh", rel_path="mesh_LOD0.fbx", lod=0),
)


@pytest.fixture
def library():
    with AssetLibrary(":memory:") as library:
        yield library


@pytest.fixture
def filled(library):
    for sample in SAMPLES:
        library.create_asset(folder_path=f"D:/Megascans/{sample['megascans_id']}", **sample)
    return library


def ids(records) -> list[str]:
    return [r.megascans_id for r in records]


# --- 接続 ---------------------------------------------------------------------


def test_with_block_closes_connection():
    with AssetLibrary(":memory:") as library:
        pass
    with pytest.raises(sqlite3.ProgrammingError):
        library.get_asset("xiwcfassc")


# --- create / get -------------------------------------------------------------


def test_create_asset_returns_record(library):
    record = library.create_asset(
        "xiwcfassc",
        "Rough Concrete",
        "surface/concrete/rough",
        "D:/Megascans/xiwcfassc",
        preview_path="D:/Megascans/xiwcfassc/preview.png",
        average_color="#564E40",
        metadata={"semanticTags": {"theme": ["urban"]}},
        tags=["concrete", "rough"],
        colors=["Gray"],
        industries=["VFX"],
        files=FILES,
    )
    assert record.megascans_id == "xiwcfassc"
    assert record.asset_type == "surface"
    assert record.folder_path == Path("D:/Megascans/xiwcfassc")
    assert record.preview_path == Path("D:/Megascans/xiwcfassc/preview.png")
    assert record.average_color == "#564E40"
    assert record.metadata == {"semanticTags": {"theme": ["urban"]}}
    assert record.tags == ("concrete", "rough")
    assert record.colors == ("Gray",)
    assert record.industries == ("VFX",)
    assert set(record.files) == set(FILES)


def test_create_asset_minimal(library):
    record = library.create_asset("aaa", "A", "3d/rock", "D:/a")
    assert record.preview_path is None
    assert record.metadata == {}
    assert record.tags == ()
    assert record.files == ()


def test_record_is_immutable(library):
    record = library.create_asset("aaa", "A", "3d/rock", "D:/a")
    with pytest.raises(AttributeError):
        record.name = "B"


def test_create_duplicate_raises(library):
    library.create_asset("aaa", "A", "3d/rock", "D:/a")
    with pytest.raises(AssetAlreadyExistsError):
        library.create_asset("aaa", "A", "3d/rock", "D:/a")


def test_create_exist_ok_replaces_everything(library):
    library.create_asset(
        "aaa",
        "Old",
        "3d/rock",
        "D:/a",
        preview_path="D:/a/old.png",
        tags=["old"],
        files=FILES,
    )
    record = library.create_asset("aaa", "New", "3d/stone", "D:/b", tags=["new"], exist_ok=True)
    assert record.name == "New"
    assert record.category == "3d/stone"
    assert record.folder_path == Path("D:/b")
    assert record.preview_path is None  # 省略された項目は空で上書き
    assert record.tags == ("new",)
    assert record.files == ()
    assert len(library.find_assets()) == 1


def test_duplicate_tags_in_input_are_ignored(library):
    record = library.create_asset("aaa", "A", "3d/plant", "D:/a", colors=["Green", "green"])
    assert record.colors == ("Green",)


def test_tags_are_shared_between_assets(library):
    library.create_asset("aaa", "A", "3d/rock", "D:/a", tags=["rock"])
    library.create_asset("bbb", "B", "3d/rock", "D:/b", tags=["Rock"])
    assert library.list_tags() == ["rock"]


def test_create_failure_rolls_back(library):
    broken = AssetFile(kind="video", rel_path="a.mp4")  # CHECK 制約で拒否される
    with pytest.raises(sqlite3.IntegrityError):
        library.create_asset("aaa", "A", "3d/rock", "D:/a", tags=["rock"], files=[broken])
    assert library.get_asset("aaa") is None
    assert library.list_tags() == []


def test_get_unknown_returns_none(library):
    assert library.get_asset("missing") is None


# --- find_assets --------------------------------------------------------------


def test_find_without_conditions_returns_all_sorted_by_name(filled):
    names = [r.name for r in filled.find_assets()]
    assert names == ["Fern", "Mossy Rock", "Rough Concrete", "Smooth Concrete"]


def test_find_by_name_is_partial_and_case_insensitive(filled):
    assert ids(filled.find_assets(name="CONCRETE")) == ["xiwcfassc", "ukopbhbqx"]


def test_find_by_name_escapes_like_wildcards(library):
    library.create_asset("aaa", "50% Gray", "surface/paint", "D:/a")
    library.create_asset("bbb", "500 Gray", "surface/paint", "D:/b")
    library.create_asset("ccc", "a_b", "surface/paint", "D:/c")
    library.create_asset("ddd", "axb", "surface/paint", "D:/d")
    assert ids(library.find_assets(name="50%")) == ["aaa"]
    assert ids(library.find_assets(name="a_b")) == ["ccc"]
    assert len(library.find_assets(name="%")) == 1


def test_find_by_asset_type(filled):
    assert ids(filled.find_assets(asset_type="3dplant")) == ["vgvmcgf"]


def test_find_by_category_includes_children(filled):
    assert ids(filled.find_assets(category="surface/concrete")) == ["xiwcfassc", "ukopbhbqx"]
    assert ids(filled.find_assets(category="surface/concrete/rough")) == ["xiwcfassc"]


def test_find_by_category_does_not_match_prefix_of_name(library):
    library.create_asset("aaa", "A", "3d/rock", "D:/a")
    library.create_asset("bbb", "B", "3d/rocky", "D:/b")
    assert ids(library.find_assets(category="3d/rock")) == ["aaa"]


def test_find_by_tags_requires_all(filled):
    assert ids(filled.find_assets(tags=["concrete"])) == ["xiwcfassc", "ukopbhbqx"]
    assert ids(filled.find_assets(tags=["concrete", "rough"])) == ["xiwcfassc"]
    assert filled.find_assets(tags=["concrete", "plant"]) == []


def test_find_by_tags_ignores_case_and_duplicates(filled):
    assert ids(filled.find_assets(colors=["gray", "GRAY", "Green"])) == ["rkszw"]


def test_find_by_colors_and_industries(filled):
    assert ids(filled.find_assets(colors=["Green"], industries=["VFX"])) == ["vgvmcgf"]


def test_same_name_in_other_kind_does_not_match(filled):
    # "green" はタグとしては Fern に付いているが、色の Green とは別物として扱う
    assert ids(filled.find_assets(tags=["green"])) == ["vgvmcgf"]
    assert ids(filled.find_assets(colors=["green"])) == ["vgvmcgf", "rkszw"]


def test_find_combines_conditions_with_and(filled):
    assert ids(filled.find_assets(asset_type="3d", colors=["Gray"])) == ["rkszw"]
    assert filled.find_assets(asset_type="3d", name="Fern") == []


def test_find_returns_nothing_for_unknown_tag(filled):
    assert filled.find_assets(tags=["unknown"]) == []


# --- list_categories / list_tags ----------------------------------------------


def test_list_categories(filled):
    assert filled.list_categories() == [
        "3d/rock/mossy",
        "3dplant/fern",
        "surface/concrete/rough",
        "surface/concrete/smooth",
    ]


def test_list_tags_by_kind(filled):
    assert filled.list_tags("color") == ["Beige", "Gray", "Green"]
    assert filled.list_tags("industry") == ["architecture", "games", "VFX"]


def test_list_tags_rejects_unknown_kind(library):
    with pytest.raises(ValueError):
        library.list_tags("mood")


def test_list_tags_excludes_unused(library):
    library.create_asset("aaa", "A", "3d/rock", "D:/a", tags=["rock"])
    library.delete_asset("aaa")
    assert library.list_tags() == []


# --- update_asset -------------------------------------------------------------


def test_update_only_given_fields(filled):
    record = filled.update_asset("xiwcfassc", name="Renamed")
    assert record.name == "Renamed"
    assert record.category == "surface/concrete/rough"
    assert record.tags == ("concrete", "rough", "wall")


def test_update_category_also_updates_asset_type(filled):
    record = filled.update_asset("xiwcfassc", category="3d/rock")
    assert record.asset_type == "3d"


def test_update_none_clears_value(library):
    library.create_asset("aaa", "A", "3d/rock", "D:/a", preview_path="D:/a/p.png")
    record = library.update_asset("aaa", preview_path=None, metadata=None)
    assert record.preview_path is None
    assert record.metadata == {}


def test_update_replaces_one_tag_kind_only(filled):
    record = filled.update_asset("xiwcfassc", colors=["Brown"])
    assert record.colors == ("Brown",)
    assert record.tags == ("concrete", "rough", "wall")
    assert record.industries == ("games", "VFX")


def test_update_replaces_files(library):
    library.create_asset("aaa", "A", "3d/rock", "D:/a", files=FILES)
    new_file = AssetFile(kind="mesh", rel_path="mesh_LOD1.fbx", lod=1)
    record = library.update_asset("aaa", files=[new_file])
    assert record.files == (new_file,)


def test_update_without_fields_keeps_values(filled):
    before = filled.get_asset("xiwcfassc")
    after = filled.update_asset("xiwcfassc")
    assert after.name == before.name
    assert after.tags == before.tags


def test_update_unknown_raises(library):
    with pytest.raises(AssetNotFoundError):
        library.update_asset("missing", name="X")


def test_unset_repr():
    assert repr(UNSET) == "UNSET"


# --- delete_asset -------------------------------------------------------------


def test_delete_asset(filled):
    assert filled.delete_asset("xiwcfassc") is True
    assert filled.get_asset("xiwcfassc") is None
    assert len(filled.find_assets()) == 3


def test_delete_unknown_returns_false(library):
    assert library.delete_asset("missing") is False


def test_delete_does_not_touch_files(tmp_path):
    folder = tmp_path / "asset"
    folder.mkdir()
    (folder / "Albedo_4K.jpg").write_bytes(b"")
    with AssetLibrary(tmp_path / "library.db") as library:
        library.create_asset("aaa", "A", "surface/x", folder, files=FILES[:1])
        library.delete_asset("aaa")
    assert (folder / "Albedo_4K.jpg").exists()


def test_list_asset_ids(filled):
    assert filled.list_asset_ids() == ["rkszw", "ukopbhbqx", "vgvmcgf", "xiwcfassc"]


# --- transaction --------------------------------------------------------------


def test_transaction_rolls_back_everything_on_error(library):
    with pytest.raises(RuntimeError), library.transaction():
        library.create_asset("aaa", "A", "3d/rock", "D:/a")
        library.create_asset("bbb", "B", "3d/rock", "D:/b")
        raise RuntimeError
    assert library.list_asset_ids() == []


def test_transaction_commits_all(tmp_path):
    db_path = tmp_path / "library.db"
    with AssetLibrary(db_path) as library, library.transaction():
        library.create_asset("aaa", "A", "3d/rock", "D:/a")
        library.create_asset("bbb", "B", "3d/rock", "D:/b")
    with AssetLibrary(db_path) as library:
        assert library.list_asset_ids() == ["aaa", "bbb"]


def test_failed_inner_operation_is_undone_but_outer_continues(library):
    broken = AssetFile(kind="video", rel_path="a.mp4")
    with library.transaction():
        library.create_asset("aaa", "A", "3d/rock", "D:/a")
        with pytest.raises(sqlite3.IntegrityError):
            library.create_asset("bbb", "B", "3d/rock", "D:/b", tags=["rock"], files=[broken])
    assert library.list_asset_ids() == ["aaa"]
    assert library.list_tags() == []
