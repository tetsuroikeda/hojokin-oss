"""T0-7 原本を書き換えない（TASKS M4。SPEC 共通の要件「書類の版の管理」、DESIGN 4.7 の2・5章・10章）。

SPEC：整理と処理の前後で、原本と公式資料を比べる。
合格ライン：1バイトも変わらない。

- 公式資料は、junbi の道具（skills/junbi/scripts/fetch_documents.py）で、手元の公式サイトの写し（downloads/）を
  127.0.0.1 から取って置く（公募要領の PDF、Word のその1・2、Excel のその3）。
- 原本は、デモの会社の書類（testdata/デモの会社/書類/。F14）を入れ口に入れ、書類を整理する道具
  （skills/shorui/scripts/seiri.py）で原本の置き場へ移す。道具は Claude が Bash で動かすのと同じ形で、
  hook は hooks.json のコマンドで、Claude Code と同じ入力で動かす（tests/version_tool.py）。
- 「整理と処理の前後」：入れ口に入れた書類と整理した原本、整理の前と後の公式資料、
  その後の処理（申請書を3回直す、提出版を記録する、前の版を見る、もう1件整理する、公式資料を取り直す、
  開く・送る・応答を終える）の前と後を、バイト列で比べる。
- 道具が書き換えないことに加えて、どの経路で変わっても結果で守ることを確かめる（DESIGN 5章）：
  Claude がその場のコードで書き換えた・消したもの（応答の終わり）、社長が閉じている間に手で書き換えたもの
  （開いたとき）、書き換えた中身が先に版になったもの（社長が送ったとき）を、入れたときのバイト列に戻す。
  書き換わった中身は版に残さず、原本と公式資料の版は入れたときの1版のまま。戻せないときは消さずに知らせる。
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import company_tool as ct
import hook_runner as hr
import pytest
import version_tool as vt
from test_seiri_min import DOCS, LEDGER, TODAY, ok_json, organize, put
from test_seiri_min import run_tool as seiri_tool
from test_T0_6 import SONO1, blob, edit_three_times, submit
from test_T0_6 import run_tool as versions_tool
from test_T3_1 import Site

FETCH = Path("skills") / "junbi" / "scripts" / "fetch_documents.py"
FETCH_LIST = hr.REPO_ROOT / "skills" / "junbi" / "取る資料" / "省力化_一般型_第8回.json"
DOWNLOADS = hr.REPO_ROOT / "downloads" / "shoryokuka_ippan"
CASE = vt.CASE
OFFICIAL_DIR = f"案件/{CASE}/公式資料"
OFFICIAL_IDS = ("要領8", "Wordその1・2", "Excelその3")
SCHEDULE_ID = "スケジュール"
SCHEDULE_HTML = DOWNLOADS / "site_html" / "ippan_schedule.html"

# 入れ口に入れる3件と、Claude が読み取ったことにする区分・種類・日付・相手先
THREE = (
    ("入れ口/決算書18.pdf", "決算書_第18期.pdf", "決算・税", "決算書", "2025-04-01", ""),
    ("入れ口/scan0001.pdf", "履歴事項全部証明書.pdf", "登記・名簿", "履歴事項全部証明書", "2026-10-22", ""),
    ("入れ口/見積もり（つばさ台）.pdf", "見積書_つばさ台フードシステム.pdf", "見積・契約・請求", "見積書", "2026-10-20",
     "つばさ台フードシステム"),
)
KESSAN = "原本/決算・税/2025-04-01_決算書.pdf"
TOUKI = "原本/登記・名簿/2026-10-22_履歴事項全部証明書.pdf"
MITSUMORI = "原本/見積・契約・請求/2026-10-20_見積書_つばさ台フードシステム.pdf"


class World:
    """公式資料を取り、入れ口に3件を入れた会社のフォルダ。"""

    def __init__(self, tmp_path: Path) -> None:
        self.company = vt.Company(tmp_path)
        settings = self.company.folder / ".hojokin" / "設定.json"
        data = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
        data["今日の日付"] = TODAY
        settings.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.site = Site()
        self.lists = tmp_path / "一覧"
        self.lists.mkdir()
        self.bundled = json.loads(FETCH_LIST.read_text(encoding="utf-8"))
        for doc in self.bundled["資料"]:
            path = urlsplit(doc["URL"]).path
            if doc["id"] == SCHEDULE_ID:
                self.site.put(path, SCHEDULE_HTML.read_bytes(), "text/html; charset=utf-8")
            elif doc["id"] in OFFICIAL_IDS:
                self.site.put(path, (DOWNLOADS / Path(path).name).read_bytes())

    def fetch(self, ids) -> str:
        """junbi の道具で、公式資料を取る（Claude が Bash で動かすのと同じ形）。"""
        data = {"制度": self.bundled["制度"],
                "資料": [dict(d, URL=self.site.local(d["URL"])) for d in self.bundled["資料"] if d["id"] in ids]}
        path = self.lists / "一覧.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        env = {"PATH": self.company.env.path, "HOME": str(self.company.env.home), "TMPDIR": str(self.company.env.tmp)}
        r = subprocess.run(
            [hr.real_python(), "-B", str(self.company.env.plugin / FETCH), "--folder", str(self.company.folder),
             "--list", str(path), "--case-round", "第9回"],
            env=env, cwd=self.company.env.cwd, capture_output=True, timeout=600,
        )
        return ct.ok(r)

    def official_files(self) -> list:
        base = self.company.folder / OFFICIAL_DIR
        return sorted(p.relative_to(self.company.folder).as_posix() for p in base.iterdir() if p.is_file())

    def close(self) -> None:
        self.site.close()


@pytest.fixture
def world(tmp_path, downloads_files):
    w = World(tmp_path)
    c = w.company
    c.say("省力化の第9回の準備をして")
    w.fetch(OFFICIAL_IDS)
    assert c.stop() is None
    assert len(w.official_files()) == 3
    yield w
    w.close()


def protected(company: vt.Company) -> dict:
    """原本の置き場と公式資料のファイル（会社のフォルダからの場所 → (中身, 読み書きの権限)）。"""
    found = {}
    for top in [company.folder / "原本"] + sorted((company.folder / "案件").glob("*/公式資料")):
        for p in sorted(top.rglob("*")):
            if p.is_file():
                found[p.relative_to(company.folder).as_posix()] = (p.read_bytes(), stat.S_IMODE(p.stat().st_mode))
    return found


def put_three(company: vt.Company) -> dict:
    return {rel: put(company, rel, source) for rel, source, *_ in THREE}


def organize_three(company: vt.Company) -> None:
    for rel, _source, category, kind, day, partner in THREE:
        organize(company, rel, category, kind, day, partner)


def organized(world: World) -> dict:
    """3件を整理して応答を終えた後の、原本と公式資料。"""
    c = world.company
    put_three(c)
    c.say("書類を入れたので整理して")
    organize_three(c)
    assert c.stop() is None
    return protected(c)


def one_version_each(company: vt.Company, paths) -> None:
    """原本と公式資料の版は、入れたときの1版だけ。"""
    for rel in paths:
        records = company.log(rel)
        assert len(records) == 1, (rel, records)
        assert records[0]["変更"] == "足した", (rel, records)


def make_writable(path: Path) -> None:
    os.chmod(str(path), 0o644)


def stop_reason(output) -> str:
    assert output is not None and output.get("decision") == "block", output
    return output["reason"]


# ---- T0-7 の合格ライン ----


def test_T0_7_no_byte_changes_through_organizing_and_processing(world) -> None:
    c = world.company
    official_before = protected(c)
    assert set(official_before) == set(world.official_files())
    for data, mode in official_before.values():
        assert mode == 0o444

    # 整理の前と後：入れ口に入れたバイト列と、整理した原本が同じ。公式資料も変わらない
    sources = put_three(c)
    c.say("書類を入れたので整理して")
    assert sorted(d["場所"] for d in ok_json(seiri_tool(c, "scan"))["新しい書類"]) == sorted(sources)
    organize_three(c)
    assert c.stop() is None
    before = protected(c)
    for rel, path in zip(sources, (KESSAN, TOUKI, MITSUMORI)):
        assert before[path] == (sources[rel], 0o444)
    for rel, value in official_before.items():
        assert before[rel] == value
    assert set(before) == set(official_before) | {KESSAN, TOUKI, MITSUMORI}

    # 処理：申請書を3回直す、提出版を記録する、前の版を見る、もう1件整理する、公式資料を取り直す、開く・送る・終える
    edit_three_times(c)
    submit(c)
    c.start("startup")
    ct.ok(versions_tool(c, "show", "--document", SONO1, "--back", "1"))
    ct.ok(versions_tool(c, "log"))
    c.say("名簿も入れたので整理して")
    put(c, "入れ口/名簿.docx", "役員名簿.docx")
    organize(c, "入れ口/名簿.docx", "登記・名簿", "役員名簿", "2026-11-01")
    ct.ok(seiri_tool(c, "text", "--path", KESSAN))
    ct.ok(seiri_tool(c, "list"))
    assert ok_json(seiri_tool(c, "scan"))["新しい書類"] == []
    assert c.stop() is None
    c.say("公募要領が新しくなっていないか確かめて")
    out = world.fetch(OFFICIAL_IDS)
    assert "前と同じ" in out
    assert c.stop() is None
    c.start("resume")
    c.say("ありがとう")
    assert c.stop() is None

    after = protected(c)
    # 1バイトも変わらない（読み取り専用のまま）
    for rel, value in before.items():
        assert after[rel] == value, rel
    assert set(after) == set(before) | {"原本/登記・名簿/2026-11-01_役員名簿.docx"}
    one_version_each(c, after)


# ---- どの経路で変わっても、入れたときのバイト列に戻す ----


def test_changed_by_tool_code_is_restored_at_stop(world) -> None:
    """Claude がその場のコード（Bash など）で書き換えた・消した原本と公式資料を、応答の終わりに戻す。"""
    c = world.company
    before = organized(world)
    word, excel = [p for p in world.official_files() if p.endswith((".docx", ".xlsx"))]
    c.say("決算書の PDF を回転して、その3 も整えて")
    # 原本1：書き込めるようにして書き足す。原本2：消す
    make_writable(c.folder / KESSAN)
    with open(c.folder / KESSAN, "ab") as f:
        f.write(b"%% rotated\n")
    os.unlink(c.folder / TOUKI)
    # 公式資料1：1バイトだけ変え、大きさと更新時刻はそのままにする（時刻で読み飛ばさないことも確かめる）
    target = c.folder / excel
    st = target.stat()
    make_writable(target)
    data = bytearray(target.read_bytes())
    data[len(data) // 2] ^= 0x01
    target.write_bytes(bytes(data))
    os.utime(str(target), ns=(st.st_atime_ns, st.st_mtime_ns))
    assert target.stat().st_size == st.st_size and target.stat().st_mtime_ns == st.st_mtime_ns
    # 公式資料2：中身は変えず、書き込めるようにしただけ
    make_writable(c.folder / word)

    reason = stop_reason(c.stop())
    assert "戻しました" in reason
    for rel in (KESSAN, TOUKI, excel):
        assert rel in reason
    assert word not in reason
    assert protected(c) == before  # 1バイトも違わず、読み取り専用に戻る
    # 書き換えた中身は版に残らない。原本と公式資料の版は入れたときの1版のまま。社長の分として残るものもない
    one_version_each(c, before)
    assert c.pending() == []
    # 続けた応答の終わりと、次の発言では、もう何も伝えない
    assert c.stop(active=True) is None
    c.say("ありがとう")
    assert c.stop() is None
    one_version_each(c, before)


def test_changed_by_owner_while_closed_is_restored_at_start(world) -> None:
    """社長が閉じている間に手で書き換えた原本と公式資料を、開いたときに戻して知らせる。"""
    c = world.company
    before = organized(world)
    pdf = [p for p in world.official_files() if p.endswith(".pdf")][0]
    for rel in (MITSUMORI, pdf):
        make_writable(c.folder / rel)
        (c.folder / rel).write_bytes("%PDF-1.7\n% 社長がプレビューで書き込んだ\n".encode("utf-8"))
    context = vt.start_context(c.start("startup"))
    assert "戻しました" in context and "社長の最初の発言に答えるときに" in context
    assert MITSUMORI in context and pdf in context
    assert protected(c) == before
    one_version_each(c, before)
    assert c.pending() == []


def test_change_recorded_at_prompt_is_restored_from_earlier_version(world) -> None:
    """社長が送ったときに、書き換わった中身が先に「社長」の版になっていても、入れたときの版から戻す。"""
    c = world.company
    before = organized(world)
    word = [p for p in world.official_files() if p.endswith(".docx")][0]
    for rel in (TOUKI, word):
        make_writable(c.folder / rel)
        (c.folder / rel).write_bytes(b"PK\x03\x04" + "社長が上書きした".encode("utf-8"))
    c.say("証明書を差し替えておいた")
    assert c.log(TOUKI)[0]["だれ"] == "社長"  # 書き換えた中身が先に版になった
    reason = stop_reason(c.stop())
    assert TOUKI in reason and word in reason
    assert protected(c) == before


def test_unrestorable_change_is_reported_once_and_kept(world) -> None:
    """版の履歴に入れたときの中身がないもの（同じ応答の中で取った公式資料を、すぐ書き換えた）は、消さずに知らせる。
    応答の終わりには一度だけ伝え、開いたときは伝え直す。"""
    c = world.company
    c.say("スケジュールのページも取って")
    world.fetch([SCHEDULE_ID])
    html = [p for p in world.official_files() if p.endswith(".html")][0]
    make_writable(c.folder / html)
    (c.folder / html).write_bytes(b"<html>changed</html>")
    reason = stop_reason(c.stop())
    assert "戻せませんでした" in reason and html in reason
    assert (c.folder / html).read_bytes() == b"<html>changed</html>"  # 消さない
    assert c.stop(active=True) is None
    c.say("わかった")
    assert c.stop() is None  # 同じことでは続けさせない
    context = vt.start_context(c.start("startup"))
    assert "戻せませんでした" in context and html in context


def test_broken_ledger_does_not_stop_hooks(world) -> None:
    """台帳が読めなくても hook は落ちない（落ちると書き込みと Bash が止まる）。ほかの公式資料は照らし続ける。"""
    c = world.company
    before = organized(world)
    c.say("台帳を見て")
    make_writable(c.folder / LEDGER)
    (c.folder / LEDGER).write_text("{ 壊れた", encoding="utf-8")
    pdf = [p for p in world.official_files() if p.endswith(".pdf")][0]
    make_writable(c.folder / pdf)
    (c.folder / pdf).write_bytes(b"%PDF-1.7 changed")
    reason = stop_reason(c.stop())
    assert "確かめられないもの" in reason and "書類の台帳.json" in reason
    assert pdf in reason and "戻しました" in reason
    assert (c.folder / pdf).read_bytes() == before[pdf][0]
    context = vt.start_context(c.start("startup"))
    assert "書類の台帳.json" in context


def test_documents_outside_inbox_are_not_touched_by_hooks(world) -> None:
    """照らすのは台帳と資料の一覧にあるものだけ。入れ口のまだ整理していない書類や、ほかの書類には触れない。"""
    c = world.company
    organized(world)
    data = (DOCS / "見積書_ほしみ機工.pdf").read_bytes()
    c.write("入れ口/見積2.pdf", data)
    c.write("社長/メモ.txt", "そのまま")
    c.say("見積書をもう1通入れた")
    assert c.stop() is None
    c.start("startup")
    assert (c.folder / "入れ口/見積2.pdf").read_bytes() == data
    assert stat.S_IMODE((c.folder / "入れ口/見積2.pdf").stat().st_mode) == 0o644
    assert (c.folder / "社長/メモ.txt").read_text(encoding="utf-8") == "そのまま"
