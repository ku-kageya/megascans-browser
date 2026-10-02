"""配色・文言の設定。スタイルシートは QApplication ではなくブラウザウィジェットに
適用するので、Houdini / Maya などホスト側の UI には影響しない。"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from string import Template


@dataclass
class Theme:
    font_family: str = ('"Segoe UI","Helvetica Neue","Hiragino Kaku Gothic ProN",'
                        '"Noto Sans JP",sans-serif')
    bg: str = "#0d0d0d"
    rail: str = "#161616"
    sheet: str = "#181818"
    surface: str = "#1d1d1d"
    surface_hover: str = "#262626"
    control: str = "#242424"
    control_hover: str = "#2f2f2f"
    border: str = "#232323"
    border_strong: str = "#2c2c2c"
    border_hover: str = "#3a3a3a"
    text: str = "#ededed"
    text_sub: str = "#b7b7b7"
    text_dim: str = "#9a9a9a"
    text_mute: str = "#5f5f5f"
    accent: str = "#2b9bf4"
    accent_hover: str = "#1c86db"
    accent_text: str = "#05233b"
    accent_soft: str = "#123247"
    accent_soft_text: str = "#7fc7ff"
    favorite: str = "#ff5a7a"
    thumb_bg: str = "#0a0a0a"
    logo_from: str = "#3aa9ff"
    logo_to: str = "#1c7fd6"
    logo_text: str = "#06263f"
    icon: str = "#c6c6c6"
    extra_qss: str = ""          # 追加の QSS（末尾に連結）


@dataclass
class Texts:
    """UI 文言。多言語化やツールごとの言い回し変更はここを差し替える。"""
    search_placeholder: str = "\U0001F50D  検索…"
    favorites: str = "Favorites"
    favorites_title: str = "お気に入り"
    count: str = "{n} 件"
    loading: str = "読み込み中…"
    refresh: str = "更新"
    refresh_tip: str = "再スキャンしてインデックスを更新"
    change_root: str = "パスを変更"
    choose_root: str = "ライブラリのルートを選択"
    zoom_tip: str = "サムネイルサイズ"
    empty_filter: str = "「{cond}」に一致するアイテムがありません。"
    empty_favorites: str = ("お気に入りに登録されたアイテムはまだありません。\n"
                            "カード右上の ♡ から登録できます。")
    empty_category: str = ("{category} が見つかりませんでした。\n"
                           "「パスを変更」でライブラリのルートを選んでください。")
    load_error: str = "読み込みに失敗しました。\n{error}"
    spec_category: str = "カテゴリ"
    spec_id: str = "ID"
    spec_path: str = "パス"
    open_folder: str = "フォルダーを開く"
    opened: str = "開きました"
    not_found: str = "パスが見つかりません"
    copy_path: str = "パスをコピー"
    copied: str = "コピーしました"


_QSS = Template("""
* { font-family:$font_family; }
QWidget#AssetBrowser, QWidget#abContent, QWidget#abTagbar { background:$bg; }
QFrame#abRail { background:$rail; border-right:1px solid $border; }
QFrame#abRailSep { background:#2a2a2a; max-width:48px; }
QLabel#abLogo {
    background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 $logo_from, stop:1 $logo_to);
    border-radius:9px; color:$logo_text; font-size:18px; font-weight:800; }
QToolButton#abCat {
    background:transparent; border:none; border-radius:8px;
    border-left:3px solid transparent; color:$text_dim; font-size:10px; padding-top:4px; }
QToolButton#abCat:hover { background:#202020; color:#e6e6e6; }
QToolButton#abCat:checked { background:#1e1e1e; color:#ffffff; border-left:3px solid $accent; }

QLineEdit#abSearch {
    background:$surface; border:1px solid $border_strong; border-radius:21px;
    padding:0 16px; min-height:40px; color:$text; font-size:14px; }
QLineEdit#abSearch:focus { border-color:$border_hover; }

QLabel#abTitle { color:#8c8c8c; font-size:12px; font-weight:600; letter-spacing:2px; }
QLabel#abPath { color:$text_sub; font-size:12px; background:#171717;
    border:1px solid $border; border-radius:5px; padding:4px 9px; }
QLabel#abCount { color:$text_mute; font-size:12px; padding:0 6px; }
QPushButton#abGhostSm { background:transparent; border:1px solid $border_strong;
    border-radius:6px; color:$text_dim; padding:6px 12px; font-size:12px; }
