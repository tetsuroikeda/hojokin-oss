# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""制度データと資料の材料（TASKS D10）を確かめ、混ぜたものの一覧と新旧2版で変わった箇所を出す。

確かめること：
1. 混ぜたものの一覧.json・新旧2版の正解.json・材料の一覧.md が、make_materials.py で作り直したものと同じバイト列。
   どれにも「架空のテスト用データ」がある。T3-8 の混ぜ方の3つ（SPEC T3-8）が、どれも1件以上ある。T4-2 に混ぜた答えと
   混ぜていない答えがある。T7-1 に変更ありと変更なしの組がある。
2. downloads/ があれば、材料を一時の場所に作って、今の道具で照らす（なければ飛ばす）。
   - T3-8：2回の読み取りが、どちらも読み取り役の形に合う。1回目をページで裏取りする（lib/urakadori.py の verify）と、
     「出典のページと違う値」と「そのページにない根拠の文」の場所だけが要確認になる。2回目は1つも要確認にならない。
     1回目と2回目で値が違う場所は、「出典のページと違う値」と「2回の読み取りで食い違う重要な項目」の場所だけ。
     2つを合わせると、混ぜた場所がすべて入り、混ぜていない場所は入らない。
   - T4-2：引用が、示したページの文字（形をそろえた後）にない答えが、混ぜた答えと同じ。
   - T7-1：変更ありの組は、lib/kaitei.py で比べると、変わったページが正解のページと同じで、書き換えた語が変わった行に出る。
     変更なしの組は、変わった所が0件。どちらの組も、資料の一覧.json から前の版と後の版が対になる。

合わないものがあれば、終了コード1で終わる。

動かし方：uv run --script testdata/制度データ/check_materials.py
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Set

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

import make_materials as mm  # noqa: E402


def flat_values(reading: Dict) -> Dict[str, object]:
    out = {}
    part = reading["制度データ"]
    for item in part.get("補助額", []):
        for leaf in ("上限", "補助率"):
            out[f"補助額「{item['区分']}」の{leaf}"] = item[leaf]["値"]
    for item in part.get("決まった期日", []):
        out[f"決まった期日「{item['名前']}」の日時"] = item["日時"]["値"]
    return out


