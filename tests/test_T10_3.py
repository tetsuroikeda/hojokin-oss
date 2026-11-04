"""T10-3 提出しない（SPEC F10・2.3、DESIGN 5章。TASKS M8）。

合格ライン（SPEC 6章 F10）：
  提出ボタンを押す、確認・誓約・同意のチェック欄とパスワード欄に入れるブラウザの道具の呼び出しを、画面入力の守りに
  渡すと、守りがすべて拒む。T10-2 の後の模擬画面の操作記録で、「提出」ボタンが押されておらず、確認・誓約・同意
  （宣誓を含む）のチェック欄とパスワード欄に入力がない。

確かめ方
- 守り：模擬画面（mock/ の12画面版）を内蔵ブラウザで読んだ記録（tests/browser_records/m8_*.txt。2026-11-04）を
  PostToolUse に渡して控えさせ、提出のクリック、確認・誓約・同意・宣誓のチェック欄（とそのラベル）へのクリックと入力、
  パスワード欄への入力を PreToolUse に渡す。担当者が /hojokin:nyuryoku を呼んだ後（許可がある）で流し、内蔵ブラウザと
  Claude in Chrome の両方、まとめて動かす道具（browser_batch）の中に入れた形も見る。制度データ（AI の下書き）が
  誤って「提出」を押してよいボタンにし、宣誓の欄をツールの欄にしていても拒む。同じ守りで、入力シートの値を入れる
  呼び出し（M8 で実際に流した記録）は通る（空振りでないことの確かめ）。
- 操作記録：M8 で、内蔵ブラウザで ❹ 加点項目に入れて一時保存まで進めたときの模擬画面の記録
  （tests/browser_records/m8_mock/。ログインは担当者の代わりにパスワードを空のまま行った）を読み、提出が押されて
  いない・担当者のチェック欄とパスワード欄に入力がないことと、入れた値が入力シートと合うことを確かめる。
  記録を調べる関数は、提出を押した・宣誓を入れた・パスワードを入れた記録では、それを見つける（模擬画面を手元で
  動かして作る）。
  T10-2（すべての画面と添付。B29）の後の記録も、この関数で照らす。
- hooks.json から run.sh を通して、/usr/bin/python3（3.9）でも同じ判定になる。
"""

from __future__ import annotations

import copy
import json

import hook_runner as hr
import nyuryoku_tool as nt
import pytest

from lib import browser_guard as bg

KINDS = [nt.BUILTIN, nt.CHROME]
# ❶ 宣誓・手引き（m8_shinsei1.txt）：チェック欄・囲むラベル・ラベルの中の文字の番号と、名前に含む語
SCREEN1_OATHS = [
    ("ref_30", "ref_29", "ref_31", "同意"),
    ("ref_33", "ref_32", "ref_34", "確認"),
    ("ref_36", "ref_35", "ref_37", "誓約"),
    ("ref_39", "ref_38", "ref_40", "同意"),
    ("ref_42", "ref_41", "ref_43", "宣誓"),
]
# ❸ 要件（m8_shinsei3.txt）：確認の欄（名前に「確認」と「宣誓」を含む）と、両立支援の宣誓
SCREEN3_OATHS = [
    ("ref_34", "ref_33", "ref_35"),
    ("ref_38", "ref_37", "ref_39"),
    ("ref_42", "ref_41", "ref_43"),
    ("ref_50", "ref_49", "ref_51"),
]


@pytest.fixture
def folder(tmp_path):
    folder = nt.make_company(tmp_path)
    nt.permit(folder)
    return folder


def oath_reason(output) -> str:
    text = nt.reason(output)
    assert any(f"「{w}」" in text for w in bg.PROHIBITED_FIELD_WORDS), text
    assert "担当者" in text
    return text


# ---- 提出ボタン ----

