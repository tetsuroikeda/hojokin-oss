"""申請の締切から逆算した日程・加点が間に合うかの判定・申請の書類の一覧を出す道具（SPEC F3・T3-2・T3-3・T3-4。lib/nittei.py）。

使い方：
  python3 -B <この場所>/nittei.py --folder <会社のフォルダ> [--case <案件>] [--json]          日程と加点の判定
  python3 -B <この場所>/nittei.py --folder <会社のフォルダ> [--case <案件>] --docs [--json]   書類の一覧

- 制度データ（`記録/制度データ/<略称>_<公募回>.json`）と、会社の記録の「依頼の目安の日数：<書類>」「加点の日数：<加点>」と、
  今日の日付（差し替えを含む）から作る。日付は道具が計算する（Claude は頭で計算しない）。
- 何も書かない。
- 終了コード：0 出した。2 何もしていない（会社のフォルダでない、案件を決められない、制度データがない など）。3 補助プログラムが動かない。
"""

import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

NOT_DONE = "何もしていません："


def parse(argv):
    parser = argparse.ArgumentParser(description="申請までの日程・加点の判定・書類の一覧")
    parser.add_argument("--folder", required=True)
    parser.add_argument("--case", help="案件のフォルダの名前（1つしかなければ省ける）")
    parser.add_argument("--docs", action="store_true", help="書類の一覧（必須・条件付き・任意と、効く審査項目・加点）")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse(argv)
    try:
        from lib import company, dates, deadlines, nittei, seido_data, urakadori
    except Exception as e:  # 同梱のファイルが欠けた・壊れた
        print(f"{NOT_DONE}補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。プラグインを入れ直してください。")
        return 3
    folder = Path(args.folder)
    if not company.is_company_folder(folder):
        print(f"{NOT_DONE}ここは会社のフォルダではありません（.hojokin/ がありません）。")
        return 2
    try:
        case = urakadori.find_case(folder, args.case)
        _path, data = seido_data.load_data(folder, case)
    except (ValueError, OSError) as e:
        print(f"{NOT_DONE}{e}")
        return 2
    try:
        if args.docs:
            if args.json:
                print(json.dumps(nittei.doc_list(data), ensure_ascii=False, indent=1))
            else:
                print(f"案件：{case}")
                print(nittei.doc_report(data))
            return 0
        today = dates.today(folder)
        facts = deadlines._company_facts(folder)
        sched = nittei.build_schedule(data, today, facts, deadlines._case_round(folder, case))
        if args.json:
            print(json.dumps(sched.as_dict(), ensure_ascii=False, indent=1))
        else:
            print(f"案件：{case}")
            print(nittei.report(sched, deadlines._title(data)))
        return 0
    except Exception as e:  # 途中で止まった
        print(f"{NOT_DONE}途中で止まりました（{type(e).__name__}: {e}）。プラグインを入れ直してから、もう一度試してください。")
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
