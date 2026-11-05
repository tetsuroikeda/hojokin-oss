"""保存した状態「書く前」を戻した会社のフォルダに、計画書（その1・2 の Word）とその版を足す（eval の scaffold から。
TASKS B5（T13-14）・B8（T0-9））。

計画書の本文は testdata/計画書/材料/1_正しい計画書/本文.json（架空。D9）。公式の様式（downloads/ の Word）は使わず、
lib/docx_min.py で見出しと段落だけの Word を作る（eval の scaffold は /usr/bin/python3 で動き、python-docx などがないため。
T13-14・T0-9 が確かめるのは、言い回しの手直しと版の扱いで、様式の書式ではない）。

使い方（今いるフォルダ＝会社のフォルダ）：
  /usr/bin/python3 -B evals/_lib/keikaku.py tenaoshi   T13-14：ツールが書いた版を版の履歴に残し、社長が言い回しを1か所直した版に置き換える
                                                         （社長の分は版に残さない。開いたとき・送ったときに hook が「社長」で残す）
  /usr/bin/python3 -B evals/_lib/keikaku.py sanpan     T0-9：初稿・直し1・直し2の3つの版を「ツール」として残す（台本「前の版を見る・戻す」）
- 終了コード：0 できた、1 できなかった。
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import List, Optional

sys.dont_write_bytecode = True
LIB_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = LIB_DIR.parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

BODY = PLUGIN_ROOT / "testdata" / "計画書" / "材料" / "1_正しい計画書" / "本文.json"
ANSWER = PLUGIN_ROOT / "testdata" / "計画書" / "正解.json"
CASE = "2026_省力化（一般型）第9回"
PLAN = f"案件/{CASE}/1_申請/申請書/その1・2.docx"
# T0-9 の台本の直し（回答表 G-03・H-09 の事実。架空）
FIX1 = ("1-1 現状分析", "今は盛り付けから検品までを6人で、1日に延べ約38時間かけて手で行っています。")
FIX2 = ("5. 事業の実施体制とスケジュール", "機械を入れた後は、盛り付けから検品までを2人で、1日に延べ約14時間で回します。浮いた4人は冷凍惣菜づくりなどに回します。")


def items() -> List[dict]:
    return json.loads(BODY.read_text(encoding="utf-8"))["項目"]


def build(entries: List[dict], extra: Optional[dict] = None, replace: Optional[tuple] = None) -> bytes:
    from lib.docx_min import Document

    doc = Document()
    doc.title("事業計画書（その1・その2）")
    for entry in entries:
        doc.heading(entry["名前"], level=2)
        text = entry["本文"]
        if replace and replace[0] in text:
            text = text.replace(replace[0], replace[1], 1)
        for line in text.split("\n"):
            if line.strip():
                doc.paragraph(line)
        sentence = (extra or {}).get(entry["名前"])
        if sentence:
            doc.paragraph(sentence)
    return doc.to_bytes()


def put(folder: Path, blob: bytes) -> None:
    from lib.docx_min import write_replacing

    path = folder / PLAN
    path.parent.mkdir(parents=True, exist_ok=True)
    write_replacing(path, blob)


def record(folder: Path, reason: str, back_hours: float) -> None:
    from lib import dates, history

    history.record(folder, history.TOOL, reason, when=dates.now(folder) - timedelta(hours=back_hours))


def tenaoshi(folder: Path) -> None:
    fix = json.loads(ANSWER.read_text(encoding="utf-8"))["手直し（T13-14）"]
    put(folder, build(items()))
    record(folder, "計画書（その1・2）の初稿を書いて", 3)
    owner = build(items(), replace=(fix["ツールが書いた言い回し"], fix["社長が直した言い回し"]))
    if owner == build(items()):
        raise RuntimeError("直す言い回しが本文にありません")
    put(folder, owner)  # 社長が Word で直した（版には残さない）


def sanpan(folder: Path) -> None:
    put(folder, build(items()))
    record(folder, "計画書（その1・2）の初稿を書いて", 6)
    put(folder, build(items(), extra={FIX1[0]: FIX1[1]}))
    record(folder, "今の工程の人と時間を足して", 4)
    put(folder, build(items(), extra={FIX1[0]: FIX1[1], FIX2[0]: FIX2[1]}))
    record(folder, "機械を入れた後の人の回し方を書き足して", 2)


def main(argv: List[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    folder = Path(argv[1]).resolve() if len(argv) > 1 else Path.cwd()
    try:
        if argv and argv[0] == "tenaoshi":
            tenaoshi(folder)
        elif argv and argv[0] == "sanpan":
            sanpan(folder)
        else:
            print(__doc__, file=sys.stderr)
            return 1
    except Exception as e:
        print(f"keikaku: できませんでした（{type(e).__name__}: {e}）", file=sys.stderr)
        return 1
    print(f"keikaku: ok {argv[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
