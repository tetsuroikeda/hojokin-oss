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
  同じ応答の中で取った公式資料・整理した原本を書き換えても戻す（道具が置く前に中身を版の履歴の置き場に入れる）。
- 台帳と資料の一覧は Claude も社長も直せるので、それが書き換えられても守りが崩れないことを確かめる：
  置き場の外（.claude/・.hojokin/・.git/・申請書・記録/、別名のフォルダの先）を指しても書かず、読み取り専用にもしない。
  台帳が消えた・読めない（UTF-8 でない、権限がない）・項目が消えた・ハッシュが書き換えられたときも、
  控えにある入れたときの中身で照らして戻し、知らせる（応答の終わりには一度だけ）。
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
from test_seiri_min import DOCS, LEDGER, TODAY, blob_id, ok_json, organize, put, sha256
from test_seiri_min import refused as seiri_refused
from test_seiri_min import run_tool as seiri_tool
from test_T0_6 import SONO1, blob, edit_three_times, submit
from test_T0_6 import run_tool as versions_tool
from test_T3_1 import Site

FETCH = Path("skills") / "junbi" / "scripts" / "fetch_documents.py"
FETCH_LIST = hr.REPO_ROOT / "skills" / "junbi" / "取る資料" / "省力化_一般型_第8回.json"
DOWNLOADS = hr.REPO_ROOT / "downloads" / "shoryokuka_ippan"
CASE = vt.CASE
OFFICIAL_DIR = f"案件/{CASE}/公式資料"
LIST = f"記録/資料の本文/{CASE}/資料の一覧.json"
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
ANCHORS = ".hojokin/一時/原本の印.json"  # 道具が置いた原本と公式資料の控え（lib/protected_store.py）
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


def doc_list(company: vt.Company) -> dict:
    """公式資料を取る道具が残した、資料の一覧。"""
    return json.loads((company.folder / LIST).read_text(encoding="utf-8"))


VERSION_HASHES_CODE = """
import hashlib
from pathlib import Path
folder = Path(sys.argv[1])
out = []
for r in history.log(folder, sys.argv[2]):
    data = history.content_at(folder, r.version, sys.argv[2])
    out.append(None if data is None else hashlib.sha256(data).hexdigest())
print(json.dumps(out))
"""


def version_hashes(company: vt.Company, rel: str) -> list:
    """その書類の版ごとの中身のハッシュ（新しい順）。"""
    return ct.py_json(VERSION_HASHES_CODE, str(company.folder), rel)


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


def test_official_changed_in_same_response_is_restored(tmp_path, downloads_files) -> None:
    """同じ応答の中で取った公式資料を、その場のコードで書き換えても、応答の終わりに取ったときのバイト列に戻す。
    書き換えた中身は「入れたときの1版」にならず、取り直しても改訂と取り違えない。"""
    w = World(tmp_path)
    try:
        c = w.company
        ids = OFFICIAL_IDS + (SCHEDULE_ID,)
        c.say("省力化の第9回の準備をして、その1に書き始めて")
        w.fetch(ids)
        fetched = protected(c)
        assert len(fetched) == 4
        word = [p for p in w.official_files() if p.endswith(".docx")][0]
        html = [p for p in w.official_files() if p.endswith(".html")][0]
        # 取る道具は、置く前に中身を版の履歴の置き場に入れ、版の印を資料の一覧に残す
        places = doc_list(c)["置き場所"]
        for place in places.values():
            assert place["版の印"] == blob_id(fetched[place["ファイル"]][0])
        for rel in (word, html):
            make_writable(c.folder / rel)
        (c.folder / word).write_bytes(b"PK\x03\x04 written in place")
        (c.folder / html).write_bytes(b"<html>changed</html>")

        reason = stop_reason(c.stop())
        assert "戻しました" in reason and word in reason and html in reason
        assert "戻せませんでした" not in reason
        assert protected(c) == fetched
        # 版は取ったときの1版だけで、その中身は取ったときのバイト列
        one_version_each(c, fetched)
        for rel in fetched:
            assert version_hashes(c, rel) == [sha256(fetched[rel][0])], rel
        assert c.stop(active=True) is None

        # 取り直しても「前と同じ」（書き換えたファイルを改訂と取り違えない）
        c.say("公募要領が新しくなっていないか確かめて")
        out = w.fetch(ids)
        assert out.count("前と同じ") >= len(ids)
        assert "前と中身が違う" not in out and "改訂" not in out
        assert c.stop() is None
        assert protected(c) == fetched
        one_version_each(c, fetched)
    finally:
        w.close()