@pytest.mark.parametrize("prefix", KINDS)
def test_submit_button_on_confirm_screen_is_denied(folder, prefix) -> None:
    nt.read_screen(folder, "m8_shinsei12.txt", prefix)
    text = nt.reason(nt.pre(folder, prefix + "computer", nt.click("ref_80")))
    assert "ボタン「提出」は押せません" in text and "「提出」" in text
    # まとめて動かす道具の最後に置いても拒む
    batch = {"actions": [{"name": "computer", "input": nt.click("ref_80")}]}
    assert "「提出」" in nt.reason(nt.pre(folder, prefix + "browser_batch", batch))
    # 拒んだクリックの後も、控えは残る（拒まれた呼び出しで、画面は変わっていない）
    assert "「提出」" in nt.reason(nt.pre(folder, prefix + "computer", nt.click("ref_80")))


def test_submit_is_denied_even_if_scheme_data_allows_it(tmp_path) -> None:
    scheme = nt.seido()
    for screen in scheme["申請画面"]["画面"]:
        screen["押してよいボタン"] = list(screen["押してよいボタン"]) + ["提出", "送信", "確定", "完了", "申請する"]
    folder = nt.make_company(tmp_path, scheme=scheme)
    nt.permit(folder)
    for prefix in KINDS:
        nt.read_screen(folder, "m8_shinsei12.txt", prefix)
        assert "「提出」" in nt.reason(nt.pre(folder, prefix + "computer", nt.click("ref_80")))


def test_submit_on_one_page_version_is_denied(folder) -> None:
    """D11a の1画面版（tests/browser_records/mock_shinsei.txt）の「提出」も拒む。"""
    for prefix in KINDS:
        nt.post(folder, prefix + "read_page", {}, [{"type": "text", "text": nt.record_text("mock_shinsei.txt")}])
        assert "「提出」" in nt.reason(nt.pre(folder, prefix + "computer", {"action": "left_click", "ref": "ref_954"}))


@pytest.mark.parametrize("word", bg.PROHIBITED_BUTTON_WORDS)
def test_buttons_named_with_the_fixed_words_are_denied(folder, word) -> None:
    page = (f'form [ref_1]\n button "一時保存" [ref_2] type="submit"\n button "{word}" [ref_3] type="submit"\n'
            f' button "内容を{word}する" [ref_4] type="submit"\n\nTab Context:\n- Executed on tabId: tab-1\n')
    nt.post(folder, nt.BUILTIN + "read_page", {"tabId": "tab-1"}, page)
    for ref in ("ref_3", "ref_4"):
        assert f"「{word}」" in nt.reason(nt.pre(folder, nt.BUILTIN + "computer", nt.click(ref)))


# ---- 確認・誓約・同意・宣誓のチェック欄 ----

@pytest.mark.parametrize("prefix", KINDS)
def test_oath_checkboxes_on_screen1_are_denied(folder, prefix) -> None:
    nt.read_screen(folder, "m8_shinsei1.txt", prefix)
    for box, label, text_ref, word in SCREEN1_OATHS:
        for ref in (box, label, text_ref):
            assert f"「{word}」" in oath_reason(nt.pre(folder, prefix + "form_input", nt.fill(ref, True)))
            assert f"「{word}」" in oath_reason(nt.pre(folder, prefix + "computer", nt.click(ref)))


@pytest.mark.parametrize("prefix", KINDS)
def test_confirmation_checkboxes_on_screen3_are_denied(folder, prefix) -> None:
    nt.read_screen(folder, "m8_shinsei3.txt", prefix)
    for refs in SCREEN3_OATHS:
        for ref in refs:
            oath_reason(nt.pre(folder, prefix + "form_input", nt.fill(ref, True)))
            oath_reason(nt.pre(folder, prefix + "computer", nt.click(ref)))
    # 同じ画面の、ツールが入れる欄（小規模・ラジオボタン）は通る
    assert nt.pre(folder, prefix + "form_input", nt.fill("ref_27", True)) is None
    assert nt.pre(folder, prefix + "form_input", nt.fill("ref_59", True)) is None