def main() -> int:
    problems: List[str] = []
    for path, text in mm.answers().items():
        if not path.is_file():
            problems.append(f"{path.name} がない（make_materials.py を流してください）")
        elif path.read_text(encoding="utf-8") != text:
            problems.append(f"{path.name} が make_materials.py の出力と違う（手で直さず、make_materials.py を流し直す）")
        if mm.MARK not in text:
            problems.append(f"{path.name} に「{mm.MARK}」がない")
    mixed = mm.mixed_answer()
    kinds = {v["混ぜ方"] for v in mm.T3_8_VALUES}
    for k in (mm.WRONG_VALUE, mm.OTHER_PAGE, mm.TWO_READINGS, mm.CONTROL):
        if k not in kinds:
            problems.append(f"T3-8 に「{k}」の値がない")
    if not mixed["T4-2"]["混ぜた答え"] or not mixed["T4-2"]["混ぜていない答え"]:
        problems.append("T4-2 に、混ぜた答えと混ぜていない答えの両方がない")

    expected_check: Set[str] = set(mixed["T3-8"]["要確認になるべき場所"])
    page_kinds = {mm.place_label(v) for v in mm.T3_8_VALUES if v["混ぜ方"] in (mm.WRONG_VALUE, mm.OTHER_PAGE)}
    diff_kinds = {mm.place_label(v) for v in mm.T3_8_VALUES if v["混ぜ方"] in (mm.WRONG_VALUE, mm.TWO_READINGS)}

    print("■ T3-8：混ぜたもの")
    for v in mixed["T3-8"]["値"]:
        if v["混ぜ方"] != mm.CONTROL:
            print(f"  {v['場所']}：{v['混ぜ方']}（1回目 {json.dumps(v['1回目の値'], ensure_ascii=False)}、2回目 {json.dumps(v['2回目の値'], ensure_ascii=False)}）")
    print(f"  混ぜていない値：{len(mixed['T3-8']['確認済みのまま残るべき場所'])}")
    print("■ T4-2：混ぜた答え")
    for n, how in mixed["T4-2"]["混ぜ方"].items():
        print(f"  答え{n}：{how}")
    print("■ T7-1：書き換えた箇所（要領8 → 要領8_書き換え）")
    for r in mm.REWRITES:
        print(f"  {r['番']}. p.{r['ページ']}「{r['前']}」→「{r['後']}」：{r['変わったこと']}")
    print("  変更なしの組：書き換え0件")

    if not mm.have_downloads():
        print("\ndownloads/ に省力化 第8回の資料がないので、材料を作る確かめは飛ばした")
    else:
        from lib import kaitei, urakadori

        with tempfile.TemporaryDirectory() as tmp:
            built = mm.build(Path(tmp).resolve())  # /var → /private/var の別名をたどった場所にする（lib/places.py が別名を断るため）
            company = built["T3-8"]
            texts = urakadori.Texts(company, mm.CASE)
            # T3-8
            flagged: Dict[int, Set[str]] = {}
            for n, data in built["読み取り"].items():
                errors = urakadori.shape_errors(data)
                if errors:
                    problems.append(f"T3-8：{n}回目の読み取りの形が合わない：{errors[:3]}")
                    continue
                part = copy.deepcopy(data["制度データ"])
                result = urakadori.verify(part, texts)
                flagged[n] = {f.where for f in result.downgraded}
                print(f"\n■ T3-8 の{n}回目をページで裏取り：出典つき値 {result.values}、要確認 {len(flagged[n])}")
                for f in result.downgraded:
                    print(f"  {f.where}：{f.problems[0][:70]}")
            if flagged:
                if flagged.get(1) != page_kinds:
                    problems.append(f"T3-8：1回目で要確認になった場所 {sorted(flagged.get(1, set()))} が、ページの裏取りで見つかるはずの場所 {sorted(page_kinds)} と違う")
                if flagged.get(2):
                    problems.append(f"T3-8：2回目で要確認になった場所がある {sorted(flagged[2])}")
                one, two = flat_values(built["読み取り"][1]), flat_values(built["読み取り"][2])
                differ = {k for k in one if one[k] != two.get(k)}
                print(f"■ T3-8 の1回目と2回目で値が違う場所：{len(differ)}")
                for k in sorted(differ):
                    print(f"  {k}：{json.dumps(one[k], ensure_ascii=False)} と {json.dumps(two[k], ensure_ascii=False)}")
                if differ != diff_kinds:
                    problems.append(f"T3-8：値が違う場所 {sorted(differ)} が、決めた場所 {sorted(diff_kinds)} と違う")
                union = flagged.get(1, set()) | differ
                if union != expected_check:
                    problems.append(f"T3-8：見つかる場所の和 {sorted(union)} が、混ぜた場所 {sorted(expected_check)} と違う")
            # T4-2
            not_found = []
            for a in built["T4-2"]:
                q = a["引用"]
                page = mm._page(built["資料の本文"], q["資料"], q["ページ"])
                if urakadori.normalize(q["文"]) not in urakadori.normalize(page):
                    not_found.append(a["番"])
            print(f"\n■ T4-2：引用が示したページにない答え {not_found}（混ぜた答え {mixed['T4-2']['混ぜた答え']}）")
            if not_found != mixed["T4-2"]["混ぜた答え"]:
                problems.append("T4-2：引用が示したページにない答えが、混ぜた答えと違う")
            # T7-1
            for kind, company7 in built["T7-1"].items():
                listed = kaitei.load_listed(company7, mm.CASE)
                pairs = kaitei.doc_pairs(listed)
                if pairs != {"要領8": mm.NEW_ID}:
                    problems.append(f"T7-1 {kind}：資料の一覧から前の版と後の版が対にならない {pairs}")
                    continue
                diff = kaitei.page_diffs(company7, mm.CASE, pairs)["要領8"]
                print(f"■ T7-1 {kind}：変わった所 {len(diff.changes)}、変わったページ {diff.changed_new_pages}")
                for c in diff.changes:
                    print(f"  p.{c.new_page} {c.kind}：{' / '.join(c.old_lines)[:50]} → {' / '.join(c.new_lines)[:50]}")
                if kind == "変更あり":
                    want = sorted({r["ページ"] for r in mm.REWRITES})
                    if diff.changed_new_pages != want:
                        problems.append(f"T7-1 変更あり：変わったページ {diff.changed_new_pages} が正解 {want} と違う")
                    new_text = "\n".join(line for c in diff.changes for line in c.new_lines)
                    for r in mm.REWRITES:
                        if r["後"].replace(" ", "") not in new_text.replace(" ", ""):
                            problems.append(f"T7-1 変更あり：書き換え{r['番']}の「{r['後']}」が変わった行に出ない")
                elif not diff.same:
                    problems.append("T7-1 変更なし：変わった所がある")

    if problems:
        print("\n合わないもの：")
        for p in problems:
            print(f"- {p}")
        return 1
    print("\nすべて合った")
    return 0


if __name__ == "__main__":
    sys.exit(main())
