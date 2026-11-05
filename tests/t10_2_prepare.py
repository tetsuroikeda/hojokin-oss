"""デスクトップでの通し（T10-2・T10-3 の残り、TASKS B29）の会社のフォルダを用意する。

  /usr/bin/python3 tests/t10_2_prepare.py <会社のフォルダ> [--state 書く前]

1. 保存した状態（既定は「書く前」。省力化の前半を通した後のデモの会社。制度データは正解の第8回）を、
   evals/_lib/fukugen.py で <会社のフォルダ> に戻す（フォルダが空か、ないときだけ。downloads/ が要る）。
2. 案件の段階のフォルダ（1_申請）の「添付する書類/」に、添付する写し（架空。tests/t10_2_tool.py の ATTACHMENTS）を置く。
3. 入力シート.xlsx を、制度データの申請画面から作り、ツールが入れるすべての欄にデモの会社（架空）の値を書く
   （lib/input_sheet.py。kaku の yoshiki.py sheet と同じ形）。添付の欄の値は、置いた写しの場所。
4. 次にすること（模擬画面のサーバーの起動、/hojokin:nyuryoku に渡す言葉、記録の照らし方）を出す。

入力シートを kaku に作らせる通し（デモ）とは別に、画面入力（nyuryoku）だけを短く確かめるための準備。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
TESTS = Path(__file__).resolve().parent
REPO = TESTS.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TESTS))

import t10_2_tool as t2  # noqa: E402

from lib import input_sheet  # noqa: E402

STAGE = "1_申請"


def main(argv) -> int:
    parser = argparse.ArgumentParser(description="T10-2 のデスクトップでの通しの会社のフォルダを用意する")
    parser.add_argument("folder", type=Path, help="会社のフォルダ（空か、まだないフォルダ。戻した後なら、そのまま足す）")
    parser.add_argument("--state", default="書く前", help="戻す保存した状態（既定は 書く前）")
    args = parser.parse_args(argv)
    folder = args.folder.expanduser().resolve()
    if not folder.exists() or not any(folder.iterdir()):
        folder.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([sys.executable, "-B", str(REPO / "evals" / "_lib" / "fukugen.py"), args.state, str(folder)])
        if r.returncode != 0:
            print(f"保存した状態「{args.state}」を戻せませんでした（終了コード {r.returncode}）。")
            return 1
    if not (folder / ".hojokin").is_dir():
        print(f"{folder} は会社のフォルダではありません（.hojokin/ がありません）。空のフォルダを渡してください。")
        return 2
    cases = sorted(p.name for p in (folder / "案件").iterdir() if p.is_dir() and (p / STAGE).is_dir())
    if len(cases) != 1:
        print(f"案件/ に、{STAGE} のある案件が{len(cases)}つあります（{'、'.join(cases)}）。1つの形で用意してください。")
        return 2
    case = cases[0]
    seido_files = sorted((folder / "記録" / "制度データ").glob("*.json"))
    if len(seido_files) != 1:
        print("記録/制度データ/ に制度データが1つではありません。")
        return 2
    seido = json.loads(seido_files[0].read_text(encoding="utf-8"))
    placed = t2.place_attachments(folder, case, STAGE)
    values = t2.demo_values(seido, case, STAGE)
    sheet = folder / "案件" / case / STAGE / "申請書" / input_sheet.FILE_NAME
    sheet.parent.mkdir(parents=True, exist_ok=True)
    sheet.write_bytes(t2.write_sheet(seido, values))
    filled = [v for v in values if not input_sheet.is_not_applicable(v["値"]) and v["値"] != "いいえ"]
    print(f"用意しました：{folder}")
    print(f"- 入力シート：案件/{case}/{STAGE}/申請書/{input_sheet.FILE_NAME}（ツールが入れる欄 {len(values)}、"
          f"そのうち「該当なし」「いいえ」でない値 {len(filled)}）")
    print(f"- 添付する写し：{len(placed)}件（案件/{case}/{STAGE}/添付する書類/）")
    print("次にすること：")
    print(f"1. 模擬画面：python3 {REPO}/mock/server.py --screens --reset --record-dir <記録のフォルダ>")
    print(f"2. デスクトップアプリで {folder} を開き、/hojokin:nyuryoku と送る（下の手順は報告の「明日の通し」）")
    print(f"3. 照らす：HOJOKIN_T10_2_RECORD=<記録のフォルダ> HOJOKIN_T10_2_FOLDER={folder} "
          f"uv run pytest -q tests/test_T10_2.py -k desktop -s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