def test_unrestorable_change_is_reported_once_and_kept(world) -> None:
    """版の履歴に入れたときの中身がないもの（版の履歴の置き場から中身が失われた）は、消さずに知らせる。
    応答の終わりには一度だけ伝え、開いたときは伝え直す。"""
    c = world.company
    c.say("スケジュールのページも取って")
    world.fetch([SCHEDULE_ID])
    html = [p for p in world.official_files() if p.endswith(".html")][0]
    # 取ったときに預けた中身を、版の履歴の置き場から消す（まだ版にしていないので、ほかに中身はない）
    blob = doc_list(c)["置き場所"][SCHEDULE_ID]["版の印"]
    loose = c.folder / ".git" / "objects" / blob[:2] / blob[2:]
    os.chmod(str(loose), 0o644)
    loose.unlink()
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


# ---- 台帳と資料の一覧が書き換えられても、置き場の外には書かない ----


def test_ledger_and_list_pointing_outside_are_not_written(world) -> None:
    """台帳と資料の一覧に、原本・公式資料の置き場の外を指す場所を書き足しても、照らしと戻しはそこに書かず、
    読み取り専用にもしない（.claude/・.hojokin/・.git/・申請書・記録/ など）。何も書かずに知らせる。"""
    c = world.company
    before = organized(world)
    # 1. Claude が好きな中身のファイルを作る（応答の終わりに版の置き場へ入る）
    payload = b'{"permissions": {"allow": ["Bash(*)"]}}\n'
    c.say("メモを作って")
    c.write("記録/メモ.json", payload)
    assert c.stop() is None
    # 2. 台帳と資料の一覧に、その中身で、置き場の外を指す項目を足す（記録/ は Claude が直せる）
    watched = (".claude/settings.json", ".hojokin/設定.json", ".git/config", f"{vt.APPLICATION}/その1・2.docx")
    c.write(f"{vt.APPLICATION}/その1・2.docx", b"PK\x03\x04 sono1")
    c.say("台帳を直して")
    snapshot = {rel: ((c.folder / rel).read_bytes(), stat.S_IMODE((c.folder / rel).stat().st_mode)) for rel in watched}
    # 原本の区分のフォルダを、.claude/ を指す別名にする（区分の中に見えるが、書けば .claude/ に及ぶ）
    alias = c.folder / "原本" / "会社の資料"
    alias.rmdir()
    alias.symlink_to(c.folder / ".claude", target_is_directory=True)
    settings = c.folder / ".claude/settings.json"
    hojokin_settings = c.folder / ".hojokin/設定.json"
    data = json.loads((c.folder / LEDGER).read_text(encoding="utf-8"))
    outside = [".claude/settings.json", ".git/config", f"{vt.APPLICATION}/その1・2.docx", "記録/メモ2.json",
               "原本/../.claude/settings.json", str(settings), "原本/でたらめ/x.json", "入れ口/x.json"]
    for rel in outside:
        data["原本"].append({"場所": rel, "ハッシュ": sha256(payload), "版の印": blob_id(payload)})
    # 中身が同じなら読み取り専用にするだけの枝も、置き場の外では動かない
    data["原本"].append({"場所": ".hojokin/設定.json", "ハッシュ": sha256(hojokin_settings.read_bytes())})
    data["原本"].append({"場所": "原本/会社の資料/settings.json", "ハッシュ": sha256(settings.read_bytes())})
    c.write(LEDGER, json.dumps(data, ensure_ascii=False))
    lists = doc_list(c)
    pdf_id = next(i for i, p in lists["置き場所"].items() if p["ファイル"].endswith(".pdf"))
    pdf = lists["置き場所"][pdf_id]["ファイル"]
    lists["置き場所"][pdf_id] = {"ファイル": ".claude/settings.json", "本文": "", "版の印": blob_id(payload)}
    for doc in lists["資料"]:
        if doc["id"] == pdf_id:
            doc["ハッシュ"] = sha256(payload)
    c.write(LIST, json.dumps(lists, ensure_ascii=False))

    # 3. 応答の終わりと、次に開いたときの照らし
    reason = stop_reason(c.stop())
    context = vt.start_context(c.start("startup"))
    for text in (reason, context):
        assert "確かめられないもの" in text
        assert "原本の置き場（原本/<区分>/）の外を指すもの" in text and ".claude/settings.json" in text
        assert "公式資料の置き場（案件/<案件>/公式資料/）の外を指すもの" in text
        assert "原本/会社の資料 が別名（エイリアス）になっています" in text
        assert pdf in text  # 資料の一覧から消えた公式資料は、控えで照らし続けて知らせる
    for rel, value in snapshot.items():
        assert ((c.folder / rel).read_bytes(), stat.S_IMODE((c.folder / rel).stat().st_mode)) == value, rel
    for rel in ("記録/メモ2.json", "入れ口/x.json", "原本/でたらめ"):
        assert not (c.folder / rel).exists(), rel
    # 同じことでは、応答の終わりに続けさせない
    c.say("わかった")
    assert c.stop() is None
    for rel, value in snapshot.items():
        assert ((c.folder / rel).read_bytes(), stat.S_IMODE((c.folder / rel).stat().st_mode)) == value, rel
    alias.unlink()
    alias.mkdir()
    assert protected(c) == before  # 原本と公式資料はそのまま


