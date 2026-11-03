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
- --input：読み取りの結果。- なら標準入力。ファイルなら、会社のフォルダの中のものだけ（外は読まない）。
- 置き場所は道具が決める（ほかの場所には書かない）。
  - 章ごとの結果：`記録/制度データ/読み取り/<案件>/<章>_<回目>回目.json`。
    同じ章・同じ回目の結果がすでにあれば、渡された項目だけを差し替え、ほかの項目は残して、章の全体を照らし直す。
  - 制度データの全体：`記録/制度データ/<制度の略称>_<公募回>.json`。
- Claude が Bash で動かすコマンドには、CLAUDE_PROJECT_DIR の環境変数が入らないので、--folder で渡す。
- 終了コード：0 形が合い、どの値も裏取りで外れなかった（結果を置いた）。
  1 形は合ったが、裏取りで外れた値がある（「要確認」にして、結果を置いた）。
  2 動かさなかった（会社のフォルダでない、形が合わない、案件を決められない、入力が外にある、
    名前に版の名前の語がある、前の結果が読めない）。何も書いていない。
  3 補助プログラムが動かない、または裏取りの途中で止まった。
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
BROKEN = 3


class OutsideInput(ValueError):
    """読み取りの結果のファイルが、会社のフォルダの外にある。"""


def parse(argv):
    parser = argparse.ArgumentParser(description="読み取り役が返した制度データの下書きを、形と出典で裏取りする")
    parser.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    parser.add_argument("--case", help="案件の名前（記録/資料の本文/ の下のフォルダの名前）")
    parser.add_argument("--input", help="読み取りの結果（- なら標準入力。ファイルなら会社のフォルダの中のもの）")
    parser.add_argument("--form", nargs="+", metavar="項目", help="読み取り役に渡す形を出す（制度データの項目を並べる）")
    return parser.parse_args(argv)


def read_input(where: str, folder: Path, inside) -> object:
    if where == "-":
        return json.loads(sys.stdin.read())
    path = Path(where).expanduser()
    if not path.is_absolute():
        path = folder / path
    if not inside(path, folder):
        raise OutsideInput(where)
    return json.loads(path.read_text(encoding="utf-8"))


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
        return BROKEN

    if args.form:
        try:
            form = urakadori.form_for(args.form)
        except urakadori.InputError as e:
            print(f"形を出せませんでした。\n\n{e}")
            return 2
        except Exception as e:  # スキーマが読めない
            print(f"形を出せませんでした（{type(e).__name__}: {e}）。プラグインを入れ直してから、もう一度試してください。")
            return BROKEN
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
        data = read_input(args.input, folder, urakadori.inside)
    except OutsideInput:
        print(f"{NOT_DONE}読み取りの結果のファイル（{args.input}）が、会社のフォルダの外にあります。"
              "外のファイルは読みません。読み取り役が返した JSON を、--input - で標準入力から渡してください。")
        return 2
    except (OSError, ValueError) as e:
        print(f"{NOT_DONE}読み取りの結果を読めませんでした（{type(e).__name__}）。JSON の形で渡してください。")
        return 2
    try:
        case = urakadori.find_case(folder, args.case)
    except case_folder.CaseError as e:
        print(f"{NOT_DONE}案件を決められませんでした（{e}）。")
        return 2
    try:
        result, saved = urakadori.run(folder, case, data)
    except urakadori.InputError as e:
        print(urakadori.error_report(e.errors), end="")
        return 2
    except (urakadori.PlaceError, case_folder.CaseError) as e:  # 版の名前の語、外になる置き場所、読めない前の結果、使えない名前
        print(f"{NOT_DONE}置き場所を決められませんでした。{e}")
        return 2
    except Exception as e:  # スキーマや資料の本文が読めない、書けない場所など
        print(f"裏取りの途中で止まりました（{type(e).__name__}: {e}）。結果は置いていないか、置きかけです。"
              "プラグインを入れ直すか、公式資料を取り直してから、もう一度試してください。")
        return BROKEN
    if urakadori.is_full(data):
        label = "制度データの全体"
    else:
        info = saved["読み取り"]
        label = f"章：{info['章']}、{info['回目']}回目"
    print(urakadori.report(result, case, label), end="")
    return 0 if result.clean else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
