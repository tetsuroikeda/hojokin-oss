"""採択後に、次の手続きの段階へ切り替える道具（SPEC F12・F3・F6、DESIGN 4.5・4.7・6章・9章、TASKS M10）。

使い方：
  1. 採択されたとき（採択発表日を、通知の原本か社長の答えで確かめてから）
     python3 -B <この場所>/stage_switch.py --folder "${CLAUDE_PROJECT_DIR}" [--case <案件>] --event 採択発表日=2027-03-10 \
       [--source "原本/役所からの通知/2027-03-10_採択の通知_….pdf"]
  2. 段階は変えずに、出来事の日付だけを残す（交付決定日など）
     python3 -B <この場所>/stage_switch.py --folder "${CLAUDE_PROJECT_DIR}" --stage 2_交付申請 --event 交付決定日=2027-05-20
  3. 書かずに、今の段階（か --stage の段階）の書類の一覧と期限を見る
     python3 -B <この場所>/stage_switch.py --folder "${CLAUDE_PROJECT_DIR}" --show [--stage 2_交付申請]

- 切り替え方と結果の中身は、lib/stage_switch.py の説明のとおり。
- --stage：切り替える先の段階のフォルダの名前（2_交付申請 など）。なければ、今の段階の次の、フォルダのある段階。
- --event：出来事の名前と日付（「採択発表日=2027-03-10」。いくつ並べてもよい）。名前は、制度データの期限の決め方にある出来事の名前。
  期限の台帳（記録/期限の台帳.json）の「出来事」に「確定」として残し、期限はその日から計算する。
- --source：出来事の出典（通知の原本の、会社のフォルダからの場所か「社長の答え」）。なければ「社長の答え」。
- --case：案件の名前（`記録/資料の本文/` の下のフォルダの名前）。案件が1つなら、渡さなくてよい。
- 今日の日付は、`.hojokin/設定.json` の「今日の日付」で差し替えられる（lib/dates.py）。結果の日付と日数は、その今日から出す。
- Claude が Bash で動かすコマンドには、CLAUDE_PROJECT_DIR の環境変数が入らないので、--folder で渡す。
- 終了コード：
  0 切り替えた（か、もうその段階だった）。その段階の期限の日付が出せた。--show は、期限の日付が出せた。
  1 切り替えた（--show は一覧を出した）が、その段階の期限の日付がまだ出せない（決め方にある出来事の日付が分からない）。
    通知の原本の日付か社長の答えで出来事の日付を確かめ、--event で渡し直す。
  2 動かさなかった（会社のフォルダでない、案件を決められない、制度データがない、手続きの段階にない段階、今の段階より前の段階、
    制度データにない出来事、今日より後の日付、書く先が別名など）。何も書いていない。
  3 補助プログラムが動かない、または途中で止まった。
"""

import sys

# 会社のフォルダやプラグインの場所に __pycache__ を書かない
sys.dont_write_bytecode = True

import argparse  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

NOT_DONE = "何も書いていません。\n\n"
BROKEN = 3


def parse(argv):
    parser = argparse.ArgumentParser(description="採択後に、次の手続きの段階へ切り替える")
    parser.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    parser.add_argument("--case", help="案件の名前（記録/資料の本文/ の下のフォルダの名前）")
    parser.add_argument("--stage", metavar="フォルダ", help="切り替える先の段階のフォルダの名前（2_交付申請 など）")
    parser.add_argument("--event", action="append", default=[], metavar="出来事=日付",
                        help="確かめた出来事の日付（採択発表日=2027-03-10。いくつ並べてもよい）")
    parser.add_argument("--source", help="出来事の出典（通知の原本の、会社のフォルダからの場所か「社長の答え」）")
    parser.add_argument("--show", action="store_true", help="書かずに、書類の一覧と期限だけを出す")
    return parser.parse_args(argv)


def main(argv) -> int:
    # 環境の文字コードによらず、日本語の結果を UTF-8 で返す
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse(argv)
    try:
        from lib import case_folder, company, stage_switch, urakadori
    except Exception as e:  # 同梱のファイルが欠けた・壊れた、Python が古いなど
        print(f"{NOT_DONE}補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。"
              "プラグインを入れ直してから、もう一度試してください。")
        return BROKEN

    folder = Path(args.folder).expanduser() if args.folder else company.project_dir()
    if company.company_folder(folder) is None:
        print(f"{NOT_DONE}このフォルダ（{folder}）は、まだ会社のフォルダではありません（目印の {company.MARKER_DIR}/ がありません）。"
              "先に、社長の了承を得て会社のフォルダを作り、公式資料を取って制度データを作ってください。")
        return 2
    try:
        case = urakadori.find_case(folder, args.case)
    except case_folder.CaseError as e:
        print(f"{NOT_DONE}案件を決められませんでした（{e}）。")
        return 2

    try:
        outcome = stage_switch.switch(folder, case, stage=args.stage, events=args.event, source=args.source,
                                      show_only=args.show)
    except stage_switch.SwitchError as e:
        print(f"{NOT_DONE}{e}")
        return 2
    except ValueError as e:  # 今日の日付の差し替えが読めない など
        print(f"{NOT_DONE}{e}")
        return 2
    except Exception as e:  # 書けない場所、壊れた制度データなど
        print(f"途中で止まりました（{type(e).__name__}: {e}）。期限の台帳か段階のフォルダを、書きかけのことがあります。"
              "プラグインを入れ直すか、制度データを確かめてから、もう一度試してください。")
        return BROKEN
    print(stage_switch.report(outcome), end="")
    return 0 if outcome.dated() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
