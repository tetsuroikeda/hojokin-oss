"""書く前に、会社の記録から関係する事実と書き方の決まりを取り出す道具（SPEC F13「使い方と見せ方」、DESIGN 10章。TASKS M11）。

kaku が申請書の項目を書き始める前（書く前の質問を組み立てる前）に動かす。記録にあることは社長に聞かずに使い、
変わりうる情報は使い回す前に確かめる。記録から書いた箇所は、根拠対照表に記録の項目（出力の「根拠対照表の出典」）を残す。

使い方（--folder "${CLAUDE_PROJECT_DIR}" を付ける。なければ今いるフォルダ）：
  python3 -B <この場所>/relevant_records.py --item "<書く項目の名前>" [--item …] [--json]
      --item には、様式の項目の名前や、書こうとしていることを渡す（例：「常時使用する従業員数」「企業概要」）。
      名前が重なる事実を「当たりそうな事実」として先に並べ、ほかの事実、書き方の決まり、前の申請で受けた指摘も添える。
      --item を省くと、すべての事実を並べる。--json を付けると、同じ中身を JSON で出す。

- 終了コード：0 できた、1 補助プログラムを読み込めない、2 しなかった（会社のフォルダでない、記録が読めないなど）。
  この道具は記録を変えない。
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


class Refused(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused(message)


def parse(argv):
    parser = Parser(description="書く前に、会社の記録から関係する事実と書き方の決まりを取り出す")
    parser.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    parser.add_argument("--item", action="append", default=[], help="書く項目の名前（いくつでも）")
    parser.add_argument("--json", action="store_true", help="JSON で出す")
    return parser.parse_args(argv)


def main(argv) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    try:
        args = parse(argv)
    except Refused as e:
        print(f"しませんでした：引数が違います（{e}）。")
        return 2
    folder = Path(args.folder).expanduser() if args.folder else company.project_dir()
    if company.company_folder(folder) is None:
        print(f"{folder} は会社のフォルダではありません（.hojokin/ がありません）。何もしていません。"
              "会社のフォルダで動かしてください。")
        return 2
    try:
        from lib import company_record as record
    except Exception as e:  # 同梱のファイルが欠けた・壊れた、Python が古いなど
        print(f"補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。"
              "プラグインを入れ直してから、もう一度試してください。")
        return 1
    try:
        found = record.relevant(folder, args.item)
    except (record.RecordError, ValueError) as e:  # ValueError は今日の日付の差し替えの書き方など
        print(f"しませんでした：{e}。記録にあるはずのことも、推測で書かずに社長に確かめてください。")
        return 2
    except OSError as e:
        print(f"しませんでした：ファイルを読めませんでした（{e}）。")
        return 2
    if args.json:
        print(json.dumps(found, ensure_ascii=False, indent=2))
    else:
        head = check_lines(found, record)
        print(("\n".join(head) + "\n\n" if head else "") + record.relevant_text(found))
    return 0


CHECK_MAX = 20  # 先頭に並べる、確かめが要る事実の数


def check_lines(found: dict, record) -> list:
    """先頭に置く「使い回す前に確かめる変わりうる情報」の一覧（SPEC F13「変わりうる情報は確認する」。B7）。

    記録がある会社の2件目の申請で、変わりうる情報を確かめずに初稿に使わないよう、項目に当たるかどうかに関わらず、
    確かめが要る事実を先に並べる（どれを書く文に使うかは Claude が判断し、使うものだけを1問にまとめて確かめる）。
    """
    checks = [f for f in found["事実"] if f["使う前に確かめる"]]
    if not checks:
        return []
    lines = [f"## 使い回す前に確かめる変わりうる情報（{len(checks)}件）",
             "書く文に使うものは、書く前の最初の質問の1問目で「前回は◯でしたが、変わりましたか」とまとめて確かめる。"
             "確かめずに初稿に使わない（変わらなければ record.py confirm、変わったら record.py update-fact）。"]
    for f in checks[:CHECK_MAX]:
        lines.append(f"- [{f['id']}] {f['名前']}：{record.short(record.value_text(f['値']), 60)}"
                     f"（最後に確かめた日 {f['最後に確かめた日']}）")
    if len(checks) > CHECK_MAX:
        lines.append(f"- ほか{len(checks) - CHECK_MAX}件（下の事実の「変わりうる情報」を見る）")
    return lines


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
