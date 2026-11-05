"""例年公募がある制度の一覧（同梱の知見）を出す道具（SPEC F1、DESIGN 9.1、TASKS A7・B21）。

会社のフォルダの設定では、プラグインの中のファイル（knowledge/）を Read で読めないので（実験 E6）、この道具が中身を出す。
会社のフォルダでなくても動く（探すことは許されている。SPEC 共通の要件）。何も書かない。

使い方：
  python3 -B <この場所>/reinen.py [--folder <会社のフォルダ>] [--name <名前の一部>] [--json]

- 制度ごとに、公式サイト・受付の形・これまでの公募（日付と出典URL）・合う取り組み・対象の目安・注意を出す。
- 「今日の区分の目安」：今日の日付（会社のフォルダなら、差し替えた日付）と、これまでの公募の日付から、
  公募中・公募予定（発表済み）・例年公募がある・確かめが要る のどれかを、わけと一緒に出す（日付の比べは道具で行う。DESIGN 6章）。
  一覧は確かめた日の記録なので、社長に示す前に、公式サイトで今の公募を確かめ直す。
- 予算の調べ先（当初予算・補正予算・概算要求の資料の場所）も出す。
- 終了コード：0 出した。2 引数が正しくない・名前に当たる制度がない。3 一覧のファイルが読めない（プラグインを入れ直す）。
"""

import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
from datetime import date  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

from lib import company, dates  # noqa: E402

LIST_FILE = PLUGIN_ROOT / "knowledge" / "例年公募がある制度の一覧.json"
STALE_DAYS = 30  # 確かめた日からこれだけたっていたら、古いかもしれないと添える
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")

OPEN = "公募中"
ANNOUNCED = "公募予定（発表済み）"
YEARLY = "例年公募がある"
CHECK = "確かめが要る"


def parse(argv):
    parser = argparse.ArgumentParser(description="例年公募がある制度の一覧を出す")
    parser.add_argument("--folder", help="会社のフォルダ（今日の日付の差し替えを読むだけ。なくてもよい）")
    parser.add_argument("--name", help="名前か略称の一部で絞る")
    parser.add_argument("--json", action="store_true", help="JSON で出す")
    return parser.parse_args(argv)


