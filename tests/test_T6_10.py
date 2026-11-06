"""T6-10 claude.ai の今の状態（Artifact）（SPEC F6・共通の要件の②、DESIGN 4.6・5章。テストの番号と合格ラインは文案。
day5 のセッションが SPEC に入れる）。

合格ライン（文案）：金額・相手先・会社名を含む2案件の状態から、claude.ai に上げる画面を作る → 画面に会社名・金額・相手先と
依頼先・書類のファイルの場所・メモが入らず、案件名・工程表・期限と作業・依頼の状態・様式の項目ごとの進み具合が入る。
入れてはいけない言葉が入るときは作らない。hook は、同意の記録がない、写しでないファイル、添えるファイルなどの値がある、
写しが書き換わっている、題・説明が決まった値でない、残した URL と違う、のどれかで publish を拒み、そろえば通す。
会社のフォルダでは、ArtifactData の書き込みと ArtifactComments の返信を拒み、読むだけの使い方は通す。

材料は tests/status_tool.py（省力化 第9回は事業の完了の後、持続化 第20回は見積書等の提出の段階。今日 2028-02-10）。
計画書の Word は公式の様式から作るので、downloads/ がなければ、2案件の材料を使うテストは飛ばす。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import status_tool as st
from lib import status_artifact as sa
from lib import status_view

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

import pre_tool_use  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "skills" / "junbi" / "scripts" / "artifact.py"
COMPANY = "やまぶき 惣菜"
COMPANY_FACT = "株式会社やまぶき惣菜"
URL = "https://claude.ai/artifact/AbCdEf123456"


# ---- 画面の中身（2案件の材料） ----


def two_cases(tmp_path: Path) -> Path:
    folder = tmp_path / COMPANY
    st.build(folder)
    # 依頼先に相手先の名前を入れ、会社の記録に会社名を足す（画面に出てはいけないもの）
    ledger_path = folder / "記録" / "期限の台帳.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["作業"][0]["依頼先"] = st.VENDOR
    st.write_json(ledger_path, ledger)
    facts_path = folder / "記録" / "会社の記録.json"
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    facts["項目"].append({"id": "事実-0002", "種類": "事実", "名前": "会社名", "値": COMPANY_FACT})
    st.write_json(facts_path, facts)
    assert status_view.refresh_page(folder) is None
    return folder


@pytest.mark.slow
def test_page_leaves_out_company_amounts_and_partners(tmp_path: Path) -> None:
    folder = two_cases(tmp_path)
    full = (folder / status_view.PAGE_NAME).read_text(encoding="utf-8")
    # パソコンの画面（正本）には、会社名・金額・相手先が入っている（材料が確かめる値を持つことの確かめ）
    assert COMPANY in full and "円" in full and st.VENDOR in full and st.OLD_QUOTE in full

    path = sa.make(folder)
    assert path == folder / sa.PAGE_REL
    page = path.read_text(encoding="utf-8")
    text = sa.leaks(page, [])  # 「円」だけを見る
    assert text == []
    for word in (COMPANY, COMPANY.replace(" ", ""), COMPANY_FACT, st.VENDOR, "つばさ台", "原本/", "添付する書類/",
                 ".pdf", ".docx", "要領", "社長の答え", "頼んだ日"):
        assert word not in page, word

    # 入るもの：案件名、工程表、期限と作業、依頼の状態、様式の項目ごとの進み具合、長い期限
    tables = st.html_tables(page)
    assert st.CASE_A in page and st.CASE_B in page
    gantt = tables.tables["工程表"]
    assert {r[0] for r in gantt[1:]} == {st.CASE_A, st.CASE_B}
    assert any("g-today" in c for row in tables.classes["工程表"] for c in row)  # 今日の線
    assert any("◆" in cell for row in gantt for cell in row)  # 期限の印
    requests = tables.tables["外部への依頼と待ち"]
    assert requests[0] == ["書類", "案件", "依頼の状態", "だれがするか", "始める日", "締切"]
    row = next(r for r in requests[1:] if r[1] == st.CASE_B)
    assert row[0] == "見積書等" and row[2] == "依頼した" and row[3] == "頼む：社長／書く：外部"
    tasks = tables.tables["期限と作業"]
    assert tasks[0] == ["締切", "あと何日", "案件", "すること", "見込みか確定か", "だれがするか", "依頼の状態"]
    assert any(r[3] == "見積書等を頼む" for r in tasks[1:])
    assert {r[4] for r in tasks[1:] if len(r) > 4} <= {"見込み", "確定", "—", "見込みか確定か"}
    forms = tables.tables["申請書（様式の項目ごとの進み具合）"]
    assert forms[0] == ["案件", "様式", "項目", "進み具合", "文字数", "上限"]
    assert {r[3] for r in forms[1:]} >= {"下書き", "仮の印あり", "まだ"}
    assert f"<h3>{st.CASE_A}：" in page and "仮の印あり 1" in page  # 案件ごとの件数（表は畳む）
    assert len(tables.tables["長い期限（効果報告など、年ごと）"]) > 1

    # 題は決まった文（会社名を入れない）。ハッシュを控える
    assert f"<title>{sa.TITLE}</title>" in page
    assert sa.stamp(folder) == sa.file_hash(path)


@pytest.mark.slow
def test_page_is_not_made_when_a_forbidden_word_is_in(tmp_path: Path) -> None:
    folder = two_cases(tmp_path)
    # 案件名に会社の記録の会社名が入る（入れてはいけない言葉が画面に出る形）
    facts_path = folder / "記録" / "会社の記録.json"
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    facts["項目"][-1]["値"] = "省力化"
    st.write_json(facts_path, facts)
    with pytest.raises(sa.ArtifactPageError, match="会社の記録の会社名"):
        sa.make(folder)
    assert not (folder / sa.PAGE_REL).exists() and not (folder / sa.STAMP_REL).exists()


def test_leaks_finds_amounts_and_words() -> None:
    page = "<p>見積書 1,200,000円</p><td>つばさ台</td>"
    assert sa.leaks(page, [("つばさ台", "書類の相手先"), ("やまぶき", "会社のフォルダの名前")]) == ["金額（「円」）", "書類の相手先"]
    assert sa.leaks("<p title=\"円\">期限</p>", []) == []  # タグの中は見ない（文字だけを見る）


# ---- hook（案件のない会社のフォルダで） ----


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    path = tmp_path / "テスト商店"  # 画面の案内の文（「会社のフォルダにある…」）に当たらない名前
    (path / ".hojokin").mkdir(parents=True)
    return path


def decide(tool: str, folder: Path, **tool_input):
    return pre_tool_use.handle({"tool_name": tool, "tool_input": tool_input, "cwd": str(folder)}, folder)


def reason(output) -> str:
    assert output and output["hookSpecificOutput"]["permissionDecision"] == "deny", output
    return output["hookSpecificOutput"]["permissionDecisionReason"]


def publish(folder: Path, **extra):
    values = {"file_path": str(folder / sa.PAGE_REL), "description": sa.DESCRIPTION, "icon": sa.ICON}
    values.update(extra)
    return decide("Artifact", folder, **{k: v for k, v in values.items() if v is not None})


def test_publish_needs_agreement_and_the_made_page(folder: Path) -> None:
    assert "同意" in reason(publish(folder))  # まだ作っていない・同意がない
    sa.make(folder)
    assert "同意" in reason(publish(folder))
    sa.agree(folder)
    (folder / sa.STAMP_REL).unlink()
    assert "作ったときと違います" in reason(publish(folder))  # 控えがない
    sa.make(folder)
    assert publish(folder) is None  # そろえば通す
    assert publish(folder, description=None, icon=None) is None
    assert decide("Artifact", folder, file_path=sa.PAGE_REL, action="publish") is None  # 相対の場所も同じ


def test_publish_of_other_files_is_denied(folder: Path) -> None:
    sa.make(folder)
    sa.agree(folder)
    (folder / "財務モデル.html").write_text("<p>売上 1,000万円</p>", encoding="utf-8")
    assert "写しではありません" in reason(decide("Artifact", folder, file_path=str(folder / "財務モデル.html")))
    assert "写しではありません" in reason(decide("Artifact", folder, file_path=str(folder / "今の状態.html")))
    assert "file_path" in reason(decide("Artifact", folder, description=sa.DESCRIPTION))
    for key, value in (("files", {"a.xlsx": "財務モデル.xlsx"}), ("root", "."), ("asset", True),
                       ("file_paths", ["財務モデル.xlsx"]), ("capabilities", {"db": {}}), ("type_url", "x"),
                       ("from_url", URL), ("label", "x")):
        assert key in reason(publish(folder, **{key: value})), key


def test_publish_of_a_changed_page_is_denied(folder: Path) -> None:
    sa.make(folder)
    sa.agree(folder)
    page = folder / sa.PAGE_REL
    page.write_text(page.read_text(encoding="utf-8") + "<p>売上 1,000万円</p>", encoding="utf-8")
    assert "作ったときと違います" in reason(publish(folder))
    sa.make(folder)  # 作り直せば通す
    assert publish(folder) is None


def test_title_and_description_are_fixed(folder: Path) -> None:
    sa.make(folder)
    sa.agree(folder)
    assert "description" in reason(publish(folder, description="やまぶき惣菜の今の状態"))
    assert "title" in reason(publish(folder, title="やまぶき惣菜"))
    assert "icon" in reason(publish(folder, icon="building"))
    assert publish(folder, title=sa.TITLE) is None


def test_url_must_be_the_saved_one(folder: Path) -> None:
    sa.make(folder)
    sa.agree(folder)
    assert "まだありません" in reason(publish(folder, url=URL))
    sa.set_url(folder, URL)
    assert publish(folder, url=URL, description=None, icon=None) is None
    assert "違います" in reason(publish(folder, url="https://claude.ai/artifact/Other1234567"))
    assert sa.call_values(folder) == {"file_path": str(folder / sa.PAGE_REL), "url": URL}


def test_stop_denies_the_next_publish(folder: Path) -> None:
    sa.make(folder)
    sa.agree(folder)
    sa.set_url(folder, URL)
    assert sa.stop(folder) == URL
    assert "同意" in reason(publish(folder, url=URL))
    settings = json.loads((folder / ".hojokin" / "設定.json").read_text(encoding="utf-8"))
    assert settings[sa.SETTINGS_KEY][sa.URL_KEY] == URL and settings[sa.SETTINGS_KEY][sa.STOPPED]
    sa.agree(folder)  # 同意し直せば通す
    assert publish(folder, url=URL) is None


def test_url_needs_agreement_and_shape(folder: Path) -> None:
    with pytest.raises(sa.ArtifactPageError, match="同意"):
        sa.set_url(folder, URL)
    sa.agree(folder)
    with pytest.raises(sa.ArtifactPageError, match="URL"):
        sa.set_url(folder, "https://example.com/artifact/AbCdEf123456")


@pytest.mark.parametrize("action", sorted(["read", "list", "open", "quickstart", "pin", "unpin", "delete"]))
def test_other_artifact_actions_pass(folder: Path, action: str) -> None:
    assert decide("Artifact", folder, action=action, url=URL) is None


def test_unknown_artifact_action_is_denied(folder: Path) -> None:
    assert "action" in reason(decide("Artifact", folder, action="share", url=URL))


def test_data_writes_and_comment_replies_are_denied(folder: Path) -> None:
    for action in ("set", "update", "delete", "str_replace", "batch"):
        assert "書き込みません" in reason(decide("ArtifactData", folder, action=action, url=URL)), action
    for action in ("get", "list", "query", "profiles"):
        assert decide("ArtifactData", folder, action=action, url=URL) is None, action
    assert "返信しません" in reason(decide("ArtifactComments", folder, action="reply", url=URL, thread_id="t", text="x"))
    for action in ("read", "resolve", "watch"):
        assert decide("ArtifactComments", folder, action=action, url=URL) is None, action


# ---- 道具（/usr/bin/python3 で動かす） ----


def run(folder: Path, *args: str) -> subprocess.CompletedProcess:
    python = "/usr/bin/python3" if Path("/usr/bin/python3").exists() else sys.executable
    return subprocess.run([python, "-B", str(SCRIPT), "--folder", str(folder), *args],
                          capture_output=True, text=True, timeout=60)


def test_script_makes_agrees_saves_and_stops(folder: Path) -> None:
    r = run(folder, "--make")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "## 上げるもの" in r.stdout and "## 上げないもの" in r.stdout and "## だれが見られるか" in r.stdout
    assert "同意：まだありません" in r.stdout and f"description: {sa.DESCRIPTION}" in r.stdout
    assert run(folder, "--agree").returncode == 0
    r = run(folder, "--url", URL)
    assert r.returncode == 0, r.stdout
    r = run(folder, "--make")
    assert "同意：あり" in r.stdout and f"url: {URL}" in r.stdout and "description" not in r.stdout.split("## Artifact")[1]
    r = run(folder, "--stop")
    assert r.returncode == 0 and URL in r.stdout and "/artifacts" in r.stdout
    assert run(folder, "--url", "x").returncode == 2  # 同意がない・形が違う：何も書かない


def test_script_refuses_outside_company_folder(tmp_path: Path) -> None:
    r = run(tmp_path, "--make")
    assert r.returncode == 2 and "会社のフォルダ" in r.stdout
    assert not (tmp_path / ".hojokin").exists()
