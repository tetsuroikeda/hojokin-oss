"""期限と、外部への依頼と待ちの道具（SPEC F6、DESIGN 4.5〜4.7・6章。TASKS K1・K2）。

使い方（どれも --folder "${CLAUDE_PROJECT_DIR}" を付ける。案件が2つ以上なら --case も渡す）：
  1. 期限と作業の一覧（期限切れ・今日やること・近い締切・遅れている作業、それより先、日付がまだ出せないもの、
     外部への依頼と待ち、済んだもの）
       python3 -B <この場所>/kigen.py --folder "${CLAUDE_PROJECT_DIR}" --show
  2. 人に頼む書類の候補（今の段階と次の段階。目安の日数・締切・始める日・台帳の状態。聞くもの）
       python3 -B <この場所>/kigen.py --folder "${CLAUDE_PROJECT_DIR}" --case "<案件>" --requests
  3. 依頼を残す（どれも「<書類>=<値>」。同じ引数をいくつ並べてもよい。書類の名前は制度データの書類の名前）
       --add "<書類>"                 台帳に足す（状態「まだ」）
       --days "<書類>=14日"            頼んでから届くまでの目安の日数（社長の答え）。会社の記録にも残す
       --who "<書類>=社長"             頼む人（社長・担当者）
       --to "<書類>=信用金庫"          依頼先
       --status "<書類>=依頼した"      状態（まだ・依頼した・待っている・届いた・済み）。「依頼した@2026-11-18」で日付も渡せる
       --received "<書類>=原本/…pdf"  届いた（状態を「届いた」にし、整理した後の原本の場所を残す）
  4. 近い締切の日数を変える（社長・担当者が会話で頼んだとき）
       python3 -B <この場所>/kigen.py --folder "${CLAUDE_PROJECT_DIR}" --near-days 60

- 中身は lib/deadline_tool.py（組み立ては lib/deadlines.py、台帳は lib/task_ledger.py）。
- 期限の台帳（記録/期限の台帳.json）に残すのは、状態・頼む人・依頼先・目安の日数・依頼した日・届いた日だけ。
  締切と始める日は、読むたびに制度データと出来事の日付から計算する。
- 今日の日付は、`.hojokin/設定.json` の「今日の日付」で差し替えられる（lib/dates.py）。
- 書いた後は、今の状態.html を作り直す。
- 終了コード：
  0 できた（一覧・候補を出した、残した）。
  1 できたが、目安の日数がまだ分からない依頼がある（社長に聞いて --days で残す）。
  2 動かさなかった（会社のフォルダでない、案件を決められない、制度データにない書類、値の形が違う、書く先が別名など）。
    何も書いていない。
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
    parser = argparse.ArgumentParser(description="期限と、外部への依頼と待ち")
    parser.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    parser.add_argument("--case", help="案件の名前（記録/資料の本文/ の下のフォルダの名前）")
    parser.add_argument("--show", action="store_true", help="期限と作業の一覧を出す")
    parser.add_argument("--requests", action="store_true", help="人に頼む書類の候補を出す")
    parser.add_argument("--add", action="append", default=[], metavar="書類", help="依頼を台帳に足す")
    parser.add_argument("--days", action="append", default=[], metavar="書類=日数", help="目安の日数（社長の答え）")
    parser.add_argument("--who", action="append", default=[], metavar="書類=頼む人", help="頼む人（社長・担当者）")
    parser.add_argument("--to", action="append", default=[], metavar="書類=依頼先", help="依頼先")
    parser.add_argument("--status", action="append", default=[], metavar="書類=状態", help="依頼の状態")
    parser.add_argument("--received", action="append", default=[], metavar="書類=場所", help="届いた書類の場所")
    parser.add_argument("--near-days", type=int, metavar="日数", help="近い締切の日数（はじめは30日）")
    return parser.parse_args(argv)


def changes_of(args, tool, today):
    """引数を、書類ごとの変更にまとめる。"""
    found = {}

    def get(name):
        key = tool.task_ledger.nfc(name.strip())
        for known in found:
            if tool.task_ledger.same_doc(known, key):
                return found[known]
        found[key] = tool.Change(doc=key)
        return found[key]

    for name in args.add:
        if not name.strip():
            raise tool.ToolError("--add には書類の名前を渡してください")
        get(name).add = True
    for text in args.days:
        name, value = tool.split_change(text, "--days")
        get(name).days = tool.parse_days(value)
    for text in args.who:
        name, value = tool.split_change(text, "--who")
        get(name).asker = value
    for text in args.to:
        name, value = tool.split_change(text, "--to")
        get(name).to = value
    for text in args.status:
        name, value = tool.split_change(text, "--status")
        change = get(name)
        change.state, change.day = tool.parse_state(value, today)
    for text in args.received:
        name, value = tool.split_change(text, "--received")
        get(name).received = value
    return list(found.values())


def main(argv) -> int:
    # 環境の文字コードによらず、日本語の結果を UTF-8 で返す
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse(argv)
    try:
        from lib import case_folder, company, dates, deadline_tool, task_ledger, urakadori
    except Exception as e:  # 同梱のファイルが欠けた・壊れた、Python が古いなど
        print(f"{NOT_DONE}補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。"
              "プラグインを入れ直してから、もう一度試してください。")
        return BROKEN

    folder = Path(args.folder).expanduser() if args.folder else company.project_dir()
    if company.company_folder(folder) is None:
        print(f"{NOT_DONE}このフォルダ（{folder}）は、まだ会社のフォルダではありません（目印の {company.MARKER_DIR}/ がありません）。"
              "先に、社長の了承を得て会社のフォルダを作ってください。")
        return 2
    editing = any([args.add, args.days, args.who, args.to, args.status, args.received])
    try:
        today = dates.today(folder)
        out = []
        asking = False
        if args.near_days is not None:
            before = task_ledger.set_near_days(folder, args.near_days)
            out.append(f"近い締切の日数を{args.near_days}日にしました（前は{before if before is not None else 30}日。"
                       f"{company.MARKER_DIR}/{company.SETTINGS_FILE} に残しました。開いたときの一覧と今の状態.html も、この日数で分けます）。")
        case = None
        if editing or args.requests:
            try:
                case = urakadori.find_case(folder, args.case)
            except case_folder.CaseError as e:
                print(f"{NOT_DONE}案件を決められませんでした（{e}）。")
                return 2
        if editing:
            changes = changes_of(args, deadline_tool, today)
            applied = deadline_tool.apply(folder, case, changes)
            out.append(f"## 期限の台帳に残したこと（{case}）")
            out += [f"- {line}" for line in applied.lines]
            out += [f"- {note}" for note in applied.notes]
            out += ["", f"## {case} の外部への依頼と待ち（今日 {dates.format_date(today)}）"]
            out += deadline_tool.requests_rows(folder, case)
        if args.requests:
            text, ask = deadline_tool.requests_text(folder, case)
            out.append(text.rstrip())
            asking = asking or ask
        if args.show or not (editing or args.requests or args.near_days is not None):
            text, ask = deadline_tool.show_text(folder)
            out.append(text.rstrip())
            asking = asking or ask
        if editing or args.near_days is not None:
            problem = deadline_tool.refresh_page(folder)
            if problem:
                out.append(problem)
        if editing and not args.requests and not args.show:
            asking = any("目安の日数をまだ聞いていません" in line for line in deadline_tool.requests_rows(folder, case))
    except (deadline_tool.ToolError, task_ledger.TaskLedgerError) as e:
        print(f"{NOT_DONE}{e}")
        return 2
    except ValueError as e:  # 今日の日付の差し替えや近い締切の日数が読めない など
        print(f"{NOT_DONE}{e}")
        return 2
    except Exception as e:  # 書けない場所、壊れた制度データ、会社の記録が読めないなど
        print(f"途中で止まりました（{type(e).__name__}: {e}）。期限の台帳か会社の記録を、書きかけのことがあります。"
              "プラグインを入れ直すか、制度データと会社の記録を確かめてから、もう一度試してください。")
        return BROKEN
    print("\n\n".join(x for x in out if x) + "\n", end="")
    return 1 if asking else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
