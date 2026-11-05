"""T5-1 不備の検出の準備（TASKS B12。testdata/書類セット/セットの一覧.md の「不備を仕込んだセット」）。

保存した状態「書類の前」（原本のない形。省力化 第9回の案件と、第8回の制度データの正解がある）を戻し、
不備を仕込んだセットの14件を入れ口に入れる。今日の日付は 2026-11-05（申請の日の範囲 2026-11-01〜2027-01-21 の中）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
import shorui_case as sc  # noqa: E402

target = sc.restore("書類の前")
sc.put_folder(target, "書類セット/不備を仕込んだセット", "入れ口")
sc.done({"セット": "不備を仕込んだセット"})