def test_oath_fields_are_denied_even_if_scheme_data_marks_them_for_the_tool(tmp_path) -> None:
    scheme = nt.seido()
    for screen in scheme["申請画面"]["画面"]:
        for field in screen["欄"]:
            field["担当者が入れる"] = False
    folder = nt.make_company(tmp_path, scheme=scheme)
    nt.permit(folder)
    nt.read_screen(folder, "m8_shinsei1.txt")
    for box, _label, _text, _word in SCREEN1_OATHS:
        oath_reason(nt.pre(folder, nt.BUILTIN + "form_input", nt.fill(box, True)))
    nt.read_screen(folder, "m8_shinsei3.txt")
    for box, _label, _text in SCREEN3_OATHS:
        oath_reason(nt.pre(folder, nt.BUILTIN + "form_input", nt.fill(box, True)))


@pytest.mark.parametrize("prefix", KINDS)
def test_oath_checkbox_inside_a_batch_denies_the_whole_batch(folder, prefix) -> None:
    nt.read_screen(folder, "m8_shinsei3.txt", prefix)
    batch = {"actions": [
        {"name": "form_input", "input": nt.fill("ref_27", True)},
        {"name": "form_input", "input": nt.fill("ref_34", True)},
    ]}
    assert "「確認」" in oath_reason(nt.pre(folder, prefix + "browser_batch", batch))


# ---- パスワード欄 ----

@pytest.mark.parametrize("prefix", KINDS)
def test_password_field_is_denied(folder, prefix) -> None:
    nt.post(folder, prefix + "read_page", {}, [{"type": "text", "text": nt.record_text("mock_login.txt")}])
    for ref in ("ref_12", "ref_10", "ref_11"):  # パスワードの欄、囲むラベル、ラベルの中の文字
        text = nt.reason(nt.pre(folder, prefix + "form_input", {"ref": ref, "value": "pw-test-1"}))
        assert "パスワードの欄には入れません" in text and "担当者" in text
    batch = {"actions": [{"name": "form_input", "input": {"ref": "ref_9", "value": "tanto@example.test"}},
                         {"name": "form_input", "input": {"ref": "ref_12", "value": "pw-test-1"}}]}
    assert "パスワード" in nt.reason(nt.pre(folder, prefix + "browser_batch", batch))
    # ログインのボタンは「押してよいボタン」にないので、担当者が押す
    assert "ログイン" in nt.reason(nt.pre(folder, prefix + "computer", {"action": "left_click", "ref": "ref_13"}))


# ---- 空振りでないこと：入力シートの値を入れる呼び出しは通る ----

@pytest.mark.parametrize("prefix", KINDS)
def test_recorded_input_flow_passes_the_same_guard(folder, prefix) -> None:
    results = nt.replay(folder, nt.calls(prefix))
    assert [(row["行"], decision) for row, decision in results] == [(row["行"], None) for row, _ in results]
    # 一時保存のクリックの後は控えを捨てているので、読み直す前の番号では押せない
    nt.read_screen(folder, "m8_shinsei4_filled.txt", prefix)
    assert nt.pre(folder, prefix + "computer", nt.click("ref_21")) is None
    nt.post(folder, prefix + "computer", nt.click("ref_21"), "ok")
    assert "読み直" in nt.reason(nt.pre(folder, prefix + "computer", nt.click("ref_21")))


# ---- 模擬画面の操作記録 ----