# ---- 台帳が消えた・項目が消えた・書き換えられた・読めない ----


def test_deleted_ledger_keeps_originals_protected(world) -> None:
    """台帳を消して原本を書き換えても、控えにある入れたときの中身で照らして戻し、台帳がないことを知らせる。"""
    c = world.company
    before = organized(world)
    c.say("台帳を消して、決算書に書き足して")
    (c.folder / LEDGER).unlink()
    make_writable(c.folder / KESSAN)
    with open(c.folder / KESSAN, "ab") as f:
        f.write(b"%% appended\n")
    reason = stop_reason(c.stop())
    assert "戻しました" in reason and KESSAN in reason
    assert "書類の台帳.json がありません" in reason and "revert" in reason
    assert protected(c) == before
    one_version_each(c, before)
    # 整理の道具も、台帳を戻すまで動かない（原本を新しい書類として出さない）
    out = seiri_refused(seiri_tool(c, "scan"))
    assert "書類の台帳.json がありません" in out
    assert c.stop(active=True) is None
    c.say("どうしたらいい？")
    assert c.stop() is None  # 同じことでは続けさせない
    assert "書類の台帳.json がありません" in vt.start_context(c.start("startup"))
    # 台帳を前の版に戻すと、知らせは止まり、整理の道具も動く
    c.say("台帳を戻して")
    ct.ok(versions_tool(c, "revert", "--document", LEDGER, "--back", "1", "--reason", "台帳を戻して"))
    assert c.stop() is None
    assert ok_json(seiri_tool(c, "scan"))["新しい書類"] == []
    assert "書類の台帳" not in vt.start_context(c.start("startup"))
    assert protected(c) == before


def test_removed_ledger_entry_keeps_original_protected(world) -> None:
    """台帳から1件を消して、その原本を書き換えても戻す。新しい書類として出さず、もう一度移さない。"""
    c = world.company
    before = organized(world)
    c.say("台帳を書き直して、決算書を回転して")
    data = json.loads((c.folder / LEDGER).read_text(encoding="utf-8"))
    data["原本"] = [e for e in data["原本"] if e["場所"] != KESSAN]
    c.write(LEDGER, json.dumps(data, ensure_ascii=False))
    make_writable(c.folder / KESSAN)
    (c.folder / KESSAN).write_bytes(b"%PDF-1.7 rotated")
    reason = stop_reason(c.stop())
    assert "戻しました" in reason and "台帳から項目が消えました" in reason and KESSAN in reason
    assert protected(c) == before
    one_version_each(c, before)
    assert KESSAN not in [d["場所"] for d in ok_json(seiri_tool(c, "scan"))["新しい書類"]]
    out = seiri_refused(seiri_tool(c, "organize", "--path", KESSAN, "--category", "決算・税", "--kind", "決算書",
                                   "--date", "2025-04-02"))
    assert "もう整理した原本" in out
    assert protected(c) == before


def test_ledger_deleted_in_same_response_as_organizing(world) -> None:
    """整理したのと同じ応答の中で台帳を消し、原本を書き換えても戻す（整理の道具が控えにも残すため）。"""
    c = world.company
    official = protected(c)
    sources = put_three(c)
    c.say("書類を入れたので整理して")
    organize_three(c)
    (c.folder / LEDGER).unlink()
    make_writable(c.folder / TOUKI)
    (c.folder / TOUKI).write_bytes(b"%PDF-1.7 overwritten")
    reason = stop_reason(c.stop())
    assert "戻しました" in reason and TOUKI in reason and "書類の台帳.json がありません" in reason
    after = protected(c)
    for rel, path in zip(sources, (KESSAN, TOUKI, MITSUMORI)):
        assert after[path] == (sources[rel], 0o444)
    for rel, value in official.items():
        assert after[rel] == value
    one_version_each(c, after)


