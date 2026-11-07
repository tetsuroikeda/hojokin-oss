"""説明の練習の道具（skills/kaku/scripts/renshu.py。SPEC F11・T11-2、DESIGN 4.2）の、練習で問う審査項目の選び方。

確かめること（11/7 の採択後の通し：口頭審査の練習に、口頭審査の観点にない政策面を混ぜていた）：
- 口頭審査の練習（--oral）では、制度データの口頭審査の観点に名前が挙がった審査項目だけを問い、ほかの審査項目
  （政策面など、書面審査だけの項目）は「そのほか」に回す。観点が名前を並べた形でも、1つの文の形（第9回の読み取り）でも当たる。
- 口頭審査と言わないとき（--oral なし）は、今までどおりすべての審査項目を問う（SPEC T11-2）。
- 口頭審査の観点がない制度データでは、--oral でもすべてを問う（呼ぶ側が一言添える）。

材料は、このファイルの中の架空の審査項目（観点の文は、公募要領の文を写さず、このテストのために書いたもの）と、
testdata/正解/省力化_第8回.json（口頭審査の項目がない形）。
"""

from __future__ import annotations

import importlib.util
import json

from conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "skills" / "kaku" / "scripts" / "renshu.py"


def _load():
    spec = importlib.util.spec_from_file_location("renshu_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


renshu = _load()


def _item(name: str, kind: str, views) -> dict:
    return {"名前": name, "区分": kind, "観点": {"値": views, "出典": [{"資料": "要領", "ページ": 30}], "状態": "確認済み"}}


def items_round9() -> list:
    """第9回の読み取りの形：口頭審査の観点が、項目の名前を含む1つの文になっている（架空の文）。"""
    return [
        _item("補助対象事業としての適格性", "書面審査", ["要件を満たすか（架空）"]),
        _item("技術面", "書面審査", ["省力化の効果の根拠（架空）"]),
        _item("計画面", "書面審査", ["体制と資金（架空）"]),
        _item("政策面", "書面審査", ["地域への波及（架空）"]),
        _item("口頭審査の審査内容", "口頭審査",
              ["補助対象事業としての適格性、技術面、計画面の観点で見る（架空の文）",
               "計画書を補う質問や、申請を決めた背景を聞くことがある（架空の文）"]),
    ]


def names(items: list) -> list:
    return [it["名前"] for it in items]


def test_oral_practice_asks_only_the_oral_viewpoints_in_one_sentence_form() -> None:
    chosen, rest = renshu.pick_items(items_round9(), oral_only=True)
    assert names(chosen) == ["補助対象事業としての適格性", "技術面", "計画面"]
    assert names(rest) == ["政策面", "口頭審査の審査内容"]  # 政策面は口頭審査の観点にないので問わない


def test_oral_practice_also_reads_the_list_of_names_form() -> None:
    items = items_round9()
    items[-1]["観点"]["値"] = ["補助対象事業としての適格性", "技術面", "計画面"]  # 第8回の読み取りの形（名前を並べる）
    chosen, _rest = renshu.pick_items(items, oral_only=True)
    assert names(chosen) == ["補助対象事業としての適格性", "技術面", "計画面"]


def test_without_oral_every_item_is_asked() -> None:
    """「審査で聞かれそうなこと」の練習は、今までどおりすべての審査項目（SPEC T11-2。口頭審査の説明の項目は残す）。"""
    chosen, rest = renshu.pick_items(items_round9())
    assert names(chosen) == ["補助対象事業としての適格性", "技術面", "計画面", "政策面"]
    assert names(rest) == ["口頭審査の審査内容"]
    chosen, rest = renshu.pick_items(items_round9(), count=2, oral_only=True)
    assert names(chosen) == ["補助対象事業としての適格性", "技術面"] and "計画面" in names(rest)


def test_oral_without_oral_viewpoints_falls_back_to_every_item() -> None:
    data = json.loads((REPO_ROOT / "testdata" / "正解" / "省力化_第8回.json").read_text(encoding="utf-8"))
    items = renshu._items(data)
    assert renshu.oral_items(items) == []
    chosen, rest = renshu.pick_items(items, oral_only=True)
    assert names(chosen) == names(items) and rest == []  # T11-2 の5項目（政策面・減点を含む）


def test_oral_flag_is_accepted() -> None:
    assert renshu.parse(["--oral"]).oral is True
    assert renshu.parse([]).oral is False