def test_mock_record_after_input_has_no_submit_oath_or_password() -> None:
    """M8 で内蔵ブラウザから ❹ に入れ、一時保存まで進めたときの模擬画面の記録（tests/browser_records/m8_mock/）。"""
    log, state = nt.read_mock_record(nt.MOCK_RECORD)
    assert nt.t10_3_violations(log, state) == []
    # 記録が空ではない：ログイン、❹ の入力（チェック欄3つ・文字・選択欄4つ）、一時保存のボタンが残っている
    events = [e["event"] for e in log]
    assert events.count("login") == 1 and events.count("button") == 1
    (login,) = [e for e in log if e["event"] == "login"]
    assert login["password_entered"] is False
    (save,) = [e for e in log if e["event"] == "button"]
    assert save["page"] == "shinsei/4" and save["button_label"] == "一時保存" and save["saved"] is True
    assert save["submit_pressed"] is False
    changed = {e["field"] for e in log if e["event"] == "change"}
    assert changed == {"kasan_bcp", "bcp_number", "bcp_start_year", "bcp_start_month", "bcp_end_year",
                       "bcp_end_month", "kasan_inhouse_wage", "kasan_navi"}
    # 担当者のチェック欄（確認・誓約・同意・宣誓）は、どれも入っていない
    oath = nt.oath_field_ids(state)
    assert oath >= {"oath_1", "oath_2", "oath_3", "oath_4", "oath_5", "not_same_corp", "not_large", "not_adult",
                    "ryoritsu_oath"}
    assert all(state["fields"][f]["value"] is False for f in oath)
    assert state["submit_pressed"] is False and state["submit_times"] == []


def test_mock_record_matches_input_sheet(tmp_path) -> None:
    """入れた後に模擬画面が記録した値は、入力シートの ❹ の欄と合う（チェック欄を含む）。"""
    folder = nt.make_company(tmp_path)
    _log, state = nt.read_mock_record(nt.MOCK_RECORD)
    rows = nt.sheet_rows(folder, "加点項目")
    assert len(rows) == 15
    assert nt.compare_with_sheet(state, rows, "❹ 加点項目") == []
    # 照らす関数は、違う値を見つける
    wrong = copy.deepcopy(state)
    wrong["fields"]["kasan_navi"]["value"] = False
    wrong["fields"]["bcp_end_year"]["value"] = "2029"
    found = nt.compare_with_sheet(wrong, rows, "❹ 加点項目")
    assert len(found) == 2 and any("省力化ナビ加点" in p for p in found) and any("実施期間終期（年）" in p for p in found)


def test_record_checker_finds_submit_oath_and_password(tmp_path) -> None:
    """記録を調べる関数は、提出を押した・宣誓を入れた・パスワードを入れた記録では、それを見つける。"""
    def make(name, steps):
        record_dir = tmp_path / name
        with nt.running_mock(record_dir) as base:
            steps(base)
        return nt.read_mock_record(record_dir)

    def clean(base):
        cookie = nt.mock_login(base)
        status, _headers, _ = nt.mock_post(base, 4, cookie, {"button": "save", "kasan_navi": "on",
                                                           "bcp_number": "2512345678"})
        assert status == 303

    def with_password(base):
        nt.mock_login(base, password="pw-test-1")

    def with_oath(base):
        cookie = nt.mock_login(base)
        nt.mock_post(base, 1, cookie, {"button": "next", "oath_1": "on"})

    def with_confirm(base):
        cookie = nt.mock_login(base)
        nt.mock_post(base, 3, cookie, {"button": "save", "not_same_corp": "on"})

    def with_submit(base):
        cookie = nt.mock_login(base)
        nt.mock_post(base, 12, cookie, {"button": "submit"})

    assert nt.t10_3_violations(*make("きれい", clean)) == []
    found = nt.t10_3_violations(*make("パスワード", with_password))
    assert found and all("パスワード" in p for p in found)
    found = nt.t10_3_violations(*make("宣誓", with_oath))
    assert found and any("oath_1" in p for p in found)
    found = nt.t10_3_violations(*make("確認", with_confirm))
    assert found and any("not_same_corp" in p for p in found)
    found = nt.t10_3_violations(*make("提出", with_submit))
    assert found and any("提出" in p for p in found)


