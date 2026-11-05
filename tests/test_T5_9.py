"""T5-9 フォルダの外を読まない（SPEC F5「ファイルの道具は、会社のフォルダの外を読まない（社長が伝えた場所を除く）。
外のものは、社長が場所を伝えたら取り込む」、DESIGN 4.7。TASKS B10）。

合格ライン：会社のフォルダの設定を見る。社長が伝えた場所と伝えていない場所を、取り込みに渡す。
ファイルの道具が会社のフォルダの外を読まない設定になっている。伝えていない場所からは何も取り込まない。
伝えた場所のものだけが取り込まれる。

- 会社のフォルダは道具で用意する（.claude/settings.json は lib/company_init.py が作る）。
- 社長の発言は、社長が送ったときの hook（hooks.json のコマンド）に渡す。hook が発言にある外の場所を控え、
  取り込みの道具（skills/shorui/scripts/torikomi.py）は控えた場所だけを、番号で受け付ける。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import company_tool as ct
import hook_runner as hr
import pytest
import version_tool as vt

SCRIPT = Path("skills") / "shorui" / "scripts" / "torikomi.py"
DOCS = hr.REPO_ROOT / "testdata" / "デモの会社" / "書類"
TODAY = "2026-11-05"


def run(company: vt.Company, command: str, *args: str) -> subprocess.CompletedProcess:
    env = {"PATH": company.env.path, "HOME": str(company.env.home), "TMPDIR": str(company.env.tmp)}
    return subprocess.run(
        [hr.real_python(), "-B", str(company.env.plugin / SCRIPT), command, "--folder", str(company.folder), *args],
        env=env, cwd=company.env.cwd, capture_output=True, timeout=120,
    )


def ok_json(r: subprocess.CompletedProcess):
    return json.loads(ct.ok(r))


@pytest.fixture
def company(tmp_path) -> vt.Company:
    c = vt.Company(tmp_path, name="やまぶき惣菜")
    settings = c.folder / ".hojokin" / "設定.json"
    data = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
    data["今日の日付"] = TODAY
    settings.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return c


@pytest.fixture
def outside(company, tmp_path) -> dict:
    """会社のフォルダの外の書類。told は社長が伝える場所、secret は伝えない場所（同じ HOME の下）。"""
    told = tmp_path / "社長の書類" / "見積書 つばさ台.pdf"
    told.parent.mkdir()
    told.write_bytes((DOCS / "見積書_つばさ台フードシステム.pdf").read_bytes())
    secret = company.env.home / "Documents" / "個人の書類.pdf"
    secret.parent.mkdir()
    secret.write_bytes(b"%PDF-1.4 secret")
    desktop = company.env.home / "Desktop"
    desktop.mkdir()
    (desktop / "決算書18.pdf").write_bytes((DOCS / "決算書_第18期.pdf").read_bytes())
    (desktop / "役員名簿.docx").write_bytes((DOCS / "役員名簿.docx").read_bytes())
    (desktop / ".DS_Store").write_bytes(b"x")
    return {"told": told, "secret": secret, "desktop": desktop}


def imported(company: vt.Company) -> list:
    base = company.folder / "入れ口" / "取り込み"
    return sorted(p.relative_to(company.folder).as_posix() for p in base.rglob("*") if p.is_file()) if base.exists() else []


def test_settings_keep_file_tools_inside(company) -> None:
    data = json.loads((company.folder / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert data["permissions"]["blockReadsOutsideWorkingDirectories"] is True
    assert data["permissions"]["blockWritesOutsideWorkingDirectories"] is True


def test_only_the_told_place_is_imported(company, outside) -> None:
    told, secret = outside["told"], outside["secret"]
    before = {p: p.read_bytes() for p in (told, secret)}
    # 社長が場所を伝える（ファイルを画面に引いて入れた形。空白は「\ 」で逃がされる）
    company.say("この見積書を取り込んで " + str(told).replace(" ", "\\ "))
    listed = ok_json(run(company, "list"))["社長が伝えた場所"]
    assert [item["場所"] for item in listed] == [str(told.resolve())]

    out = ok_json(run(company, "import", "--number", "1"))["取り込んだもの"]
    assert [o["取り込んだ場所"] for o in out] == [f"入れ口/取り込み/{TODAY}/見積書 つばさ台.pdf"]
    assert (company.folder / out[0]["取り込んだ場所"]).read_bytes() == before[told]

    # 伝えていない場所は、番号がないので取り込めない（何も写さない）
    r = run(company, "import", "--number", "2")
    assert r.returncode == 2 and "番号" in r.stdout.decode("utf-8")
    assert imported(company) == [f"入れ口/取り込み/{TODAY}/見積書 つばさ台.pdf"]

    # 次の発言に場所がなければ、前の場所も受け付けない（直前の発言の場所だけ）
    company.say("ありがとう。次は書類の整理をお願いします")
    assert ok_json(run(company, "list"))["社長が伝えた場所"] == []
    r = run(company, "import", "--number", "1")
    assert r.returncode == 2 and "場所がありません" in r.stdout.decode("utf-8")

    # 元のファイルは変えない。伝えていない書類は1つも取り込まれていない
    assert {p: p.read_bytes() for p in (told, secret)} == before
    assert all("個人の書類" not in rel for rel in imported(company))


def test_desktop_word_and_folder_place(company, outside) -> None:
    company.say("デスクトップに置いた決算書を取り込んでください")
    listed = ok_json(run(company, "list"))["社長が伝えた場所"]
    assert listed == [{"番号": 1, "場所": str(outside["desktop"].resolve()), "種類": "フォルダ",
                       "中のファイル": ["役員名簿.docx", "決算書18.pdf"]}] or \
        sorted(listed[0]["中のファイル"]) == ["役員名簿.docx", "決算書18.pdf"]
    out = ok_json(run(company, "import", "--number", "1", "--name", "決算書18.pdf"))["取り込んだもの"]
    assert [o["取り込んだ場所"] for o in out] == [f"入れ口/取り込み/{TODAY}/決算書18.pdf"]
    # 名前で指さなければ、すぐ下の書類をすべて（隠しファイルは除く）。同じ中身のものは写し直さない
    out = ok_json(run(company, "import", "--number", "1"))["取り込んだもの"]
    assert sorted(o["取り込んだ場所"] for o in out) == sorted(
        [f"入れ口/取り込み/{TODAY}/決算書18.pdf", f"入れ口/取り込み/{TODAY}/役員名簿.docx"])
    assert imported(company) == sorted([f"入れ口/取り込み/{TODAY}/決算書18.pdf", f"入れ口/取り込み/{TODAY}/役員名簿.docx"])


def test_home_itself_and_inside_places_are_not_told(company, outside) -> None:
    company.say(f"{company.env.home} と / と {company.folder}/入れ口 を見て")
    assert ok_json(run(company, "list"))["社長が伝えた場所"] == []
