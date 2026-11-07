"""kaku をどの補助金にも使える形にした直し（11/7 の作者の指摘：省力化に寄りすぎ、図表が少ない）。

- 作者の知見（kakunin.py chiken）：審査の観点は、どの制度にも当てはまる観点と、この会社の制度データの制度の観点だけを出す。
  制度ごとの注（knowledge/制度ごと/省力化.md）は、制度の名前に「省力化」が入るときだけ出す。
- 推移の図（lib/zuhyo.py の trend_svg）：財務モデルの好きな行を1〜3つ選んで、年ごとの棒にする。数字は数字の控えから取る。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from lib import zuhyo  # noqa: E402

CHIKEN = REPO_ROOT / "skills" / "kaku" / "scripts" / "kakunin.py"


def company(tmp_path: Path, scheme: dict) -> Path:
    folder = tmp_path / "会社"
    (folder / ".hojokin").mkdir(parents=True)
    (folder / "記録" / "制度データ").mkdir(parents=True)
    (folder / "記録" / "制度データ" / "制度.json").write_text(json.dumps({"制度": scheme}, ensure_ascii=False),
                                                              encoding="utf-8")
    return folder


def chiken(folder: Path) -> str:
    r = subprocess.run(["/usr/bin/python3", "-B", str(CHIKEN), "chiken", "--folder", str(folder)],
                       capture_output=True, cwd=str(folder))
    assert r.returncode == 0, r.stdout.decode("utf-8") + r.stderr.decode("utf-8")
    return r.stdout.decode("utf-8")


def test_chiken_gives_only_the_scheme_notes_and_observations(tmp_path: Path) -> None:
    shoryoku = chiken(company(tmp_path / "a", {"名前": "中小企業省力化投資補助金", "枠": "一般型"}))
    assert "制度ごとの注（knowledge/制度ごと/省力化.md）" in shoryoku and "省力化指数と投資回収期間" in shoryoku
    assert '"制度": "省力化"' in shoryoku and '"制度": "持続化"' not in shoryoku
    jizoku = chiken(company(tmp_path / "b", {"名前": "小規模事業者持続化補助金", "枠": "一般型"}))
    assert "制度ごとの注" not in jizoku and "省力化指数" not in jizoku
    assert '"制度": "持続化"' in jizoku and '"制度": "省力化"' not in jizoku
    assert '"制度": "共通"' in jizoku


NUMBERS = {"合算": {"売上": [100.0, 120.0, 140.0], "営業利益": [5.0, 8.0, 12.0]},
           "指標": {"付加価値額": [30.0, 33.0, 36.0]},
           "投資の効果の見え方": {"営業利益率": [0.05, 0.066, 0.085]},
           "人数": {"常勤従業員数": [10.0, 10.0, 11.0]}}


def test_trend_figure_takes_rows_from_the_model() -> None:
    svg, title = zuhyo.trend_svg(NUMBERS, "売上・営業利益率・常勤従業員数")
    assert title == "売上・営業利益率・常勤従業員数の推移（基準年度と事業計画の2年間）"
    assert "8.5%" in svg and "11人" in svg and "基準" in svg and "2年目" in svg
    with pytest.raises(zuhyo.FigureError, match="選べるもの：売上・営業利益"):
        zuhyo.trend_svg(NUMBERS, "客数")
    with pytest.raises(zuhyo.FigureError, match="1〜3つ"):
        zuhyo.trend_svg(NUMBERS, "売上・営業利益・付加価値額・常勤従業員数")
    with pytest.raises(zuhyo.FigureError, match="1〜3つ"):
        zuhyo.trend_svg(NUMBERS, "")
