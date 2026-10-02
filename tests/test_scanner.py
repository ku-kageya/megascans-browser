"""scanner のテスト。tmp_path に assetsData.json だけを置いた偽の Downloaded フォルダを使う。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from megascans_browser.library import AssetLibrary
from megascans_browser.scanner import clean_names, normalize_category, scan


def make_entry(megascans_id: str, **overrides) -> dict:
    """実際の assetsData.json の1項目に近い形 (必要な項目だけ)。"""

    entry = {
        "id": megascans_id,
        "name": "Smooth Concrete",
        "type": "surface",
        "categories": ["surface", "concrete", "smooth", "base"],
        "tags": ["grey", "gray", " dark", " black", " dirty", " ", "archviz"],
        "semanticTags": {"color": ["gray"], "industry": ["games", "VFX"], "theme": ["dirty"]},
        "averageColor": "#6D6B5C",
        "path": ["surface", f"concrete_smooth_{megascans_id}"],
        "preview": ["surface", f"concrete_smooth_{megascans_id}", f"{megascans_id}_Preview.png"],
        "meta": [{"key": "tileable", "name": "Tileable", "value": True}],
        "environment": {"biome": "none", "region": "none"},
        "properties": [],
        "assetCategories": {"surface": {"concrete": {"smooth": {}}}},
        "searchStr": "smooth concrete surface",
    }
    entry.update(overrides)
    return entry


def write_index(root: Path, entries: list) -> None:
    (root / "assetsData.json").write_text(json.dumps(entries), encoding="utf-8")


@pytest.fixture
def library():
    with AssetLibrary(":memory:") as library:
        yield library


def test_scan_registers_entry(library, tmp_path):
    write_index(tmp_path, [make_entry("pjtwu0")])

    result = scan(library, tmp_path)

    assert result.added == ["pjtwu0"]
    record = library.get_asset("pjtwu0")
    assert record.name == "Smooth Concrete"
    assert record.asset_type == "surface"
    assert record.category == "surface/concrete/smooth/base"
    assert record.folder_path == tmp_path / "surface" / "concrete_smooth_pjtwu0"
    assert record.preview_path == tmp_path / "surface/concrete_smooth_pjtwu0/pjtwu0_Preview.png"
    assert record.average_color == "#6D6B5C"
    assert set(record.tags) == {"grey", "gray", "dark", "black", "dirty", "archviz"}
    assert record.colors == ("gray",)
    assert set(record.industries) == {"games", "VFX"}


def test_scan_keeps_only_selected_metadata(library, tmp_path):
    write_index(tmp_path, [make_entry("pjtwu0")])
    scan(library, tmp_path)
    metadata = library.get_asset("pjtwu0").metadata
    assert metadata["semanticTags"]["theme"] == ["dirty"]
    assert metadata["environment"] == {"biome": "none", "region": "none"}
    assert "searchStr" not in metadata


def test_scan_twice_gives_same_result(library, tmp_path):
    write_index(tmp_path, [make_entry("pjtwu0"), make_entry("oecco0")])
    scan(library, tmp_path)
    before = library.get_asset("pjtwu0")

    result = scan(library, tmp_path)

    assert result.added == []
    assert sorted(result.updated) == ["oecco0", "pjtwu0"]
    after = library.get_asset("pjtwu0")
    assert (after.name, after.tags, after.colors) == (before.name, before.tags, before.colors)


def test_scan_applies_changes_in_index(library, tmp_path):
    write_index(tmp_path, [make_entry("pjtwu0")])
    scan(library, tmp_path)

    write_index(tmp_path, [make_entry("pjtwu0", name="Renamed", tags=["new"])])
    scan(library, tmp_path)

    record = library.get_asset("pjtwu0")
    assert record.name == "Renamed"
    assert record.tags == ("new",)


def test_scan_removes_assets_missing_from_index(library, tmp_path):
    write_index(tmp_path, [make_entry("pjtwu0"), make_entry("oecco0")])
    scan(library, tmp_path)

    write_index(tmp_path, [make_entry("pjtwu0")])
    result = scan(library, tmp_path)

    assert result.removed == ["oecco0"]
    assert library.list_asset_ids() == ["pjtwu0"]


def test_scan_skips_broken_entry_and_continues(library, tmp_path):
    broken = make_entry("broken")
    del broken["categories"]
    write_index(tmp_path, [broken, make_entry("pjtwu0"), "not a dict"])

    result = scan(library, tmp_path)

    assert result.added == ["pjtwu0"]
    assert [label for label, _ in result.errors] == ["broken", "#2"]


def test_broken_entry_does_not_delete_previous_registration(library, tmp_path):
    write_index(tmp_path, [make_entry("pjtwu0")])
    scan(library, tmp_path)

    write_index(tmp_path, [make_entry("pjtwu0", name="")])
    result = scan(library, tmp_path)

    assert result.removed == []
    assert library.get_asset("pjtwu0").name == "Smooth Concrete"


def test_scan_without_preview(library, tmp_path):
    write_index(tmp_path, [make_entry("pjtwu0", preview=None, averageColor="")])
    scan(library, tmp_path)
    record = library.get_asset("pjtwu0")
    assert record.preview_path is None
    assert record.average_color is None


def test_scan_without_index_raises(library, tmp_path):
    with pytest.raises(FileNotFoundError):
        scan(library, tmp_path)


def test_normalize_category():
    assert normalize_category(["3d", "Nature", "Rock"]) == "3d/nature/rock"
    assert normalize_category([" surface ", "", "Asphalt"]) == "surface/asphalt"


def test_clean_names():
    assert clean_names(["grey", " dark", " ", "", "Games", "games", 3]) == ("grey", "dark", "Games")
    assert clean_names(None) == ()
