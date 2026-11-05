"""様式に1項目を書く（TASKS M6。SPEC F8「様式に書式を壊さずに書き込む」T8-1 の最小限、DESIGN 1.1・4.1・5章・6章・9.1）。

- 先に小さく試す：標準のライブラリ（ElementTree）で word/document.xml を読んで書き出すと、名前空間の宣言が落ちる。
  そのため、書く道具は XML のバイトの一部だけを差し替える（lib/xml_spans.py）。
- 一覧：様式の見出し・表・セルを、場所の名前付きで出す（読み取り役に渡す）。
- 対応づけ：読み取り役が返した書き込む位置を、様式と照らして確かめ、制度データに書く（正しくなければ書かない）。
- 書く：その1・2 の1項目（1-2 経営課題）と、入力シート.xlsx の1つの欄に書く。説明の青字は消す。
  書いた後に直前の版と比べ、範囲の外が1か所でも変わっていたら保存しない（直前の版のまま残る）。
- 会社のフォルダの外は読まない・書かない（lib/places.py）。

様式は downloads/ から読み、写しや書いたファイルは tmp_path にだけ作る（リポに入れない）。downloads/ がなければ飛ばす。
道具は、社長の Mac と同じ /usr/bin/python3 で、Claude が Bash で動かすのと同じく引数で場所を渡して動かす。
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Optional

import hook_runner as hr
import pytest

from lib import input_sheet, xml_spans
from lib import yoshiki_word as yw

REPO_ROOT = hr.REPO_ROOT
FORM = REPO_ROOT / "downloads" / "shoryokuka_ippan" / "yoshiki_business_plan_part1_part2_ippan.docx"
SEIDO = REPO_ROOT / "tests" / "data" / "yoshiki" / "制度データ_様式と画面.json"
SCRIPT = Path("skills") / "kaku" / "scripts" / "yoshiki.py"
CASE = "2026_省力化（一般型）第9回"
STAGE = "1_申請"
OFFICIAL = f"案件/{CASE}/公式資料/事業計画書 その1・その2（参考様式）_第8回.docx"
APP = f"案件/{CASE}/{STAGE}/申請書/その1・2.docx"
SHEET = f"案件/{CASE}/{STAGE}/申請書/入力シート.xlsx"
SEIDO_IN_FOLDER = "記録/制度データ/省力化_第8回.json"
FORM_NAME = "【参考様式】事業計画書（その1・その2）"

KEIEI = {"見出し": "１‐2経営課題", "場所": "t4.r2.c0.p0", "範囲": "見出しの後"}
PLAN_NAME = {"見出し": "（２）事業計画名（３０字程度）", "場所": "t1.r0.c0", "範囲": "セル"}
HOSOKU = {"見出し": "６. 補足事項", "場所": "t4.r11.c0.p0", "範囲": "見出しの後"}
BLUE = "0070C0"
KEIEI_TEXT = "受注が増えても、盛り付けと包装の人手が足りず、断る注文が出ている（試しの文）。\n繁忙期の残業が続き、人を増やしても定着しない（試しの文 & <記号>）。"
W = yw.W


@pytest.fixture(scope="module")
def form_bytes() -> bytes:
    if not FORM.is_file():
        pytest.skip("downloads/ に省力化の様式（その1・2）がありません（公式資料を取ってから流す）")
    return FORM.read_bytes()


# ---------------------------------------------------------------- 準備と動かし方


class Env:
    """プラグインの写しと、会社のフォルダ。"""

    def __init__(self, tmp_path: Path, form: bytes) -> None:
        self.root = tmp_path
        self.plugin = tmp_path / "plugin"
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
        for name in ("lib", "skills"):
            shutil.copytree(REPO_ROOT / name, self.plugin / name, ignore=ignore)
        self.home = tmp_path / "home"
        self.tmp = tmp_path / "tmp"
        self.cwd = tmp_path / "どこか"
        for d in (self.home, self.tmp, self.cwd):
            d.mkdir()
        self.folder = tmp_path / "山田 製作所"
        f = self.folder
        (f / ".hojokin").mkdir(parents=True)
        (f / "記録" / "制度データ").mkdir(parents=True)
        (f / SEIDO_IN_FOLDER).write_bytes(SEIDO.read_bytes())
        (f / OFFICIAL).parent.mkdir(parents=True)
        (f / OFFICIAL).write_bytes(form)
        (f / OFFICIAL).chmod(0o444)
        for sub in ("申請書", "添付する書類"):
            (f / "案件" / CASE / STAGE / sub).mkdir(parents=True)
        listed = f / "記録" / "資料の本文" / CASE / "資料の一覧.json"
        listed.parent.mkdir(parents=True)
        listed.write_text(json.dumps({"案件": CASE, "置き場所": {"Wordその1・2": {"ファイル": OFFICIAL}}},
                                     ensure_ascii=False), encoding="utf-8")

    def run(self, *args: str, stdin: bytes = b"", folder: Optional[Path] = None) -> subprocess.CompletedProcess:
        argv = list(args)
        argv[1:1] = ["--folder", str(folder or self.folder)]
        return subprocess.run(
            [hr.real_python(), "-B", str(self.plugin / SCRIPT), *argv],
            env={"PATH": "/usr/bin:/bin", "HOME": str(self.home), "TMPDIR": str(self.tmp)},
            cwd=self.cwd, input=stdin, capture_output=True, timeout=300,
        )

    def seido(self) -> dict:
        return json.loads((self.folder / SEIDO_IN_FOLDER).read_text(encoding="utf-8"))

    def set_positions(self, positions: Dict[str, dict]) -> None:
        """制度データに、対応づけた書き込む位置を直接置く（map を通さずに書く道具を試すとき）。"""
        data = self.seido()
        for form in data["様式"]:
            for entry in form["項目"]:
                if entry["名前"] in positions:
                    entry["書き込む位置"] = positions[entry["名前"]]
        (self.folder / SEIDO_IN_FOLDER).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def out(r: subprocess.CompletedProcess) -> str:
    return r.stdout.decode("utf-8")


def ok(r: subprocess.CompletedProcess) -> str:
    assert r.returncode == 0, (r.returncode, out(r), r.stderr.decode("utf-8"))
    assert r.stderr == b"", r.stderr.decode("utf-8")
    return out(r)


def refused(r: subprocess.CompletedProcess, code: int = 2) -> str:
    assert r.returncode == code, (r.returncode, out(r), r.stderr.decode("utf-8"))
    assert r.stderr == b"", r.stderr.decode("utf-8")
    return out(r)


def parts_of(blob: bytes) -> Dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        return {i.filename: zf.read(i) for i in zf.infolist()}


def doc_root(blob: bytes):
    data = parts_of(blob)[yw.DOC]
    return data, xml_spans.parse(data)


def root_start_tag(data: bytes) -> bytes:
    return re.search(rb"<w:document\b[^>]*>", data).group(0)


def blue_paragraphs(root) -> int:
    return sum(1 for p in yw._paragraphs(root) if yw.blue_state(p))


@pytest.fixture
def env(tmp_path: Path, form_bytes: bytes) -> Env:
    return Env(tmp_path, form_bytes)


# ---------------------------------------------------------------- 先に小さく試す（DESIGN 4.1）


def test_elementtree_roundtrip_drops_namespace_declarations(form_bytes: bytes) -> None:
    """標準のライブラリの ElementTree で読んで書き出すと、名前空間の宣言が落ち、mc:Ignorable の接頭辞が宣言されなくなる。
    （だから書く道具はバイトの一部だけを差し替える。差し替えた後は、根の宣言がそのまま残る）"""
    data = parts_of(form_bytes)[yw.DOC]
    tag = root_start_tag(data).decode("utf-8")
    declared = set(re.findall(r"xmlns:(\w+)=", tag))
    ignorable = set(re.search(r'mc:Ignorable="([^"]*)"', tag).group(1).split())
    assert ignorable <= declared and len(declared) >= 30
    rewritten = ET.tostring(ET.fromstring(data), encoding="utf-8")
    new_tag = re.search(rb"<[^ >]*document\b[^>]*>", rewritten).group(0).decode("utf-8")
    new_declared = set(re.findall(r"xmlns:(\w+)=", new_tag))
    assert len(new_declared) < len(declared)
    assert not ignorable <= new_declared  # mc:Ignorable が指す接頭辞の宣言がなくなる
    assert "ns0" in new_declared  # 接頭辞も ns0 などに変わる

    written, _summary = yw.write_item(form_bytes, KEIEI, KEIEI_TEXT, "1-2 経営課題")
    assert root_start_tag(parts_of(written)[yw.DOC]) == root_start_tag(data)


# ---------------------------------------------------------------- 一覧


def test_outline_lists_tables_cells_and_headings(env: Env) -> None:
    """様式の表・セル・文字のある段落を、場所の名前付きで出す。説明の青字には印を付ける。"""
    listed = json.loads(ok(env.run("outline", "--json")))
    assert listed["様式"] == OFFICIAL
    by_place = {e["場所"]: e for e in listed["一覧"]}
    assert by_place["t4"]["種類"] == "表" and by_place["t4"]["行"] == 12
    assert by_place["t0"]["行"] == 8 and by_place["t0"]["列"] == [2] * 8
    assert by_place["t1.r0.c0"] == {"場所": "t1.r0.c0", "種類": "セル", "段落": 1, "空": True, "深さ": 1}
    assert by_place["t4.r2.c0.p0"]["文字"] == "１‐2経営課題"
    assert by_place["p3"]["文字"].startswith("（２）事業計画名（３０字程度）")
    blue = [e for e in listed["一覧"] if e["場所"].startswith("t4.r2.c0.p") and e.get("説明の青字")]
    assert len(blue) == 2 and all(e["説明の青字"] == "全部" for e in blue)
    assert any(e.get("結合") == "横に2つ分" for e in listed["一覧"])  # 結合したセルも示す
    text = ok(env.run("outline"))
    assert "t4.r2.c0.p0 段落「１‐2経営課題」" in text
    assert "【説明の青字：全部】" in text
    # 一覧を作っても、何も書かない
    assert not (env.folder / APP).exists()


# ---------------------------------------------------------------- 対応づけ（読み取り役の結果を確かめて制度データに書く）


def test_map_writes_checked_positions_into_seido(env: Env) -> None:
    before = env.seido()
    mapping = {"様式": FORM_NAME, "対応": [
        {"項目": "1-2 経営課題", "書き込む位置": {"見出し": "１‐2経営課題", "範囲": "見出しの後"}},
        {"項目": "（２）事業計画名", "書き込む位置": PLAN_NAME},
    ]}
    text = ok(env.run("map", stdin=json.dumps(mapping, ensure_ascii=False).encode("utf-8")))
    assert "書き込む位置を2件書きました" in text
    after = env.seido()
    items = {e["名前"]: e for e in after["様式"][0]["項目"]}
    # 場所を省いても、見出しから場所を決めて書く
    assert items["1-2 経営課題"]["書き込む位置"] == KEIEI
    assert items["（２）事業計画名"]["書き込む位置"] == PLAN_NAME
    # 対応づけた2件のほかは変えない
    for form_b, form_a in zip(before["様式"], after["様式"]):
        for eb, ea in zip(form_b["項目"], form_a["項目"]):
            if eb["名前"] not in ("1-2 経営課題", "（２）事業計画名"):
                assert eb == ea
    assert {k: v for k, v in before.items() if k != "様式"} == {k: v for k, v in after.items() if k != "様式"}


@pytest.mark.parametrize("pair, reason", [
    ({"項目": "1-2 経営課題", "書き込む位置": {"見出し": "１‐2経営の課題", "範囲": "見出しの後"}}, "様式にありません"),
    ({"項目": "1-2 経営課題", "書き込む位置": {"見出し": "１‐2経営課題", "範囲": "表の右"}}, "範囲"),
    ({"項目": "（２）事業計画名", "書き込む位置": {"見出し": "（２）事業計画名（３０字程度）", "場所": "p3", "範囲": "セル"}},
     "セルではありません"),
    ({"項目": "（２）事業計画名", "書き込む位置": {"見出し": "（２）事業計画名（３０字程度）", "場所": "t2.r0.c0", "範囲": "セル"}},
     "見出し"),
    ({"項目": "（２）事業計画名", "書き込む位置": {"見出し": "（２）事業計画名（３０字程度）", "範囲": "見出しの後"}},
     "セルの中にありません"),
    ({"項目": "ない項目", "書き込む位置": KEIEI}, "項目「ない項目」がありません"),
])
def test_map_refuses_wrong_positions(env: Env, pair: dict, reason: str) -> None:
    """読み取り役の対応づけが様式と合わなければ、制度データを1件も変えない。"""
    before = (env.folder / SEIDO_IN_FOLDER).read_bytes()
    mapping = {"様式": FORM_NAME, "対応": [{"項目": "6. 補足事項", "書き込む位置": HOSOKU}, pair]}
    text = refused(env.run("map", stdin=json.dumps(mapping, ensure_ascii=False).encode("utf-8")))
    assert reason in text
    assert (env.folder / SEIDO_IN_FOLDER).read_bytes() == before


# ---------------------------------------------------------------- その1・2 の1項目に書く


def test_write_one_item_keeps_everything_outside_the_range(env: Env, form_bytes: bytes) -> None:
    """1-2 経営課題に書く。範囲の外（スタイル、余白、表の行と列、結合セル、ヘッダーとフッター、ほかの部品）は1バイトも
    変わらず、名前空間の宣言も残る。範囲の中の説明の青字は消え、書いた文字は青くならない。"""
    env.set_positions({"1-2 経営課題": KEIEI})
    text = ok(env.run("write", "--item", "1-2 経営課題", stdin=KEIEI_TEXT.encode("utf-8")))
    assert f"{APP} に、公式資料の様式から写して作り、「1-2 経営課題」を書きました" in text
    assert "説明の青字（2段落）" in text
    written = (env.folder / APP).read_bytes()
    assert (env.folder / OFFICIAL).read_bytes() == form_bytes  # 公式資料は変えない

    # 書いた文が、その項目の範囲にそのまま入っている
    assert yw.item_text(written, KEIEI) == KEIEI_TEXT
    # ほかの部品（スタイル、ヘッダー、番号、設定など）は1バイトも変わらない
    before_parts, after_parts = parts_of(form_bytes), parts_of(written)
    assert list(before_parts) == list(after_parts)
    changed = [n for n in before_parts if before_parts[n] != after_parts[n]]
    assert changed == [yw.DOC]
    # 本文も、範囲の外は1バイトも変わらない（範囲の前と後ろがそのまま）
    data_b, root_b = doc_root(form_bytes)
    data_a, root_a = doc_root(written)
    rng_b, rng_a = yw.resolve(root_b, KEIEI), yw.resolve(root_a, KEIEI)
    start_b, end_b = rng_b.nodes[0].start, rng_b.nodes[-1].end
    start_a, end_a = rng_a.nodes[0].start, rng_a.nodes[-1].end
    assert data_a[:start_a] == data_b[:start_b]
    assert data_a[end_a:] == data_b[end_b:]
    assert root_start_tag(data_a) == root_start_tag(data_b)
    # T8-1 の物差し：表の数・行と列・結合セル・節（用紙・余白・ヘッダーの参照）が同じ
    for name in ("tbl", "tr", "tc", "gridSpan", "vMerge", "sectPr", "pgMar", "headerReference"):
        assert sum(1 for n in root_a.iter() if n.is_(W, name)) == sum(1 for n in root_b.iter() if n.is_(W, name)), name
    assert [s.raw(data_a) for s in root_a.iter() if s.is_(W, "sectPr")] == \
        [s.raw(data_b) for s in root_b.iter() if s.is_(W, "sectPr")]
    # 道具の比べ方でも、範囲の外の差は0件。範囲を覆わなければ差が出る（比べ方が範囲の中も見ている）
    assert yw.compare_docx(form_bytes, written, [("1-2 経営課題", KEIEI)]) == []
    assert yw.compare_docx(form_bytes, written, []) != []
    # 説明の青字：範囲の中の2段落は消え、ほかの項目の青字は残る。書いた文字にも、段落の印にも色はない
    assert blue_paragraphs(root_a) == blue_paragraphs(root_b) - 2
    for node in rng_a.nodes:
        assert not yw.blue_state(node)
        assert not any(n.is_(W, "color") for n in node.iter())
        assert b"paraId" not in node.start_tag(data_a)  # 新しい段落に Word の段落の番号を付けない
    assert any(yw.blue_state(p) for p in yw.resolve(root_a, {"見出し": "１‐１現状分析", "範囲": "見出しの後"}).nodes)
    # 書いた段落の書式は、範囲の空の段落の書式を写したもの
    template = next(n for n in rng_b.nodes if n.is_(W, "p") and not yw.text_of(n).strip())
    ppr_b = template.find(W, "pPr")
    for p in rng_a.nodes:
        ppr_a = p.find(W, "pPr")
        assert [c.local for c in ppr_a.children] == [c.local for c in ppr_b.children]


def test_rewrite_replaces_the_previous_text(env: Env) -> None:
    """同じ項目に書き直すと、前の文が置き換わる。直前の版（1回目の版）と比べ、範囲の外は変わらない。"""
    env.set_positions({"1-2 経営課題": KEIEI})
    ok(env.run("write", "--item", "1-2 経営課題", "--text", "1回目の文（試し）"))
    first = (env.folder / APP).read_bytes()
    text = ok(env.run("write", "--item", "1-2 経営課題", "--text", "2回目の文（試し）\n2つ目の段落"))
    assert "公式資料の様式から写して" not in text
    second = (env.folder / APP).read_bytes()
    assert yw.item_text(second, KEIEI) == "2回目の文（試し）\n2つ目の段落"
    assert "1回目の文" not in yw.text_of(doc_root(second)[1])
    assert yw.compare_docx(first, second, [("1-2 経営課題", KEIEI)]) == []


def test_write_reads_text_from_a_file_inside(env: Env, tmp_path: Path) -> None:
    """書く文は、Claude が Write で置いた会社のフォルダの中のファイルでも渡せる（SKILL.md の手順）。外のファイルは読まない。"""
    env.set_positions({"1-2 経営課題": KEIEI})
    src = env.folder / "記録" / "一時" / "書く文.txt"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("ファイルから書く文（試し）\n2つ目の段落", encoding="utf-8")
    ok(env.run("write", "--item", "1-2 経営課題", "--input", "記録/一時/書く文.txt"))
    assert yw.item_text((env.folder / APP).read_bytes(), KEIEI) == "ファイルから書く文（試し）\n2つ目の段落"
    outside = tmp_path / "外の文.txt"
    outside.write_text("外の文", encoding="utf-8")
    text = refused(env.run("write", "--item", "1-2 経営課題", "--input", str(outside)))
    assert "会社のフォルダの外" in text


def test_second_item_keeps_the_first(env: Env) -> None:
    """別の項目（セルの形の（２）事業計画名）にも書ける。前に書いた項目はそのまま残る。"""
    env.set_positions({"1-2 経営課題": KEIEI, "（２）事業計画名": PLAN_NAME})
    ok(env.run("write", "--item", "1-2 経営課題", "--text", "経営課題の文（試し）"))
    first = (env.folder / APP).read_bytes()
    ok(env.run("write", "--item", "（２）事業計画名", "--text", "盛り付けと包装をつなぐ省力化の計画（試し）"))
    second = (env.folder / APP).read_bytes()
    assert yw.item_text(second, PLAN_NAME) == "盛り付けと包装をつなぐ省力化の計画（試し）"
    assert yw.item_text(second, KEIEI) == "経営課題の文（試し）"
    assert yw.compare_docx(first, second, [("（２）事業計画名", PLAN_NAME)]) == []


def test_write_refuses_unmapped_item(env: Env) -> None:
    """まだ対応づけていない項目には書かない（ファイルも作らない）。"""
    text = refused(env.run("write", "--item", "1-2 経営課題", "--text", "試し"))
    assert "まだ様式と対応づけられていません" in text
    assert not (env.folder / APP).exists()


def test_write_refuses_when_the_heading_is_gone(env: Env) -> None:
    """社長が見出しを書き換えて目印が見つからないときは、書かずに前のままにする。"""
    env.set_positions({"1-2 経営課題": KEIEI})
    ok(env.run("write", "--item", "1-2 経営課題", "--text", "1回目の文（試し）"))
    app = env.folder / APP
    parts = parts_of(app.read_bytes())
    edited = parts[yw.DOC].replace("１‐2経営課題".encode("utf-8"), "１‐2経営の課題".encode("utf-8"), 1)
    assert edited != parts[yw.DOC]
    app.write_bytes(yw.rebuild_zip(app.read_bytes(), {yw.DOC: edited}))
    before = app.read_bytes()
    text = refused(env.run("write", "--item", "1-2 経営課題", "--text", "2回目の文"))
    assert "見出し「１‐2経営課題」の段落が、様式にありません" in text
    assert app.read_bytes() == before


# ---------------------------------------------------------------- 範囲の外を変える書き込みは保存しない（否定の対照）


def _edit_doc(blob: bytes, old: bytes, new: bytes) -> bytes:
    data = parts_of(blob)[yw.DOC]
    assert old in data, old
    return yw.rebuild_zip(blob, {yw.DOC: data.replace(old, new, 1)})


def _edit_part(blob: bytes, name: str, old: bytes, new: bytes) -> bytes:
    data = parts_of(blob)[name]
    assert old in data, (name, old)
    return yw.rebuild_zip(blob, {name: data.replace(old, new, 1)})


def _add_row(blob: bytes) -> bytes:
    data, root = doc_root(blob)
    row = yw.node_at(yw.body_of(root), "t0").findall(W, "tr")[2]
    return yw.rebuild_zip(blob, {yw.DOC: xml_spans.splice(data, row.end, row.end, row.raw(data))})


def _write_in_checkbox_cell(blob: bytes) -> bytes:
    data, root = doc_root(blob)
    p = yw.node_at(yw.body_of(root), "t0.r1.c1.p0")
    t = next(n for n in p.iter() if n.is_(W, "t"))
    return yw.rebuild_zip(blob, {yw.DOC: xml_spans.splice(data, t.tag_end, t.tag_end, "■".encode("utf-8"))})


def _drop_declaration(blob: bytes) -> bytes:
    data = parts_of(blob)[yw.DOC]
    tag = root_start_tag(data)
    decl = re.search(rb' xmlns:w15="[^"]*"', tag).group(0)
    return yw.rebuild_zip(blob, {yw.DOC: data.replace(tag, tag.replace(decl, b""), 1)})


TAMPERS = {
    "余白": lambda b: _edit_doc(b, b'w:left="720" w:header="227"', b'w:left="900" w:header="227"'),
    "表に行を足す": _add_row,
    "□の選択肢のセルに書く": _write_in_checkbox_cell,
    "ほかの項目の説明の青字": lambda b: _edit_doc(b, "必要性を記載".encode("utf-8"), "必要を記載".encode("utf-8")),
    "スタイルの文字の大きさ": lambda b: _edit_part(b, "word/styles.xml", b'<w:sz w:val="21"/>', b'<w:sz w:val="22"/>'),
    "ヘッダー": lambda b: _edit_part(b, "word/header1.xml", b"<w:p ", b'<w:p w:rsidR="00ABCDEF" '),
    "名前空間の宣言": _drop_declaration,
    "部品を足す": lambda b: _add_part(b),
}


def _add_part(blob: bytes) -> bytes:
    buf = io.BytesIO(blob)
    with zipfile.ZipFile(buf, "a") as zf:
        zf.writestr("word/extra.xml", "<a/>")
    return buf.getvalue()


@pytest.fixture(scope="module")
def written_blob(form_bytes: bytes) -> bytes:
    written, _s = yw.write_item(form_bytes, KEIEI, KEIEI_TEXT, "1-2 経営課題")
    return written


@pytest.mark.parametrize("name", sorted(TAMPERS))
def test_compare_finds_changes_outside_the_range(form_bytes: bytes, written_blob: bytes, name: str) -> None:
    """書いた版の、範囲の外をわざと変えると、比べる道具が差を見つける（範囲の中の書き込みは差にしない）。"""
    written = written_blob
    assert yw.compare_docx(form_bytes, written, [("1-2 経営課題", KEIEI)]) == []
    tampered = TAMPERS[name](written)
    assert yw.compare_docx(form_bytes, tampered, [("1-2 経営課題", KEIEI)]) != []
    assert yw.compare_docx(written, tampered, [("1-2 経営課題", KEIEI)]) != []


TAMPER_DRIVER = r"""
import runpy, sys
plugin, script = sys.argv[1], sys.argv[2]
sys.path.insert(0, plugin)
from lib import yoshiki_word as yw
original = yw.rebuild_zip

