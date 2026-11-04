# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""回答表の変種（TASKS D3）を確かめ、デモの会社の回答表との違いを出す。

確かめること：
1. 変種・T0-10_設定.json・回答表の一覧.md が、make_variants.py で作り直したものと同じバイト列。どれにも「架空のテスト用データ」がある。
2. 変種は、デモの会社の回答表と同じ ID が同じ順に並び、違うのは決めた ID の答えだけ。
3. 所在地の変種：3つの区分（大都市・地方の県庁所在地・町村）が1つずつあり、都道府県が3つとも違う。
   B-01 に決めた都道府県と市区町村がある。ほかの所在地の名前（デモの「東京」「大田」）が、B-01 のほかに出ない。
   A-15 の市外局番が変わる（大都市はデモのまま）。
4. 従業員25人：C-01 が25人で、正社員とパートの和が25。C-02 の内訳の和が正社員の数。D-03 の内訳の和が合計。
   E-02 の内訳の和が F-01 の第18期。
5. 賃上げの計画が立たない：D-08 に、賃上げの率（%）や金額の約束がない。
6. 情報を一部抜いた：替えた行がすべて「（空け）」。
7. T0-10：見る語（大家・家主・予備）が、デモの会社の回答表・変種・testdata/ のほかの文字のファイルにない。
   downloads/ があれば、省力化 第8回の公募要領と応募申請の手引きの文字にも「予備」がない（なければ、その確かめは飛ばす）。

合わないものがあれば、終了コード1で終わる。

動かし方：uv run --script testdata/回答表/check_variants.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, List

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import make_variants as mv  # noqa: E402

TEXT_SUFFIXES = (".md", ".json", ".py", ".txt", ".csv")


def number(text: str) -> int:
    return int(text.replace(",", ""))