QPushButton#abGhostSm:hover { color:$text; border-color:$border_hover; }
QSlider#abZoom::groove:horizontal { height:3px; background:$border_strong; border-radius:1px; }
QSlider#abZoom::sub-page:horizontal { background:$accent; border-radius:1px; }
QSlider#abZoom::handle:horizontal { background:$text_sub; width:12px; height:12px;
    margin:-5px 0; border-radius:6px; }

QScrollArea#abScroll { background:$bg; border:none; }
QWidget#abHolder { background:$bg; }
QPushButton#abChip { background:#1b1b1b; border:1px solid $border_strong; border-radius:13px;
    color:#b8b8b8; font-size:12px; padding:4px 12px; }
QPushButton#abChip:hover { color:$text; border-color:$border_hover; }
QPushButton#abChip:checked { background:$accent_soft; border:1px solid $accent;
    color:$accent_soft_text; }
QLabel#abGroupHeader { color:#cfcfcf; font-size:14px; font-weight:700;
    letter-spacing:1px; padding:10px 2px 0 2px; }
QScrollBar:vertical { background:$bg; width:11px; margin:0; }
QScrollBar::handle:vertical { background:#2a2a2a; border-radius:5px; min-height:40px; }
QScrollBar::handle:vertical:hover { background:#383838; }
QScrollBar::add-line, QScrollBar::sub-line { height:0; }
QScrollBar::add-page, QScrollBar::sub-page { background:none; }

QFrame#abCard { background:$surface; border:1px solid $border; border-radius:8px; }
QFrame#abCard:hover { background:$surface_hover; border-color:$border_hover; }
QWidget#abThumbWrap { background:$thumb_bg; border-top-left-radius:8px;
    border-top-right-radius:8px; }
QLabel#abBadge { background:rgba(0,0,0,150); color:#dcdcdc; font-size:10px;
    padding:2px 7px; border-radius:4px; }
QToolButton#abHeart { background:rgba(0,0,0,120); border:none; border-radius:14px;
    font-size:15px; color:#e8e8e8; }
QToolButton#abHeart:hover { background:rgba(0,0,0,190); }
QToolButton#abHeart[fav="true"] { color:$favorite; }
QLabel#abName { color:#e8e8e8; font-size:13px; }
QLabel#abSub { color:$text_mute; font-size:11px; }
QLabel#abEmpty { color:$text_mute; font-size:14px; padding:80px 20px; }

QDialog#abDetail { background:transparent; }
QFrame#abSheet { background:$sheet; border:1px solid $border_strong; border-radius:12px; }
QLabel#abPreview { background:$thumb_bg; border-top-left-radius:12px;
    border-bottom-left-radius:12px; }
QLabel#abPreviewTop { background:$thumb_bg; border-top-left-radius:12px;
    border-top-right-radius:12px; }
QWidget#abDetailBody, QScrollArea#abSpecScroll, QWidget#abSpecs { background:transparent; }
QLabel#abDType { color:$accent; font-size:11px; font-weight:700; letter-spacing:2px; }
QLabel#abDName { color:#f2f2f2; font-size:22px; font-weight:600; }
QLabel#abK { color:#8c8c8c; font-size:13px; }
QLabel#abV { color:#e0e0e0; font-size:13px; }
QLabel#abVMono { color:$text_sub; font-size:11px; }
QFrame#abLine { background:$border; }
QToolButton#abClose { background:rgba(30,30,30,180); border:none; border-radius:8px;
    color:#cfcfcf; font-size:18px; }
QToolButton#abClose:hover { background:#333; color:#fff; }
QPushButton#abPrimary { background:$accent; color:$accent_text; border:none;
    border-radius:8px; min-height:42px; padding:0 16px; font-size:13px; font-weight:700; }
QPushButton#abPrimary:hover { background:$accent_hover; }
QPushButton#abGhost { background:$control; color:#d6d6d6; border:none;
    border-radius:8px; min-height:42px; padding:0 16px; font-size:13px; font-weight:600; }
QPushButton#abGhost:hover { background:$control_hover; }
QToolButton#abFavBtn { background:$control; border:none; border-radius:8px;
    font-size:19px; color:#cfcfcf; }
QToolButton#abFavBtn:hover { background:$control_hover; }
QToolButton#abFavBtn[fav="true"] { color:$favorite; }
""")


def build_stylesheet(theme: Theme) -> str:
    return _QSS.substitute(asdict(theme)) + "\n" + theme.extra_qss
