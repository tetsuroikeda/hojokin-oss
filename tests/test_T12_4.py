"""T12-4 計画と実績（SPEC F12「実績報告と効果報告では、実績を財務モデルに入れて計画と比べる」、DESIGN 4.6・8.3。TASKS B31c）。

合格ライン：計画を下回る実績を財務モデルに入れる → 計画との差が示される。満たせない要件があれば、返還の条件とあわせて示される。

材料は D9 の「計画を下回る実績」（testdata/計画書/材料/6_計画を下回る実績/。応募のときの財務モデルの指定と、1年目の実績）と、
正解（testdata/計画書/正解.json の「計画と実績（T12-4）」）。制度データは省力化 第8回の正解。目標値（4.0%）と交付額
（15,000,000円。testdata/期限 の交付決定通知書）は、kaku が提出版の計画書と通知から読んで渡す値として渡す。
道具（skills/kaku/scripts/zaimu_model.py の compare）は、Claude が Bash で動かすのと同じ形で動かす。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import hook_runner as hr
import pytest
from lib import jisseki, zaimu

MATERIAL = hr.REPO_ROOT / "testdata" / "計画書" / "材料" / "6_計画を下回る実績"
ANSWER = json.loads((hr.REPO_ROOT / "testdata" / "計画書" / "正解.json").read_text(encoding="utf-8"))["計画と実績（T12-4）"]
SEIDO = json.loads((hr.REPO_ROOT / "testdata" / "正解" / "省力化_第8回.json").read_text(encoding="utf-8"))
TOOL = hr.REPO_ROOT / "skills" / "kaku" / "scripts" / "zaimu_model.py"


def spec():
    data = json.loads((MATERIAL / "財務モデルの指定.json").read_text(encoding="utf-8"))
    return zaimu.parse_spec({k: v for k, v in data.items() if k != "説明"})


def actual() -> dict:
    return json.loads((MATERIAL / "実績_1年目.json").read_text(encoding="utf-8"))


def by_name(result: dict, head: str) -> dict:
    found = [j for j in result["要件"] if j["名前"].startswith(head)]
    assert len(found) == 1, [j["名前"] for j in result["要件"]]
    return found[0]


def test_rows_and_indicators_match_the_answer() -> None:
    result = jisseki.compare(spec(), SEIDO, actual(), target=4.0, grant=15000000)
    assert result["年"] == 1
    for key, want in ANSWER["行ごとの差（円）"].items():
        got = result["行ごとの差（円）"][key]
        assert (got["計画"], got["実績"], got["差"]) == (want["計画"], want["実績"], want["差"]), key
        assert got["差の割合（%）"] == want["差の割合（%）"], key
    for key, want in ANSWER["指標"].items():
        got = result["指標"][key]
        assert got["基準年度"] == pytest.approx(want["基準年度"], abs=0.01)
        assert got["計画"] == pytest.approx(want["計画"], abs=0.01)
        assert got["実績"] == pytest.approx(want["実績"], abs=0.01)


def test_requirements_with_repayment_conditions() -> None:
    result = jisseki.compare(spec(), SEIDO, actual(), target=4.0, grant=15000000)
    want = {r["名前"].split("（")[0]: r for r in ANSWER["要件"]}
    productivity = by_name(result, "労働生産性の年平均成長率")
    assert productivity["実績の伸び（%）"] == want["労働生産性の年平均成長率"]["実績の伸び（1年目）"] == 2.02
    assert productivity["計画の伸び（%）"] == 10.89
    assert productivity["判定"] == "満たさない（1年目）"
    assert "資料から読み取れません" in productivity["返還の条件"]  # 未達のときの定めは資料にない（正解の G34）

    pay = by_name(result, "1人当たり給与支給総額の年平均成長率")
    assert pay["実績の伸び（%）"] == 1.2 and pay["目標値（%）"] == 4.0
    assert pay["判定"].startswith("届かない見込み")
    assert pay["届くのに要る伸び（残りの年、毎年。%）"] == 4.71
    assert "達成率" in pay["返還の条件"] and pay["返還の条件の出典"] == "要領8 p.13、応募手引8 p.35"
    example = want["1人当たり給与支給総額の年平均成長率"]["返還額の例（最終年度まで同じ伸びなら）"]
    assert pay["返還額の目安"]["達成率"] == example["達成率"] == 0.3
    assert pay["返還額の目安"]["返還額"] == example["返還額"] == 10500000

    # 付加価値額の増加は、制度データの基準に「◯%以上」がなく道具では判定しない要件。指標の表で、基準年度より増えたことを示す
    added = result["指標"]["付加価値額"]
    assert added["実績"] > added["基準年度"] and added["実績"] == ANSWER["指標"]["付加価値額"]["実績"]
    assert result["満たさない・届かない要件"] == ["労働生産性の年平均成長率", "1人当たり給与支給総額の年平均成長率"]
    text = jisseki.report(result)
    assert "| 売上 | 214,400,000 | 205,200,000 | -9,200,000 | -4.3% |" in text
    assert "返還の条件：達成率" in text and "10,500,000円" in text


def test_tool_prints_the_comparison(tmp_path: Path) -> None:
    """道具（zaimu_model.py compare）が、会社のフォルダの中の指定と実績から、差と返還の条件を出す。"""
    folder = tmp_path / "やまぶき惣菜"
    (folder / ".hojokin").mkdir(parents=True)
    (folder / "記録" / "一時").mkdir(parents=True)
    (folder / "記録" / "制度データ").mkdir(parents=True)
    (folder / "記録" / "財務モデルの指定.json").write_bytes((MATERIAL / "財務モデルの指定.json").read_bytes())
    (folder / "記録" / "一時" / "実績.json").write_bytes((MATERIAL / "実績_1年目.json").read_bytes())
    (folder / "記録" / "制度データ" / "省力化_第8回.json").write_text(json.dumps(SEIDO, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([hr.real_python(), "-B", str(TOOL), "compare", "--folder", str(folder),
                        "--spec", "記録/財務モデルの指定.json", "--actual", "記録/一時/実績.json",
                        "--target", "4.0", "--grant", "15000000"], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert "| 営業利益 | 8,396,400 | 3,250,000 | -5,146,400 | -61.3% |" in r.stdout
    assert "届かない見込み" in r.stdout and "返還の条件" in r.stdout and "10,500,000円" in r.stdout
    r = subprocess.run([hr.real_python(), "-B", str(TOOL), "compare", "--folder", str(folder),
                        "--spec", "記録/財務モデルの指定.json", "--actual", "../外.json"], capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 2, (r.stdout, r.stderr)  # 会社のフォルダの外は読まない
