# asset_browser_kit

`asset_browser.py`（Megascans 用ブラウザ）の UI を、データ構造から切り離して再利用できる形にまとめた PySide6 パッケージです。見た目と操作感（左レール／検索／キーワードチップ／仮想グリッド／詳細モーダル／お気に入り）はそのままに、「何を並べるか」と「押したら何をするか」を差し替えられます。

## 構成

```
asset_browser_kit/
  model.py       BrowserItem / CategoryDef / ItemAction（UI が知るのはこの3つだけ）
  sources.py     ItemSource（基底）, FolderSource, StaticSource, JsonCache
  favorites.py   FavoritesStore（JSON 永続化）
  thumbnails.py  非同期サムネ読み込み + LRU + プレースホルダー描画
  widgets.py     FlowLayout / ItemCard / VirtualGrid / DetailDialog / 既定アクション / D&D
  browser.py     AssetBrowser（上記を組み合わせた完成形 QWidget）
  theme.py       Theme（配色）/ Texts（文言）/ スタイルシート生成
  icons.py       レール用線画アイコン
  app.py         スタンドアロン起動ヘルパー（ログ抑制・ログファイル）
examples/
  megascans_browser.py      元ツールと同等の構成を再現
  prop_library_browser.py   ファイル単位のプロップライブラリ（サイドカー JSON 対応）
  houdini_python_panel.py   Houdini の Python Panel に埋め込む例
```

## 最小コード

```python
from asset_browser_kit import AssetBrowser, FolderSource, CategoryDef
from asset_browser_kit.app import run_standalone

src = FolderSource("D:/library", [
    CategoryDef("props", "Props", icon="box", folders=["props"]),
    CategoryDef("trees", "Trees", icon="plant", folders=["trees"], placeholder="plant"),
], item_kind="file", file_exts=[".usd", ".bgeo.sc"])

run_standalone(lambda: AssetBrowser(src), title="Library")
```

## 差し替えポイント

**データ（ItemSource）** — `categories()` と `load(category, force)` を実装すれば何でも並べられます。`load` はワーカースレッドで呼ばれるので、DB・USD ステージ・ShotGrid などの重い問い合わせもそのまま書けます（ウィジェットには触らないこと）。用意済みのものは次の3つです。

- `FolderSource` — `item_kind="dir"`（フォルダ＝1アイテム）か `"file"`（ファイル＝1アイテム、同名画像や `*_preview` / `*_thumb` をサムネに使用。`file_exts` を空にすると画像自体をアイテム化）。`preview_pattern="{id}_Preview.png"` を指定するとフォルダ内を列挙せずパスを組み立てるので、ネットワークドライブで速くなります。`id_fn` / `name_fn` / `meta_fn` で ID・表示名・詳細項目を自由に決められます。
- `StaticSource` — リストをそのまま表示（デモ、他ツールからの受け渡し）。
- `JsonCache` — 一覧キャッシュ。ライブラリ直下（チーム共有）→ユーザー領域の順に書き、読むときは新しい方を使います。

**アクション（ItemAction）** — 詳細ダイアログのボタン。`callback(item)` が文字列を返すとボタンに1.5秒表示されます。`actions=None` なら「フォルダーを開く」「パスをコピー」が既定。

```python
ItemAction("Houdini に読み込む", import_fn, primary=True, close_after=True)
```

**シグナル** — `item_activated(item)` / `favorite_changed(item, bool)` / `items_loaded(list)` / `category_changed(str)`。`detail_dialog=False` にすればクリック時はシグナルだけ出し、自前のプロパティパネル等に繋げます。

**見た目・文言** — `Theme(accent="#f39c12", ...)`、`Texts(search_placeholder=..., count="{n} items")`。`Theme.extra_qss` で QSS を追記できます。

**その他のオプション** — `thumb_size`、`zoom`（サムネサイズスライダー、`(min, max)` 指定可）、`keywords`（チップ。`False` で非表示、関数で独自抽出）、`match_fn`（検索ロジック）、`drag`（`False` / 独自 MIME 関数）、`favorites`（`False` / 任意の `FavoritesStore`）、`show_badge`、`logo_text`。

## ドラッグ＆ドロップ

カードをドラッグすると、ファイル URL・テキスト（パス）・アイテム JSON（`MIME_TYPE`）が載ります。受け側では `item_from_mime(event.mimeData())` で `BrowserItem` に戻せます。クリック判定はドラッグと区別するためマウスを離した時点に変更しています。

## DCC への埋め込み

`AssetBrowser` は `QWidget` で、スタイルシートは `QApplication` ではなくこのウィジェットにだけ適用されます。設定・お気に入りの保存先も `applicationName` に依存しない場所（`GenericConfigLocation/<app_name>`）なので、Houdini や Maya のパネルに入れてもホスト側の UI や設定を汚しません。詳細モーダルは親ウィジェットの範囲を覆い、狭いペインでは縦並びに切り替わります。PySide6 を同梱するバージョンの DCC が前提です。

## 元コードからの主な変更

| 元 | 今 |
|---|---|
| `Asset`（type/resolution/formats 固定） | `BrowserItem`（category + 任意の `meta` / `tags` / `data`） |
| `CATEGORY_MAP` / `scan_library` 直書き | `CategoryDef` + `FolderSource`（または独自 `ItemSource`） |
| `QMainWindow` 内に全ロジック | `AssetBrowser(QWidget)` + 部品単体でも利用可 |
| `app.setStyleSheet(STYLE)` | ウィジェット単位の QSS（`Theme` から生成） |
| QThread をウィンドウごとに生成 | 共有 `QThreadPool` + 世代番号（読み込み中にウィジェットを閉じても安全） |
| サムネ 512×256 固定 | `thumb_size` + ズームスライダー |
| ボタン2つ固定 | `ItemAction` で任意に追加 |
| お気に入りキー＝ID | `カテゴリ:ID`（カテゴリをまたいだ衝突を防止） |
| キャッシュはライブラリ側を優先 | 新しい方を優先（共有側が古いまま固定される問題を解消） |

お気に入り・キャッシュの保存形式が変わったため、元ツールのファイルは引き継がれません（初回のみ再登録・再スキャンになります）。
