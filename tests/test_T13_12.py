"""T13-12 フォルダの移動（SPEC F13「会社の記録は会社のフォルダに置き、フォルダごと別のパソコンに移しても使える」、
DESIGN 10章、TASKS B3）。

合格ライン：会社のフォルダを別の場所にコピーして開く → 学んだ内容の一覧が同じに出る。フォルダの外を指す書き込み0件。

- 1件目で学んだ（事実・書き方の決まり・出典の書類・変更の履歴がある）会社のフォルダを、別の場所に丸ごと写す。
- 写した先で開き（SessionStart）、一覧（record.py list）を作ると、元の場所の一覧と1文字も違わない（変更の履歴も含む）。
- 写した先のファイル（版の履歴を含む）に、元の場所や写した先の場所（パソコンの中の絶対の場所）が書かれていない。
  開いた後・記録を足した後・応答の終わりの後も同じ。出典の書類は、会社のフォルダからの場所で残る。
- 版のファイルの形（同期されるフォルダ）でも同じ。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import company_tool as ct
import hook_runner as hr
import pytest
import version_tool as vt
from test_kiroku_min import RECORD, RECORD_FILE, record, run, set_today  # noqa: F401

DAY1 = "2026-11-04"
DAY2 = "2026-12-01"


def make_company(tmp_path: Path, form: str) -> vt.Company:
    c = vt.Company(tmp_path / "前", name="やまぶき 惣菜", form=form)
    for plugin in (c.env.plugin, c.plugin):
        shutil.copytree(hr.REPO_ROOT / "schema", plugin / "schema")
    set_today(c, DAY1)
    return c


def learn(c: vt.Company) -> None:
    """1件目で学ぶ：書類からの事実、聞き取りの答え、社長の指摘、ツールの直し（版が何件か残る）。"""
    c.write("原本/登記・名簿/2026-10-22_履歴事項全部証明書.pdf", b"%PDF-1.4 dummy")
    c.say("書類を入れました")
    ct.ok(run(c, RECORD, "add-fact", "--name", "資本金", "--value", "1,000万円", "--changeable", "--source", "原本",
              "--file", str(c.folder / "原本/登記・名簿/2026-10-22_履歴事項全部証明書.pdf"), "--page", "1"))
    ct.ok(run(c, RECORD, "add-fact", "--name", "従業員の数", "--value", "15人", "--changeable", "--source", "質問",
              "--question", "常時使用する従業員は何人ですか"))
    ct.ok(run(c, RECORD, "add-rule", "--kind", "避けたい言い方", "--content", "「〜を図る」は使わない",
              "--trigger", "この言い方は使わないで", "--source", "社長の発言", "--utterance", "この言い方は使わないで"))
    c.stop()
    set_today(c, DAY2)
    c.say("従業員は16人になりました")
    ct.ok(run(c, RECORD, "update-fact", "--id", "事実-0002", "--value", "16人", "--source", "社長の発言",
              "--utterance", "従業員は16人になりました"))
    c.stop()


def absolute_hits(folder: Path, needles) -> list:
    """フォルダの中のファイル（版の履歴の中身も、zlib の圧縮を開かずに読める所は）に、絶対の場所が書かれていないか。"""
    hits = []
    for p in sorted(folder.rglob("*")):
        if not p.is_file():
            continue
        data = p.read_bytes()
        blobs = [data]
        if "/.git/objects/" in p.as_posix():
            import zlib
            try:
                blobs.append(zlib.decompress(data))
            except zlib.error:
                pass
        for needle in needles:
            raw = needle.encode("utf-8")
            if any(raw in b for b in blobs):
                hits.append((p.relative_to(folder).as_posix(), needle))
    return hits


@pytest.mark.parametrize("form", [vt.GIT, vt.FILES])
def test_copied_folder_lists_the_same_and_writes_nothing_outside(tmp_path: Path, form: str) -> None:
    c = make_company(tmp_path, form)
    learn(c)
    before = ct.ok(run(c, RECORD, "list"))
    assert "変更の履歴" in before and "原本 原本/登記・名簿/2026-10-22_履歴事項全部証明書.pdf 1ページ" in before

    # 別の場所（別のパソコンのつもり）に丸ごと写す
    moved = tmp_path / "後" / "移した先" / c.folder.name
    shutil.copytree(c.folder, moved, symlinks=True)
    old_folder = str(c.folder)
    c.folder = moved  # 同じ道具と hook を、写した先で動かす

    # 開いて、一覧を作る：元の一覧と同じ
    vt.start_context(c.start())
    after = ct.ok(run(c, RECORD, "list"))
    assert after == before

    # 写した先で学び続けても（足す・応答の終わり）、外を指す書き込みはない
    c.say("強みも覚えておいて")
    ct.ok(run(c, RECORD, "add-fact", "--name", "強み", "--value", "病院・介護施設ごとの細かい注文に応えられる",
              "--changeable", "--source", "社長の発言", "--utterance", "病院・介護施設ごとの細かい注文に応えられる"))
    c.stop()
    data = record(c)
    sources = [it["出典"].get("ファイル") for it in data["項目"] if it["出典"].get("ファイル")]
    assert sources == ["原本/登記・名簿/2026-10-22_履歴事項全部証明書.pdf"]
    needles = [old_folder, str(moved), str(tmp_path)]
    assert absolute_hits(moved, needles) == []
    assert "強み＝" in ct.ok(run(c, RECORD, "list"))
    # 元のフォルダは、写した先の作業で変わらない
    old_items = json.loads((Path(old_folder) / RECORD_FILE).read_text(encoding="utf-8"))["項目"]
    assert all(it.get("名前") != "強み" for it in old_items)
