"""経費明細を作る道具（SPEC F8「経費明細」、DESIGN 8.4。TASKS B20）。中身は lib/keihi.py。

使い方（する事の後に、--folder "${CLAUDE_PROJECT_DIR}" を付ける。なければ今いるフォルダ）：
  python3 -B <この場所>/keihi.py save --case <案件> --input 記録/一時/経費明細.json
      Claude が Write で置いた行（{"行": [ … ]}）を確かめ、記録/経費明細.json に残す。結果は JSON（行・状態・合計）。
  python3 -B <この場所>/keihi.py show [--case <案件>]
      残した経費明細を出す。

- 根拠が見積書の行は、照合済みの見積書の明細の番号を指し、金額がその明細と合わないと残さない。メモ・聞き取りの行は「仮」。
  要確認の行は、資料のページがないと残さない。
- 終了コード：0 できた、1 補助プログラムを読み込めない、2 しなかった（理由を出す。何も書いていない）。
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
    parser = argparse.ArgumentParser(description="照合を通った見積書の金額とメモから、経費明細を作る")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    sub = parser.add_subparsers(dest="command")
    p = sub.add_parser("save", parents=[common], help="経費明細の行を確かめて残す")
    p.add_argument("--case", required=True, help="案件の名前")
    p.add_argument("--input", required=True, help="Claude が Write で置いた JSON（記録/一時/ の下）")
    p = sub.add_parser("show", parents=[common], help="残した経費明細を出す")
    p.add_argument("--case", default="", help="案件の名前（なければ全部）")
    return parser.parse_args(argv)


def main(argv) -> int:
    args = parse(argv)
    if not args.command:
        print("する事（save・show）を指定してください。")
        return 2
    folder = company.company_folder(args.folder) if args.folder else company.company_folder()
    if folder is None:
        print(f"{args.folder or company.project_dir()} は会社のフォルダではありません（目印の .hojokin/ がありません）。何もしていません。")
        return 2
    try:
        from lib import keihi, places
    except Exception as e:
        print(f"補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。何もしていません。")
        return 1
    try:
        if args.command == "save":
            try:
                path = places.resolve_inside(folder, args.input)
            except places.PlaceError:
                print(f"{args.input} は会社のフォルダの外です。記録/一時/ に置いてください。")
                return 2
            try:
                data = json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                print(f"{args.input} が JSON として読めません（{type(e).__name__}: {e}）。")
                return 2
            rows = data.get("行") if isinstance(data, dict) else data
            entry = keihi.save(folder, args.case, rows)
            print(json.dumps({"結果": f"経費明細を {keihi.RECORD_PATH} に残しました", "合計": entry["合計"],
                              "行": [{k: e.get(k) for k in ("品名", "金額", "根拠", "状態", "要確認")} for e in entry["行"]]},
                             ensure_ascii=False, indent=1))
        else:
            data = keihi.load(folder)
            cases = [c for c in data["案件"] if not args.case or c.get("案件") == args.case]
            print(json.dumps(cases, ensure_ascii=False, indent=1))
    except keihi.KeihiError as e:
        print(f"{e}")
        return 2
    except OSError as e:
        print(f"ファイルを扱えませんでした（{e}）。")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
