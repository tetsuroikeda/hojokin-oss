"""開いたときに、前回から増えた・変わった書類だけを見つける（SPEC F5、DESIGN 4.7 の2。TASKS B9。T5-3 の自動の部分）。

testdata/書類の変化/開いたときの確認/ の前6件で開き（前回開いたときに見つけた形）、後の形（1つ足し・1つ書き換え・
1つ動かし・1つ名前を変え）にしてから開き直す。開いたときの hook が渡す文と、見つける道具の「前回から」で、
足したもの（見積書 ほしみ機工）と書き換えたもの（労働者名簿）だけが出ることを見る（testdata/書類の変化/正解.json）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import company_tool as ct
import hook_runner as hr
import pytest
import version_tool as vt

SCRIPT = Path("skills") / "shorui" / "scripts" / "seiri.py"
BASE = hr.REPO_ROOT / "testdata" / "書類の変化" / "開いたときの確認"
ANSWER = json.loads((hr.REPO_ROOT / "testdata" / "書類の変化" / "正解.json").read_text(encoding="utf-8"))["T5-3 開いたときの確認"]
HEAD = "前回から増えた・変わった書類"


def run_tool(company: vt.Company, command: str, *args: str) -> subprocess.CompletedProcess:
    env = {"PATH": company.env.path, "HOME": str(company.env.home), "TMPDIR": str(company.env.tmp)}
    return subprocess.run(
        [hr.real_python(), "-B", str(company.env.plugin / SCRIPT), command, "--folder", str(company.folder), *args],
        env=env, cwd=company.env.cwd, capture_output=True, timeout=120,
    )


def context(output) -> str:
    return (output or {}).get("hookSpecificOutput", {}).get("additionalContext", "")


def to_after(company: vt.Company) -> None:
    """前の形を、後の形にする（社長が閉じている間にしたこと）。"""
    for op in ANSWER["操作"]:
        if op["操作"] in ("動かし", "名前を変え"):
            src, dest = company.folder / op["前"], company.folder / op["後"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
    for op in ANSWER["操作"]:
        if op["操作"] == "足し":
            company.write(op["後"], (BASE / "後" / op["後"]).read_bytes())
        if op["操作"] == "書き換え":
            company.write(op["場所"], (BASE / "後" / op["場所"]).read_bytes())


@pytest.fixture
def company(tmp_path) -> vt.Company:
    c = vt.Company(tmp_path, name="やまぶき惣菜")
    for rel in ANSWER["前の書類"]:
        c.write(rel, (BASE / "前" / rel).read_bytes())
    return c


def test_only_added_and_rewritten_documents_are_reported(company) -> None:
    first = context(company.start())
    # 初めて開いたときは、前の6件が「増えた」として出る（控えがないため）
    for rel in ANSWER["前の書類"]:
        assert f"- {rel}（増えた）" in first, rel
    company.say("今日は別のことを先にお願いします")  # 整理はしないまま閉じる
    assert company.stop() is None

    to_after(company)
    text = context(company.start())
    assert HEAD in text
    reported = [line for line in text.splitlines() if line.startswith("- ") and "（" in line and line.endswith(("）", "同じ中身"))]
    reported = [line for line in reported if "増えた）" in line or "変わった）" in line]
    assert sorted(reported) == sorted(["- 入れ口/見積書_ほしみ機工.pdf（増えた）", "- 入れ口/労働者名簿.xlsx（変わった）"])
    for rel in ANSWER["確かめないもの"]:
        assert rel not in text, rel
    assert "前からある整理していない書類が5件" in text

    # 見つける道具でも、同じ2件だけが「増えた」「変わった」、ほかは「前からある」
    found = json.loads(ct.ok(run_tool(company, "scan")))
    since = {d["場所"]: d["前回から"] for d in found["新しい書類"]}
    assert since == {**{rel: "前からある" for rel in ANSWER["確かめないもの"]},
                     "入れ口/見積書_ほしみ機工.pdf": "増えた", "入れ口/労働者名簿.xlsx": "変わった"}
    assert sorted(ANSWER["確かめるもの"]) == sorted(r for r, s in since.items() if s != "前からある")

    # 会話を縮めた後は、まだ整理していない変化を続けて渡す
    assert "入れ口/見積書_ほしみ機工.pdf（増えた）" in context(company.start("compact"))

    # 会話の途中で入れた書類は「開いた後に入れた」
    company.write("入れ口/メモ.txt", "金曜まで")
    found = json.loads(ct.ok(run_tool(company, "scan")))
    assert {d["場所"]: d["前回から"] for d in found["新しい書類"]}["入れ口/メモ.txt"] == "開いた後に入れた"

    # 次に開いたときは、前の変化は「前からある」になり、新しい変化だけが出る
    text = context(company.start())
    assert "入れ口/メモ.txt（増えた）" in text
    assert "見積書_ほしみ機工" not in text


def test_kept_documents_are_not_reported_until_their_content_changes(company) -> None:
    company.start()
    ct.ok(run_tool(company, "keep", "--path", "社長の書類/株主名簿.docx", "--reason", "社長がそのままでいいと答えた"))
    company.write("社長の書類/株主名簿.docx", b"changed")
    text = context(company.start())
    assert "- 社長の書類/株主名簿.docx（変わった）" in text


def test_broken_control_file_does_not_stop_opening(company) -> None:
    company.start()
    company.write(".hojokin/一時/見つけた書類.json", "{壊れた")
    text = context(company.start())
    # 控えが読めなければ、初めて開いたときと同じく、整理していない書類を「増えた」として渡す
    assert "- 入れ口/労働者名簿.xlsx（増えた）" in text
