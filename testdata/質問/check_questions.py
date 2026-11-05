# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""T4-1 の質問20問と正解（TASKS A4 の下書き）を確かめる。

確かめること：
1. 質問.json・正解.json・質問の一覧.md が、make_questions.py で作り直したものと同じバイト列。どれにも「架空のテスト用データ」がある。
2. 20問で、答えが資料にあるもの15問・ないもの5問。番が1〜20。質問の文が重ならない。案件は省力化と持続化の2つ。
3. 出典の資料の id が、その案件の制度データの正解（testdata/正解/）の「資料」にある。
4. downloads/ があれば（なければ飛ばす）：
   - ある15問：見る語が、出典の最初のページの文字（形をそろえた後）にすべてある。ほかの出典のページにも、見る語が1つ以上ある。
   - ない5問：ない語が、その案件の資料のどのページの文字にもない。
5. 正解の値（答え・見る語）が、資料の文字と20字以上続けて同じでない（資料の文を写していない）。

合わないものがあれば、終了コード1で終わる。

動かし方：uv run --script testdata/質問/check_questions.py
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Dict, List

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

import make_questions as mq  # noqa: E402

COPY_LIMIT = 20


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(str.maketrans({c: "~" for c in "〜～∼"}))
    return re.sub(r"\s+", "", text)


def main() -> int:
    problems: List[str] = []
    for path, text in mq.build().items():
        if not path.is_file():
            problems.append(f"{path.name} がない（make_questions.py を流してください）")
        elif path.read_text(encoding="utf-8") != text:
            problems.append(f"{path.name} が make_questions.py の出力と違う（手で直さず、make_questions.py を流し直す）")
        if mq.MARK not in text:
            problems.append(f"{path.name} に「{mq.MARK}」がない")

    qs = mq.numbered()
    found = [q for q in qs if q["区分"] == mq.IN_DOCS]
    missing = [q for q in qs if q["区分"] == mq.NOT_IN_DOCS]
    if len(qs) != 20 or len(found) != 15 or len(missing) != 5:
        problems.append(f"問の数が 20（ある15、ない5）でない：{len(qs)}（{len(found)}、{len(missing)}）")
    if [q["番"] for q in qs] != list(range(1, 21)):
        problems.append("番が1〜20でない")
    if len({q["質問"] for q in qs}) != len(qs):
        problems.append("同じ質問の文がある")
    if {q["案件"] for q in qs} != set(mq.CASES):
        problems.append("案件が省力化と持続化の2つでない")
    for case, c in mq.CASES.items():
        seikai = json.loads((REPO / c["制度データの正解"]).read_text(encoding="utf-8"))
        ids = {d["id"] for d in seikai["資料"]}
        for q in found:
            if q["案件"] == case:
                for s in q["出典"]:
                    if s["資料"] not in ids:
                        problems.append(f"問{q['番']}：出典の資料「{s['資料']}」が {c['制度データの正解']} の資料にない")
        unknown = set(c["資料"]) - ids
        if unknown:
            problems.append(f"{case}：確かめる資料 {sorted(unknown)} が {c['制度データの正解']} の資料にない")

    have = all((REPO / p).is_file() for c in mq.CASES.values() for p in c["資料"].values())
    if not have:
        print("downloads/ に資料がないので、資料の文字との確かめは飛ばした")
    else:
        from lib import doc_text  # 同梱の pypdf で文字にする

        with tempfile.TemporaryDirectory() as tmp:
            dirs: Dict[str, Path] = {}
            for case, c in mq.CASES.items():
                for doc_id, rel in c["資料"].items():
                    out = Path(tmp) / doc_id.replace("&", "and")
                    doc_text.write_text(REPO / rel, out, {"id": doc_id, "名前": doc_id, "公募回": "-", "ハッシュ": ""})
                    dirs[doc_id] = out

            def page(doc_id: str, n: int) -> str:
                text = doc_text.page_text(dirs[doc_id], printed_page=n)
                return norm(text or "")

            def all_pages(doc_id: str) -> List[str]:
                index = doc_text.load_index(dirs[doc_id])
                return [norm(doc_text.read_page(dirs[doc_id], info)) for info in index["ページ"]]

            print("■ 答えが資料にある15問")
            for q in found:
                first = q["出典"][0]
                text = page(first["資料"], first["ページ"])
                lost = [w for w in q["見る語"] if norm(w) not in text]
                if lost:
                    problems.append(f"問{q['番']}：見る語 {lost} が {first['資料']} p.{first['ページ']} にない")
                for s in q["出典"][1:]:
                    other = page(s["資料"], s["ページ"])
                    if not any(norm(w) in other for w in q["見る語"]):
                        problems.append(f"問{q['番']}：{s['資料']} p.{s['ページ']} に見る語が1つもない")
                for value in [q["答え"]] + q["見る語"]:
                    v = norm(value)
                    for i in range(max(0, len(v) - COPY_LIMIT + 1)):
                        if len(v) >= COPY_LIMIT and v[i:i + COPY_LIMIT] in text:
                            problems.append(f"問{q['番']}：正解の値が資料の文と{COPY_LIMIT}字以上続けて同じ")
                            break
                where = "、".join(f"{s['資料']} p.{s['ページ']}" for s in q["出典"])
                print(f"  {q['番']:>2}. {q['質問']} → {q['答え']}（{where}）{'' if not lost else ' ×'}")
            print("■ 答えが資料にない5問")
            for q in missing:
                hits = []
                for doc_id in mq.CASES[q["案件"]]["資料"]:
                    for i, text in enumerate(all_pages(doc_id)):
                        for w in q["ない語"]:
                            if norm(w) in text:
                                hits.append(f"{doc_id} の PDF の {i + 1} ページ目に「{w}」")
                if hits:
                    problems.append(f"問{q['番']}：ない語が資料にある（{'、'.join(hits[:3])}）")
                print(f"  {q['番']:>2}. {q['質問']} → 書かれていない（{'・'.join(q['ない語'])} が {len(mq.CASES[q['案件']]['資料'])} 資料のどこにもない）{'' if not hits else ' ×'}")

    if problems:
        print("\n合わないもの：")
        for p in problems:
            print(f"- {p}")
        return 1
    print("\nすべて合った")
    return 0


if __name__ == "__main__":
    sys.exit(main())
