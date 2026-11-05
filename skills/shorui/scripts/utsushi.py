"""原本から写しを作る道具（SPEC F5、DESIGN 4.5・14章。TASKS B10）。中身は lib/utsushi.py。

使い方（する事の後に、--folder "${CLAUDE_PROJECT_DIR}" を付ける。なければ今いるフォルダ）：
  python3 -B <この場所>/utsushi.py make --original <原本の場所か id> [--original <2つ目>] --case <案件> --stage <段階>
                                       [--document <制度データの書類の名前>] [--name <写しの名前>]
      原本から、案件の 段階/添付する書類/ に写しを作る（提出するファイルの決まりに合わせて PDF にする・つなぐ）。
      結果は JSON（台帳の写しの1件。整え方と注意を含む）。
  python3 -B <この場所>/utsushi.py stale
      古い原本から作った写し（同じ種類の新しい原本が入ったもの）を、案件ごとに JSON で出す。何も変えない。
  python3 -B <この場所>/utsushi.py remake --copy <写しの場所か id>
      写しを、新しくなった原本で作り直す（同じ場所・同じ名前。古い原本は消さない）。
  python3 -B <この場所>/utsushi.py list
      台帳の写しの一覧を JSON で出す。

- 終了コード：0 できた、1 補助プログラムを読み込めない、2 しなかった（原本でない、段階のフォルダがない、
  PDF にできない など）。2 のとき、写しも台帳も変えていない。
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
    parser = argparse.ArgumentParser(description="原本から、案件の添付する書類に写しを作る")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    sub = parser.add_subparsers(dest="command")
    p = sub.add_parser("make", parents=[common], help="原本から写しを作る")
    p.add_argument("--original", action="append", default=[], help="原本の場所か id（つなぐときは2回以上）")
    p.add_argument("--case", required=True, help="案件の名前（案件/ の下のフォルダの名前）")
    p.add_argument("--stage", required=True, help="段階のフォルダ（1_申請 など。効果報告は 4_効果報告/1年目）")
    p.add_argument("--document", default="", help="制度データの書類の名前（形式の決まりを引く。なければ原本の種類）")
    p.add_argument("--name", default="", help="写しの名前（拡張子なし。なければ原本の名前）")
    sub.add_parser("stale", parents=[common], help="古い原本から作った写しを出す")
    p = sub.add_parser("remake", parents=[common], help="写しを、新しくなった原本で作り直す")
    p.add_argument("--copy", required=True, help="写しの場所か id")
    sub.add_parser("list", parents=[common], help="台帳の写しの一覧を出す")
    return parser.parse_args(argv)


def _print_json(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=1))


def main(argv) -> int:
    args = parse(argv)
    if not args.command:
        print("する事（make・stale・remake・list）を指定してください。")
        return 2
    folder = company.company_folder(args.folder) if args.folder else company.company_folder()
    if folder is None:
        print(f"{args.folder or company.project_dir()} は会社のフォルダではありません（目印の .hojokin/ がありません）。何もしていません。")
        return 2
    try:
        from lib import history  # noqa: F401  同梱の dulwich（版の履歴）が読めるか
        from lib import seiri, utsushi
    except Exception as e:
        print(f"補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。何もしていません。")
        return 1
    try:
        if args.command == "make":
            entry = utsushi.make(folder, args.original, args.case, args.stage, args.document, args.name)
            _print_json({"結果": "写しを作りました", "写し": entry})
        elif args.command == "stale":
            found = utsushi.stale(folder)
            _print_json({"作り直す写し": found, "数": len(found)})
        elif args.command == "remake":
            entry = utsushi.remake(folder, args.copy)
            _print_json({"結果": "写しを作り直しました（古い原本は残しています）", "写し": entry})
        elif args.command == "list":
            _print_json(utsushi.copies(seiri.load_ledger(folder)))
    except (utsushi.UtsushiError, seiri.SeiriError) as e:
        print(f"{e}")
        return 2
    except OSError as e:
        print(f"ファイルを扱えませんでした（{e}）。")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
