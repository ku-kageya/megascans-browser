from __future__ import annotations

import argparse
import time


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="megascans-browser")
    commands = parser.add_subparsers(dest="command", required=True)

    scan_parser = commands.add_parser("scan", help="Downloaded フォルダを読んで DB を更新する")
    scan_parser.add_argument(
        "root", help=r"Downloaded フォルダ (例: Z:\Assets\Megascans\Downloaded)"
    )
    scan_parser.add_argument(
        "--db", default="megascans.db", help="DB ファイル (既定: megascans.db)"
    )

    args = parser.parse_args(argv)
    if args.command == "scan":
        _run_scan(args.root, args.db)


def _run_scan(root: str, db_path: str) -> None:
    # 重い import はコマンドが決まってから行う
    from megascans_browser.library import AssetLibrary
    from megascans_browser.scanner import scan

    start = time.perf_counter()
    with AssetLibrary(db_path) as library:
        result = scan(library, root)
    elapsed = time.perf_counter() - start

    print(
        f"追加 {len(result.added)} / 更新 {len(result.updated)} / 削除 {len(result.removed)}"
        f" / エラー {len(result.errors)} ({elapsed:.1f} 秒)"
    )
    for label, reason in result.errors:
        print(f"  ! {label}: {reason}")