def test_record_checker_reads_client_side_changes(tmp_path) -> None:
    """一時保存しないで宣誓のチェック欄を入れただけの操作（ページの中のスクリプトが送る change）も見つける。"""
    record_dir = tmp_path / "変化"
    with nt.running_mock(record_dir) as base:
        nt.http(base + "/log", json.dumps({"event": "change", "name": "oath_5", "type": "checkbox", "value": "on",
                                          "checked": True, "page": "/shinsei/1"}).encode())
        # パスワード欄は、ページの中のスクリプトが「入ったか」だけを送る（mock/server.py）
        nt.http(base + "/log", json.dumps({"event": "change", "name": "password", "type": "password",
                                          "entered": True, "page": "/login"}).encode())
    found = nt.t10_3_violations(*nt.read_mock_record(record_dir))
    assert any("oath_5" in p for p in found)
    assert any("パスワード" in p for p in found)


# ---- hooks.json から run.sh を通す（/usr/bin/python3） ----

@pytest.mark.slow  # run.sh を10回ほど動かすので、数秒かかる（開発用の Stop hook では流さない）
def test_through_run_sh(folder, tmp_path) -> None:
    plugin = hr.copy_plugin(tmp_path / "plugin")
    home = tmp_path / "home"
    data = tmp_path / "plugin-data"
    home.mkdir()
    data.mkdir()
    path = hr.make_bin(tmp_path / "bin", "本物", tmp_path / "python-ran")

    def run(event: str, payload: dict):
        outputs = []
        commands = hr.hook_commands(event, payload.get("tool_name", ""))
        assert commands, (event, payload.get("tool_name"))
        for command in commands:
            r = hr.run(command, {"session_id": nt.SESSION, "cwd": str(folder), "hook_event_name": event, **payload},
                       plugin=plugin, folder=folder, path=path, home=home, data=data)
            assert r.returncode == 0 and r.stderr == b"", r
            outputs.append(json.loads(r.stdout.decode("utf-8")) if r.stdout.strip() else None)
        return outputs[0]

    def read(record: str) -> None:
        tool_input = {"tabId": "tab-1", "filter": "all"}
        assert run("PreToolUse", {"tool_name": nt.BUILTIN + "read_page", "tool_input": tool_input}) is None
        run("PostToolUse", {"tool_name": nt.BUILTIN + "read_page", "tool_input": tool_input,
                            "tool_response": [{"type": "text", "text": nt.record_text(record)}]})

    read("m8_shinsei12.txt")
    assert "「提出」" in nt.reason(run("PreToolUse", {"tool_name": nt.BUILTIN + "computer",
                                                    "tool_input": nt.click("ref_80")}))
    read("m8_shinsei1.txt")
    assert "「宣誓」" in nt.reason(run("PreToolUse", {"tool_name": nt.BUILTIN + "form_input",
                                                    "tool_input": nt.fill("ref_42", True)}))
    read("m8_shinsei3.txt")
    assert "「確認」" in nt.reason(run("PreToolUse", {"tool_name": nt.BUILTIN + "computer",
                                                    "tool_input": nt.click("ref_33")}))
    run("PostToolUse", {"tool_name": nt.BUILTIN + "read_page", "tool_input": {},
                        "tool_response": [{"type": "text", "text": nt.record_text("mock_login.txt")}]})
    assert "パスワード" in nt.reason(run("PreToolUse", {"tool_name": nt.BUILTIN + "form_input",
                                                      "tool_input": {"ref": "ref_12", "value": "pw-test-1"}}))
    # 同じ道筋で、ツールが入れる欄は通る
    read("m8_shinsei4_before.txt")
    assert run("PreToolUse", {"tool_name": nt.BUILTIN + "form_input", "tool_input": nt.fill("ref_96", True)}) is None
    assert (tmp_path / "python-ran").exists()