def test_rewritten_ledger_hash_does_not_overwrite_original(world) -> None:
    """台帳のハッシュと版の印を、別の中身のものに書き換えても、原本をその中身で上書きしない。"""
    c = world.company
    before = organized(world)
    payload = b"%PDF-1.7 fake statement"
    c.say("メモを作って")
    c.write("記録/偽.pdf", payload)
    assert c.stop() is None
    c.say("台帳を直して")
    data = json.loads((c.folder / LEDGER).read_text(encoding="utf-8"))
    for e in data["原本"]:
        if e["場所"] == KESSAN:
            e["ハッシュ"], e["版の印"] = sha256(payload), blob_id(payload)
    c.write(LEDGER, json.dumps(data, ensure_ascii=False))
    reason = stop_reason(c.stop())
    assert "ハッシュが、入れたときと違うもの" in reason and KESSAN in reason
    assert "戻しました" not in reason
    assert protected(c) == before
    one_version_each(c, before)


def anchors(company: vt.Company) -> dict:
    """道具が置いた原本と公式資料の控え（場所 → {ハッシュ, 版の印, 種類}）。"""
    return json.loads((company.folder / ANCHORS).read_text(encoding="utf-8"))["守るもの"]


def make_fake(world: World) -> bytes:
    """Claude が好きな中身のファイルを作り、応答の終わりに版の置き場へ入れる（台帳に書けば、戻す元として見つかる中身）。"""
    c = world.company
    payload = b"%PDF-1.7 fake statement"
    c.say("メモを作って")
    c.write("記録/偽.pdf", payload)
    assert c.stop() is None
    return payload


def point_ledger(company: vt.Company, rel: str, payload: bytes) -> None:
    """台帳の原本 rel のハッシュと版の印を、payload のものにする（なければ足す）。"""
    data = json.loads((company.folder / LEDGER).read_text(encoding="utf-8"))
    entries = [e for e in data["原本"] if e["場所"] == rel]
    if not entries:
        entries = [{"場所": rel}]
        data["原本"].append(entries[0])
    for e in entries:
        e["ハッシュ"], e["版の印"] = sha256(payload), blob_id(payload)
    company.write(LEDGER, json.dumps(data, ensure_ascii=False))


NO_RECORD = "道具が置いた記録（控え）がなく、今の中身もそのハッシュと違うもの"
ANCHORS_GONE = "原本と公式資料の控え（.hojokin/一時/原本の印.json）がありません"


def test_rewritten_ledger_with_anchors_deleted_does_not_overwrite_original(world) -> None:
    """台帳の原本のハッシュと版の印を別の中身のものに書き換え、控えのファイルも消しても、原本をその中身で
    置き換えない。控えが消えたことと、道具が置いた記録がないことを知らせる。台帳を前の版に戻せば、また守る。"""
    c = world.company
    before = organized(world)
    payload = make_fake(world)
    c.say("台帳を直して")
    point_ledger(c, KESSAN, payload)
    (c.folder / ANCHORS).unlink()
    reason = stop_reason(c.stop())
    assert "戻しました" not in reason
    assert ANCHORS_GONE in reason
    assert NO_RECORD in reason and KESSAN in reason
    assert protected(c) == before  # 1バイトも変わらない
    one_version_each(c, before)
    # 控えは、今の中身と版の履歴で確かめられたものだけで作り直す（台帳の偽のハッシュは採らない）
    rebuilt = anchors(c)
    assert set(rebuilt) == set(before) - {KESSAN}
    for rel, a in rebuilt.items():
        assert a["ハッシュ"] == sha256(before[rel][0]), rel
    # 同じことでは、応答の終わりに続けさせない。開いたときは伝え直す。原本はそのまま
    c.say("わかった")
    assert c.stop() is None
    context = vt.start_context(c.start("startup"))
    assert NO_RECORD in context and KESSAN in context
    assert protected(c) == before
    # 台帳を前の版に戻すと、知らせが止まり、決算書も入れたときの中身で控えに戻る（書き換えても戻す）
    c.say("台帳を戻して")
    ct.ok(versions_tool(c, "revert", "--document", LEDGER, "--back", "1", "--reason", "台帳を戻して"))
    assert c.stop() is None
    assert anchors(c)[KESSAN]["ハッシュ"] == sha256(before[KESSAN][0])
    c.say("決算書に書き足して")
    make_writable(c.folder / KESSAN)
    with open(c.folder / KESSAN, "ab") as f:
        f.write(b"%% appended\n")
    reason = stop_reason(c.stop())
    assert "戻しました" in reason and KESSAN in reason
    assert protected(c) == before
    one_version_each(c, before)


