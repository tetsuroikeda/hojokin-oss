"""見積書・請求書・納品書の金額を照合する道具（SPEC F5、DESIGN 8.4。TASKS B11）。中身は lib/kingaku.py と lib/page_image.py。

使い方（する事の後に、--folder "${CLAUDE_PROJECT_DIR}" を付ける。なければ今いるフォルダ）：
  python3 -B <この場所>/kingaku.py image --path <原本> [--rotate 180] [--band 0.55,0.75]
      文字のない PDF と写真を、ページの画像にして 記録/一時/画像/ に置く（向きを直す・帯を切り出して拡大する）。
  python3 -B <この場所>/kingaku.py check --path <原本> --input 記録/一時/読み取り.json --model sonnet [--round 2]
      読み取り役が返した JSON を計算で照合し、記録/金額の読み取り.json に残す。結果は JSON（外れ・読めない・状態）。
  python3 -B <この場所>/kingaku.py confirm --path <原本> --field 明細7.単価 --value 1380
      社長が確かめた値を入れ、照合し直す（出典は「社長の答え」）。
  python3 -B <この場所>/kingaku.py show [--path <原本>]
      記録した読み取りと照合の結果を出す。

- 終了コード：0 できた（外れがあっても、記録できたら 0。状態を見る）、1 補助プログラムを読み込めない、
  2 しなかった（原本でない、読み取りの形が違う など。記録は変えていない）。
"""

import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

from lib import company  # noqa: E402

NEXT = {
    "照合済み": "照合を通りました。この読み取りの金額を使えます",
    "読み直す": "外れた所があります。外れた明細の帯を image --band で切り出し、読み取り役に model: opus で読み直させて、"
               "--round 2 でもう一度照合してください",
    "要確認": "読み直しても合わない所か、読めない所があります。推測で埋めずに、その部分の画像の場所と読み取った数字を並べて、"
             "社長に確かめてください。答えは confirm で入れます",
}


def parse(argv):
    parser = argparse.ArgumentParser(description="見積書・請求書・納品書の金額と明細を、計算で照合する")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    sub = parser.add_subparsers(dest="command")
    p = sub.add_parser("image", parents=[common], help="ページの画像を作る（向きを直す・帯を切り出す）")
    p.add_argument("--path", required=True, help="原本の場所か id")
    p.add_argument("--rotate", type=int, default=0, help="まわす角度（0・90・180・270）")
    p.add_argument("--band", default="", help="切り出す帯（上からの割合。例：0.55,0.75）")
    p = sub.add_parser("check", parents=[common], help="読み取りを照合して記録する")
    p.add_argument("--path", required=True, help="原本の場所か id")
    p.add_argument("--input", required=True, help="読み取り役が返した JSON を置いたファイル（記録/一時/ の下）")
    p.add_argument("--model", default="", help="読んだモデル（haiku・sonnet・opus）")
    p.add_argument("--round", type=int, default=1, help="何回目か（読み直しは 2）")
    p = sub.add_parser("confirm", parents=[common], help="社長が確かめた値を入れて照合し直す")
    p.add_argument("--path", required=True, help="原本の場所か id")
    p.add_argument("--field", required=True, help="欄（明細7.単価、小計 など）")
    p.add_argument("--value", required=True, help="社長が確かめた値")
    p = sub.add_parser("show", parents=[common], help="記録した読み取りと照合の結果を出す")
    p.add_argument("--path", default="", help="原本の場所か id（なければ全部）")
    return parser.parse_args(argv)


def _print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=1))


def _result(entry: dict) -> dict:
    return {"原本": entry["原本"], "状態": entry["状態"], "次にすること": NEXT.get(entry["状態"], ""),
            "外れ": entry["照合"]["外れ"], "読めない": entry["照合"]["読めない"],
            "合計": entry["読み取り"].get("合計"), "回目": entry["回目"], "読んだモデル": entry["読んだモデル"]}


def main(argv) -> int:
    args = parse(argv)
    if not args.command:
        print("する事（image・check・confirm・show）を指定してください。")
        return 2
    folder = company.company_folder(args.folder) if args.folder else company.company_folder()
    if folder is None:
        print(f"{args.folder or company.project_dir()} は会社のフォルダではありません（目印の .hojokin/ がありません）。何もしていません。")
        return 2
    try:
        from lib import kingaku, page_image, places, seiri
    except Exception as e:
        print(f"補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。何もしていません。")
        return 1
    try:
        if args.command == "image":
            original = kingaku._original(folder, args.path)
            band = None
            if args.band:
                try:
                    band = tuple(float(x) for x in args.band.split(","))
                except ValueError:
                    print("帯（--band）は「0.55,0.75」の形にしてください。")
                    return 2
                if len(band) != 2:
                    print("帯（--band）は「0.55,0.75」の形にしてください。")
                    return 2
            made = page_image.make_images(folder, folder / original["場所"], original.get("id") or "原本",
                                          args.rotate, band)
            _print({"結果": "ページの画像を作りました。Read で開いて読むか、読み取り役に場所を渡してください", "画像": made})
        elif args.command == "check":
            try:
                path = places.resolve_inside(folder, args.input)
            except places.PlaceError:
                print(f"{args.input} は会社のフォルダの外です。読み取りは 記録/一時/ に置いてください。")
                return 2
            try:
                reading = json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                print(f"{args.input} が JSON として読めません（{type(e).__name__}: {e}）。")
                return 2
            if isinstance(reading, dict) and isinstance(reading.get("読み取り"), dict):
                reading = reading["読み取り"]
            entry = kingaku.save_reading(folder, args.path, reading, args.model, args.round)
            _print(_result(entry))
        elif args.command == "confirm":
            entry = kingaku.confirm(folder, args.path, args.field, args.value)
            _print(_result(entry))
        else:
            data = kingaku.load(folder)
            if args.path:
                original = kingaku._original(folder, args.path)
                found = kingaku.find(data, original["場所"])
                _print(found if found else {"結果": f"{original['場所']} の読み取りはまだありません"})
            else:
                _print([_result(d) for d in data["書類"]])
    except (kingaku.KingakuError, page_image.ImageError, seiri.SeiriError) as e:
        print(f"{e}")
        return 2
    except OSError as e:
        print(f"ファイルを扱えませんでした（{e}）。")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
