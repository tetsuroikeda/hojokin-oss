"""T5-4 書類の整理の準備（TASKS B9。testdata/書類の変化/材料の一覧.md の2章）。

保存した状態「書類の前」（原本のない形）を戻し、散らばった書類11件を、会社のフォルダの根・入れ口とその下・
社長が作ったフォルダに、材料のとおりの場所で写す。今日の日付は「書く前」と同じ 2026-11-05。
開いたときの控えは作らない（11件とも、開いたときに「増えた」として見つかる）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
import shorui_case as sc  # noqa: E402

target = sc.restore("書類の前")
sc.put_folder(target, "書類の変化/散らばった書類")
sc.done({"書類": 11})
