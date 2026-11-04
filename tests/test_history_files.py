"""版のファイルの形（同期されるフォルダの形）だけの確かめ（TASKS M0c。SPEC 共通の要件「書類の版の管理」・T0-6、
DESIGN 4.7・10章「書類の版」）。

T0-6 と版の記録のふるまい（だれ・理由・社長の手直し・提出版・見るだけ・戻す・錠待ち など）は、tests/test_T0_6.py・
tests/test_history.py・tests/test_revert.py が、Git の形と版のファイルの形の両方で確かめる。ここでは、版のファイルの形の
作り（DESIGN 10章）に当たることを確かめる。
- Git を使わず（.git を作らず）、版を1つずつ丸ごとのファイルとして `記録/版/<書類>/` に残し、1件ごとの記録（日時・書類・
  理由・だれ・案件・段階）を添える。版のファイルは足すだけで書き換えず、読み取り専用。名前で日時とだれが分かる。
- 何が変わったかの控え（索引）は、消えても `記録/版/` から作り直す（別のパソコンに移したとき）。
- 止められた処理の残り（錠、書きかけ）を片付ける。書く途中で時間の上限を過ぎたら、書きかけを残さない。
- 版のファイルが書き換えられていれば、取り出さずに断る。`記録/版/` やその中が別名なら、外に書かない。
- 会社のフォルダを作る道具は、同期されるフォルダでも、経営者が選べば版のファイルの形で用意する（Git の形は断る）。
- iCloud の「デスクトップと書類」の見分け（Finder の設定が 1 のときだけ）。CloudDocs の中の Desktop・Documents の
  フォルダは、同期を切った後も残る（この Mac で 11/4 に確かめた）ので、見分けに使わない。

hook は hooks.json のコマンドから、Claude Code と同じ入力で動かす（tests/version_tool.py）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import time
from pathlib import Path

import company_tool as ct
import hook_runner as hr
import pytest
import version_tool as vt
from test_T0_6 import blob, refused, run_tool

SONO1 = f"{vt.APPLICATION}/その1.docx"
OWNER_REASON = "社長が手で変更"
SCENES = f"{vt.STORE}/_版の一覧"
INDEX = f"{vt.STATE}/版のファイルの索引.json"
NAME = re.compile(r"^[0-9]{4}年[0-9]{2}月[0-9]{2}日 [0-9]{2}時[0-9]{2}分[0-9]{2}秒 (ツール|社長) [0-9a-f]{7}\.docx$")


@pytest.fixture
def company(tmp_path) -> vt.Company:
    return vt.Company(tmp_path, form=vt.FILES)


def version_files(company: vt.Company, document: str) -> dict:
    """書類の版のファイル（名前 → 中身）。"""
    place = company.folder / vt.STORE / document
    return {p.name: p.read_bytes() for p in sorted(place.iterdir())} if place.is_dir() else {}


def scenes(company: vt.Company) -> list:
    """版ごとの記録（古い順）。"""
    place = company.folder / SCENES
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(place.iterdir()) if p.suffix == ".json"]


def tree(folder: Path) -> dict:
    """フォルダの中のすべて（場所 → 中身。フォルダと別名は None）。別名はたどらない。"""
    found = {}
    for dirpath, dirnames, filenames in os.walk(str(folder)):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            found[path.relative_to(folder).as_posix()] = None if path.is_dir() or path.is_symlink() else path.read_bytes()
    return found


def three_edits(company: vt.Company) -> None:
    """ツール → 社長が手で → ツール の順に、その1を3回直す。"""
    company.say("計画書のその1を作って")
    company.write(SONO1, blob("docx", 1))
    assert company.stop() is None
    company.write(SONO1, blob("docx", 2))
    company.say("その1を手で直しました")
    assert company.stop() is None
    company.say("効果の段を直して")
    company.write(SONO1, blob("docx", 3))
    assert company.stop() is None


# ---- 版を丸ごとのファイルとして残し、1件ごとの記録を添える ----

def test_versions_are_whole_files_with_a_record_each(company) -> None:
    """Git を使わず、版を丸ごとのファイルとして 記録/版/<書類>/ に残し、1件ごとに日時・書類・理由・だれ・案件・段階を添える。"""
    three_edits(company)
    assert not (company.folder / ".git").exists()
    # 作業のファイルは1つのまま
    assert sorted(p.name for p in (company.folder / vt.APPLICATION).iterdir()) == ["その1.docx"]
    files = version_files(company, SONO1)
    assert sorted(files.values()) == sorted([blob("docx", 1), blob("docx", 2), blob("docx", 3)])
    for name in files:
        assert NAME.match(name), name  # Finder でも、日時とだれが分かる名前
        path = company.folder / vt.STORE / SONO1 / name
        assert stat.S_IMODE(path.stat().st_mode) & 0o222 == 0, name  # 読み取り専用
    assert sorted(n.split(" ")[2] for n in files) == ["ツール", "ツール", "社長"]

    mine = [s for s in scenes(company) if any(i["書類"] == SONO1 for i in s["書類"])]
    assert [(s["だれ"], s["理由"]) for s in mine] == [
        ("ツール", "計画書のその1を作って"), ("社長", OWNER_REASON), ("ツール", "効果の段を直して")]
    for scene, n in zip(mine, (1, 2, 3)):
        assert re.fullmatch(r"[0-9a-f]{40}", scene["版"])
        assert scene["日時"].endswith("+09:00")
        (item,) = scene["書類"]
        assert (item["書類"], item["案件"], item["段階"]) == (SONO1, vt.CASE, vt.STAGE)
        assert item["変更"] == ("足した" if n == 1 else "変えた")
        assert item["版のファイル"].startswith(f"{vt.STORE}/{SONO1}/")
        data = (company.folder / item["版のファイル"]).read_bytes()
        assert data == blob("docx", n)
        assert item["sha256"] == hashlib.sha256(data).hexdigest() and item["大きさ"] == len(data)
    # 同じ入口（lib/history.py の log）で読むと、Git の形と同じ形の履歴になる
    records = company.log(SONO1)
    assert [(r["だれ"], r["理由"], r["版"]) for r in records] == [(s["だれ"], s["理由"], s["版"]) for s in reversed(mine)]
    assert company.store_problems() == []


def test_version_files_are_only_added(company) -> None:
    """版のファイルは足すだけで、前の版のファイルは書き換えない（同期で食い違いにくい）。"""
    company.say("その1を作って")
    company.write(SONO1, blob("docx", 1))
    company.stop()
    before = {name: (company.folder / vt.STORE / SONO1 / name).stat() for name in version_files(company, SONO1)}
    first_scenes = sorted(p.name for p in (company.folder / SCENES).iterdir())
    time.sleep(0.05)
    for n in (2, 3, 4):
        company.say(f"{n}版目に直して")
        company.write(SONO1, blob("docx", n))
        company.stop()
    for name, st in before.items():
        now = (company.folder / vt.STORE / SONO1 / name).stat()
        assert (now.st_mtime_ns, now.st_ino, now.st_size) == (st.st_mtime_ns, st.st_ino, st.st_size)
    assert len(version_files(company, SONO1)) == 4
    names = sorted(p.name for p in (company.folder / SCENES).iterdir())
    assert names[: len(first_scenes)] == first_scenes and len(names) == len(first_scenes) + 3


def test_deleted_document_keeps_its_version_files(company) -> None:
    """書類を消しても、版のファイルは残り、消す前の版を取り出せる。"""
    company.say("その1を作って")
    company.write(SONO1, blob("docx", 1))
    company.stop()
    (company.folder / SONO1).unlink()
    company.say("消しました")
    (latest, first) = company.log(SONO1)
    assert (latest["変更"], latest["だれ"]) == ("消した", "社長")
    assert company.content(latest["版"], SONO1) is None
    assert list(version_files(company, SONO1).values()) == [blob("docx", 1)]
    out = ct.ok(run_tool(company, "show", "--document", SONO1, "--back", "1"))
    assert "見るだけ/" in out


# ---- 何が変わったかの控え（索引）は、消えても作り直す ----

def test_index_is_rebuilt_from_the_store(company) -> None:
    """索引（.hojokin/一時/ の中）が消えても（別のパソコンに移したときなど）、記録/版/ から作り直す。
    変わっていない書類で版を増やさず、変わった書類は「変えた」として残す。"""
    three_edits(company)
    count = len(company.versions())
    (company.folder / INDEX).unlink()
    assert company.say("続けて") is None
    assert company.stop() is None
    assert len(company.versions()) == count
    assert company.pending() == []
    company.write(SONO1, blob("docx", 4))
    (company.folder / INDEX).write_text("壊れた控え", encoding="utf-8")
    company.say("直しました")
    (record,) = [r for r in company.log() if r["版"] == company.log()[0]["版"]]
    assert (record["書類"], record["変更"], record["だれ"]) == (SONO1, "変えた", "社長")
    assert len(company.versions()) == count + 1


def test_sync_conflict_copies_are_not_read_as_records(company) -> None:
    """同期の食い違いで増えた記録の写し（「… (1).json」など）は、版ごとの記録として読まない。"""
    three_edits(company)
    records = company.log()
    place = company.folder / SCENES
    newest = sorted(p for p in place.iterdir() if p.suffix == ".json")[-1]
    (place / f"{newest.stem} (1).json").write_bytes(newest.read_bytes())
    assert company.log() == records


# ---- 止められた処理の残り、時間の上限 ----

def dead_pid() -> int:
    p = subprocess.Popen(["/usr/bin/true"])
    p.wait()
    return p.pid


def test_leftovers_of_a_stopped_hook_are_cleared(company) -> None:
    """見張りに止められた hook が残した錠と書きかけの版のファイルは、次の場面で片付けて残す
    （錠を持っていた処理がもう動いていなければ、すぐに外す）。"""
    company.write("入れ口/写真/IMG_0001.jpg", b"photo-" * 2000)
    work = company.folder / vt.WORK
    work.mkdir(parents=True, exist_ok=True)
    (work / "hojokin-tmp-abc123").write_bytes(b"half")
    company.lock_path().write_text(f"{dead_pid()}\n", encoding="ascii")
    assert len(company.leftovers()) == 2
    start = time.monotonic()
    assert company.say("写真を入れた") is None
    # 錠を持っていた処理が動いていると見誤れば、5秒待って版を残せず、錠待ちの控えになる。時間は、負荷が高くても通る
    # 上限にし、すぐに外したことは、その場面で版が残り、控えがないことで確かめる
    assert time.monotonic() - start < 20
    assert vt.carried_notes(company.folder) == []
    (record,) = [r for r in company.log() if r["版"] == company.log()[0]["版"]]
    assert (record["書類"], record["だれ"], record["理由"]) == ("入れ口/写真/IMG_0001.jpg", "社長", OWNER_REASON)
    assert company.leftovers() == []
    assert company.store_problems() == []


def test_writing_stops_midway_at_the_deadline(company) -> None:
    """版のファイルを写す途中で時間の上限を過ぎたら、やめて、書きかけを残さない。"""
    company.write("入れ口/a.bin", b"x" * (3 * 1024 * 1024))
    code = ("import time\nfrom pathlib import Path\nfrom lib import history_files\n"
            "status, _st, info = history_files._write_version(Path(sys.argv[1]), sys.argv[2], time.monotonic() - 1)\n"
            "print(json.dumps([status, info], ensure_ascii=False))")
    assert ct.py_json(code, str(company.folder), str(company.folder / "入れ口" / "a.bin")) == ["時間切れ", None]
    assert company.leftovers() == []


# ---- 版のファイルが書き換えられた・置き場が別名 ----

def test_changed_version_file_is_not_handed_out(company) -> None:
    """社長が Finder で版のファイルを開いて直してしまったなど、中身が記録の印と合わなければ、取り出さずに断る。"""
    three_edits(company)
    first = company.log(SONO1)[-1]
    (scene,) = [s for s in scenes(company) if s["版"] == first["版"]]
    path = company.folder / scene["書類"][0]["版のファイル"]
    path.chmod(0o644)
    path.write_bytes("書き換えた中身".encode("utf-8"))
    out = refused(run_tool(company, "show", "--document", SONO1, "--version", first["版"]))
    assert "合いません" in out and "取り出せません" in out, out
    out = refused(run_tool(company, "revert", "--document", SONO1, "--version", first["版"], "--reason", "最初に戻して"))
    assert "合いません" in out
    assert (company.folder / SONO1).read_bytes() == blob("docx", 3)
    assert not (company.folder / "見るだけ").exists()
    problems = company.store_problems()
    assert any("合いません" in p for p in problems) and any("書き込める" in p for p in problems), problems


@pytest.mark.parametrize("where", [vt.STORE, f"{vt.STORE}/案件"])
def test_store_behind_a_link_is_not_written(company, where) -> None:
    """記録/版/ か、その中のフォルダが外への別名なら、版のファイルを書かずに（外を変えずに）、版の記録が止まったことを
    開いたときに伝える。.git も作らない。"""
    company.say("その1を作って")
    company.write(SONO1, blob("docx", 1))
    company.stop()
    outside = company.env.folder("外のフォルダ")
    place = company.folder / where
    moved = outside / "移した置き場"
    place.rename(moved)
    place.symlink_to(moved, target_is_directory=True)
    before = tree(outside)
    company.say("直して")
    company.write(SONO1, blob("docx", 2))
    assert company.stop() is None
    assert tree(outside) == before
    context = vt.start_context(company.start())
    assert "版の記録が止まっています" in context and "別名" in context, context
    assert not any(word in context for word in ("補助プログラム（Python）が動かない", "xcode-select")), context
    assert tree(outside) == before
    assert not (company.folder / ".git").exists()


# ---- 守り ----

def test_settings_deny_editing_version_files(company) -> None:
    """会社のフォルダの設定は、組み込みの Edit・Write で版のファイル（記録/版/）を書き換えさせない（DESIGN 4.7）。"""
    settings = json.loads((company.folder / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "Edit(/記録/版/**)" in settings["permissions"]["deny"]
    assert "Edit(/.git/**)" in settings["permissions"]["deny"]


def test_version_files_are_not_reverted(company) -> None:
    """版のファイルの置き場（記録/版/）は、戻す道具の対象にしない。"""
    three_edits(company)
    name = next(iter(version_files(company, SONO1)))
    out = refused(run_tool(company, "revert", "--document", f"{vt.STORE}/{SONO1}/{name}"))
    assert "履歴がありません" in out or "戻せません" in out, out


# ---- 会社のフォルダを作る道具（同期されるフォルダ） ----

def synced_env(tmp_path: Path):
    """ホームの下の Google ドライブ（~/Library/CloudStorage/GoogleDrive-…）に、会社のフォルダにするフォルダを置く。"""
    env = ct.Env(tmp_path)
    folder = env.home / "Library" / "CloudStorage" / "GoogleDrive-yamada@example.com" / "マイドライブ" / "山田 製作所"
    folder.mkdir(parents=True)
    (folder / "決算書.pdf").write_bytes(b"%PDF-1.7 before")
    return env, folder


def init_files(env, folder: Path) -> dict:
    code = ("from pathlib import Path\nfrom lib import company_init, sync_folder\n"
            "folder = Path(sys.argv[1])\n"
            "synced = sync_folder.synced(folder)\n"
            "result = company_init.init(folder, form='files')\n"
            "print(json.dumps({'同期': synced.service if synced else None, '出力': company_init.report(result)},"
            " ensure_ascii=False))")
    return ct.py_json(code, str(folder), env={"HOME": str(env.home), "PATH": "/usr/bin:/bin"})


def test_files_form_can_be_made_in_a_synced_folder(tmp_path) -> None:
    """同期されるフォルダでは、Git の形では断る（版の持ち方を選んでもらう）。経営者が版のファイルの形を選べば、
    .git を作らずに用意する。前からあったファイルは「社長」、用意したものは「ツール」の版にする。もう一度動かしても
    （道具の既定のままでも）、版のファイルの形のまま補う。"""
    env, folder = synced_env(tmp_path)
    r = env.run(folder)
    assert r.returncode == 2 and "Google ドライブで同期されています" in r.stdout.decode("utf-8")
    assert sorted(p.name for p in folder.iterdir()) == ["決算書.pdf"]

    made = init_files(env, folder)
    assert made["同期"] == "Google ドライブ"
    assert "版は1つずつファイルで残す形" in made["出力"] and "2台のパソコンから同時に使わないで" in made["出力"]
    assert not (folder / ".git").exists() and (folder / vt.STORE).is_dir() and (folder / ".hojokin").is_dir()
    records = {r["書類"]: (r["だれ"], r["理由"]) for r in
               ct.py_json("from pathlib import Path\n"
                          "print(json.dumps([r.as_dict() for r in history.log(Path(sys.argv[1]))], ensure_ascii=False))",
                          str(folder))}
    assert records == {"決算書.pdf": ("社長", "会社のフォルダにする前からあったファイル"),
                       ".gitignore": ("ツール", "会社のフォルダを用意した"),
                       ".claude/settings.json": ("ツール", "会社のフォルダを用意した"),
                       ".hojokin/設定.json": ("ツール", "会社のフォルダを用意した")}
    # 道具（init_company.py）をもう一度動かしても、Git の形にはしない
    out = ct.ok(env.run(folder))
    assert "すでに会社のフォルダです" in out
    assert not (folder / ".git").exists()


def test_git_form_company_is_not_switched_to_files(tmp_path) -> None:
    """すでに Git の形の会社のフォルダは、版のファイルの形に変えない（何も書かずに断る）。"""
    company = vt.Company(tmp_path)
    before = hr.snapshot(company.folder)
    code = ("from pathlib import Path\nfrom lib import company_init\n"
            "try:\n    company_init.init(Path(sys.argv[1]), form='files')\n    print(json.dumps('作った'))\n"
            "except company_init.Refused as e:\n    print(json.dumps(e.reasons, ensure_ascii=False))")
    reasons = ct.py_json(code, str(company.folder))
    assert any("版をファイルで残す形には変えません" in r for r in reasons), reasons
    assert hr.snapshot(company.folder) == before


# ---- iCloud の「デスクトップと書類」の見分け（読むだけ） ----

def test_icloud_desktop_is_judged_by_the_finder_setting_only(tmp_path, monkeypatch) -> None:
    """iCloud の「デスクトップと書類」は、Finder の設定が 1 のときだけ同期されるとみなす。CloudDocs の中の Desktop・
    Documents のフォルダは、同期を切った後も残る（この Mac で確かめた）ので、それだけでは同期されるとみなさない。
    ~/Desktop が iCloud Drive の中への別名なら、別名をたどった場所で iCloud Drive と見分ける。"""
    from lib import sync_folder  # 標準のライブラリだけのモジュール（dulwich を読み込まない）

    home = tmp_path / "home"
    cloud = home / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
    for name in ("Desktop", "Documents"):
        (cloud / name).mkdir(parents=True)
        (home / name / "会社").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(sync_folder, "home_dirs", lambda: [home.resolve()])
    assert sync_folder.synced(home / "Desktop" / "会社", icloud_desktop=set) is None
    assert sync_folder.synced(home / "Documents" / "会社", icloud_desktop=set) is None
    found = sync_folder.synced(home / "Desktop" / "会社", icloud_desktop=lambda: {"Desktop"})
    assert found is not None and found.service == "iCloud Drive（デスクトップと書類）"
    # ~/Desktop が iCloud Drive の中への別名になっている形
    linked = tmp_path / "home2"
    (linked / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "Desktop" / "会社").mkdir(parents=True)
    (linked / "Desktop").symlink_to(linked / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "Desktop")
    monkeypatch.setattr(sync_folder, "home_dirs", lambda: [linked.resolve()])
    found = sync_folder.synced(linked / "Desktop" / "会社", icloud_desktop=set)
    assert found is not None and found.service == "iCloud Drive"