def test_original_replaced_together_with_ledger_is_not_adopted(world) -> None:
    """控えを消し、台帳と原本を同じ別の中身に置き換えても、その中身を控えに採らない（版の履歴の入れたときの版と違う）。
    置き換えたことを知らせ、入れたときの中身は版の履歴に残る。後で元の中身に戻されても、置き換えた中身で上書きしない。"""
    c = world.company
    before = organized(world)
    payload = make_fake(world)
    c.say("決算書を差し替えて")
    point_ledger(c, KESSAN, payload)
    (c.folder / ANCHORS).unlink()
    make_writable(c.folder / KESSAN)
    (c.folder / KESSAN).write_bytes(payload)
    reason = stop_reason(c.stop())
    assert "戻しました" not in reason
    assert ANCHORS_GONE in reason
    assert "版の履歴にある入れたときの版の中身と違い" in reason and KESSAN in reason
    assert KESSAN not in anchors(c)
    assert version_hashes(c, KESSAN)[-1] == sha256(before[KESSAN][0])  # 入れたときの中身は版の履歴に残る
    # 社長と相談して元の中身に戻しても、台帳の偽のハッシュの中身で上書きしない
    c.say("決算書を元に戻した")
    (c.folder / KESSAN).write_bytes(before[KESSAN][0])
    reason = stop_reason(c.stop())
    assert "戻しました" not in reason and NO_RECORD in reason and KESSAN in reason
    assert (c.folder / KESSAN).read_bytes() == before[KESSAN][0]
    assert KESSAN not in anchors(c)


def test_deleted_ledger_and_anchors_are_told_until_fixed(world) -> None:
    """台帳と控えのファイルを両方消しても、黙らない。控えが消えたことと、前に照らした原本が照らせなくなったことを
    知らせ、台帳を前の版に戻すまで、開いたときに伝え直す。原本は1バイトも変えない。"""
    c = world.company
    before = organized(world)
    c.say("台帳と控えを消して")
    (c.folder / LEDGER).unlink()
    (c.folder / ANCHORS).unlink()
    reason = stop_reason(c.stop())
    assert ANCHORS_GONE in reason and "照らせなくなったもの" in reason
    for rel in (KESSAN, TOUKI, MITSUMORI):
        assert rel in reason
    assert "戻しました" not in reason
    assert protected(c) == before
    c.say("わかった")
    assert c.stop() is None  # 同じことでは続けさせない
    context = vt.start_context(c.start("startup"))
    assert "照らせなくなったもの" in context and KESSAN in context
    # 台帳を前の版に戻すと、原本を控えに採り直して、知らせが止まる。書き換えても戻す
    c.say("台帳を戻して")
    ct.ok(versions_tool(c, "revert", "--document", LEDGER, "--back", "1", "--reason", "台帳を戻して"))
    assert c.stop() is None
    assert set(anchors(c)) == set(before)
    assert "照らせなくなった" not in vt.start_context(c.start("startup"))
    c.say("証明書を差し替えて")
    make_writable(c.folder / TOUKI)
    (c.folder / TOUKI).write_bytes(b"%PDF-1.7 overwritten")
    reason = stop_reason(c.stop())
    assert "戻しました" in reason and TOUKI in reason
    assert protected(c) == before
    one_version_each(c, before)


