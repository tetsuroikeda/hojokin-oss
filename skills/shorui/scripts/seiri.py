"""書類を整理する道具（SPEC F5、DESIGN 4.5・5章・6章。TASKS M4）。

入れ口などの書類を中身のハッシュで見つけ、原本の置き場へ移して決まった形の名前にし、書類の台帳に残す。
何の書類か（種類・日付・相手先・区分）は Claude が読み取って引数で渡す。道具は推測しない。

使い方（する事の後に、--folder "${CLAUDE_PROJECT_DIR}" を付ける。なければ今いるフォルダ）：
  python3 -B <この場所>/seiri.py scan
      入れ口（下のフォルダも）と、原本の置き場のうち台帳にない書類を見つける。結果は JSON
      （新しい書類、同じ中身、確かめ済みで出さなかった数）。何も変えない。
  python3 -B <この場所>/seiri.py text --path <場所> [--limit 4000]
      書類の文字を出す（PDF・Word・Excel）。写真と、文字のない PDF は、Read で開くよう案内する。
  python3 -B <この場所>/seiri.py organize --path <場所> --category <区分> --kind <種類> --date <日付>
                                         [--partner <相手先>] [--note <補足>]
      1つの書類を 原本/<区分>/<日付>_<種類>[_<相手先>][_<補足>].<拡張子> に移し、読み取り専用にして台帳に残す。
      結果は JSON（台帳の1件。元の場所と新しい場所を含む）。
  python3 -B <この場所>/seiri.py keep --path <場所> --reason "<理由>"
      動かさずに確かめた書類として台帳に残す（次から scan に出さない。中身が変われば、また出す）。
  python3 -B <この場所>/seiri.py list
      台帳の原本の一覧を JSON で出す。

- 場所は、会社のフォルダからの場所（例：入れ口/scan0001.pdf）か、中の絶対の場所。
- 区分は、登記・名簿／決算・税／見積・契約・請求／役所からの通知／会社の資料／写真・カタログ のどれか。
- 日付は「2026-10-20」の形（年だけの書類は「2026」、月までなら「2026-10」）。
- 終了コード：0 できた、1 補助プログラムを読み込めない、
  2 しなかった（会社のフォルダでない、台帳が読めない、引数が違う、同じ名前・同じ中身の原本がある など）。
  2 のとき、書類も台帳も変えていない。
"""

import sys

# 会社のフォルダやプラグインの場所に __pycache__ を書かない
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

from lib import company  # noqa: E402


def parse(argv):
    parser = argparse.ArgumentParser(description="書類を見つけ、原本の置き場へ移して決まった形の名前にし、台帳に残す")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("scan", parents=[common], help="入れ口などの新しい書類を、中身のハッシュで見つける")

    p = sub.add_parser("text", parents=[common], help="書類の文字を出す")
    p.add_argument("--path", required=True, help="書類の場所")
    p.add_argument("--limit", type=int, default=4000, help="出す字数の上限")

    p = sub.add_parser("organize", parents=[common], help="書類を原本の置き場へ移し、決まった形の名前にして台帳に残す")
    p.add_argument("--path", required=True, help="書類の場所")
    p.add_argument("--category", required=True, help="原本の区分")
    p.add_argument("--kind", required=True, help="書類の種類（見積書、決算書、履歴事項全部証明書 など）")
    p.add_argument("--date", required=True, help="書類にある日付（2026-10-20 の形。年だけなら 2026）")
    p.add_argument("--partner", default="", help="相手先（見積書・請求書を出した会社など。なければ省く）")
    p.add_argument("--note", default="", help="同じ名前の原本と見分ける言葉（機械の名前 など）")

    p = sub.add_parser("keep", parents=[common], help="動かさずに確かめた書類として台帳に残す")
    p.add_argument("--path", required=True, help="書類の場所")
    p.add_argument("--reason", default="", help="動かさない理由（社長の答え など）")

    sub.add_parser("list", parents=[common], help="台帳の原本の一覧を出す")
    return parser.parse_args(argv)


def _print_json(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=1))


def main(argv) -> int:
    args = parse(argv)
    if not args.command:
        print("する事（scan・text・organize・keep・list）を指定してください。")
        return 2
    folder = company.company_folder(args.folder) if args.folder else company.company_folder()
    if folder is None:
        where = args.folder or str(company.project_dir())
        print(f"{where} は会社のフォルダではありません（目印の .hojokin/ がありません）。何もしていません。")
        return 2
    try:
        from lib import seiri
    except Exception as e:  # 同梱のライブラリが欠けたなど
        print(f"補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。何もしていません。")
        return 1
    try:
        if args.command == "scan":
            _print_json(seiri.scan(folder).as_dict())
        elif args.command == "text":
            print(seiri.text_of(folder, args.path, max(args.limit, 200)))
        elif args.command == "organize":
            try:
                from lib import history  # noqa: F401  同梱の dulwich（版の履歴の置き場に中身を入れる）
            except Exception as e:
                print(f"補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。何もしていません。")
                return 1
            entry = seiri.organize(folder, args.path, args.category, args.kind, args.date, args.partner, args.note)
            _print_json({"結果": "原本の置き場へ移しました", "元の場所": entry["元の場所"], "新しい場所": entry["場所"],
                         "台帳": entry})
        elif args.command == "keep":
            entry = seiri.keep(folder, args.path, args.reason)
            _print_json({"結果": "動かさずに、確かめ済みとして台帳に残しました", "台帳": entry})
        elif args.command == "list":
            _print_json(seiri.originals(seiri.load_ledger(folder)))
    except seiri.SeiriError as e:
        print(f"{e}")
        return 2
    except OSError as e:
        print(f"ファイルを扱えませんでした（{e}）。")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
