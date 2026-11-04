"""概要と流れ.docx を作る道具（SPEC F3・T3-9、DESIGN 4.5・4.6、TASKS M2d）。作り直すときも、同じファイルを直す。

使い方（Claude が書いた説明の文と判定の JSON を、標準入力で渡す。形は lib/gaiyou.py の先頭）：
  python3 -B <この場所>/gaiyou_word.py --folder "${CLAUDE_PROJECT_DIR}" [--case <案件>] <<'EOF'
  { "制度の概要": "…", "要件の判定": [ ... ], "加点の判定": [ ... ], "補助額の見込み": { ... } }
  EOF
  （--input - も標準入力。--input <ファイル> は、会社のフォルダの中のファイルだけ読む。外のファイルは読まずに断る。
   相対の場所は会社のフォルダから解き、別名と「..」をたどった後で比べる。DESIGN 5章）

- 書くのは `案件/<案件>/概要と流れ.docx` だけ。ほかのファイルは作らない。
- 数字・期限・一覧は、制度データ（記録/制度データ/）と会社の記録（記録/会社の記録.json）から道具が入れる。
  補助額の見込みも道具が計算する。渡す JSON には、説明の文と判定、区分・特例の名前、会社の記録の id だけを書く。
- --case：案件の名前（`記録/資料の本文/` の下のフォルダの名前）。案件が1つなら、渡さなくてよい。
- 作った日は、今日の日付（.hojokin/設定.json の差し替えを含む）。
- 終了コード：
  0 書いた。
  2 書かなかった（会社のフォルダでない、案件を決められない、制度データがない・形が合わない、
    渡した JSON の形や名前が制度データ・会社の記録と合わない、--input のファイルが会社のフォルダの外にある、
    Word を正しく作れない）。前の概要と流れ.docx はそのまま残る。
  3 補助プログラムが動かない、または途中で止まった。
"""

import sys

# 会社のフォルダやプラグインの場所に __pycache__ を書かない
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import unicodedata  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

NOT_DONE = "概要と流れ.docx を作りませんでした。何も変えていません。"
BROKEN = 3


def parse(argv):
    parser = argparse.ArgumentParser(description="概要と流れ.docx を作る（作り直すときも同じファイルを直す）")
    parser.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    parser.add_argument("--case", help="案件の名前（記録/資料の本文/ の下のフォルダの名前）")
    parser.add_argument("--input", help="説明の文と判定の JSON。なければ標準入力から読む（- も標準入力）。"
                                        "ファイルなら会社のフォルダの中のものだけ")
    return parser.parse_args(argv)


class OutsideInput(ValueError):
    """--input のファイルが、会社のフォルダの外にある。"""


class NotCompanyFolder(ValueError):
    """--input にファイルを渡したが、--folder が会社のフォルダでない（中を確かめられないので読まない）。"""


def real(path: Path) -> Path:
    """別名（シンボリックリンク）と「..」をたどり、名前の文字の形を NFC にそろえた場所（DESIGN 5章 (b)）。"""
    return Path(unicodedata.normalize("NFC", os.path.realpath(str(path))))


def inside(path: Path, folder: Path) -> bool:
    try:
        real(path).relative_to(real(folder))
        return True
    except ValueError:
        return False


def read_input(where, folder: Path, company) -> str:
    """渡された JSON の文字。ファイルは、会社のフォルダの中のものだけを読む（外のものは開かずに OutsideInput）。"""
    if not where or where == "-":
        return sys.stdin.read()
    path = Path(where).expanduser()
    if not path.is_absolute():
        path = folder / path
    # 会社のフォルダでない所のファイルも、外のファイルと同じく開かない
    if not company.is_company_folder(folder):
        raise NotCompanyFolder(where)
    if not inside(path, folder):
        raise OutsideInput(where)
    return path.read_text(encoding="utf-8")


def report(path: Path, folder: Path, summary: dict) -> str:
    reqs, judged = summary["要件"]
    stages, due = summary["流れ"]
    est = summary["補助額の見込み"]
    if est is None:
        est_line = "まだ出していません（「補助額の見込み」を渡すと出します）"
    elif est["見込み"] is None:
        est_line = f"出せませんでした（区分：{est['区分']}。上限か補助率が読み取れない）"
    else:
        from lib import gaiyou

        est_line = f"{gaiyou.yen(est['見込み'])}（区分：{est['区分']}）"
    lines = [
        f"{path.relative_to(folder)} を書きました。",
        "",
        f"- 自社が満たす要件：{reqs}件（自社の状況を書いたもの {judged}件）",
        f"- 義務と返還の条件：{summary['義務と返還の条件']}件",
        f"- 補助額の見込み：{est_line}",
        f"- 流れと期限：手続き {stages}段階、決まった期日 {due}件",
        f"- 加点：{summary['加点']}件",
        f"- 必要書類：{summary['必要書類']}件",
        f"- 読み取れなかった値 {summary['読み取れない値']}、要確認の値 {summary['要確認の値']}、"
        f"資料で食い違いの値 {summary['資料で食い違いの値']}（社長に示し、問い合わせ文の案を添える）",
    ]
    return "\n".join(lines) + "\n"


def main(argv) -> int:
    # 環境の文字コードによらず、日本語の結果を UTF-8 で返す
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    args = parse(argv)
    try:
        from lib import company, gaiyou
    except Exception as e:  # 同梱のファイルが欠けた・壊れた、Python が古いなど
        print(f"{NOT_DONE}補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。"
              "プラグインを入れ直してから、もう一度試してください。")
        return BROKEN

    folder = Path(args.folder).expanduser() if args.folder else company.project_dir()
    try:
        data = json.loads(read_input(args.input, folder, company))
    except OutsideInput:
        print(f"{NOT_DONE}説明の文と判定のファイル（{args.input}）が、会社のフォルダ（{folder}）の外にあります。"
              "外のファイルは読みません。JSON を、標準入力（--input - か、--input なし）で渡してください。")
        return 2
    except NotCompanyFolder:
        print(f"{NOT_DONE}ここ（{folder}）は会社のフォルダではありません（{company.MARKER_DIR}/ がありません）。"
              f"渡されたファイル（{args.input}）は読んでいません。"
              "社長の了承を得て会社のフォルダを作り、公式資料を取って制度データを作ってから、もう一度試してください。")
        return 2
    except (OSError, ValueError) as e:
        print(f"{NOT_DONE}渡された説明の文と判定を、JSON として読めません（{e}）。")
        return 2
    try:
        path, case, summary = gaiyou.write(folder, args.case, data)
    except gaiyou.GaiyouError as e:
        print(f"{NOT_DONE}直す所：")
        for problem in e.problems:
            print(f"- {problem}")
        return 2
    except Exception as e:  # スキーマや制度データが読めない、書けない場所など
        print(f"途中で止まりました（{type(e).__name__}: {e}）。概要と流れ.docx は書いていないか、前のままです。"
              "プラグインを入れ直してから、もう一度試してください。")
        return BROKEN
    print(report(path, folder, summary), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