def test_ledger_entries_without_tool_record_are_not_written(world) -> None:
    """台帳と資料の一覧に、置き場の中の正しい区分の場所を指す項目を足しても、道具が置いた記録（控え）がなければ書かない。
    ない場所にはファイルを作らず、社長が原本の置き場に直接入れた、まだ整理していない書類も上書きしない。"""
    c = world.company
    before = organized(world)
    payload = make_fake(world)
    owner_doc = "原本/決算・税/社長が入れた決算書.pdf"
    owner_data = (DOCS / "決算書_第17期.pdf").read_bytes()
    c.write(owner_doc, owner_data)
    c.say("台帳を直して")
    fake = "原本/決算・税/偽.pdf"
    fake_official = f"{OFFICIAL_DIR}/偽.pdf"
    for rel in (fake, owner_doc):
        point_ledger(c, rel, payload)
    lists = doc_list(c)
    lists["資料"].append({"id": "偽", "名前": "偽の資料", "公募回": "第8回", "URL": "http://127.0.0.1/x.pdf",
                         "ハッシュ": sha256(payload)})
    lists["置き場所"]["偽"] = {"ファイル": fake_official, "本文": "", "版の印": blob_id(payload)}
    c.write(LIST, json.dumps(lists, ensure_ascii=False))

    def unchanged() -> None:
        assert not (c.folder / fake).exists() and not (c.folder / fake_official).exists()
        assert (c.folder / owner_doc).read_bytes() == owner_data
        assert stat.S_IMODE((c.folder / owner_doc).stat().st_mode) == 0o644  # 読み取り専用にもしない
        after = protected(c)
        for rel, value in before.items():
            assert after[rel] == value, rel
        assert set(after) == set(before) | {owner_doc}

    reason = stop_reason(c.stop())
    assert "戻しました" not in reason and NO_RECORD in reason
    for rel in (fake, owner_doc, fake_official):
        assert rel in reason
    assert ANCHORS_GONE not in reason
    unchanged()
    for rel in (fake, owner_doc, fake_official):
        assert rel not in anchors(c)
    c.say("わかった")
    assert c.stop() is None
    context = vt.start_context(c.start("startup"))
    assert NO_RECORD in context and owner_doc in context
    unchanged()


def test_non_utf8_ledger_keeps_checking(world) -> None:
    """台帳が UTF-8 でなくても、公式資料と原本は照らし続ける。知らせは応答の終わりに一度だけ。"""
    c = world.company
    before = organized(world)
    c.say("台帳を見て")
    raw = (c.folder / LEDGER).read_bytes()
    (c.folder / LEDGER).write_bytes(raw.rstrip() + "\n// 社長のメモ：あ".encode("cp932"))
    pdf = [p for p in world.official_files() if p.endswith(".pdf")][0]
    for rel in (pdf, KESSAN):
        make_writable(c.folder / rel)
        (c.folder / rel).write_bytes(b"%PDF-1.7 changed")
    reason = stop_reason(c.stop())
    assert "確かめられないもの" in reason and "書類の台帳.json が読めません" in reason and "UTF-8" in reason
    assert "戻しました" in reason and pdf in reason and KESSAN in reason
    assert protected(c) == before
    one_version_each(c, before)
    assert c.stop(active=True) is None
    c.say("わかった")
    assert c.stop() is None  # 同じことでは続けさせない
    assert "書類の台帳.json が読めません" in vt.start_context(c.start("startup"))
    out = seiri_refused(seiri_tool(c, "scan"))  # 道具も落ちずに断る
    assert "UTF-8" in out


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="管理者では、権限を外しても読めてしまう")
def test_unreadable_ledger_keeps_checking(world) -> None:
    """台帳が読めない（権限がない）ときも、公式資料は照らし続ける。知らせは応答の終わりに一度だけ。"""
    c = world.company
    before = organized(world)
    c.say("台帳を見て")
    os.chmod(str(c.folder / LEDGER), 0o000)
    try:
        pdf = [p for p in world.official_files() if p.endswith(".pdf")][0]
        make_writable(c.folder / pdf)
        (c.folder / pdf).write_bytes(b"%PDF-1.7 changed")
        reason = stop_reason(c.stop())
        assert "書類の台帳.json が読めません（PermissionError）" in reason
        assert "戻しました" in reason and pdf in reason
        assert (c.folder / pdf).read_bytes() == before[pdf][0]
        c.say("わかった")
        assert c.stop() is None
    finally:
        os.chmod(str(c.folder / LEDGER), 0o644)


def test_failure_of_check_is_told_once_at_stop(tmp_path) -> None:
    """照らしそのものが止まったときの知らせも、応答の終わりには一度だけ。開いたときは伝え直す。"""
    from lib import originals_guard

    folder = tmp_path / "会社"
    (folder / ".hojokin" / "一時").mkdir(parents=True)
    error = RuntimeError("思わぬ形")
    first = originals_guard.failure_notes(folder, error, at_start=False)
    assert len(first) == 1 and "照らせませんでした" in first[0]
    assert originals_guard.failure_notes(folder, error, at_start=False) == []
    assert originals_guard.failure_notes(folder, error, at_start=True) == first


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