def day_of(text):
    """「2026-07-31 17:00」の形なら日付。「2026年12月上旬（予定）」のような形は None（まだ決まっていない）。"""
    if not isinstance(text, str):
        return None
    m = _ISO.match(text.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _label(entry):
    return entry.get("回", "（回の名前なし）")


def category(item, today):
    """今日の区分の目安と、そのわけ。"""
    form = item.get("受付の形", "")
    if form.startswith("随時"):
        return OPEN, "受付の形が随時（今も受け付けているかを公式サイトで確かめる）"
    if form.startswith("取組ごと"):
        return OPEN, "決まった公募の期間がなく、取組ごとに申請する（取り組む前に出す計画の時期を確かめる）"
    rounds = item.get("これまでの公募") or []
    for entry in rounds:
        start = day_of(entry.get("申請受付開始")) or day_of(entry.get("公募開始"))
        end = day_of(entry.get("締切"))
        if start and start <= today and end and today <= end:
            return OPEN, f"{_label(entry)}の申請の受付が、{entry.get('締切')} まで開いている"
    for entry in rounds:
        announced = day_of(entry.get("公募開始"))
        start = day_of(entry.get("申請受付開始"))
        end = day_of(entry.get("締切"))
        if announced and announced <= today and (start is None or today < start) and (end is None or today <= end):
            when = entry.get("申請受付開始", "まだ決まっていない")
            return ANNOUNCED, f"{_label(entry)}の公募が発表されていて、申請の受付は {when} から"
        if announced and today < announced:
            return ANNOUNCED, f"{_label(entry)}の公募が {entry.get('公募開始')} に始まる予定"
    for entry in rounds:
        start = day_of(entry.get("申請受付開始"))
        end_text = entry.get("締切")
        if start and start <= today and day_of(end_text) is None:
            if end_text:
                return CHECK, f"{_label(entry)}の締切が「{end_text}」で、日付が所在地などで変わる。公表の資料で確かめてから区分を決める"
            return CHECK, f"{_label(entry)}の受付は始まっているが、締切が記録にない。公式サイトの日程で確かめてから区分を決める"
    past = [e for e in rounds if day_of(e.get("締切")) and day_of(e.get("締切")) < today]
    if len(past) >= 2:
        names = "、".join(f"{_label(e)}（締切 {e.get('締切')}）" for e in past[-2:])
        return YEARLY, f"今は受け付けていない。直近の公募：{names}"
    if past:
        return YEARLY, f"今は受け付けていない。直近の公募は {_label(past[-1])}（締切 {past[-1].get('締切')}）だけが記録にある。もう1回前の時期は公式サイトで確かめる"
    return CHECK, "これまでの公募の日付が記録にない。公式サイトの日程で確かめる"


def load():
    data = json.loads(LIST_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("制度"), list):
        raise ValueError("「制度」の並びがありません")
    return data


def _line(value):
    if isinstance(value, list):
        return "\n".join(f"  - {v}" for v in value)
    return f"  {value}"


def report(data, items, today):
    checked = data.get("確かめた日", "")
    lines = [f"# 例年公募がある制度の一覧（同梱の知見。確かめた日：{checked}。今日：{dates.format_date(today)}）", ""]
    checked_day = day_of(checked)
    if checked_day and (today - checked_day).days > STALE_DAYS:
        lines.append(f"注意：確かめた日から{(today - checked_day).days}日たっています。公募の日付が古いかもしれません。")
        lines.append("")
    lines.append("この一覧は、確かめた日の公式サイトの記録です。社長に示す前に、公式サイトで今の公募を確かめ直してください"
                 "（通信できないときは、確かめられなかったと伝える）。所在地の都道府県・市区町村の制度は、ここにありません。")
    for item in items:
        cat, why = item["今日の区分の目安"]
        lines += ["", f"## {item.get('名前')}（{item.get('種類')}）",
                  f"- 略称：{item.get('略称')}",
                  f"- 所管：{item.get('所管')}",
                  f"- 公式サイト：{item.get('公式サイト')}"]
        if item.get("日程のページ"):
            lines.append(f"- 日程のページ：{item['日程のページ']}")
        lines.append(f"- 受付の形：{item.get('受付の形')}")
        lines.append(f"- 今日の区分の目安：{cat}（{why}）")
        rounds = item.get("これまでの公募") or []
        if rounds:
            lines.append("- これまでの公募：")
            for e in rounds:
                parts = [f"{k} {e[k]}" for k in ("公募開始", "申請受付開始", "締切") if e.get(k)]
                note = f"。{e['注記']}" if e.get("注記") else ""
                lines.append(f"  - {_label(e)}：{'、'.join(parts)}{note}（出典：{e.get('出典URL')}）")
        for old in item.get("前の制度") or []:
            past = "、".join(f"{_label(e)} 締切 {e.get('締切')}" for e in old.get("これまでの公募") or [])
            note = f"。{old['注記']}" if old.get("注記") else ""
            lines.append(f"- 前の制度：{old.get('名前')}" + (f"（{past}）" if past else "") + f"{note}（出典：{old.get('出典URL')}）")
        lines.append("- 合う取り組み：\n" + _line(item.get("合う取り組み") or []))
        target = item.get("対象の目安") or {}
        where = target.get("出典URL", "")
        if target.get("出典の資料"):
            where += f"、{target['出典の資料']}"
        lines.append(f"- 対象の目安：{target.get('内容')}（出典：{where}）")
        if item.get("注意"):
            lines.append("- 注意：\n" + _line(item["注意"]))
    lines += ["", "## 予算の調べ先（当初予算・補正予算・概算要求）"]
    for b in data.get("予算の調べ先") or []:
        lines.append(f"- {b.get('所管')}：{b.get('名前')} {b.get('URL')}")
    lines.append("予算の状況が見つからなければ「見つからなかった」と書き、推測しない（SPEC F1）。")
    return "\n".join(lines)


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse(argv)
    try:
        data = load()
    except (OSError, ValueError) as e:
        print(f"例年公募がある制度の一覧が読めませんでした（{e}）。プラグインを入れ直してください", file=sys.stderr)
        return 3
    folder = Path(args.folder) if args.folder else None
    try:
        today = dates.today(folder if folder is not None and company.is_company_folder(folder) else None)
    except ValueError as e:
        print(f"今日の日付が読めませんでした（{e}）", file=sys.stderr)
        return 2
    items = data["制度"]
    if args.name:
        items = [i for i in items if args.name in i.get("名前", "") or args.name in i.get("略称", "")]
        if not items:
            print(f"「{args.name}」に当たる制度は、一覧にありません（名前を変えるか、--name を外してください）", file=sys.stderr)
            return 2
    shown = []
    for item in items:
        item = dict(item)
        item["今日の区分の目安"] = category(item, today)
        shown.append(item)
    if args.json:
        out = {"確かめた日": data.get("確かめた日"), "今日": today.isoformat(), "予算の調べ先": data.get("予算の調べ先"),
               "制度": [dict(i, 今日の区分の目安={"区分": i["今日の区分の目安"][0], "わけ": i["今日の区分の目安"][1]})
                       for i in shown]}
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print(report(data, shown, today))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
