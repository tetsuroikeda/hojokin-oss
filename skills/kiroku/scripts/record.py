"""会社の記録の道具（SPEC F13、DESIGN 10章。TASKS M11）。

社長の答えや書類から分かった会社の事実と、書き方の決まりを、出典と覚えた日を付けて `記録/会社の記録.json` に残す。
形は schema/会社の記録.schema.json で確かめてから書く。版は応答の終わりに hook が自動で残す。

使い方（する事の後に、--folder "${CLAUDE_PROJECT_DIR}" を付ける。なければ今いるフォルダ）：
  python3 -B <この場所>/record.py add-fact --name <名前> --value <値> (--changeable | --fixed) --source <出典の種類> …
      事実を足す。同じ名前・同じ値があれば、最後に確かめた日を今日にする。
      同じ名前で値が違えば、上書きせずに断る（終了コード2。両方を出典付きで出す）。
  python3 -B <この場所>/record.py add-rule --kind <区分> --content <内容> --trigger <社長の発言や手直し> --source … [--case <案件>]
      書き方の決まり（直した表現・好む言い方・避けたい言い方・書き方の方針・構成）を足す。
  python3 -B <この場所>/record.py confirm --id <事実の id>
      記録のままでよいと社長が確かめた。最後に確かめた日を今日にする。
  python3 -B <この場所>/record.py update-fact --id <事実の id> --value <新しい値> --source … [--changeable | --fixed]
      社長が決めた新しい値にする（食い違いを決めてもらった後や、社長が直したとき）。
  python3 -B <この場所>/record.py list
      覚えていることの一覧（何を、いつ、どこから）。

出典の指し方（--source のほかに）：
  原本         --file <会社のフォルダの中の場所> [--page <ページ>]
  質問         --question "<聞いた質問>" [--answered-date 2026-11-04]（省けば今日）
  社長の手直し --file <直した書類> [--date 2026-11-04]
  社長の発言   --utterance "<社長の発言>" [--date 2026-11-04]
値は文字のまま残す。数や一覧で残すときは --json-value を付けて、JSON で渡す。

- 終了コード：0 できた、1 補助プログラムを読み込めない、
  2 しなかった（会社のフォルダでない、引数が足りない・違う、記録が読めない、食い違いなど）。2 のとき、記録は変えていない。
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

SOURCE_KINDS = ("原本", "質問", "社長の手直し", "社長の発言")
RULE_KINDS = ("直した表現", "好む言い方", "避けたい言い方", "書き方の方針", "構成")


class Refused(Exception):
    """引数が足りない・違う（argparse の英語の文を、社長に伝えられる文にする）。"""


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused(message)


def parse(argv):
    parser = Parser(description="会社の記録に、事実と書き方の決まりを出典つきで残す")
    common = Parser(add_help=False)
    common.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    source = Parser(add_help=False)
    source.add_argument("--source", choices=SOURCE_KINDS, required=True, help="出典の種類")
    source.add_argument("--file", help="原本・社長の手直しの書類（会社のフォルダの中の場所）")
    source.add_argument("--page", type=int, help="原本のページ")
    source.add_argument("--question", help="聞いた質問の文（出典が質問のとき）")
    source.add_argument("--answered-date", help="答えた日（省けば今日）")
    source.add_argument("--utterance", help="社長の発言（出典が社長の発言のとき）")
    source.add_argument("--date", help="社長の手直し・発言の日（省けば今日）")
    sub = parser.add_subparsers(dest="command", parser_class=Parser)

    p = sub.add_parser("add-fact", parents=[common, source], help="事実を足す")
    p.add_argument("--name", required=True, help="事実の名前（例：従業員の数）")
    p.add_argument("--value", required=True, help="値")
    p.add_argument("--json-value", action="store_true", help="値を JSON として読む（数や一覧のとき）")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--changeable", action="store_true", help="変わりうる情報（従業員数・売上・給与など）")
    group.add_argument("--fixed", action="store_true", help="変わらない情報（設立の日・法人番号など）")

    p = sub.add_parser("add-rule", parents=[common, source], help="書き方の決まりを足す")
    p.add_argument("--kind", required=True, choices=RULE_KINDS, help="区分")
    p.add_argument("--content", required=True, help="決まりの内容")
    p.add_argument("--trigger", required=True, help="きっかけ（社長の発言や手直し）")
    p.add_argument("--case", help="きっかけの案件")

    p = sub.add_parser("confirm", parents=[common], help="記録のままでよいと確かめた")
    p.add_argument("--id", required=True, help="事実の id")

    p = sub.add_parser("update-fact", parents=[common, source], help="社長が決めた新しい値にする")
    p.add_argument("--id", required=True, help="事実の id")
    p.add_argument("--value", required=True, help="新しい値")
    p.add_argument("--json-value", action="store_true", help="値を JSON として読む")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--changeable", action="store_true", help="変わりうる情報にする")
    group.add_argument("--fixed", action="store_true", help="変わらない情報にする")

    sub.add_parser("list", parents=[common], help="覚えていることの一覧")
    return parser.parse_args(argv)


def _value(args):
    if not args.json_value:
        return args.value
    try:
        return json.loads(args.value)
    except ValueError as e:
        raise Refused(f"値（--value）が JSON として読めません（{e}）") from e


def _source(folder, args, record):
    return record.make_source(folder, args.source, file=args.file, page=args.page, question=args.question,
                              answered=args.answered_date, utterance=args.utterance, day=args.date)


def _add_fact(folder, args, record) -> int:
    result, item, existing = record.add_fact(folder, args.name, _value(args), args.changeable, _source(folder, args, record))
    if result == "added":
        print(f"覚えました：{record.fact_line(item)}")
        print("版は、応答の終わりに自動で残ります。")
        return 0
    if result == "same":
        print(f"もう覚えています（同じ値）。最後に確かめた日を {item['最後に確かめた日']} にしました（出典は前のまま）："
              f"{record.fact_line(item)}")
        return 0
    print("しませんでした：記録と違う値です（食い違い）。上書きしていません。")
    print("両方を出典付きで社長に示し、どちらが正しいかを決めてもらってください。")
    for old in existing:
        print(f"- 記録：{record.fact_line(old)}")
    print(f"- 新しい値：{record.value_text(item['値'])}（出典：{record.source_text(item['出典'])}）")
    first = existing[0]["id"]
    print(f"社長が新しい値に決めたら update-fact --id {first} で直し、記録のままでよければ confirm --id {first} で"
          "確かめた日を今日にしてください。")
    return 2


def _add_rule(folder, args, record) -> int:
    result, item = record.add_rule(folder, args.kind, args.content, args.trigger, _source(folder, args, record),
                                   case=args.case)
    if result == "same":
        print(f"もう覚えています（同じ区分・同じ内容）。何も足していません：{record.rule_line(item)}")
        return 0
    print(f"覚えました：{record.rule_line(item)}")
    print("版は、応答の終わりに自動で残ります。")
    return 0


def _confirm(folder, args, record) -> int:
    item = record.confirm(folder, args.id)
    print(f"確かめた日を {item['最後に確かめた日']} にしました：{record.fact_line(item)}")
    return 0


def _update(folder, args, record) -> int:
    changeable = True if args.changeable else (False if args.fixed else None)
    before, item = record.update_fact(folder, args.id, _value(args), _source(folder, args, record), changeable)
    print(f"直しました：{item['id']} {item['名前']}＝{record.value_text(before['値'])} → {record.value_text(item['値'])}")
    print(f"- 今の記録：{record.fact_line(item)}")
    print("前の値は、版の履歴に残ります。")
    return 0


def main(argv) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    try:
        args = parse(argv)
    except Refused as e:
        print(f"しませんでした：引数が足りないか違います（{e}）。何も変えていません。")
        return 2
    if args.command is None:
        print("する事（add-fact・add-rule・confirm・update-fact・list）を指してください。")
        return 2
    folder = Path(args.folder).expanduser() if args.folder else company.project_dir()
    if company.company_folder(folder) is None:
        print(f"{folder} は会社のフォルダではありません（.hojokin/ がありません）。何もしていません。"
              "会社のフォルダで動かしてください。")
        return 2
    try:
        from lib import company_record as record
    except Exception as e:  # 同梱のファイルが欠けた・壊れた、Python が古いなど
        print(f"補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。何もしていません。"
              "プラグインを入れ直してから、もう一度試してください。")
        return 1
    try:
        if args.command == "add-fact":
            return _add_fact(folder, args, record)
        if args.command == "add-rule":
            return _add_rule(folder, args, record)
        if args.command == "confirm":
            return _confirm(folder, args, record)
        if args.command == "update-fact":
            return _update(folder, args, record)
        try:
            from lib import record_changes  # 変更の履歴（版の履歴から作る。dulwich を読み込む）
            found = record_changes.changes(folder)
        except Exception:  # 版の履歴を読めなくても、一覧は出す
            found = {}
        print(record.listing(folder, found))
        return 0
    except (record.RecordError, Refused, ValueError) as e:  # ValueError は今日の日付の差し替えの書き方など
        print(f"しませんでした：{e}。記録は変えていません。")
        return 2
    except OSError as e:  # ファイルを読み書きできない（権限がない、ディスクがいっぱいなど）
        print(f"しませんでした：ファイルを読み書きできませんでした（{e}）。")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