def main() -> int:
    problems: List[str] = []
    built = mv.build()
    for path, text in built.items():
        if not path.is_file():
            problems.append(f"{path.name} がない（make_variants.py を流してください）")
            continue
        if path.read_text(encoding="utf-8") != text:
            problems.append(f"{path.name} が make_variants.py の出力と違う（手で直さず、make_variants.py を流し直す）")
        if mv.MARK not in text:
            problems.append(f"{path.name} に「{mv.MARK}」がない")

    demo = mv.DEMO_FILE.read_text(encoding="utf-8")
    demo_rows = mv.parse_rows(demo)
    demo_ids = [r[0] for r in demo_rows]
    variants: Dict[str, Dict[str, str]] = {}
    for v in mv.VARIANTS:
        text = built[HERE / v["ファイル"]]
        rows = mv.parse_rows(text)
        if [r[0] for r in rows] != demo_ids:
            problems.append(f"{v['ファイル']}：ID の並びがデモの会社の回答表と違う")
        changed = {d[0] for d in mv.diff_rows(demo, text)}
        if changed != set(v["替え"]):
            problems.append(f"{v['ファイル']}：違う行 {sorted(changed)} が、決めた行 {sorted(v['替え'])} と違う")
        variants[v["ファイル"]] = {rid: answer for rid, _item, answer in rows}

    # 3. 所在地の変種
    places = [v for v in mv.VARIANTS if "所在地" in v]
    kinds = [v["所在地"]["区分"] for v in places]
    if len(places) != 3 or len(set(kinds)) != 3 or not any("大都市" in k for k in kinds) \
            or not any("県庁所在地" in k for k in kinds) or kinds.count("町村") != 1:
        problems.append(f"所在地の変種の区分が、大都市・地方の県庁所在地・町村の3つになっていない：{kinds}")
    if len({v["所在地"]["都道府県"] for v in places}) != 3:
        problems.append("所在地の変種の都道府県が3つとも違うになっていない")
    demo_map = dict((r[0], r[2]) for r in demo_rows)
    for v in places:
        rows = variants[v["ファイル"]]
        pref, city = v["所在地"]["都道府県"], v["所在地"]["市区町村"]
        if pref not in rows["B-01"] or city not in rows["B-01"]:
            problems.append(f"{v['ファイル']}：B-01 に {pref}{city} がない")
        for rid, answer in rows.items():
            if rid in ("B-01", "B-02"):
                continue
            if v["替え"] and ("東京" in answer or "大田" in answer):
                problems.append(f"{v['ファイル']}：{rid} にデモの所在地の名前がある")
        if v["替え"] and rows["A-15"][:4] == demo_map["A-15"][:4]:
            problems.append(f"{v['ファイル']}：A-15 の市外局番がデモのまま")
        if not v["替え"] and rows != demo_map:
            problems.append(f"{v['ファイル']}：大都市の変種がデモの会社の回答表と違う")

    # 4. 従業員25人
    rows = variants["従業員25人.md"]
    m = re.match(r"(\d+)人。正社員(\d+)人とパート(\d+)人", rows["C-01"])
    if not m or int(m.group(1)) != 25 or int(m.group(2)) + int(m.group(3)) != 25:
        problems.append("従業員25人：C-01 が25人（正社員とパートの和が25）になっていない")
    else:
        regular = int(m.group(2))
        if sum(int(n) for n in re.findall(r"(\d+)人", rows["C-02"])) != regular:
            problems.append("従業員25人：C-02 の内訳の和が正社員の数と違う")
        d03 = [number(n) for n in re.findall(r"([\d,]+)千円", rows["D-03"])]
        if len(d03) != 3 or d03[0] != d03[1] + d03[2]:
            problems.append(f"従業員25人：D-03 の内訳の和が合計と違う {d03}")
        e02 = [number(n) for n in re.findall(r"([\d,]+)千円", rows["E-02"])]
        f01 = [number(n) for n in re.findall(r"([\d,]+)千円", rows["F-01"])]
        if len(e02) != 4 or sum(e02[:3]) != e02[3] or e02[3] != f01[-1]:
            problems.append(f"従業員25人：E-02 の内訳の和が F-01 の第18期と合わない {e02} {f01}")

    # 5. 賃上げの計画が立たない
    d08 = variants["賃上げの計画が立たない.md"]["D-08"]
    if re.search(r"\d+(\.\d+)?%|\d[\d,]*円", d08):
        problems.append("賃上げの計画が立たない：D-08 に率か金額の約束がある")

    # 6. 情報を一部抜いた
    lacking = next(v for v in mv.VARIANTS if v["ファイル"] == "情報を一部抜いた.md")
    for rid in lacking["替え"]:
        if variants["情報を一部抜いた.md"][rid] != mv.BLANK:
            problems.append(f"情報を一部抜いた：{rid} が「{mv.BLANK}」になっていない")

    # 7. T0-10 の見る語
    words = mv.T0_10["会社のこと"]["見る語"] + mv.T0_10["制度のこと"]["見る語"]
    own = {mv.LIST_FILE, mv.T0_10_FILE, HERE / "make_variants.py", HERE / "check_variants.py"}
    for path in sorted((REPO / "testdata").rglob("*")):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES or path in own:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for w in words:
            if w in text:
                problems.append(f"T0-10：「{w}」が {path.relative_to(REPO).as_posix()} にある（回答表にも記録にもない事柄にならない）")
    docs = [REPO / p for p in mv.T0_10["制度のこと"]["調べる資料"]]
    if all(p.is_file() for p in docs):
        sys.path.insert(0, str(REPO))
        from lib import doc_text  # 同梱の pypdf で文字にする

        for p in docs:
            pages = doc_text.pdf_pages(p)
            for w in mv.T0_10["制度のこと"]["見る語"]:
                hits = [i + 1 for i, t in enumerate(pages) if w in t]
                if hits:
                    problems.append(f"T0-10：「{w}」が {p.name} の PDF の {hits} ページ目にある（公募要領にない事柄にならない）")
        print(f"T0-10：{'・'.join(p.name for p in docs)} の文字に「{'」「'.join(mv.T0_10['制度のこと']['見る語'])}」がないことを確かめた")
    else:
        print("T0-10：downloads/ に省力化 第8回の資料がないので、公募要領の文字の確かめは飛ばした")

    # 違いを出す（行の終わりの確かめに使う）
    print(f"デモの会社の回答表：{len(demo_rows)}行")
    for v in mv.VARIANTS:
        diffs = mv.diff_rows(demo, built[HERE / v["ファイル"]])
        print(f"\n■ {v['ファイル']}（{v['名前']}。{'、'.join(v['使うテスト'])}）：違う行 {len(diffs)}")
        for rid, item, before, after in diffs:
            print(f"  {rid} {item}：{before[:40]} → {after[:60]}")
    print(f"\n■ T0-10_設定.json：最初の発言「{mv.T0_10['社長役の最初の発言']}」")

    if problems:
        print("\n合わないもの：")
        for p in problems:
            print(f"- {p}")
        return 1
    print("\nすべて合った")
    return 0


if __name__ == "__main__":
    sys.exit(main())