def tampered(blob, replacements):
    # 書く処理が、範囲の外（事業者情報の表の見出し）も書き換えてしまう不具合をまねる
    replacements = dict(replacements)
    for name, data in list(replacements.items()):
        if name == yw.DOC:
            replacements[name] = data.replace("商号又は名称".encode("utf-8"), "商号又は名前".encode("utf-8"), 1)
        elif name.endswith("sheet1.xml"):
            replacements[name] = data.replace("画面の順番".encode("utf-8"), "画面の番号".encode("utf-8"), 1)
    return original(blob, replacements)

yw.rebuild_zip = tampered
sys.argv = [script] + sys.argv[3:]
runpy.run_path(script, run_name="__main__")
"""


def run_tampered(env: Env, *args: str, stdin: bytes = b"") -> subprocess.CompletedProcess:
    argv = list(args)
    argv[1:1] = ["--folder", str(env.folder)]
    return subprocess.run(
        [hr.real_python(), "-B", "-c", TAMPER_DRIVER, str(env.plugin), str(env.plugin / SCRIPT), *argv],
        env={"PATH": "/usr/bin:/bin", "HOME": str(env.home), "TMPDIR": str(env.tmp)},
        cwd=env.cwd, input=stdin, capture_output=True, timeout=300,
    )


def test_write_that_changes_outside_is_not_saved(env: Env) -> None:
    """書く処理が範囲の外まで変えてしまったら保存しない。初めてならファイルを作らず、2回目以降は直前の版のまま残る。"""
    env.set_positions({"1-2 経営課題": KEIEI})
    text = refused(run_tampered(env, "write", "--item", "1-2 経営課題", "--text", "試しの文"), code=3)
    assert "保存しませんでした" in text and "書いてよい範囲の外が変わります" in text
    assert "商号又は名称" in text  # どこが変わったかを示す
    assert not (env.folder / APP).exists()

    ok(env.run("write", "--item", "1-2 経営課題", "--text", "1回目の文（試し）"))
    before = (env.folder / APP).read_bytes()
    refused(run_tampered(env, "write", "--item", "1-2 経営課題", "--text", "2回目の文"), code=3)
    assert (env.folder / APP).read_bytes() == before


# ---------------------------------------------------------------- 入力シート.xlsx の1つの欄に書く


def test_sheet_is_made_from_screens_and_one_field_is_written(env: Env) -> None:
    """入力シートを申請画面の順に作り、1つの欄の値に書く。範囲の外（ほかのセル・書式・部品）は変わらない。"""
    value = "盛り付けと包装をつなぐ省力化の計画（試し）"
    text = ok(env.run("sheet", "--field", "事業計画名（３０文字程度）", "--value", value))
    assert "制度データの申請画面から作り" in text and "セル G" in text
    blob = (env.folder / SHEET).read_bytes()
    assert input_sheet.value_of(blob, "事業計画名（３０文字程度）") == value
    # 申請画面の順番に並ぶ（宣誓 → 事業計画名 → 数値 → 確認）。担当者が入れる欄も並べる
    _parts, _name, grid = input_sheet.read_grid(blob)
    rows = grid.field_rows()
    assert [(s, f, staff) for _r, s, f, staff in rows] == [
        ("宣誓・手引き", "宣誓の確認", True),
        ("事業計画名及び作成者情報", "事業計画名（３０文字程度）", False),
        ("事業計画名及び作成者情報", "事業計画の概要", False),
        ("事業計画数値", "常勤従業員数（基準年度）", False),
    ]
    assert input_sheet.NO_FIELDS in grid.texts.values()  # 欄のない画面（確認）も示す
    assert grid.texts["E4"] == "30字（目安）"
    # 作ったばかりの入力シートと比べ、変わったのは書いた欄のセルだけ
    fresh = input_sheet.build(json.loads(SEIDO.read_text(encoding="utf-8")))
    assert input_sheet.compare_xlsx(fresh, blob) == []
    pb, pa = parts_of(fresh), parts_of(blob)
    assert [n for n in pb if pb[n] != pa[n]] == ["xl/worksheets/sheet1.xml"]
    _p, _n, grid_b = input_sheet.read_grid(fresh)
    cell_b, cell_a = grid_b.cells["G4"], grid.cells["G4"]
    sheet_b, sheet_a = pb["xl/worksheets/sheet1.xml"], pa["xl/worksheets/sheet1.xml"]
    assert sheet_a[:cell_a.start] == sheet_b[:cell_b.start]
    assert sheet_a[cell_a.end:] == sheet_b[cell_b.end:]
    assert cell_a.attrs["s"] == cell_b.attrs["s"]  # セルの書式は変えない
    # Excel のファイルとして読める（同梱の openpyxl で、/usr/bin/python3 で読む）
    dumped = dump_xlsx(env.folder / SHEET)
    assert dumped["sheets"] == ["入力シート"]
    assert dumped["cells"]["入力シート"]["G4"] == value
    assert dumped["cells"]["入力シート"]["C2"] == "欄"


def test_sheet_second_field_keeps_the_first(env: Env) -> None:
    ok(env.run("sheet", "--field", "事業計画名（３０文字程度）", "--value", "1つ目の値（試し）"))
    first = (env.folder / SHEET).read_bytes()
    text = ok(env.run("sheet", "--field", "常勤従業員数（基準年度）", "--value", "12"))
    assert "制度データの申請画面から作り" not in text
    second = (env.folder / SHEET).read_bytes()
    assert input_sheet.value_of(second, "事業計画名（３０文字程度）") == "1つ目の値（試し）"
    assert input_sheet.value_of(second, "常勤従業員数（基準年度）") == "12"
    assert b"<v>12</v>" in parts_of(second)["xl/worksheets/sheet1.xml"]  # 数字の欄は数として書く
    assert input_sheet.compare_xlsx(first, second) == []
    # 書き直すと値が置き換わる
    ok(env.run("sheet", "--field", "事業計画名（３０文字程度）", "--value", "書き直した値（試し）"))
    assert input_sheet.value_of((env.folder / SHEET).read_bytes(), "事業計画名（３０文字程度）") == "書き直した値（試し）"


@pytest.mark.parametrize("args, reason", [
    (("--field", "宣誓の確認", "--value", "はい"), "担当者が画面で入れる欄です"),
    (("--field", "事業計画の概要", "--value", "あ" * 101), "システムの上限は100字"),
    (("--field", "ない欄", "--value", "x"), "欄「ない欄」がありません"),
    (("--field", "常勤従業員数（基準年度）", "--value", "十二人"), "数でない値"),
])
def test_sheet_refuses(env: Env, args, reason: str) -> None:
    """担当者が入れる欄、上限を超える値、ない欄、数でない値は書かない（入力シートも作らない）。"""
    text = refused(env.run("sheet", *args))
    assert reason in text
    assert not (env.folder / SHEET).exists()


def test_sheet_soft_limit_is_written_with_a_note(env: Env) -> None:
    """上限が目安の欄は、超えても書き、そのことを知らせる。"""
    text = ok(env.run("sheet", "--field", "事業計画名（３０文字程度）", "--value", "あ" * 31))
    assert "注意：目安の30字を超えています（31字）" in text


def test_sheet_change_outside_is_not_saved(env: Env) -> None:
    ok(env.run("sheet", "--field", "事業計画名（３０文字程度）", "--value", "1つ目の値（試し）"))
    before = (env.folder / SHEET).read_bytes()
    text = refused(run_tampered(env, "sheet", "--field", "常勤従業員数（基準年度）", "--value", "12"), code=3)
    assert "保存しませんでした" in text
    assert (env.folder / SHEET).read_bytes() == before


def _sheet_edit(blob: bytes, old: bytes, new: bytes) -> bytes:
    return _edit_part(blob, "xl/worksheets/sheet1.xml", old, new)


SHEET_TAMPERS = {
    "欄の名前": lambda b: _sheet_edit(b, "事業計画の概要".encode("utf-8"), "事業の概要".encode("utf-8")),
    "値のセルの書式": lambda b: _sheet_edit(b, b'<c r="G5" s="4"', b'<c r="G5" s="3"'),
    "担当者の欄の値": lambda b: _sheet_edit(b, b'<c r="G3" s="5"/>', b'<c r="G3" s="5"><v>1</v></c>'),
    "列の幅": lambda b: _sheet_edit(b, b'width="50"', b'width="60"'),
    "スタイル": lambda b: _edit_part(b, "xl/styles.xml", b'FFFFF2CC', b'FFFFFF00'),
}


@pytest.mark.parametrize("name", sorted(SHEET_TAMPERS))
def test_sheet_compare_finds_changes_outside_the_range(name: str) -> None:
    fresh = input_sheet.build(json.loads(SEIDO.read_text(encoding="utf-8")))
    written, _s = input_sheet.write_value(fresh, "事業計画名（３０文字程度）", "値（試し）")
    assert input_sheet.compare_xlsx(fresh, written) == []
    assert input_sheet.compare_xlsx(fresh, SHEET_TAMPERS[name](written)) != []


# ---------------------------------------------------------------- 会社のフォルダの外・別名・目印


SHEET_ARGS = ["sheet", "--field", "事業計画名（３０文字程度）", "--value", "試し"]
WRITE_ARGS = ["write", "--item", "1-2 経営課題", "--text", "試し"]


def link_aside(env: Env, tmp_path: Path, rel: str, outside: Path) -> None:
    """会社のフォルダの中の rel（フォルダ）を外へ退け、代わりに外のフォルダ outside を指す別名を置く（社長のうっかりをまねる）。"""
    inner = env.folder / rel
    inner.rename(tmp_path / ("退けた_" + inner.name))
    inner.symlink_to(outside, target_is_directory=True)


def outside_names(top: Path) -> list:
    return sorted(p.relative_to(top).as_posix() for p in top.rglob("*"))


def refuses_not_company_and_outside_paths(env: Env, tmp_path: Path) -> None:
    """会社のフォルダでなければ何もしない。外の様式は読まない。書き出す先の途中に別名があれば書かない。"""
    plain = tmp_path / "ただのフォルダ"
    plain.mkdir()
    text = refused(env.run("outline", folder=plain))
    assert "会社のフォルダではありません" in text and list(plain.iterdir()) == []

    outside_form = tmp_path / "外の様式.docx"
    outside_form.write_bytes((env.folder / OFFICIAL).read_bytes())
    assert "会社のフォルダの外です" in refused(env.run("outline", "--source", str(outside_form)))

    app_dir = env.folder / "案件" / CASE / STAGE / "申請書"
    outside = tmp_path / "外の置き場"
    outside.mkdir()
    app_dir.rmdir()
    app_dir.symlink_to(outside, target_is_directory=True)
    text = refused(env.run(*WRITE_ARGS))
    assert "別名（シンボリックリンク）" in text
    text = refused(env.run(*SHEET_ARGS))
    assert "別名（シンボリックリンク）" in text
    assert list(outside.iterdir()) == []


def refuses_linked_case_folder(env: Env, tmp_path: Path) -> None:
    """案件のフォルダが別名で外を指すとき：外のフォルダの中の名前（段階のフォルダの一覧）を読まず、出さずに断る
    （--stage が違うときに「あるもの」として外の名前を出さない）。"""
    outside = tmp_path / "外の案件"
    for name in ("1_外の段階", "2_秘密の名前"):
        (outside / name / "申請書").mkdir(parents=True)
    before = outside_names(outside)
    link_aside(env, tmp_path, f"案件/{CASE}", outside)
    for command in (SHEET_ARGS, WRITE_ARGS):
        for stage in (["--stage", "9_なし"], []):
            text = refused(env.run(*command, *stage))
            assert f"案件/{CASE} が別名（シンボリックリンク）" in text, text
            assert "外の段階" not in text and "秘密の名前" not in text, text
    assert outside_names(outside) == before


def refuses_linked_seido_folder(env: Env, tmp_path: Path) -> None:
    """記録/制度データ/ が別名で外を指すとき：外のフォルダの中の名前（制度データの数・ファイルの名前）を読まず、
    出さず、書かずに断る（外の制度データが2つでも1つでも）。"""
    outside = tmp_path / "外の制度データ"
    outside.mkdir()
    secret = {name: (env.folder / SEIDO_IN_FOLDER).read_bytes() for name in ("外の制度_秘密.json", "外の制度_二つ目.json")}
    for name, blob in secret.items():
        (outside / name).write_bytes(blob)
    link_aside(env, tmp_path, "記録/制度データ", outside)
    mapping = json.dumps({"様式": FORM_NAME, "対応": [{"項目": "6. 補足事項", "書き込む位置": HOSOKU}]},
                         ensure_ascii=False).encode("utf-8")
    runs = {"2つ": [(SHEET_ARGS, b""), (["map"], mapping)],
            "1つ": [(SHEET_ARGS, b""), (WRITE_ARGS, b""), (["map"], mapping)]}
    for count, commands in runs.items():
        if count == "1つ":
            (outside / "外の制度_二つ目.json").unlink()
            del secret["外の制度_二つ目.json"]
        for command, stdin in commands:
            text = refused(env.run(*command, stdin=stdin))
            assert "記録/制度データ が別名（シンボリックリンク）" in text, text
            assert "外の制度" not in text and "秘密" not in text and "二つ目" not in text, text
        assert sorted(p.name for p in outside.iterdir()) == sorted(secret)
        assert all((outside / name).read_bytes() == blob for name, blob in secret.items())
    # 断ったときは、会社のフォルダの中にも申請書を作らない
    assert list((env.folder / APP).parent.iterdir()) == []


def refuses_linked_text_folder(env: Env, tmp_path: Path) -> None:
    """記録/資料の本文/ が別名で外を指すとき：様式を決めるための外の資料の一覧を探さず、読まずに断る。"""
    outside = tmp_path / "外の資料の本文"
    (outside / CASE).mkdir(parents=True)
    (outside / CASE / "資料の一覧.json").write_text(
        json.dumps({"案件": CASE, "置き場所": {"秘密の資料": {"ファイル": "外の秘密の様式.docx"}}}, ensure_ascii=False),
        encoding="utf-8")
    link_aside(env, tmp_path, "記録/資料の本文", outside)
    for command in (["outline"], WRITE_ARGS):
        text = refused(env.run(*command))
        assert f"記録/資料の本文/{CASE}/ が会社のフォルダの外を指しています" in text, text
        assert "秘密" not in text, text
    assert not (env.folder / APP).exists()


@pytest.mark.parametrize("case", [
    refuses_not_company_and_outside_paths,
    refuses_linked_case_folder,
    refuses_linked_seido_folder,
    refuses_linked_text_folder,
], ids=lambda f: f.__name__)
def test_refuses_outside_company_folder(env: Env, tmp_path: Path, case) -> None:
    """会社のフォルダの外は読まない・書かない（SPEC F5、DESIGN 5章）。会社のフォルダでなければ何もしない。
    書き出す先の途中に別名があれば書かない。案件のフォルダ・記録/制度データ/・記録/資料の本文/ が別名で外を指すときは、
    外のフォルダの中の名前を読まず、出さない（場合ごとの中身は、各関数の説明）。"""
    env.set_positions({"1-2 経営課題": KEIEI})
    case(env, tmp_path)


def test_no_pycache_and_no_work_files(env: Env) -> None:
    """プラグインの場所と会社のフォルダに __pycache__ や書きかけのファイルを残さない。"""
    env.set_positions({"1-2 経営課題": KEIEI})
    ok(env.run("write", "--item", "1-2 経営課題", "--text", "試し"))
    ok(env.run("sheet", "--field", "事業計画名（３０文字程度）", "--value", "試し"))
    assert not list(env.plugin.rglob("__pycache__"))
    assert not list(env.folder.rglob("__pycache__"))
    names = sorted(p.name for p in (env.folder / APP).parent.iterdir())
    assert names == ["その1・2.docx", "入力シート.xlsx"]


# ---------------------------------------------------------------- LibreOffice で開ける（あれば）


DUMP_CODE = r"""
import json, sys, warnings
sys.path.insert(0, sys.argv[1])
import openpyxl
warnings.simplefilter("ignore")
wb = openpyxl.load_workbook(sys.argv[2])
print(json.dumps({"sheets": wb.sheetnames, "cells": {ws.title: {c.coordinate: c.value for row in ws.iter_rows()
      for c in row if c.value is not None} for ws in wb.worksheets}}, ensure_ascii=False, default=str))
