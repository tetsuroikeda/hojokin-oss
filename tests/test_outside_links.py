"""場所の確かめの残り（11/4 の作者の決定 B「場所の確かめを共通の関数1つにまとめ、どの道具もそれを使う」の波2b）。

SPEC F5「会社のフォルダの外（デスクトップ、ダウンロードなど）には触れない」、DESIGN 5章「会社のフォルダの外に書かない・
外を読まない」（スクリプトは会社のフォルダの中しか扱わない。(b) 別名と「..」をたどった後に比べる）。
関わる行は M2a（T3-1）・M2b・M2c・M2d（T3-9）・M4（T0-7）。

波2a で手を付けなかった道具が、会社のフォルダの中の場所を、別名（シンボリックリンク）をたどったまま読む・書く所を、
共通の関数（lib/places.py）を通す形に直した。所ごとに、その場所を外のフォルダへの別名にしたとき、
- 道具は、その道具の今の断り方（同じ調子の文、同じ終了コード）で断る
- 外の値が出力に出ない（中に置いたときは出ることを先に確かめ、読んでいないことの確かめにする）
- 外のフォルダも会社のフォルダも変わらない
ことを確かめる。

想定する相手は、協力的な Claude と、Git を知らない社長のうっかり（作者の決定 B）。悪意のある書き換えへの備えは見ない。

- 制度データ（lib/seido_data.py、skills/junbi/scripts/seido_data.py）：まとめる・確かめる・段階のフォルダ
- 裏取り（lib/urakadori.py、skills/junbi/scripts/urakadori.py）：案件を決める・資料の本文（PDF の出典のページの
  ファイル1つずつも）・資料の一覧
- 書類の整理（lib/seiri.py）：原本の置き場への移動と、書類の台帳
- 公式資料の取得（lib/official_docs.py・lib/case_folder.py）：案件のフォルダと資料の本文
- 原本の控え（lib/protected_store.py の `.hojokin/一時/原本の印.json`。書類の整理と公式資料の取得が読む・足す）：
  控えまでの途中（`.hojokin/`・`.hojokin/一時/`）か控えそのものが別名なら、読まず・書かない。控えに書けなくても
  道具の処理は止めない作り（台帳と資料の一覧でも照らす）なので、道具は続けて終了コード 0
- 今日の日付の差し替え（lib/company.py の load_settings）：別名なら読まず、差し替えのないものとして扱う（仮）
- 原本と公式資料の照らし（lib/originals_guard.py）：外を指す資料の一覧は読まない

道具は、Claude が Bash で動かすのと同じく、社長の Mac と同じ /usr/bin/python3 で、プラグインの写しから動かす
（それぞれの道具のテストの準備を使う）。
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import test_seido_data as sd
import test_seiri_min as sm
import test_T3_1 as t31
import version_tool as vt

from lib import case_folder, company, dates

SECRET = "外に置いた略称"
OUTSIDE = "外のフォルダ"


# ---- 共通の道具 ----


def tree(folder: Path) -> dict:
    """フォルダの中のすべて（場所 → 中身。フォルダは "dir"、別名は先の場所）。別名はたどらない。"""
    found = {}
    for dirpath, dirnames, filenames in os.walk(str(folder)):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(folder).as_posix()
            if path.is_symlink():
                found[rel] = ("link", os.readlink(str(path)))
            elif path.is_dir():
                found[rel] = "dir"
            else:
                found[rel] = path.read_bytes()
    return found


def move_out(place: Path, outside: Path) -> Path:
    """place を外のフォルダへ移し、place を、移した先への別名にする。移した先を返す。"""
    moved = outside / f"移した_{place.name}"
    place.rename(moved)
    place.symlink_to(moved, target_is_directory=moved.is_dir())
    return moved


def outside_folder(root: Path) -> Path:
    path = root / OUTSIDE
    path.mkdir()
    return path


# ---- 制度データ（まとめる・確かめる・段階のフォルダ） ----


def seido_refused(r) -> str:
    """制度データの道具が、今の断り方（終了コード 2、「何も書いていません」）で断った。"""
    out = sd.check_code(r, 2)
    assert out.startswith("何も書いていません。"), out
    return out


@pytest.fixture
def merged(tmp_path) -> sd.Company:
    """章ごとの読み取りを3つ通してまとめた会社のフォルダ（制度データと、1_申請 のフォルダがある）。"""
    c = sd.Company(tmp_path)
    c.add_docs()
    sd.read_all(c)
    sd.check_code(c.tool("--merge"), 0)
    return c


@pytest.mark.parametrize("where", ["記録", "記録/制度データ", "制度データのファイル"])
def test_seido_check_does_not_read_data_outside(merged: sd.Company, where: str) -> None:
    """制度データ（その上のフォルダも）が外への別名なら、確かめる道具は外の制度データを読まない。"""
    data = merged.data()
    data["書類"][0]["手続き"] = [SECRET]  # 当たらない名前として、確かめた結果に出る
    (merged.folder / sd.DATA_REL).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    # 中にあるときは、置いた値が出る（外に移したときに出ないことが、読んでいないことの確かめになる）
    assert SECRET in sd.check_code(merged.tool("--check"), 1)

    outside = outside_folder(merged.env.root)
    place = {"記録": merged.folder / "記録", "記録/制度データ": merged.folder / "記録" / "制度データ",
             "制度データのファイル": merged.folder / sd.DATA_REL}[where]
    move_out(place, outside)
    before, outside_before = tree(merged.folder), tree(outside)
    for extra in ([], ["--case", sd.CASE]):
        out = seido_refused(merged.tool("--check", *extra))
        assert "会社のフォルダの外" in out and SECRET not in out, (where, extra, out)
        assert tree(merged.folder) == before and tree(outside) == outside_before


@pytest.mark.parametrize("where", ["記録/資料の本文", "案件の資料の本文", "資料の一覧"])
def test_seido_check_does_not_read_doc_list_outside(merged: sd.Company, where: str) -> None:
    """案件の資料の一覧（その上のフォルダも）が外への別名なら、外の一覧を読まない（制度データの場所も決めない）。"""
    listed = merged.texts / "資料の一覧.json"
    data = json.loads(listed.read_text(encoding="utf-8"))
    data["制度"]["略称"] = SECRET  # 制度データの場所（略称_公募回.json）に出る
    listed.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    # 中にあるときは、一覧の略称で制度データの場所を決める（その場所に制度データはない）
    assert SECRET in seido_refused(merged.tool("--check"))

    outside = outside_folder(merged.env.root)
    place = {"記録/資料の本文": merged.folder / "記録" / "資料の本文", "案件の資料の本文": merged.texts,
             "資料の一覧": listed}[where]
    move_out(place, outside)
    before, outside_before = tree(merged.folder), tree(outside)
    for extra in ([], ["--case", sd.CASE]):
        out = seido_refused(merged.tool("--check", *extra))
        assert "会社のフォルダの外" in out and SECRET not in out, (where, extra, out)
        assert tree(merged.folder) == before and tree(outside) == outside_before


def test_case_names_outside_are_not_listed(tmp_path) -> None:
    """記録/資料の本文 が外への別名なら、案件を決めるときに外のフォルダの中の名前を読まない（出力にも出ない）。"""
    c = sd.Company(tmp_path)
    c.add_docs()
    outside = outside_folder(tmp_path)
    for name in ("外の案件A", "外の案件B"):
        (outside / "外の資料の本文" / name).mkdir(parents=True)
    texts = c.folder / "記録" / "資料の本文"
    texts.rename(outside / "移した_資料の本文")
    texts.symlink_to(outside / "外の資料の本文", target_is_directory=True)
    before, outside_before = tree(c.folder), tree(outside)
    out = seido_refused(c.tool("--check"))
    assert "会社のフォルダの外" in out and "外の案件" not in out, out
    r = c._run(sd.URAKADORI, ["--folder", str(c.folder), "--input", "-"],
               json.dumps(sd.chapter_a(), ensure_ascii=False).encode("utf-8"))
    out = sd.check_code(r, 2)
    assert "何も書いていません" in out and "会社のフォルダの外" in out and "外の案件" not in out, out
    assert tree(c.folder) == before and tree(outside) == outside_before


@pytest.mark.parametrize("where", ["読み取りのフォルダ", "章のファイル"])
def test_seido_merge_does_not_read_chapters_outside(tmp_path, where: str) -> None:
    """章ごとの読み取りの結果（そのフォルダも）が外への別名なら、まとめる道具は外の結果を読まず、何も書かない。"""
    c = sd.Company(tmp_path)
    c.add_docs()
    sd.read_all(c)
    reading = c.folder / sd.READING_REL
    first = sorted(reading.glob("*.json"))[0]
    # 章の名前は、まとめた結果の「まとめた章」に出る（ファイルの名前でなく、中身から読む）
    chapter = json.loads(first.read_text(encoding="utf-8"))
    chapter["読み取り"]["章"] = "外に置いた章の名前"
    first.write_text(json.dumps(chapter, ensure_ascii=False, indent=2), encoding="utf-8")
    # 中にあるときは、まとめた結果に出る（外に移したときに出ないことが、読んでいないことの確かめになる）
    assert "外に置いた章の名前" in sd.check_code(c.tool("--merge"), 0)
    (c.folder / sd.DATA_REL).unlink()
    outside = outside_folder(tmp_path)
    move_out(reading if where == "読み取りのフォルダ" else first, outside)
    before, outside_before = tree(c.folder), tree(outside)
    out = seido_refused(c.tool("--merge"))
    assert "会社のフォルダの外" in out and "外に置いた章の名前" not in out, (where, out)
    assert not (c.folder / sd.DATA_REL).exists()
    assert tree(c.folder) == before and tree(outside) == outside_before


def test_seido_merge_does_not_read_doc_text_outside(tmp_path) -> None:
    """資料の本文（資料ごとのフォルダ）が外への別名なら、まとめる道具は裏取りで外の本文を読まず、何も書かない。"""
    c = sd.Company(tmp_path)
    c.add_docs()
    sd.read_all(c)
    outside = outside_folder(tmp_path)
    move_out(c.texts / sd.DOC, outside)
    before, outside_before = tree(c.folder), tree(outside)
    out = seido_refused(c.tool("--merge"))
    assert "会社のフォルダの外" in out, out
    assert not (c.folder / sd.DATA_REL).exists()
    assert tree(c.folder) == before and tree(outside) == outside_before


def test_stage_folders_are_not_made_outside(merged: sd.Company) -> None:
    """案件のフォルダが外への別名なら、段階のフォルダを外に作らない（今の断り方：--stage-folders は終了コード 2、
    --merge は制度データを置いたうえで「段階のフォルダを作れませんでした」と出して終了コード 1）。"""
    outside = outside_folder(merged.env.root)
    move_out(merged.case_dir(), outside)
    outside_before = tree(outside)
    out = seido_refused(merged.tool("--stage-folders", "--stage", "2_交付申請"))
    assert "別名" in out and "会社のフォルダの外" in out, out
    assert tree(outside) == outside_before
    out = sd.check_code(merged.tool("--merge"), 1)
    assert "段階のフォルダを作れませんでした" in out and "別名" in out, out
    assert tree(outside) == outside_before


# ---- 裏取り（章ごとの読み取りと、制度データの全体） ----


@pytest.mark.parametrize("where", ["資料のフォルダ", "案件の資料の本文"])
def test_urakadori_does_not_read_doc_text_outside(tmp_path, where: str) -> None:
    """資料の本文が外への別名なら、裏取りの道具は外の本文を読まず、章の結果を置かない（終了コード 2）。"""
    c = sd.Company(tmp_path)
    c.add_docs()
    outside = outside_folder(tmp_path)
    move_out(c.texts / sd.DOC if where == "資料のフォルダ" else c.texts, outside)
    before, outside_before = tree(c.folder), tree(outside)
    out = c.read(sd.chapter_a(), code=2)
    assert out.startswith("裏取りをしませんでした。何も書いていません。"), out
    assert "会社のフォルダの外" in out, out
    assert not (c.folder / sd.READING_REL).exists()
    assert tree(c.folder) == before and tree(outside) == outside_before


def pdf_page_file(c: sd.Company, printed: int) -> Path:
    """資料の本文の、印刷された番号で引いたページのファイル（ページの対応から引く。ファイルの名前は決め打ちしない）。"""
    doc_dir = c.texts / sd.DOC
    index = json.loads((doc_dir / "ページの対応.json").read_text(encoding="utf-8"))
    pages = [p for p in index["ページ"] if p.get("印刷されたページ") == printed]
    assert len(pages) == 1, index
    return doc_dir / pages[0]["ファイル"]


@pytest.mark.parametrize("where", ["ページのファイル", "ページの対応"])
def test_urakadori_does_not_read_pdf_page_outside(tmp_path, where: str) -> None:
    """PDF の資料の、出典のページのファイル（ページの対応も）が外への別名なら、裏取りの道具は外のページを読まず、
    章の結果を置かない（終了コード 2）。章1の出典は印刷の p.1（ずれ 1 なので、PDF の2ページ目のファイル）。"""
    c = sd.Company(tmp_path)
    c.add_docs()
    # 中にあるときは、出典のページで照らして、章の結果を置く（外に移したときに断ることが、読んでいないことの確かめになる）
    out = c.read(sd.chapter_a())
    assert "根拠の文はどれも出典のページにあり" in out, out
    reading = c.folder / sd.READING_REL
    assert list(reading.glob("*.json")), out
    for f in reading.glob("*.json"):
        f.unlink()

    outside = outside_folder(tmp_path)
    page = pdf_page_file(c, 1)
    move_out(page if where == "ページのファイル" else c.texts / sd.DOC / "ページの対応.json", outside)
    before, outside_before = tree(c.folder), tree(outside)
    out = c.read(sd.chapter_a(), code=2)
    assert out.startswith("裏取りをしませんでした。何も書いていません。"), out
    assert "会社のフォルダの外" in out and "根拠の文はどれも出典のページにあり" not in out, (where, out)
    assert not list(reading.glob("*.json"))
    assert tree(c.folder) == before and tree(outside) == outside_before


def test_urakadori_full_data_does_not_read_doc_list_outside(merged: sd.Company) -> None:
    """案件の資料の一覧が外への別名なら、制度データの全体の置き場所（略称）を外の一覧で決めない。"""
    full = merged.data()
    outside = outside_folder(merged.env.root)
    moved = move_out(merged.texts / "資料の一覧.json", outside)
    data = json.loads(moved.read_text(encoding="utf-8"))
    data["制度"]["略称"] = SECRET
    moved.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    before, outside_before = tree(merged.folder), tree(outside)
    out = merged.read(full, code=2)
    assert out.startswith("裏取りをしませんでした。何も書いていません。"), out
    assert "会社のフォルダの外" in out and SECRET not in out, out
    assert tree(merged.folder) == before and tree(outside) == outside_before


# ---- 書類の整理（原本の置き場と、書類の台帳） ----


def seiri_company(tmp_path) -> vt.Company:
    c = vt.Company(tmp_path)
    settings = c.folder / ".hojokin" / "設定.json"
    data = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
    data["今日の日付"] = sm.TODAY
    settings.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return c


ORGANIZE = ["--path", "入れ口/決算書18.pdf", "--category", "決算・税", "--kind", "決算書", "--date", "2025-04-01"]


@pytest.mark.parametrize("where", ["原本", "原本/決算・税"])
def test_organize_does_not_move_into_link(tmp_path, where: str) -> None:
    """原本の置き場（区分のフォルダも）が外への別名なら、書類を移さない（外に置かない。入れ口の書類も残る）。"""
    c = seiri_company(tmp_path)
    data = sm.put(c, "入れ口/決算書18.pdf", "決算書_第18期.pdf")
    outside = outside_folder(tmp_path)
    move_out(c.folder / where, outside)
    before, outside_before = tree(c.folder), tree(outside)
    out = sm.refused(sm.run_tool(c, "organize", *ORGANIZE))
    assert "別名" in out and "移していません" in out, out
    assert tree(c.folder) == before and tree(outside) == outside_before
    assert (c.folder / "入れ口" / "決算書18.pdf").read_bytes() == data


@pytest.mark.parametrize("where", ["記録", "書類の台帳"])
def test_ledger_link_is_not_read_or_written(tmp_path, where: str) -> None:
    """書類の台帳（記録/ も）が外への別名なら、外の台帳を読まず、書かない（一覧に外の中身が出ない）。"""
    c = seiri_company(tmp_path)
    sm.put(c, "入れ口/決算書18.pdf", "決算書_第18期.pdf")
    sm.organize(c, "入れ口/決算書18.pdf", "決算・税", "決算書", "2025-04-01")
    ledger = c.folder / sm.LEDGER
    data = json.loads(ledger.read_text(encoding="utf-8"))
    data["原本"][0]["場所"] = f"原本/決算・税/{SECRET}.pdf"
    ledger.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    # 中にあるときは、一覧に出る
    assert SECRET in sm.run_tool(c, "list").stdout.decode("utf-8")

    sm.put(c, "入れ口/見積書.pdf", "見積書_ほしみ機工.pdf")
    outside = outside_folder(tmp_path)
    move_out(c.folder / "記録" if where == "記録" else ledger, outside)
    before, outside_before = tree(c.folder), tree(outside)
    for command, args in (("list", []), ("scan", []),
                          ("organize", ["--path", "入れ口/見積書.pdf", "--category", "見積・契約・請求",
                                        "--kind", "見積書", "--date", "2026-10-27"]),
                          ("keep", ["--path", "入れ口/見積書.pdf", "--reason", "社長に確かめた"])):
        out = sm.refused(sm.run_tool(c, command, *args))
        assert "別名" in out and SECRET not in out, (command, out)
        assert tree(c.folder) == before and tree(outside) == outside_before, command


def test_ledger_place_link_without_ledger(tmp_path) -> None:
    """記録/ が外への別名で、別名の先に台帳がまだないとき：見つけるだけなら、読むものがないので台帳のないものとして続ける
    （開いたときと応答の終わりの照らしも止めない）。整理（移す・確かめ済みにする）は外に台帳を書くことになるので、
    移す前に断る（入れ口の書類も残る）。"""
    c = seiri_company(tmp_path)
    data = sm.put(c, "入れ口/決算書18.pdf", "決算書_第18期.pdf")
    outside = outside_folder(tmp_path)
    moved = move_out(c.folder / "記録", outside)
    assert not (moved / "書類の台帳.json").exists()
    before, outside_before = tree(c.folder), tree(outside)
    found = sm.ok_json(sm.run_tool(c, "scan"))
    assert [d["場所"] for d in found["新しい書類"]] == ["入れ口/決算書18.pdf"]
    for command, args in (("organize", ORGANIZE), ("keep", ["--path", "入れ口/決算書18.pdf", "--reason", "社長に確かめた"])):
        out = sm.refused(sm.run_tool(c, command, *args))
        assert "別名" in out, (command, out)
        assert tree(c.folder) == before and tree(outside) == outside_before, command
    assert (c.folder / "入れ口" / "決算書18.pdf").read_bytes() == data


# ---- 原本の控え（.hojokin/一時/原本の印.json） ----


def put_anchor(folder: Path, rel: str, digest: str) -> Path:
    """原本の控えに、原本を1件足す（道具が置いたのと同じ形。前からある控えは残す）。"""
    path = folder / company.MARKER_DIR / company.TEMP_DIR / "原本の印.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"守るもの": {}}
    body["守るもの"][rel] = {"ハッシュ": digest, "版の印": "", "種類": "原本"}
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return path


def test_organize_does_not_use_anchors_through_link(tmp_path) -> None:
    """`.hojokin/` が外への別名なら、書類の整理は、原本の控えを外から読まず（外の値が出力に出ない）、外にも書かない。
    控えを使えなくても台帳で整理を続ける作りなので、移して終了コード 0。"""
    c = seiri_company(tmp_path)
    # 台帳を作っておく（台帳がないのに控えに原本があると、整理する前に断るため）
    sm.put(c, "入れ口/見積書.pdf", "見積書_ほしみ機工.pdf")
    sm.organize(c, "入れ口/見積書.pdf", "見積・契約・請求", "見積書", "2026-10-27")
    data = sm.put(c, "入れ口/決算書18.pdf", "決算書_第18期.pdf")
    put_anchor(c.folder, f"原本/決算・税/{SECRET}.pdf", sm.sha256(data))
    # 中にあるときは、控えの原本と同じ中身として断る（控えの場所が出る。外に移したときに出ないことが、読んでいないことの確かめになる）
    out = sm.refused(sm.run_tool(c, "organize", *ORGANIZE))
    assert SECRET in out and "同じ中身" in out, out
    assert SECRET in sm.run_tool(c, "scan").stdout.decode("utf-8")

    outside = outside_folder(tmp_path)
    move_out(c.folder / company.MARKER_DIR, outside)
    assert company.is_company_folder(c.folder)
    outside_before = tree(outside)
    found = sm.ok_json(sm.run_tool(c, "scan"))
    assert [d["場所"] for d in found["新しい書類"]] == ["入れ口/決算書18.pdf"], found
    assert SECRET not in json.dumps(found, ensure_ascii=False)
    moved = sm.ok_json(sm.run_tool(c, "organize", *ORGANIZE))
    assert SECRET not in json.dumps(moved, ensure_ascii=False)
    assert moved["新しい場所"].startswith("原本/決算・税/"), moved
    assert (c.folder / moved["新しい場所"]).read_bytes() == data
    assert not (c.folder / "入れ口" / "決算書18.pdf").exists()
    assert tree(outside) == outside_before


@pytest.mark.parametrize("where", [".hojokin", ".hojokin/一時", "原本の印.json"])
def test_anchors_link_is_not_read_or_written(tmp_path, where: str) -> None:
    """原本の控え（その上の .hojokin/・.hojokin/一時/ も）が別名なら、控えを読まず（理由を返す）、書かず、足さない。"""
    from lib import protected_store

    folder = tmp_path / "会社"
    (folder / company.MARKER_DIR).mkdir(parents=True)
    rel = f"原本/決算・税/{SECRET}.pdf"
    anchors = put_anchor(folder, rel, "b" * 64)
    # 中にあるときは読める
    assert protected_store.load_anchors(folder) == ({rel: {"ハッシュ": "b" * 64, "版の印": "", "種類": "原本"}}, "")

    outside = outside_folder(tmp_path)
    place = {".hojokin": folder / company.MARKER_DIR, ".hojokin/一時": anchors.parent, "原本の印.json": anchors}[where]
    move_out(place, outside)
    outside_before = tree(outside)
    got, reason = protected_store.load_anchors(folder)
    assert got == {} and "別名" in reason and SECRET not in reason, (where, reason)
    assert protected_store.remember(folder, "原本/決算・税/新しい原本.pdf", "c" * 64, "", protected_store.ORIGINAL) is False
    protected_store.save_anchors(folder, {"原本/決算・税/新しい原本.pdf": {"ハッシュ": "c" * 64, "版の印": "", "種類": "原本"}})
    assert tree(outside) == outside_before


# ---- 公式資料の取得（案件のフォルダと資料の本文） ----


HTML = "<!DOCTYPE html><html><body><p>テストのためだけに作った架空の公募要領です。</p></body></html>".encode("utf-8")
CASE = "2026_試し第3回"


@pytest.fixture
def small_site():
    site = t31.Site()
    site.put("/doc/youryou.html", HTML, "text/html; charset=utf-8")
    yield site
    site.close()


def small_list(site) -> dict:
    return {"制度": {"名前": "試しの補助金", "略称": "試し", "公募回": "第3回"},
            "資料": [{"id": "要領3", "名前": "公募要領", "公募回": "第3回", "URL": site.base + "/doc/youryou.html"}]}


def fetch_refused(r) -> str:
    out = t31.out(r)
    assert r.returncode == 2, (r.returncode, out, r.stderr.decode("utf-8"))
    assert r.stderr == b"", r.stderr.decode("utf-8")
    assert out.startswith("公式資料を取りませんでした。何も変えていません。"), out
    return out


@pytest.mark.parametrize("where", ["案件", "公式資料", "案件の資料の本文", "資料の一覧"])
def test_fetch_does_not_write_through_links(tmp_path, small_site, where: str) -> None:
    """案件のフォルダ・公式資料・資料の本文・資料の一覧が外への別名なら、公式資料を取る道具は何も書かずに断る。"""
    c = t31.Company(tmp_path)
    data = small_list(small_site)
    outside = outside_folder(tmp_path)
    if where == "案件":
        move_out(c.folder / "案件", outside)
    else:
        r = c.fetch(data)
        assert r.returncode == 0, t31.out(r)
        if where == "公式資料":
            moved = move_out(c.case(CASE) / "公式資料", outside)
            for f in moved.iterdir():
                f.unlink()  # 取り直すと、外に置くことになる
        elif where == "案件の資料の本文":
            moved = move_out(c.texts(CASE), outside)
            (moved / "資料の一覧.json").unlink()  # 取り直すと、外に書くことになる
        else:
            moved = move_out(c.texts(CASE) / "資料の一覧.json", outside)
            listed = json.loads(moved.read_text(encoding="utf-8"))
            listed["秘密"] = SECRET  # 取り直すと、外の一覧を読んで書き直すことになる
            moved.write_text(json.dumps(listed, ensure_ascii=False), encoding="utf-8")
    before, outside_before = tree(c.folder), tree(outside)
    out = fetch_refused(c.fetch(data))
    assert "別名" in out and "会社のフォルダの外" in out and SECRET not in out, (where, out)
    assert tree(c.folder) == before and tree(outside) == outside_before


def test_fetch_does_not_write_anchors_through_link(tmp_path, small_site) -> None:
    """`.hojokin/` が外への別名なら、公式資料を取る道具は、原本の控え（.hojokin/一時/原本の印.json）を外に書かない。
    控えに書けなくても処理は止めない作りなので、公式資料は取って終了コード 0（照らしは資料の一覧でも続く）。"""
    c = t31.Company(tmp_path)
    data = small_list(small_site)
    outside = outside_folder(tmp_path)
    move_out(c.folder / company.MARKER_DIR, outside)
    assert company.is_company_folder(c.folder)
    outside_before = tree(outside)
    r = c.fetch(data)
    assert r.returncode == 0, (t31.out(r), r.stderr.decode("utf-8"))
    assert [p.name for p in (c.case(CASE) / "公式資料").iterdir()] == ["公募要領_第3回.html"]
    assert tree(outside) == outside_before


def test_case_folder_tools_do_not_follow_links(tmp_path) -> None:
    """案件のフォルダを探す・作る道具は、案件/ が外への別名なら、外の中を見ず、外に作らない。"""
    folder = tmp_path / "会社"
    folder.mkdir()
    outside = outside_folder(tmp_path)
    (outside / CASE).mkdir()
    (folder / "案件").symlink_to(outside, target_is_directory=True)
    outside_before = tree(outside)
    seido = {"略称": "試し", "公募回": "第3回"}
    assert case_folder.existing_cases(folder, seido) == []
    with pytest.raises(case_folder.CaseError, match="別名"):
        case_folder.ensure_case(folder, CASE)
    with pytest.raises(case_folder.CaseError, match="別名"):
        case_folder.ensure_stage_folders(folder, CASE, ["1_申請"])
    assert tree(outside) == outside_before


# ---- 原本と公式資料の照らし（資料の一覧） ----


@pytest.mark.parametrize("where", ["記録/資料の本文", "案件の資料の本文", "資料の一覧"])
def test_guard_does_not_read_doc_list_outside(tmp_path, where: str) -> None:
    """資料の一覧（その上のフォルダも）が外への別名なら、照らすものを外の一覧で決めず、読まなかったことを知らせる。"""
    from lib import originals_guard

    folder = tmp_path / "会社"
    texts = folder / "記録" / "資料の本文" / CASE
    texts.mkdir(parents=True)
    official = f"案件/{CASE}/公式資料/公募要領_第3回.html"
    listed = {"案件": CASE, "資料": [{"id": "要領3", "名前": "公募要領", "公募回": "第3回", "ハッシュ": "a" * 64}],
              "置き場所": {"要領3": {"ファイル": official, "本文": f"記録/資料の本文/{CASE}/要領3"}}}
    (texts / "資料の一覧.json").write_text(json.dumps(listed, ensure_ascii=False), encoding="utf-8")
    # 中にあるときは、一覧の公式資料を照らすものにする
    assert [t.path for t in originals_guard.targets(folder, [])] == [official]

    outside = outside_folder(tmp_path)
    place = {"記録/資料の本文": folder / "記録" / "資料の本文", "案件の資料の本文": texts,
             "資料の一覧": texts / "資料の一覧.json"}[where]
    move_out(place, outside)
    outside_before = tree(outside)
    problems: list = []
    assert originals_guard.targets(folder, problems) == []
    assert any("別名" in p and "会社のフォルダの外" in p for p in problems), problems
    assert tree(outside) == outside_before


# ---- 今日の日付の差し替え ----


@pytest.mark.parametrize("where", ["設定.json", ".hojokin"])
def test_settings_link_is_not_read(tmp_path, where: str) -> None:
    """`.hojokin/設定.json`（`.hojokin/` も）が別名なら読まず、差し替えのないものとして扱う（hook を止めない。仮）。"""
    folder = tmp_path / "試しの会社"
    marker = folder / company.MARKER_DIR
    marker.mkdir(parents=True)
    clock = lambda: datetime(2026, 11, 4, 3, 0, tzinfo=timezone.utc)  # noqa: E731
    settings = json.dumps({"今日の日付": "2027-03-01"})
    # 中に置いたときは差し替わる
    company.settings_path(folder).write_text(settings, encoding="utf-8")
    assert dates.today(folder, clock) == date(2027, 3, 1)
    company.settings_path(folder).unlink()

    outside = outside_folder(tmp_path)
    (outside / company.SETTINGS_FILE).write_text(settings, encoding="utf-8")
    if where == "設定.json":
        company.settings_path(folder).symlink_to(outside / company.SETTINGS_FILE)
    else:
        marker.rmdir()
        marker.symlink_to(outside, target_is_directory=True)
    assert company.is_company_folder(folder)
    assert company.load_settings(folder) == {}
    assert dates.today(folder, clock) == date(2026, 11, 4)
