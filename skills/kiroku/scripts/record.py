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
  python3 -B <この場所>/record.py add-result --case <案件> --result <採択|不採択> [--pointed <審査項目> …] [--comment <受けた指摘>]
      --notice-date <通知の日> --source 原本 --file <採否の通知か指摘のメモの原本>
      申請と採否（受けた指摘）を足す（B6）。同じ案件・同じ結果があれば足さない。
  python3 -B <この場所>/record.py add-defect --case <案件> --stage <段階> --content <中身> --cause <原因>
                                            --watch <次に注意する書類> --rule <照合の決まり> --file <差し戻しの原本> --received <日>
      差し戻し（不備）を「不備と差し戻し」として残す（B32）。次からの書類集めで、不備チェックの物差しが前もって示す。
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
RESULTS = ("採択", "不採択")


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

    p = sub.add_parser("add-result", parents=[common, source], help="申請と採否（受けた指摘）を足す")
    p.add_argument("--case", required=True, help="申請した案件（例：2025_ものづくり補助金 20次締切）")
    p.add_argument("--result", required=True, choices=RESULTS, help="結果")
    p.add_argument("--pointed", action="append", default=[], help="指摘に当たる審査項目（いくつでも。--pointed を繰り返す）")
    p.add_argument("--comment", help="受けた指摘（審査のコメントや、不採択の後の相談で受けた指摘。指摘ごとに番号を付ける）")
    p.add_argument("--notice-date", required=True, help="採否の通知の日（2025-10-28 の形）")

    p = sub.add_parser("add-defect", parents=[common], help="差し戻し（不備）を、次に注意する型として残す")
    p.add_argument("--case", required=True, help="差し戻された案件")
    p.add_argument("--stage", required=True, help="手続きの段階のフォルダ（2_交付申請 など）")
    p.add_argument("--content", required=True, help="差し戻しの中身（何が違ったか）")
    p.add_argument("--cause", required=True, help="原因（なぜそうなったか）")
    p.add_argument("--watch", required=True, action="append", help="次に注意する書類（いくつでも。--watch 見積書）")
    p.add_argument("--rule", required=True, help="照合の決まり（次の書類集めで、何を照らすか）")
    p.add_argument("--file", required=True, help="差し戻しの文面か写真の原本（会社のフォルダの中の場所）")
    p.add_argument("--received", required=True, help="受け取った日（2027-06-02 の形）")

    sub.add_parser("list", parents=[common], help="覚えていることの一覧")
    return parser.parse_args(argv)


def _add_defect(folder, args, record) -> int:
    """差し戻しを「不備と差し戻し」として残す（B32。DESIGN 10章。次の書類集めで、不備チェックの物差しが前もって示す）。"""
    from lib import dates
    received = record._date_arg(args.received, "受け取った日（--received）")
    if not received:
        raise Refused("受け取った日（--received）を 2027-06-02 の形で渡してください")
    source = record.make_source(folder, "原本", file=args.file)
    texts = {"案件": args.case, "手続きの段階": args.stage, "内容": args.content, "原因": args.cause,
             "照合の決まり": args.rule}
    empty = [k for k, v in texts.items() if not (v or "").strip()]
    watch = [w.strip() for w in args.watch if w and w.strip()]
    if empty or not watch:
        raise Refused(f"空の欄があります（{'、'.join(empty + ([] if watch else ['次に注意する書類']))}）")
    data = record.load(folder)
    for item in data["項目"]:
        if item.get("種類") == record.DEFECT and item.get("案件") == texts["案件"].strip() \
                and record.normalize(item.get("内容", "")) == record.normalize(texts["内容"]) \
                and item.get("出典", {}).get("ファイル") == source.get("ファイル"):
            print(f"もう覚えています（同じ案件・同じ中身・同じ原本）。何も足していません：{item['id']}")
            return 0
    item = {"id": record._next_id(data, record.DEFECT), "種類": record.DEFECT,
            **{k: v.strip() for k, v in texts.items()}, "次に注意する書類": watch, "出典": source,
            "受け取った日": received, "覚えた日": dates.today(folder).isoformat()}
    data["項目"].append(item)
    record.save(folder, data)
    print(f"覚えました：{item['id']}（{item['案件']}／{item['手続きの段階']}）{item['内容']}。"
          f"次に注意する書類：{'、'.join(watch)}。照合の決まり：{item['照合の決まり']}")
    print("次からの書類集めでは、shorui の不備チェックの物差し（過去の差し戻しの型）に出て、前もって注意します。"
          "版は、応答の終わりに自動で残ります。")
    return 0


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


def _add_result(folder, args, record) -> int:
    """申請と採否を足す（SPEC F13「最初に会社の資料と過去の書類から学ぶ」、DESIGN 10章。TASKS B6）。

    同じ案件・同じ結果がもうあれば、足さない（指摘が増えたときは、社長に確かめて記録を直してもらう）。
    出典は採否の通知か、受けた指摘のメモの原本（--source 原本 --file …）。
    """
    case = (args.case or "").strip()
    if not case:
        raise Refused("申請した案件（--case）が空です")
    pointed = [p.strip() for p in args.pointed if p and p.strip()]
    comment = (args.comment or "").strip()
    if args.result == "不採択" and not pointed and not comment:
        raise Refused("不採択のときは、受けた指摘（--comment）か、指摘に当たる審査項目（--pointed）を渡してください。"
                      "指摘が分からなければ、--comment に「指摘は分からない（理由は開示されていない）」と書く")
    notice = record._date_arg(args.notice_date, "通知の日（--notice-date）")
    data = record.load(folder)
    for item in data["項目"]:
        if item["種類"] == record.RESULT and record.normalize(item["案件"]) == record.normalize(case) \
                and item["結果"] == args.result:
            print(f"もう覚えています（同じ案件・同じ結果）。何も足していません：[{item['id']}] {item['案件']}：{item['結果']}")
            return 0
    item = {"id": record._next_id(data, record.RESULT), "種類": record.RESULT, "案件": case, "結果": args.result,
            "指摘された審査項目": pointed, "出典": _source(folder, args, record), "通知の日": notice,
            "覚えた日": record.dates.today(folder).isoformat()}
    if comment:
        item["審査コメント"] = comment
    data["項目"].append(item)
    record.save(folder, data)
    shown = "、".join(pointed) or "なし"
    print(f"覚えました：[{item['id']}] {case}：{args.result}（指摘された審査項目：{shown}。"
          f"出典：{record.source_text(item['出典'])}。通知の日 {notice}）")
    print("次の申請書を書くときは、この指摘に応える記述を入れ、審査役が「過去の指摘」で確かめます。版は、応答の終わりに自動で残ります。")
    return 0


def main(argv) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    try:
        args = parse(argv)
    except Refused as e:
        print(f"しませんでした：引数が足りないか違います（{e}）。何も変えていません。")
        return 2
    if args.command is None:
        print("する事（add-fact・add-rule・add-result・confirm・update-fact・add-defect・list）を指してください。")
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
        if args.command == "add-result":
            return _add_result(folder, args, record)
        if args.command == "add-defect":
            return _add_defect(folder, args, record)
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