"""


def dump_xlsx(path: Path) -> dict:
    """同梱の openpyxl で読む（テストの Python の中では読み込まない。lib/vendor/ に __pycache__ ができるため）。"""
    r = subprocess.run(
        [hr.real_python(), "-I", "-B", "-c", DUMP_CODE, str(REPO_ROOT / "lib" / "vendor"), str(path)],
        env={"PATH": "/usr/bin:/bin", "HOME": str(path.parent)}, capture_output=True, timeout=300,
    )
    assert r.returncode == 0, r.stderr.decode("utf-8")
    return json.loads(r.stdout.decode("utf-8"))


def soffice_or_skip() -> str:
    for place in ("/Applications/LibreOffice.app/Contents/MacOS/soffice",
                  os.path.expanduser("~/Applications/LibreOffice.app/Contents/MacOS/soffice")):
        if os.access(place, os.X_OK):
            return place
    found = shutil.which("soffice")
    if found:
        return found
    pytest.skip("LibreOffice がありません")


@pytest.mark.slow
def test_written_files_open_in_libreoffice(env: Env, tmp_path: Path) -> None:
    """書いたその1・2 と入力シートを、LibreOffice が変換できる（変換エラーなし）。PDF に書いた文が入る。"""
    soffice = soffice_or_skip()
    env.set_positions({"1-2 経営課題": KEIEI})
    ok(env.run("write", "--item", "1-2 経営課題", "--text", "経営課題の試しの文（変換の確かめ）"))
    ok(env.run("sheet", "--field", "事業計画名（３０文字程度）", "--value", "変換の確かめ"))
    outdir = tmp_path / "変換"
    profile = tmp_path / "lo_profile"
    for rel, kind in ((APP, "pdf"), (SHEET, "pdf")):
        r = subprocess.run(
            [soffice, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--convert-to", kind,
             "--outdir", str(outdir), str(env.folder / rel)],
            env={"PATH": "/usr/bin:/bin", "HOME": str(env.home), "TMPDIR": str(env.tmp)},
            capture_output=True, timeout=600,
        )
        assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
        assert (outdir / (Path(rel).stem + ".pdf")).stat().st_size > 0
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from pypdf import PdfReader; "
            "print(''.join(p.extract_text() for p in PdfReader(sys.argv[2]).pages))")
    r = subprocess.run([hr.real_python(), "-I", "-B", "-c", code, str(REPO_ROOT / "lib" / "vendor"),
                        str(outdir / "その1・2.pdf")], capture_output=True, timeout=300)
    assert "経営課題の試しの文（変換の確かめ）" in r.stdout.decode("utf-8")
