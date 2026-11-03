"""読み取り役が返した制度データの下書きを、形と出典で裏取りする道具（SPEC F3、DESIGN 9.2、TASKS M2b）。

使い方：
  1. 読み取り役に渡す形を出す（読む項目を並べる）
     python3 -B <この場所>/urakadori.py --form 補助額 数値の要件
  2. 読み取り役が返した JSON を裏取りする
     python3 -B <この場所>/urakadori.py --folder "${CLAUDE_PROJECT_DIR}" [--case <案件>] --input - <<'EOF'
     { "読み取り": {…}, "制度データ": {…} }
     EOF

- 読み取りの結果の形と、裏取りの決まりは、lib/urakadori.py の説明のとおり。
- --case：案件の名前（`記録/資料の本文/` の下のフォルダの名前）。案件が1つなら、渡さなくてよい。
- --input：読み取りの結果（JSON のファイル。- なら標準入力）。
- --out：置き場所（会社のフォルダの中だけ）。章ごとの結果は、渡さなければ
  `記録/制度データ/読み取り/<案件>/<章>_<回目>回目.json` に置く。制度データの全体を通すときは、必ず渡す。
- Claude が Bash で動かすコマンドには、CLAUDE_PROJECT_DIR の環境変数が入らないので、--folder で渡す。
- 終了コード：0 形が合い、どの値も裏取りで外れなかった（結果を置いた）。
  1 形は合ったが、裏取りで外れた値がある（「要確認」にして、結果を置いた）か、補助プログラムが動かない。
  2 動かさなかった（会社のフォルダでない、形が合わない、案件を決められない、置き場所が外）。何も書いていない。
"""

import sys

# 会社のフォルダやプラグインの場所に __pycache__ を書かない
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

NOT_DONE = "裏取りをしませんでした。何も書いていません。\n\n"


def parse(argv):
    parser = argparse.ArgumentParser(description="読み取り役が返した制度データの下書きを、形と出典で裏取りする")
    parser.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    parser.add_argument("--case", help="案件の名前（記録/資料の本文/ の下のフォルダの名前）")
    parser.add_argument("--input", help="読み取りの結果（JSON のファイル。- なら標準入力）")
    parser.add_argument("--out", help="置き場所（会社のフォルダの中）")
    parser.add_argument("--form", nargs="+", metavar="項目", help="読み取り役に渡す形を出す（制度データの項目を並べる）")
    return parser.parse_args(argv)


def read_input(where: str) -> object:
    text = sys.stdin.read() if where == "-" else Path(where).expanduser().read_text(encoding="utf-8")
    return json.loads(text)


def main(argv) -> int:
    # 環境の文字コードによらず、日本語の結果を UTF-8 で返す
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    args = parse(argv)
    try:
        from lib import case_folder, company, urakadori
    except Exception as e:  # 同梱のファイルが欠けた・壊れた、Python が古いなど
        print(f"{NOT_DONE}補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。"
              "プラグインを入れ直してから、もう一度試してください。")
        return 1

    if args.form:
        try:
            form = urakadori.form_for(args.form)
        except urakadori.InputError as e:
            print(f"形を出せませんでした。\n\n{e}")
            return 2
        except Exception as e:  # スキーマが読めない
            print(f"形を出せませんでした（{type(e).__name__}: {e}）。プラグインを入れ直してから、もう一度試してください。")
            return 1
        print(json.dumps(form, ensure_ascii=False, indent=1))
        return 0

    if not args.input:
        print(f"{NOT_DONE}読み取りの結果（--input）を渡してください。")
        return 2
    folder = Path(args.folder).expanduser() if args.folder else company.project_dir()
    if company.company_folder(folder) is None:
        print(f"{NOT_DONE}このフォルダ（{folder}）は、まだ会社のフォルダではありません（目印の {company.MARKER_DIR}/ がありません）。"
              "先に、社長の了承を得て会社のフォルダを作り、公式資料を取ってください。")
        return 2
    try:
        data = read_input(args.input)
    except (OSError, ValueError) as e:
        print(f"{NOT_DONE}読み取りの結果を読めませんでした（{e}）。JSON の形で渡してください。")
        return 2
    try:
        case = urakadori.find_case(folder, args.case)
    except case_folder.CaseError as e:
        print(f"{NOT_DONE}案件を決められませんでした（{e}）。")
        return 2
    out = None
    if urakadori.is_full(data) and not args.out:
        print(f"{NOT_DONE}制度データの全体を裏取りするときは、置き場所（--out）を渡してください。")
        return 2
    if args.out:
        out = Path(args.out).expanduser()
        if not out.is_absolute():
            out = folder / out
        if not urakadori._inside(out, folder):
            print(f"{NOT_DONE}置き場所（{args.out}）が、会社のフォルダの外です。会社のフォルダの中を渡してください。")
            return 2
    try:
        result, saved = urakadori.run(folder, case, data, out)
    except urakadori.InputError as e:
        print(urakadori.error_report(e.errors), end="")
        return 2
    except case_folder.CaseError as e:  # 章の名前が、ファイルの名前に使えない
        print(f"{NOT_DONE}置き場所の名前を決められませんでした（{e}）。")
        return 2
    except Exception as e:  # スキーマや資料の本文が読めない、書けない場所など
        print(f"裏取りの途中で止まりました（{type(e).__name__}: {e}）。結果は置いていないか、置きかけです。"
              "プラグインを入れ直すか、公式資料を取り直してから、もう一度試してください。")
        return 1
    if urakadori.is_full(data):
        label = "制度データの全体"
    else:
        info = saved["読み取り"]
        label = f"章：{info['章']}、{info['回目']}回目"
    print(urakadori.report(result, case, label), end="")
    return 0 if result.clean else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
