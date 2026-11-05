"""書類3件の整理（最小限。TASKS M4。SPEC F5「書類の整理」、DESIGN 4.5・4.7・6章）。

- 道具（skills/shorui/scripts/seiri.py）は、Claude が Bash で動かすのと同じ形（/usr/bin/python3 -B、
  CLAUDE_* の環境変数なし、PATH は python3 と sh だけ）で動かす。何の書類か（種類・日付・相手先・区分）は、
  Claude が読み取って引数で渡すものとして、テストが渡す。
- 会社のフォルダは、会社のフォルダを作る道具で用意し、hook は hooks.json のコマンドで動かす（tests/version_tool.py）。
- 書類は、デモの会社の書類（testdata/デモの会社/書類/。F14）を、名前を変えて入れ口に入れる。
- 版の持ち方の2つ（Git の形と、版のファイルの形。DESIGN 10章・TASKS M0c）の両方で流す。

確かめること：
- 入れ口（下のフォルダも）の書類を中身のハッシュで見つける。同じ中身のものは分けて知らせ、動かさない。
- 3件が `原本/<区分>/<日付>_<種類>[_<相手先>]<拡張子>` に移り、中身は1バイトも変わらず、読み取り専用になる。
- 台帳（記録/書類の台帳.json）に、元の名前と場所・ハッシュ・版の印・種類・日付・相手先・区分・整理した日時が残る。
- 応答の終わりに、移したことが「ツール」の版として残り、版の名前の指摘は出ない。
- 動かしただけ・名前を変えただけの書類は、新しい書類として出さない。分からない書類は動かさずに台帳に残せる。
- 同じ名前・同じ中身の原本があるとき、引数が違うとき、会社のフォルダの外・ツールの置き場の中は、何も変えずに断る。
  「.」で始まる場所（.git/・.hojokin/・.claude/）は、大文字・小文字を変えても「..」を挟んでも断る。
- 台帳から項目が消えた原本は、新しい書類として出さず、もう一度移さない。台帳が消えた・読めない（UTF-8 でない など）
  ときは、何も変えずに断る（traceback を出さない）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import unicodedata
from pathlib import Path

import company_tool as ct
import hook_runner as hr
import pytest
import version_tool as vt

SCRIPT = Path("skills") / "shorui" / "scripts" / "seiri.py"
SKILL = hr.REPO_ROOT / "skills" / "shorui" / "SKILL.md"
DOCS = hr.REPO_ROOT / "testdata" / "デモの会社" / "書類"
LEDGER = "記録/書類の台帳.json"
TODAY = "2026-11-04"

# 入れ口に入れる3件（入れる場所 → 元の書類）と、Claude が読み取ったことにする種類・日付・相手先・区分
THREE = {
    "入れ口/決算書18.pdf": ("決算書_第18期.pdf", "決算・税", "決算書", "2025-04-01", ""),
    "入れ口/見積もり（つばさ台）.pdf": ("見積書_つばさ台フードシステム.pdf", "見積・契約・請求", "見積書", "2026-10-20",
                                  "つばさ台フードシステム"),
    "入れ口/10月/名簿.docx": ("役員名簿.docx", "登記・名簿", "役員名簿", "2026-11-01", ""),
}
EXPECTED = {
    "入れ口/決算書18.pdf": "原本/決算・税/2025-04-01_決算書.pdf",
    "入れ口/見積もり（つばさ台）.pdf": "原本/見積・契約・請求/2026-10-20_見積書_つばさ台フードシステム.pdf",
    "入れ口/10月/名簿.docx": "原本/登記・名簿/2026-11-01_役員名簿.docx",
}
DUPLICATE = "入れ口/メール添付/見積書_つばさ台.pdf"  # 見積もり（つばさ台）.pdf と同じ中身


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()


@pytest.fixture(params=vt.FORMS)
def company(request, tmp_path) -> vt.Company:
    """Git の形と、版のファイルの形（同期されるフォルダの形。TASKS M0c）の両方。"""
    c = vt.Company(tmp_path, form=request.param)
    settings = c.folder / ".hojokin" / "設定.json"
    data = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
    data["今日の日付"] = TODAY
    settings.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return c


def run_tool(company: vt.Company, command: str, *args: str, folder: Path = None) -> subprocess.CompletedProcess:
    """書類を整理する道具を、Claude が Bash で動かすのと同じ形で動かす。"""
    env = {"PATH": company.env.path, "HOME": str(company.env.home), "TMPDIR": str(company.env.tmp)}
    return subprocess.run(
        [hr.real_python(), "-B", str(company.env.plugin / SCRIPT), command,
         "--folder", str(folder or company.folder), *args],
        env=env, cwd=company.env.cwd, capture_output=True, timeout=120,
    )


def ok_json(r: subprocess.CompletedProcess):
    return json.loads(ct.ok(r))


def without_since(items: list) -> list:
    """見つけた書類から「前回から」（開いたときの変化。TASKS B9 で足した。tests/test_T5_7.py で見る）を除く。"""
    return [{k: v for k, v in item.items() if k != "前回から"} for item in items]


def refused(r: subprocess.CompletedProcess) -> str:
    out = r.stdout.decode("utf-8")
    assert r.returncode == 2, (r.returncode, out, r.stderr.decode("utf-8"))
    assert r.stderr == b"", r.stderr.decode("utf-8")
    return out


def put(company: vt.Company, rel: str, source: str) -> bytes:
    data = (DOCS / source).read_bytes()
    company.write(rel, data)
    return data


def organize(company: vt.Company, rel: str, category: str, kind: str, day: str, partner: str = "",
             note: str = "") -> dict:
    args = ["--path", rel, "--category", category, "--kind", kind, "--date", day]
    if partner:
        args += ["--partner", partner]
    if note:
        args += ["--note", note]
    return ok_json(run_tool(company, "organize", *args))


def ledger(company: vt.Company) -> dict:
    return json.loads((company.folder / LEDGER).read_text(encoding="utf-8"))


def files_and_ledger(company: vt.Company) -> dict:
    """会社のフォルダのファイル（版の履歴とその場限りの置き場を除く）の中身と、読み書きの権限。
    版の履歴は、Git の形は .git/、版のファイルの形は 記録/版/（預けた中身を含む）。"""
    found = {}
    for p in sorted(company.folder.rglob("*")):
        rel = p.relative_to(company.folder).as_posix()
        if rel.startswith((".git/", ".hojokin/一時/", f"{vt.STORE}/")) or not p.is_file():
            continue
        found[rel] = (p.read_bytes(), stat.S_IMODE(p.stat().st_mode))
    return found


def latest_version(company: vt.Company) -> dict:
    """いちばん新しい版の作者と、変わったファイル（消したものも含む）。どちらの形でも同じ入口で読む。"""
    return company.versions()[0]


def put_three(company: vt.Company) -> dict:
    sources = {rel: put(company, rel, spec[0]) for rel, spec in THREE.items()}
    put(company, DUPLICATE, THREE["入れ口/見積もり（つばさ台）.pdf"][0])
    return sources


# ---- 3件の整理 ----


def test_three_documents_are_organized(company) -> None:
    sources = put_three(company)
    company.say("書類を入れ口に入れたので、整理して")

    found = ok_json(run_tool(company, "scan"))
    assert sorted(d["場所"] for d in found["新しい書類"]) == sorted(THREE)
    assert without_since(found["同じ中身"]) == [{"場所": DUPLICATE, "同じ中身の書類": "入れ口/見積もり（つばさ台）.pdf",
                                "同じ中身の書類は": "新しい書類"}]
    sizes = {d["場所"]: d["大きさ"] for d in found["新しい書類"]}
    assert sizes == {rel: len(data) for rel, data in sources.items()}
    # 見つけるだけでは何も変えない
    assert all((company.folder / rel).read_bytes() == data for rel, data in sources.items())
    assert not (company.folder / LEDGER).exists()

    for rel, (_source, category, kind, day, partner) in THREE.items():
        out = organize(company, rel, category, kind, day, partner)
        assert out["元の場所"] == rel
        assert out["新しい場所"] == EXPECTED[rel]

    for rel, dest in EXPECTED.items():
        moved = company.folder / dest
        # 中身は1バイトも変わらない。読み取り専用。入れ口には残らない
        assert moved.read_bytes() == sources[rel]
        assert stat.S_IMODE(moved.stat().st_mode) == 0o444
        assert not (company.folder / rel).exists()
    # 同じ中身のものは動かさない
    assert (company.folder / DUPLICATE).read_bytes() == sources["入れ口/見積もり（つばさ台）.pdf"]

    entries = ledger(company)["原本"]
    assert [e["場所"] for e in entries] == [EXPECTED[rel] for rel in THREE]
    for e, (rel, (_source, category, kind, day, partner)) in zip(entries, THREE.items()):
        data = sources[rel]
        assert e["元の場所"] == rel
        assert e["元の名前"] == rel.rsplit("/", 1)[1]
        assert (e["区分"], e["種類"], e["日付"], e["相手先"]) == (category, kind, day, partner)
        assert e["ハッシュ"] == sha256(data)
        assert e["版の印"] == blob_id(data)
        assert e["大きさ"] == len(data)
        assert e["整理した日時"].startswith(TODAY + "T") and e["整理した日時"].endswith("+09:00")
    assert [e["id"] for e in entries] == ["原本-0001", "原本-0002", "原本-0003"]

    # 一覧（社長に示す元の場所 → 新しい場所）
    listed = ok_json(run_tool(company, "list"))
    assert [(e["元の場所"], e["場所"]) for e in listed] == list(EXPECTED.items())

    # 応答の終わり：移したことが「ツール」の版として残り、版の名前の指摘は出ない
    assert company.stop() is None
    latest = latest_version(company)
    assert latest["author"].startswith("ツール")
    assert set(EXPECTED.values()) | {LEDGER} <= set(latest["files"])
    assert set(THREE) <= set(latest["files"])  # 入れ口から消えたことも残る
    for dest in EXPECTED.values():
        records = company.log(dest)
        assert len(records) == 1 and records[0]["変更"] == "足した", records
        assert records[0]["理由"] == "書類を入れ口に入れたので、整理して"

    # もう一度見つけると、新しい書類はない。同じ中身のものは、台帳の原本と同じ中身として出る
    again = ok_json(run_tool(company, "scan"))
    assert again["新しい書類"] == []
    assert without_since(again["同じ中身"]) == [{"場所": DUPLICATE, "同じ中身の書類": EXPECTED["入れ口/見積もり（つばさ台）.pdf"],
                                "同じ中身の書類は": "台帳の原本"}]
    # 同じ中身のものを整理しようとしても、移さない
    before = files_and_ledger(company)
    out = refused(run_tool(company, "organize", "--path", DUPLICATE, "--category", "見積・契約・請求",
                           "--kind", "見積書", "--date", "2026-10-20", "--partner", "つばさ台フードシステム"))
    assert "同じ中身" in out and "まとめるか" in out
    assert files_and_ledger(company) == before


def test_original_bytes_are_in_history_store_before_stop(company) -> None:
    """移す前に、中身を版の履歴の置き場に入れておく（同じ応答の中で書き換えられても戻せるように）。
    Git の形は .git に、版のファイルの形は `記録/版/_預け/<sha256>` に読み取り専用で預ける。"""
    data = put(company, "入れ口/決算書18.pdf", "決算書_第18期.pdf")
    entry = organize(company, "入れ口/決算書18.pdf", "決算・税", "決算書", "2025-04-01")["台帳"]
    assert entry["版の印"] == blob_id(data)
    if company.form == vt.FILES:
        kept = company.folder / vt.STORE / "_預け" / sha256(data)
        assert kept.read_bytes() == data and stat.S_IMODE(kept.stat().st_mode) == 0o444
        assert company.store_problems() == []
        return
    code = ("from dulwich.repo import Repo\n"
            "repo = Repo(sys.argv[1])\n"
            "print(json.dumps(repo.object_store[sys.argv[2].encode()].as_raw_string().hex()))")
    assert bytes.fromhex(ct.py_json(code, str(company.folder), entry["版の印"])) == data


# ---- 動かしただけ・名前を変えただけ、分からない書類 ----


def test_moved_or_renamed_documents_are_not_new(company) -> None:
    put(company, "入れ口/IMG_0001.pdf", "納税証明書_その2.pdf")
    company.write("入れ口/メモ.txt", "金曜まで A-3 ×2")
    found = ok_json(run_tool(company, "scan"))
    assert sorted(d["場所"] for d in found["新しい書類"]) == ["入れ口/IMG_0001.pdf", "入れ口/メモ.txt"]

    # 何の書類か分からないものは、動かさずに確かめ済みとして残す
    out = ok_json(run_tool(company, "keep", "--path", "入れ口/メモ.txt", "--reason", "社長がそのままでいいと答えた"))
    assert out["台帳"]["場所"] == "入れ口/メモ.txt"
    assert out["台帳"]["理由"] == "社長がそのままでいいと答えた"
    assert (company.folder / "入れ口/メモ.txt").exists()
    kept = ledger(company)["確かめ済み"]
    assert [(e["場所"], e["ハッシュ"]) for e in kept] == [("入れ口/メモ.txt", sha256("金曜まで A-3 ×2".encode()))]

    # 動かしただけ・名前を変えただけなら、新しい書類として出さない
    (company.folder / "入れ口/社長").mkdir()
    (company.folder / "入れ口/メモ.txt").rename(company.folder / "入れ口/社長/付箋.txt")
    found = ok_json(run_tool(company, "scan"))
    assert [d["場所"] for d in found["新しい書類"]] == ["入れ口/IMG_0001.pdf"]
    assert found["確かめ済みで出さなかった数"] == 1

    # 中身が変われば、また出す
    company.write("入れ口/社長/付箋.txt", "金曜まで A-3 ×3")
    found = ok_json(run_tool(company, "scan"))
    assert sorted(d["場所"] for d in found["新しい書類"]) == ["入れ口/IMG_0001.pdf", "入れ口/社長/付箋.txt"]

    # 整理した原本は、新しい書類として出さない
    organize(company, "入れ口/IMG_0001.pdf", "決算・税", "納税証明書", "2026-10-23")
    found = ok_json(run_tool(company, "scan"))
    assert [d["場所"] for d in found["新しい書類"]] == ["入れ口/社長/付箋.txt"]


def test_scan_ignores_files_made_by_computer(company) -> None:
    put(company, "入れ口/決算書18.pdf", "決算書_第18期.pdf")
    for name in (".DS_Store", "~$名簿.docx", ".~lock.名簿.docx#", "Thumbs.db", "desktop.ini"):
        company.write(f"入れ口/{name}", "x")
    found = ok_json(run_tool(company, "scan"))
    assert [d["場所"] for d in found["新しい書類"]] == ["入れ口/決算書18.pdf"]


def test_unregistered_files_in_originals_are_found(company) -> None:
    """社長が原本の置き場に直接入れた書類も、台帳になければ整理する書類として出る。"""
    put(company, "原本/決算・税/決算書.pdf", "決算書_第17期.pdf")
    found = ok_json(run_tool(company, "scan"))
    assert [d["場所"] for d in found["新しい書類"]] == ["原本/決算・税/決算書.pdf"]
    out = organize(company, "原本/決算・税/決算書.pdf", "決算・税", "決算書", "2024-04-01")
    assert out["新しい場所"] == "原本/決算・税/2024-04-01_決算書.pdf"
    assert ok_json(run_tool(company, "scan"))["新しい書類"] == []


# ---- 名前の決まりと、断るとき ----


def test_name_rules(company) -> None:
    put(company, "入れ口/doc04512.pdf", "カタログ_つばさ台フードシステム.pdf")
    put(company, "入れ口/scan.PDF", "履歴事項全部証明書.pdf")
    put(company, "入れ口/見積2.pdf", "見積書_ほしみ機工.pdf")
    # 年だけの日付、拡張子は小文字に、名前の文字は1文字の形（NFC）に、名前に使えない文字は置き換える
    nfd_kind = unicodedata.normalize("NFD", "カタログ")
    assert organize(company, "入れ口/doc04512.pdf", "写真・カタログ", nfd_kind, "2026",
                    "つばさ台フードシステム")["新しい場所"] == "原本/写真・カタログ/2026_カタログ_つばさ台フードシステム.pdf"
    assert organize(company, "入れ口/scan.PDF", "原本/登記・名簿", "履歴事項全部証明書",
                    "2026-10-22")["新しい場所"] == "原本/登記・名簿/2026-10-22_履歴事項全部証明書.pdf"
    assert organize(company, "入れ口/見積2.pdf", "見積・契約・請求", "見積書", "2026-10-27",
                    "ほしみ機工/営業部")["新しい場所"] == "原本/見積・契約・請求/2026-10-27_見積書_ほしみ機工・営業部.pdf"
    for e in ledger(company)["原本"]:
        assert unicodedata.is_normalized("NFC", e["場所"])
        assert (company.folder / e["場所"]).exists()


def test_same_name_needs_note(company) -> None:
    put(company, "入れ口/a.pdf", "見積書_つばさ台フードシステム.pdf")
    put(company, "入れ口/b.pdf", "見積書_ほしみ機工.pdf")
    organize(company, "入れ口/a.pdf", "見積・契約・請求", "見積書", "2026-10-20", "つばさ台")
    before = files_and_ledger(company)
    out = refused(run_tool(company, "organize", "--path", "入れ口/b.pdf", "--category", "見積・契約・請求",
                           "--kind", "見積書", "--date", "2026-10-20", "--partner", "つばさ台"))
    assert "同じ名前" in out and "補足" in out
    assert files_and_ledger(company) == before
    out = organize(company, "入れ口/b.pdf", "見積・契約・請求", "見積書", "2026-10-20", "つばさ台", "包装機")
    assert out["新しい場所"] == "原本/見積・契約・請求/2026-10-20_見積書_つばさ台_包装機.pdf"
    assert out["台帳"]["補足"] == "包装機"


@pytest.mark.parametrize("args, words", [
    (["--category", "決算・税", "--kind", "決算書", "--date", "2026/03/31"], "日付"),
    (["--category", "決算・税", "--kind", "決算書", "--date", "2026-02-30"], "ない日付"),
    (["--category", "決算書", "--kind", "決算書", "--date", "2026-03-31"], "区分"),
    (["--category", "決算・税", "--kind", "  ", "--date", "2026-03-31"], "種類"),
])
def test_bad_arguments_change_nothing(company, args, words) -> None:
    put(company, "入れ口/決算書18.pdf", "決算書_第18期.pdf")
    before = files_and_ledger(company)
    out = refused(run_tool(company, "organize", "--path", "入れ口/決算書18.pdf", *args))
    assert words in out
    assert files_and_ledger(company) == before


def test_refuses_places_outside_documents(company, tmp_path) -> None:
    outside = tmp_path / "デスクトップ" / "見積書.pdf"
    outside.parent.mkdir()
    shutil.copyfile(DOCS / "見積書_ほしみ機工.pdf", outside)
    put(company, "記録/見積書.pdf", "見積書_ほしみ機工.pdf")
    put(company, "案件/2026_省力化（一般型）第9回/公式資料/要領.pdf", "決算書_第17期.pdf")
    (company.folder / "入れ口/別名.pdf").symlink_to(outside)
    put(company, "入れ口/決算書18.pdf", "決算書_第18期.pdf")
    organize(company, "入れ口/決算書18.pdf", "決算・税", "決算書", "2025-04-01")
    before = files_and_ledger(company)
    outside_before = outside.read_bytes()
    for given, words in ((str(outside), "外"), ("../デスクトップ/見積書.pdf", "外"), ("記録/見積書.pdf", "記録"),
                         ("案件/2026_省力化（一般型）第9回/公式資料/要領.pdf", "案件"), ("入れ口/別名.pdf", "別名"),
                         ("原本/決算・税/2025-04-01_決算書.pdf", "もう整理した原本"), ("入れ口/ない.pdf", "見つからない")):
        out = refused(run_tool(company, "organize", "--path", given, "--category", "見積・契約・請求",
                               "--kind", "見積書", "--date", "2026-10-27"))
        assert words in out, (given, out)
    assert files_and_ledger(company) == before
    assert outside.read_bytes() == outside_before


def test_refuses_hidden_places_in_any_case(company) -> None:
    """「.」で始まる場所（.git/・.hojokin/・.claude/、隠しファイル）は、大文字・小文字を変えても、「..」を挟んでも、
    中の絶対の場所で渡しても断り、何も変えない（Mac の既定のディスクは大文字と小文字を区別しないため、
    `.Claude/settings.json` も `.claude/settings.json` を指す。DESIGN 5章・4.7）。"""
    put(company, "入れ口/決算書18.pdf", "決算書_第18期.pdf")
    put(company, "入れ口/.隠し.pdf", "見積書_ほしみ機工.pdf")
    company.say("書類を入れたので整理して")
    watched = (".claude/settings.json", ".hojokin/設定.json") + ((".git/HEAD",) if company.form == vt.GIT else ())
    snapshot = {rel: (company.folder / rel).read_bytes() for rel in watched}
    before = files_and_ledger(company)
    places = (".Claude/settings.json", ".GIT/HEAD", ".Hojokin/設定.json", ".CLAUDE/settings.json",
              "入れ口/../.Claude/settings.json", "入れ口/../.GIT/HEAD", str(company.folder / ".Claude" / "settings.json"),
              ".claude/settings.json", ".git/HEAD", ".hojokin/設定.json", "入れ口/.隠し.pdf")
    commands = (("organize", ["--category", "会社の資料", "--kind", "設定", "--date", "2026-11-04"]),
                ("keep", ["--reason", "そのままでいい"]), ("text", []))
    for given in places:
        for command, extra in commands:
            out = refused(run_tool(company, command, "--path", given, *extra))
            assert "書類を整理する場所の外" in out, (given, command, out)
    assert files_and_ledger(company) == before  # 原本の置き場に何も増えず、台帳も設定もそのまま
    for rel, data in snapshot.items():
        assert (company.folder / rel).read_bytes() == data, rel
    # 版の記録も止まらない（.git/HEAD が残り、そのあと整理した原本が「ツール」の版になる）
    dest = organize(company, "入れ口/決算書18.pdf", "決算・税", "決算書", "2025-04-01")["新しい場所"]
    assert company.stop() is None
    records = company.log(dest)
    assert len(records) == 1 and records[0]["変更"] == "足した" and records[0]["だれ"] == "ツール", records


def test_refuses_outside_company_folder(tmp_path) -> None:
    env = ct.Env(tmp_path)
    folder = env.folder("ただのフォルダ")
    (folder / "見積書.pdf").write_bytes((DOCS / "見積書_ほしみ機工.pdf").read_bytes())
    before = hr.snapshot(folder)
    for command, args in (("scan", []), ("organize", ["--path", "見積書.pdf", "--category", "見積・契約・請求",
                                                    "--kind", "見積書", "--date", "2026-10-27"])):
        r = subprocess.run(
            [hr.real_python(), "-B", str(env.plugin / SCRIPT), command, "--folder", str(folder), *args],
            env={"PATH": env.path, "HOME": str(env.home), "TMPDIR": str(env.tmp)},
            cwd=env.cwd, capture_output=True, timeout=60,
        )
        assert r.returncode == 2, r
        assert "会社のフォルダではありません" in r.stdout.decode("utf-8")
    assert hr.snapshot(folder) == before


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="管理者では、権限を外しても書けてしまう")
def test_source_folder_not_writable_changes_nothing(company) -> None:
    """元の場所から消せないとき（社長のフォルダが書き込めない など）は、原本の置き場に残さず、移さなかったことにする。"""
    put(company, "入れ口/社長/決算書18.pdf", "決算書_第18期.pdf")
    locked_dir = company.folder / "入れ口/社長"
    before = files_and_ledger(company)
    os.chmod(str(locked_dir), 0o555)
    try:
        out = refused(run_tool(company, "organize", "--path", "入れ口/社長/決算書18.pdf", "--category", "決算・税",
                               "--kind", "決算書", "--date", "2025-04-01"))
    finally:
        os.chmod(str(locked_dir), 0o755)
    assert "ファイルを扱えませんでした" in out
    assert files_and_ledger(company) == before


def test_broken_ledger_is_not_overwritten(company) -> None:
    put(company, "入れ口/決算書18.pdf", "決算書_第18期.pdf")
    company.write(LEDGER, "{ 壊れた")
    before = files_and_ledger(company)
    out = refused(run_tool(company, "organize", "--path", "入れ口/決算書18.pdf", "--category", "決算・税",
                           "--kind", "決算書", "--date", "2025-04-01"))
    assert "JSON として読めません" in out
    assert "JSON として読めません" in refused(run_tool(company, "scan"))
    assert files_and_ledger(company) == before
    # UTF-8 でない台帳も、落ちずに断る（終了コード2、traceback を出さない）
    company.write(LEDGER, '{"原本": [], "メモ": "あ"}'.encode("cp932"))
    before = files_and_ledger(company)
    for command in ("scan", "list"):
        assert "UTF-8" in refused(run_tool(company, command))
    assert "UTF-8" in refused(run_tool(company, "organize", "--path", "入れ口/決算書18.pdf", "--category", "決算・税",
                                       "--kind", "決算書", "--date", "2025-04-01"))
    assert files_and_ledger(company) == before


def test_originals_missing_from_ledger_are_still_originals(company) -> None:
    """台帳から項目が消えても、整理した原本（控えにあるもの）は新しい書類として出さず、もう一度移さない。
    台帳そのものが消えたときは、前の版に戻すまで整理しない。"""
    put(company, "入れ口/決算書18.pdf", "決算書_第18期.pdf")
    put(company, "入れ口/見積.pdf", "見積書_ほしみ機工.pdf")
    kessan = organize(company, "入れ口/決算書18.pdf", "決算・税", "決算書", "2025-04-01")["新しい場所"]
    mitsumori = organize(company, "入れ口/見積.pdf", "見積・契約・請求", "見積書", "2026-10-27", "ほしみ機工")["新しい場所"]
    data = ledger(company)
    data["原本"] = [e for e in data["原本"] if e["場所"] != kessan]
    company.write(LEDGER, json.dumps(data, ensure_ascii=False))
    put(company, "入れ口/決算書のコピー.pdf", "決算書_第18期.pdf")
    found = ok_json(run_tool(company, "scan"))
    assert found["新しい書類"] == []
    assert without_since(found["同じ中身"]) == [{"場所": "入れ口/決算書のコピー.pdf", "同じ中身の書類": kessan, "同じ中身の書類は": "台帳の原本"}]
    before = files_and_ledger(company)
    for args, words in ((["--path", kessan, "--category", "決算・税", "--kind", "決算書", "--date", "2025-04-02"],
                         "もう整理した原本"),
                        (["--path", "入れ口/決算書のコピー.pdf", "--category", "決算・税", "--kind", "決算書",
                          "--date", "2025-04-02"], "同じ中身")):
        assert words in refused(run_tool(company, "organize", *args))
    assert "もう整理した原本" in refused(run_tool(company, "keep", "--path", kessan))
    assert files_and_ledger(company) == before

    # 台帳が消えたら、どの道具も動かない（原本を新しい書類として出さない。台帳にない原本を作らない）
    (company.folder / LEDGER).unlink()
    before = files_and_ledger(company)
    for command, args in (("scan", []), ("list", []), ("keep", ["--path", "入れ口/決算書のコピー.pdf"]),
                          ("organize", ["--path", "入れ口/決算書のコピー.pdf", "--category", "決算・税",
                                        "--kind", "決算書", "--date", "2025-04-02"])):
        out = refused(run_tool(company, command, *args))
        assert "書類の台帳.json がありません" in out and "前の版に戻して" in out, (command, out)
    assert files_and_ledger(company) == before
    assert (company.folder / mitsumori).exists()


# ---- 中身を読む ----


def test_text_of_word_excel_pdf_and_photo(company) -> None:
    put(company, "入れ口/名簿.docx", "役員名簿.docx")
    put(company, "入れ口/Book2.xlsx", "労働者名簿.xlsx")
    put(company, "入れ口/見積.pdf", "見積書_つばさ台フードシステム.pdf")
    company.write("入れ口/IMG_2091.jpg", b"\xff\xd8\xff\xe0 jpeg")
    word = ct.ok(run_tool(company, "text", "--path", "入れ口/名簿.docx"))
    assert "役員名簿" in word and "2026年11月1日現在" in word
    excel = ct.ok(run_tool(company, "text", "--path", "入れ口/Book2.xlsx"))
    assert "シート" in excel and "労働者名簿" in excel
    pdf = ct.ok(run_tool(company, "text", "--path", "入れ口/見積.pdf"))
    assert "御見積書" in pdf and "2026年10月20日" in pdf and "つばさ台フードシステム" in pdf
    photo = ct.ok(run_tool(company, "text", "--path", "入れ口/IMG_2091.jpg"))
    assert "Read で開いて" in photo
    short = ct.ok(run_tool(company, "text", "--path", "入れ口/見積.pdf", "--limit", "200"))
    assert "ここまで" in short and len(short) < 400


# ---- skill の手順と道具が合っている ----


def test_skill_md_matches_tool() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\nname: shorui\n")
    assert len(text.splitlines()) < 500
    commands = re.findall(r'^python3 -B "\$\{CLAUDE_PLUGIN_ROOT\}/skills/shorui/scripts/seiri\.py" (\S+) (.*)$',
                          text, flags=re.M)
    assert {c for c, _ in commands} == {"scan", "text", "organize", "keep", "list"}
    help_text = {}
    for command, rest in commands:
        assert '--folder "${CLAUDE_PROJECT_DIR}"' in rest, rest
        if command not in help_text:
            r = subprocess.run([hr.real_python(), "-B", str(hr.REPO_ROOT / SCRIPT), command, "--help"],
                               capture_output=True, timeout=60)
            assert r.returncode == 0, r
            help_text[command] = r.stdout.decode("utf-8")
        for option in re.findall(r"(--[a-z]+)", rest):
            assert option in help_text[command], (command, option)
    # 区分の名前は、会社のフォルダの区分と同じ
    from lib.company_init import ORIGINAL_KINDS
    assert "／".join(ORIGINAL_KINDS) in text
