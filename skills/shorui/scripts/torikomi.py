"""社長が伝えた外の場所から書類を取り込む道具（SPEC F5、DESIGN 4.7。TASKS B10）。中身は lib/torikomi.py。

使い方（する事の後に、--folder "${CLAUDE_PROJECT_DIR}" を付ける。なければ今いるフォルダ）：
  python3 -B <この場所>/torikomi.py list
      社長の直前の発言にあった外の場所を、番号つきで出す（フォルダなら、すぐ下のファイルの名前も）。
  python3 -B <この場所>/torikomi.py import --number <番号> [--name <フォルダの中のファイルの名前>]
      その場所の書類を 入れ口/取り込み/<今日>/ に写す（元のファイルは変えない）。結果は JSON。

- 外の場所は、社長が発言で伝えたものだけを受け付ける（社長が送ったときの hook が控える）。コマンドには外の場所を書かない。
- 終了コード：0 できた、1 補助プログラムを読み込めない、2 しなかった（伝えられていない、番号が違う など。何も写していない）。
"""

import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

from lib import company  # noqa: E402


def parse(argv):
    parser = argparse.ArgumentParser(description="社長が伝えた外の場所から、書類を会社のフォルダに写して取り込む")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("list", parents=[common], help="社長の直前の発言にあった外の場所を出す")
    p = sub.add_parser("import", parents=[common], help="控えた場所の書類を、入れ口/取り込み/ に写す")
    p.add_argument("--number", type=int, required=True, help="list の番号")
    p.add_argument("--name", default="", help="フォルダの中のファイルの名前（なければ、すぐ下の書類をすべて）")
    return parser.parse_args(argv)


def main(argv) -> int:
    args = parse(argv)
    if not args.command:
        print("する事（list・import）を指定してください。")
        return 2
    folder = company.company_folder(args.folder) if args.folder else company.company_folder()
    if folder is None:
        print(f"{args.folder or company.project_dir()} は会社のフォルダではありません（目印の .hojokin/ がありません）。何もしていません。")
        return 2
    try:
        from lib import torikomi
    except Exception as e:
        print(f"補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。何もしていません。")
        return 1
    try:
        if args.command == "list":
            found = torikomi.listing(folder)
            print(json.dumps({"社長が伝えた場所": found,
                              "説明": "取り込むときは import --number <番号>。場所がなければ、社長に場所を伝えてもらう"},
                             ensure_ascii=False, indent=1))
        else:
            done = torikomi.import_from(folder, args.number, args.name)
            print(json.dumps({"結果": "取り込みました。続けて seiri.py の scan で整理してください", "取り込んだもの": done},
                             ensure_ascii=False, indent=1))
    except torikomi.TorikomiError as e:
        print(f"{e}")
        return 2
    except OSError as e:
        print(f"ファイルを扱えませんでした（{e}）。何も取り込んでいないか、途中までです。")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
