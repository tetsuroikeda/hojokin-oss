"""画面入力の守り（DESIGN 5章、TASKS S4）。

記録したブラウザの道具の呼び出しと結果（tests/browser_records/）を、hook の処理に渡して確かめる。
- e1_calls.jsonl：実験 E1 で、試しのプラグインの hook が受け取った呼び出しと結果（架空の試しの画面。
  セッションの ID・時刻・手元の場所は外し、会社のフォルダは {会社} と書いた）。
- mock_shinsei.txt・mock_login.txt：模擬の申請画面（mock/。D11a）を内蔵ブラウザで読んだ結果。

確かめること（DESIGN 5章の表の行ごと）
- 提出ボタンを押さない：押してよいボタン（制度データの画面の定義）だけを、番号で指したクリックで通す。
  押さないボタンの語（提出・送信・申請する・確定・完了）はコードに固定し、制度データにあっても押させない。
  座標でのクリック、ダブルクリック・右クリック・ドラッグ、打ち込み、キー、JavaScript とショートカットは拒む。
  知らない道具の名前も拒む。クリックとページの移動の後は控えを捨てる。まとめて動かす道具は中を1つずつ見て、
  クリックは1回までで最後に限る。会社のフォルダでは computer use を拒む。
- 確認・誓約・同意のチェック欄に入れない：選ぶ欄は、囲むラベルから名前が読め、制度データでツールが入れる欄とされ、
  名前に確認・誓約・同意・宣誓を含まないものだけ通す。名前が読めない欄には入れない。
- 添付するのは、決まった写しだけ：案件の「添付する書類」にある写しだけを、添付の欄に通す。
- パスワードを扱わない：種類がパスワードの欄への入力を拒む。
- 画面入力は、担当者が呼んだときだけ：/hojokin:nyuryoku で記録した許可がないと、クリック・入力・添付を拒む。
  ページを読むだけの道具は拒まない。許可はそのセッションだけ。
- hooks.json から run.sh を通して、/usr/bin/python3（3.9）で同じ判定になる。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import hook_runner as hr
import pytest

from lib import browser_guard as bg
from lib import input_sheet, page_tree

RECORDS = Path(__file__).resolve().parent / "browser_records"
BUILTIN = "mcp__Claude_Browser__"
CHROME = "mcp__claude-in-chrome__"
SESSION = "sess-1"

# 制度データの申請画面（架空。省力化の模擬画面と E1 の試しの画面に合わせた欄とボタン）
SCHEME = {
    "申請画面": {
        "流れ": {"値": "試し", "出典": [], "根拠の文": "", "状態": "確認済み"},
        "画面": [
            {
                "順番": 1,
                "名前": "試しの画面",
                "欄": [
                    {"名前": "会社名", "種類": "文字", "担当者が入れる": False},
                    {"名前": "一般型", "種類": "ラジオ", "担当者が入れる": False},
                    {"名前": "賃上げ加点を申請する", "種類": "チェック", "担当者が入れる": False},
                    {"名前": "経営革新計画の加点を申請する", "種類": "チェック", "担当者が入れる": False},
                    {"名前": "組織形態", "種類": "選択", "担当者が入れる": False},
                    {"名前": "国の他の助成制度との重複", "種類": "ラジオ", "担当者が入れる": False},
                    {"名前": "事業承継又はM&A加点", "種類": "チェック", "担当者が入れる": False},
                    {"名前": "小規模企業者・小規模事業者", "種類": "チェック", "担当者が入れる": False},
                    {"名前": "省力化ナビ加点", "種類": "チェック", "担当者が入れる": False},
                    # 担当者が入れる欄
                    {"名前": "事業継続力強化計画加点", "種類": "チェック", "担当者が入れる": True},
                    # 種類が画面と合わない欄
                    {"名前": "経営戦略・経営計画", "種類": "文字", "担当者が入れる": False},
                    # 制度データ（AI の下書き）がツールの欄と誤っても、4つの語を含む欄は入れない
                    {"名前": "宣誓事項1", "種類": "チェック", "担当者が入れる": False},
                    {"名前": "申請の内容に相違ないことを誓約します", "種類": "チェック", "担当者が入れる": False},
                    # 添付の欄（入力シートの値に書いた書類の写しだけを添付する。B29）
                    {"名前": "見積書", "種類": "添付", "担当者が入れる": False},
                    {"名前": "賃金台帳", "種類": "添付", "担当者が入れる": False},
                ],
                # 制度データ（AI の下書き）に「提出」があっても、コードに固定した語が優先する
                "押してよいボタン": ["一時保存", "次へ", "戻る", "計算", "提出する", "提出", "送信する"],
            }
        ],
    }
}


# ---- 準備 ----

CASE = "2026_省力化（一般型）第8回"


def write_sheet(stage_dir: Path, values: dict, scheme: dict = None) -> Path:
    """段階のフォルダの申請書/入力シート.xlsx を、制度データから作って値を書く（values は 欄 → 値）。"""
    scheme = scheme or SCHEME
    blob = input_sheet.build(scheme)
    for (screen, field) in [(s, f) for s, f in input_sheet.fields_of(scheme) if f["名前"] in values]:
        blob, _ = input_sheet.write_value(blob, field["名前"], values[field["名前"]], screen["名前"])
    path = stage_dir / "申請書" / input_sheet.FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)
    return path


@pytest.fixture
def folder(tmp_path) -> Path:
    company = tmp_path / "試しの会社"
    (company / ".hojokin").mkdir(parents=True)
    scheme_dir = company / "記録" / "制度データ"
    scheme_dir.mkdir(parents=True)
    (scheme_dir / "省力化_第8回.json").write_text(json.dumps(SCHEME, ensure_ascii=False), encoding="utf-8")
    attach = company / "案件" / CASE / "1_申請" / "添付する書類"
    attach.mkdir(parents=True)
    (attach / "見積書の写し.pdf").write_bytes(b"%PDF-1.4 test")
    # 入力シートの添付の欄に、添付する写しの場所を書く（守りは、ここに書いた書類の写しだけを添付させる）
    write_sheet(attach.parent, {"見積書": f"案件/{CASE}/1_申請/添付する書類/見積書の写し.pdf"})
    (company / "見積書の写し.txt").write_text("会社のフォルダの直下（添付する書類ではない）", encoding="utf-8")
    (company / "原本").mkdir()
    (company / "原本" / "見積書.pdf").write_bytes(b"%PDF-1.4 original")
    return company


def base(folder: Path, session: str = SESSION) -> dict:
    return {"session_id": session, "cwd": str(folder), "transcript_path": str(folder / "t.jsonl")}


def prompt(folder: Path, text: str, session: str = SESSION) -> None:
    bg.user_prompt_submit({**base(folder, session), "hook_event_name": "UserPromptSubmit", "prompt": text}, folder)


def permit(folder: Path, session: str = SESSION) -> None:
    prompt(folder, "/hojokin:nyuryoku", session)
    assert bg.has_permission(folder, session)


def pre(folder: Path, tool: str, tool_input: dict, session: str = SESSION):
    data = {**base(folder, session), "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}
    return bg.pre_tool_use(data, folder)


def post(folder: Path, tool: str, tool_input: dict, response=None, session: str = SESSION) -> None:
    data = {**base(folder, session), "hook_event_name": "PostToolUse", "tool_name": tool,
            "tool_input": tool_input, "tool_response": response}
    bg.post_tool_use(data, folder)


def denied(output) -> str:
    """拒んだ判定なら理由を返す。通したなら落とす。"""
    assert output is not None, "通ってしまった"
    hso = output["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "deny"
    reason = hso["permissionDecisionReason"]
    assert "hojokin" in reason
    return reason


def passed(output) -> None:
    assert output is None, output


def read_record(name: str) -> str:
    return (RECORDS / name).read_text(encoding="utf-8")


def read_mock(folder: Path, page: str = "mock_shinsei.txt", tool: str = BUILTIN + "read_page",
              session: str = SESSION, tool_input: dict = None) -> None:
    """模擬画面を読んだ結果（内蔵ブラウザの結果と同じ、{type, text} の並び）を控えさせる。"""
    post(folder, tool, tool_input or {"filter": "all"}, [{"type": "text", "text": read_record(page)}], session)


def click(ref: str, **extra) -> dict:
    return {"action": "left_click", "ref": ref, **extra}


def e1_records() -> list:
    lines = read_record("e1_calls.jsonl").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def e1(row: int) -> dict:
    for record in e1_records():
        if record["行"] == row:
            return record
    raise KeyError(row)


def replay(folder: Path, row: int, session: str = SESSION):
    """E1 の記録の1行を、hook の処理に渡す。PreToolUse なら判定を返す。"""
    record = json.loads(json.dumps(e1(row), ensure_ascii=False).replace("{会社}", str(folder)))
    data = {**base(folder, session), "hook_event_name": record["event"], "tool_name": record["tool_name"],
            "tool_input": record["tool_input"], "tool_response": record.get("tool_response")}
    if record["event"] == "PreToolUse":
        return bg.pre_tool_use(data, folder)
    bg.post_tool_use(data, folder)
    return None


# ---- 部品の控え（PostToolUse）と読み方 ----

def test_parse_e1_tree_reads_names_kinds_and_labels() -> None:
    """E1 の木から、ボタンの名前、欄の種類、チェック欄・ラジオボタンの名前（囲むラベル）が読める。選択欄は読めない形がある。"""
    text = page_tree.response_text(e1(4)["tool_response"])
    tree = page_tree.parse(text)
    assert tree["tab"] == "seed"
    page = page_tree.Page(tree["elements"])
    assert page.get("ref_32")["role"] == "button" and page.get("ref_32")["name"] == "提出する"
    assert page.get("ref_29")["type"] == "password"
    assert page.get("ref_27")["type"] == "file"
    assert page.get("ref_4")["type"] == "hidden"
    assert page.field_name("ref_21") == "賃上げ加点を申請する"
    assert page.field_name("ref_23") == "申請の内容に相違ないことを誓約します"
    assert page.field_name("ref_17") == "一般型"
    # ラベルのない欄と、名前の空の選択欄（選択肢の文字はラベルの名前に数えない）
    assert page.field_name("ref_25") == ""
    assert page.field_name("ref_10") == ""
    # 番号のない選択肢の行は控えない。部品の形でない行（Viewport・Tab Context）も控えない
    assert all(e["role"] != "option" for e in tree["elements"].values())
    assert len(tree["elements"]) == 32


def test_parse_mock_tree_reads_label_text() -> None:
    """模擬画面の形（ラベルに名前がなく、ラベルの中の文字に名前がある）でも、欄の名前が読める。"""
    tree = page_tree.parse(read_record("mock_shinsei.txt"))
    page = page_tree.Page(tree["elements"])
    assert page.field_name("ref_17") == "宣誓事項1：公募要領を理解し、申請者自身が計画を作って申請することに同意する"
    assert page.field_name("ref_221") == "国の他の助成制度との重複：はい"
    assert page.field_name("ref_37") == "組織形態"
    assert page.field_name("ref_694") == "履歴事項全部証明書"
    assert page.field_name("ref_151") == ""  # 名前の空のラベル
    assert page.controls_in("ref_229") == ["ref_230"]


def test_response_text_accepts_list_json_and_plain() -> None:
    text = 'button "次へ" [ref_3]'
    blocks = [{"type": "text", "text": text}]
    for response in (blocks, json.dumps(blocks, ensure_ascii=False), text, {"content": blocks}):
        assert page_tree.parse(page_tree.response_text(response))["elements"]["ref_3"]["name"] == "次へ"


def test_snapshot_is_kept_per_session_and_browser(folder) -> None:
    """控えは、セッションとブラウザ（内蔵ブラウザ・Claude in Chrome）ごとに、.hojokin/一時/ の下に置く。"""
    read_mock(folder)
    snap = folder / ".hojokin" / "一時" / "画面入力" / SESSION / "控え.json"
    saved = json.loads(snap.read_text(encoding="utf-8"))
    assert set(saved) == {bg.BUILTIN}
    assert saved[bg.BUILTIN]["tab"] == "seed"
    assert saved[bg.BUILTIN]["tab_given"] is False  # タブを指さずに読んだ
    assert saved[bg.BUILTIN]["elements"]["ref_954"]["name"] == "提出"
    # 版の履歴に入れない置き場（lib/company_init.py の .gitignore の行）
    from lib import company_init
    assert "/.hojokin/一時/" in company_init.GITIGNORE_LINES


# ---- 画面入力は、担当者が呼んだときだけ（T10-5 の形） ----

def test_without_permission_click_input_upload_are_denied(folder) -> None:
    read_mock(folder)
    post(folder, CHROME + "read_page", {"tabId": 7, "filter": "all"},
         [{"type": "text", "text": read_record("mock_shinsei.txt")}])
    attach = folder / "案件" / "2026_省力化（一般型）第8回" / "1_申請" / "添付する書類" / "見積書の写し.pdf"
    for tool, tool_input in (
        (BUILTIN + "computer", click("ref_7")),
        (BUILTIN + "form_input", {"ref": "ref_58", "value": "試し商事"}),
        (BUILTIN + "form_input", {"ref": "ref_230", "value": True}),
        (CHROME + "computer", click("ref_7", tabId=7)),
        (CHROME + "form_input", {"ref": "ref_58", "value": "試し商事", "tabId": 7}),
        (CHROME + "file_upload", {"paths": [str(attach)], "ref": "ref_694", "tabId": 7}),
        (BUILTIN + "browser_batch", {"actions": [{"name": "form_input", "input": {"ref": "ref_58", "value": "x"}}]}),
    ):
        reason = denied(pre(folder, tool, tool_input))
        assert "/hojokin:nyuryoku" in reason, (tool, reason)


def test_reading_tools_pass_without_permission(folder) -> None:
    for tool, tool_input in (
        (BUILTIN + "read_page", {"filter": "all"}),
        (BUILTIN + "get_page_text", {}),
        (BUILTIN + "find", {"query": "次へ"}),
        (BUILTIN + "computer", {"action": "screenshot"}),
        (BUILTIN + "computer", {"action": "zoom", "region": [0, 0, 10, 10]}),
        (BUILTIN + "computer", {"action": "scroll", "coordinate": [10, 10], "scroll_direction": "down"}),
        (BUILTIN + "navigate", {"url": "http://127.0.0.1:8780/"}),
        (BUILTIN + "tabs_context", {}),
        (CHROME + "tabs_context_mcp", {"createIfEmpty": True}),
        (CHROME + "tabs_create_mcp", {}),
        (CHROME + "read_page", {"tabId": 1, "filter": "all"}),
        ("mcp__remote-devices__Claude_Browser__read_page", {}),
    ):
        passed(pre(folder, tool, tool_input))


def test_permission_is_recorded_only_for_nyuryoku_at_the_start(folder) -> None:
    """許可は、文の先頭が /hojokin:nyuryoku のときだけ残す（別のセッションから送られた文は頭に印が付く。実験 E1）。"""
    for text in ("/hojokin:nyuryokuX", "画面に /hojokin:nyuryoku で入れて", "nyuryoku して",
                 "<system-reminder>知らせ</system-reminder>\n/hojokin:nyuryoku", "/hojokin:kaku"):
        prompt(folder, text)
        assert not bg.has_permission(folder, SESSION), text
    prompt(folder, "  /hojokin:nyuryoku 申請画面に入れて")
    assert bg.has_permission(folder, SESSION)
    record = json.loads((folder / ".hojokin" / "一時" / "画面入力" / SESSION / "許可.json").read_text(encoding="utf-8"))
    assert record["session_id"] == SESSION


def test_permission_is_only_for_that_session(folder) -> None:
    permit(folder, "sess-1")
    read_mock(folder, session="sess-2")
    assert not bg.has_permission(folder, "sess-2")
    assert "/hojokin:nyuryoku" in denied(pre(folder, BUILTIN + "computer", click("ref_7"), session="sess-2"))
    # セッションの ID がないときは、許可がないものとして扱う
    data = {"hook_event_name": "PreToolUse", "tool_name": BUILTIN + "computer", "tool_input": click("ref_7")}
    denied(bg.pre_tool_use(data, folder))


# ---- 提出ボタンを押さない ----

def test_allowed_buttons_pass_and_prohibited_words_win(folder) -> None:
    permit(folder)
    for ref in ("ref_7", "ref_8", "ref_6", "ref_612", "ref_955"):  # 一時保存・次へ・戻る・計算・下の戻る
        read_mock(folder)
        passed(pre(folder, BUILTIN + "computer", click(ref)))
    # 制度データの「押してよいボタン」に「提出」があっても、コードに固定した語が優先する
    read_mock(folder)
    reason = denied(pre(folder, BUILTIN + "computer", click("ref_954")))
    assert "「提出」" in reason and "担当者" in reason


def test_prohibited_button_words_are_fixed_in_code() -> None:
    assert bg.PROHIBITED_BUTTON_WORDS == ("提出", "送信", "申請する", "確定", "完了")
    assert bg.PROHIBITED_FIELD_WORDS == ("確認", "誓約", "同意", "宣誓")


@pytest.mark.parametrize("name", ["提出する", "送信", "申請する", "内容を確定", "申請完了", "提 出"])
def test_buttons_with_prohibited_words_are_denied(folder, name) -> None:
    permit(folder)
    scheme = json.loads(json.dumps(SCHEME, ensure_ascii=False))
    scheme["申請画面"]["画面"][0]["押してよいボタン"].append(name)
    (folder / "記録" / "制度データ" / "省力化_第8回.json").write_text(json.dumps(scheme, ensure_ascii=False), encoding="utf-8")
    post(folder, BUILTIN + "read_page", {}, f'form [ref_1]\n button "{name}" [ref_2] type="submit"\n link "{name}" [ref_3]')
    # 空白を入れた書き方（「提 出」）でも、語に当たる
    denied(pre(folder, BUILTIN + "computer", click("ref_2")))
    post(folder, BUILTIN + "read_page", {}, f'form [ref_1]\n button "{name}" [ref_2] type="submit"\n link "{name}" [ref_3]')
    denied(pre(folder, BUILTIN + "computer", click("ref_3")))


def test_buttons_not_in_scheme_and_unnamed_buttons_are_denied(folder) -> None:
    permit(folder)
    read_mock(folder)
    assert "押してよいボタン" in denied(pre(folder, BUILTIN + "computer", click("ref_187")))  # 認証コード発行
    assert "押してよいボタン" in denied(pre(folder, BUILTIN + "computer", click("ref_911")))  # 修正（リンク）
    read_mock(folder, "mock_login.txt")
    denied(pre(folder, BUILTIN + "computer", click("ref_13")))  # ログイン
    post(folder, BUILTIN + "read_page", {}, 'form [ref_1]\n button [ref_2] type="submit"')
    assert "名前の読めない" in denied(pre(folder, BUILTIN + "computer", click("ref_2")))


def test_no_scheme_data_means_no_button(folder) -> None:
    permit(folder)
    (folder / "記録" / "制度データ" / "省力化_第8回.json").write_text("{壊れた", encoding="utf-8")
    read_mock(folder)
    denied(pre(folder, BUILTIN + "computer", click("ref_7")))
    denied(pre(folder, BUILTIN + "form_input", {"ref": "ref_230", "value": True}))


@pytest.mark.parametrize("tool_input", [
    {"action": "left_click", "coordinate": [100, 200]},
    {"action": "left_click", "ref": "ref_7", "coordinate": [100, 200]},
    {"action": "left_click", "ref": "ref_7", "modifiers": "cmd"},
    {"action": "double_click", "ref": "ref_7"},
    {"action": "triple_click", "ref": "ref_7"},
    {"action": "right_click", "ref": "ref_7"},
    {"action": "left_click_drag", "start_coordinate": [1, 1], "coordinate": [2, 2]},
    {"action": "type", "text": "試し商事"},
    {"action": "key", "text": "Return"},
    {"action": "hover", "ref": "ref_7"},
    {"action": "left_click"},
])
def test_other_computer_actions_are_denied(folder, tool_input) -> None:
    permit(folder)
    read_mock(folder)
    denied(pre(folder, BUILTIN + "computer", tool_input))
    post(folder, CHROME + "read_page", {"tabId": 3}, [{"type": "text", "text": read_record("mock_shinsei.txt")}])
    denied(pre(folder, CHROME + "computer", {**tool_input, "tabId": 3}))


@pytest.mark.parametrize("tool,tool_input", [
    (BUILTIN + "javascript_tool", {"action": "javascript_exec", "text": "document.forms[0].submit()"}),
    (CHROME + "javascript_tool", {"action": "javascript_exec", "text": "1", "tabId": 1}),
    (CHROME + "shortcuts_execute", {"tabId": 1, "shortcutId": "x"}),
    (CHROME + "upload_image", {"imageId": "x", "ref": "ref_694", "tabId": 1}),
    (CHROME + "request_credentials", {}),
    (CHROME + "gif_creator", {"action": "start_recording"}),
    (BUILTIN + "preview_start", {"name": "dev"}),
    (BUILTIN + "そのほかの道具", {}),
    ("mcp__Claude_Browser_new_tool", {}),
    (BUILTIN + "navigate", {"url": "javascript:document.forms[0].submit()"}),
    (BUILTIN + "navigate", {"url": "data:text/html,x"}),
    (BUILTIN + "navigate", {"url": "file:///etc/passwd"}),
])
def test_scripts_shortcuts_and_unknown_tools_are_denied(folder, tool, tool_input) -> None:
    permit(folder)
    read_mock(folder)
    denied(pre(folder, tool, tool_input))


@pytest.mark.parametrize("tool", [
    "mcp__computer-use__left_click", "mcp__computer-use__screenshot", "mcp__computer-use__app_click",
    "mcp__remote-devices__computer-use__type",
])
def test_computer_use_is_denied_in_company_folder(folder, tool) -> None:
    permit(folder)
    assert "computer use" in denied(pre(folder, tool, {"coordinate": [1, 1]}))


def test_snapshot_is_discarded_after_click_and_page_moves(folder) -> None:
    """クリックとページの移動・タブの切り替えの後は控えを捨て、読み直すまでクリックも入力も通さない。"""
    permit(folder)
    for tool, tool_input in (
        (BUILTIN + "computer", click("ref_8")),
        (BUILTIN + "navigate", {"url": "http://127.0.0.1:8780/shinsei"}),
        (BUILTIN + "navigate", {"url": "back"}),
        (BUILTIN + "tabs_create", {}),
    ):
        read_mock(folder)
        passed(pre(folder, tool, tool_input))
        post(folder, tool, tool_input, None)
        assert "読み直" in denied(pre(folder, BUILTIN + "computer", click("ref_7")))
        assert "読み直" in denied(pre(folder, BUILTIN + "form_input", {"ref": "ref_58", "value": "x"}))
    # 控えはブラウザごと：内蔵ブラウザのクリックで、Claude in Chrome の控えは捨てない
    read_mock(folder)
    post(folder, CHROME + "read_page", {"tabId": 3}, [{"type": "text", "text": read_record("mock_shinsei.txt")}])
    passed(pre(folder, BUILTIN + "computer", click("ref_8")))
    passed(pre(folder, CHROME + "computer", click("ref_7", tabId=3)))


def test_click_ref_not_on_page_and_other_tab_are_denied(folder) -> None:
    permit(folder)
    post(folder, CHROME + "read_page", {"tabId": 3}, [{"type": "text", "text": read_record("mock_shinsei.txt")}])
    assert "ref_9999" in denied(pre(folder, CHROME + "computer", click("ref_9999", tabId=3)))
    assert "別のタブ" in denied(pre(folder, CHROME + "computer", click("ref_7", tabId=4)))
    passed(pre(folder, CHROME + "computer", click("ref_7", tabId=3)))


def test_snapshot_read_with_tab_is_used_only_with_that_tab(folder) -> None:
    """タブを指して読んだ控えは、同じ tabId を付けた操作にだけ使う。

    tabId を省いた操作は前に出ているタブで動くので、別のタブで読んだ控えで押させない
    （例：後ろに開いたタブ B を読み、tabId なしで押すと、前のタブ A の同じ番号の部品を押す）。
    """
    permit(folder)
    attach = folder / "案件" / "2026_省力化（一般型）第8回" / "1_申請" / "添付する書類" / "見積書の写し.pdf"
    page = [{"type": "text", "text": read_record("mock_shinsei.txt")}]
    for tab in ("B", 881448174):
        post(folder, CHROME + "read_page", {"tabId": tab, "filter": "all"}, page)
        for tool, tool_input in (
            (CHROME + "computer", click("ref_7")),
            (CHROME + "form_input", {"ref": "ref_58", "value": "試し商事"}),
            (CHROME + "form_input", {"ref": "ref_230", "value": True}),
            (CHROME + "file_upload", {"paths": [str(attach)], "ref": "ref_694"}),
            (CHROME + "browser_batch", {"actions": [{"name": "form_input", "input": {"ref": "ref_58", "value": "x"}}]}),
        ):
            reason = denied(pre(folder, tool, tool_input))
            assert "tabId" in reason and str(tab) in reason, (tool, reason)
        # 結果の「Executed on tabId: seed」の値でも通さない（指したタブで照らす）
        assert "別のタブ" in denied(pre(folder, CHROME + "computer", click("ref_7", tabId="seed")))
        passed(pre(folder, CHROME + "form_input", {"ref": "ref_58", "value": "試し商事", "tabId": tab}))
        passed(pre(folder, CHROME + "file_upload", {"paths": [str(attach)], "ref": "ref_694", "tabId": tab}))
        passed(pre(folder, CHROME + "computer", click("ref_7", tabId=tab)))
    # 内蔵ブラウザでも、タブを指して読んだら同じ
    read_mock(folder, tool_input={"tabId": "B", "filter": "all"})
    assert "tabId" in denied(pre(folder, BUILTIN + "computer", click("ref_7")))
    passed(pre(folder, BUILTIN + "computer", click("ref_7", tabId="B")))


def test_snapshot_read_without_tab_is_used_without_tab_or_with_executed_tab(folder) -> None:
    """タブを指さずに読んだ控えは、tabId を省いた操作か、結果の「Executed on tabId」と同じ tabId の操作にだけ使う。"""
    permit(folder)
    read_mock(folder)  # 結果に「Executed on tabId: seed」がある
    passed(pre(folder, BUILTIN + "form_input", {"ref": "ref_58", "value": "試し商事"}))
    passed(pre(folder, BUILTIN + "form_input", {"ref": "ref_58", "value": "試し商事", "tabId": "seed"}))
    assert "別のタブ" in denied(pre(folder, BUILTIN + "form_input", {"ref": "ref_58", "value": "x", "tabId": "other"}))
    assert "別のタブ" in denied(pre(folder, BUILTIN + "computer", click("ref_7", tabId="other")))
    passed(pre(folder, BUILTIN + "computer", click("ref_7")))
    # 結果にタブの番号がないときは、tabId を付けた操作を通さない（同じタブか分からない）
    post(folder, BUILTIN + "read_page", {}, 'form [ref_1]\n button "次へ" [ref_2]\n textbox "会社名" [ref_3]')
    assert "別のタブ" in denied(pre(folder, BUILTIN + "computer", click("ref_2", tabId="x")))
    assert "別のタブ" in denied(pre(folder, BUILTIN + "form_input", {"ref": "ref_3", "value": "x", "tabId": "x"}))
    passed(pre(folder, BUILTIN + "form_input", {"ref": "ref_3", "value": "試し商事"}))


def test_snapshot_without_tab_record_is_not_used(folder) -> None:
    """どのタブを読んだかの印のない控え（前の形の控えなど）は使わず、読み直させる。"""
    permit(folder)
    read_mock(folder)
    snap = folder / ".hojokin" / "一時" / "画面入力" / SESSION / "控え.json"
    saved = json.loads(snap.read_text(encoding="utf-8"))
    del saved[bg.BUILTIN]["tab_given"]
    snap.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    assert "読み直" in denied(pre(folder, BUILTIN + "form_input", {"ref": "ref_58", "value": "x"}))


# ページの移動で拒む URL（JavaScript を動かす形と、空白・制御文字を中に入れた形）
NAVIGATE_DENIED = [
    "javascript:document.forms[0].submit()",
    "javascript:alert(1)",
    "javascript:1,document.forms[0].submit()",
    "javascript:0;document.forms[0].submit()",
    "javascript:0||document.forms[0].submit()",
    "javascript:1/document.forms[0].submit()",
    "JavaScript:1;x()",
    "java\tscript:alert(1)",
    "java\nscript:alert(1)",
    "java\rscript:alert(1)",
    "java​script:alert(1)",
    " javascript:alert(1)",
    "\tjavascript:alert(1)",
    "vbscript:1",
    "data:0,x",
    "data:text/html,x",
    "file:///etc/passwd",
    "blob:http://127.0.0.1/x",
    "about:blank",
    "localhost:8780",
    "127.0.0.1:8780/shinsei",
    "//127.0.0.1/",
    "http://127.0.0.1/\tx",
    "http://127.0.0.1/\nx",
    "http://127.0.0.1/ x",
    "http://127.0.0.1/　x",
    "",
]


@pytest.mark.parametrize("url", NAVIGATE_DENIED)
@pytest.mark.parametrize("with_permission", [False, True])
def test_navigate_to_scripts_and_odd_urls_is_denied(folder, url, with_permission) -> None:
    """移れるのは http・https と back・forward だけ。ページの移動は許可がなくても通すので、許可の前後で確かめる。"""
    if with_permission:
        permit(folder)
    read_mock(folder)
    denied(pre(folder, BUILTIN + "navigate", {"url": url}))
    denied(pre(folder, CHROME + "navigate", {"url": url, "tabId": 1}))
    denied(pre(folder, BUILTIN + "browser_batch", {"actions": [{"name": "navigate", "input": {"url": url}}]}))
    # 拒んだ移動では、控えを捨てない
    if with_permission:
        passed(pre(folder, BUILTIN + "form_input", {"ref": "ref_58", "value": "x"}))


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8780/", "https://example.jp/a?b=1", "HTTPS://example.jp/", "back", "Forward",
])
def test_navigate_to_web_pages_passes(folder, url) -> None:
    passed(pre(folder, BUILTIN + "navigate", {"url": url}))
    passed(pre(folder, CHROME + "navigate", {"url": url, "tabId": 1}))


def test_partial_read_replaces_snapshot(folder) -> None:
    """一部だけ読んだ結果（ref_id）は控えを置き換える。前に控えた部品は、読み直すまで使えない。"""
    permit(folder)
    read_mock(folder)
    post(folder, BUILTIN + "read_page", {"ref_id": "ref_689"},
         'region [ref_689]\n heading "❾ 書類添付" [ref_690]')
    denied(pre(folder, BUILTIN + "computer", click("ref_7")))
    # 部品の読めない結果（読み取りの失敗など）では、控えを捨てる
    read_mock(folder)
    post(folder, BUILTIN + "read_page", {}, "ページを読めませんでした")
    denied(pre(folder, BUILTIN + "computer", click("ref_7")))


def test_batch_is_checked_one_by_one(folder) -> None:
    permit(folder)

    def batch(*actions):
        return {"actions": [{"name": name, "input": tool_input} for name, tool_input in actions]}

    read_mock(folder)
    passed(pre(folder, BUILTIN + "browser_batch", batch(
        ("form_input", {"ref": "ref_58", "value": "試し商事"}),
        ("form_input", {"ref": "ref_230", "value": True}),
        ("computer", click("ref_7")),
    )))
    # 最後のクリックで控えを捨てた
    denied(pre(folder, BUILTIN + "form_input", {"ref": "ref_58", "value": "x"}))
    read_mock(folder)
    for actions in (
        (("computer", click("ref_7")), ("computer", click("ref_8"))),               # クリックが2回
        (("computer", click("ref_7")), ("form_input", {"ref": "ref_58", "value": "x"})),  # クリックが最後でない
        (("navigate", {"url": "http://127.0.0.1/"}), ("computer", click("ref_7"))),  # 移動とクリック
        (("form_input", {"ref": "ref_58", "value": "x"}), ("computer", click("ref_954"))),  # 提出
        (("form_input", {"ref": "ref_17", "value": True}),),                        # 宣誓の欄
        (("form_input", {"ref": "ref_58", "value": "x"}), ("javascript_tool", {"text": "1"})),
        (("browser_batch", {"actions": []}),),                                       # 入れ子
        (("知らない道具", {}),),
    ):
        denied(pre(folder, BUILTIN + "browser_batch", batch(*actions)))
    denied(pre(folder, BUILTIN + "browser_batch", {"actions": "壊れた"}))
    # 拒んだまとめては、控えを捨てない（何も動いていないため）
    passed(pre(folder, BUILTIN + "form_input", {"ref": "ref_58", "value": "x"}))


# ---- 確認・誓約・同意のチェック欄に入れない ----

@pytest.mark.parametrize("ref,word", [
    ("ref_17", "同意"), ("ref_20", "確認"), ("ref_23", "誓約"), ("ref_29", "宣誓"), ("ref_199", "確認"),
])
def test_oath_and_consent_fields_are_denied(folder, ref, word) -> None:
    """宣誓・確認・誓約・同意の欄は、制度データでツールの欄とされていても、入力もクリックも拒む（ラベルや文字を指しても）。"""
    permit(folder)
    read_mock(folder)
    reason = denied(pre(folder, BUILTIN + "form_input", {"ref": ref, "value": True}))
    assert f"「{word}」" in reason and "担当者" in reason
    label_ref = f"ref_{int(ref.split('_')[1]) - 1}"
    text_ref = f"ref_{int(ref.split('_')[1]) + 1}"
    for target in (ref, label_ref, text_ref):
        read_mock(folder)
        denied(pre(folder, BUILTIN + "computer", click(target)))


def test_tool_fields_in_scheme_pass(folder) -> None:
    """制度データでツールが入れる欄（加点・要件・ラジオボタン・選択欄）は、入力でもクリックでも通す。

    名前の照らし方：画面の名前の全体か、「：」より前の項目名が、制度データの欄の名前と同じ。
    """
    permit(folder)
    read_mock(folder)
    for ref in ("ref_230", "ref_192", "ref_300", "ref_221", "ref_224"):
        passed(pre(folder, BUILTIN + "form_input", {"ref": ref, "value": True}))
    passed(pre(folder, BUILTIN + "form_input", {"ref": "ref_37", "value": "1-1.中小企業者（組合関連以外）"}))
    for ref in ("ref_230", "ref_229", "ref_231", "ref_221"):  # 欄・ラベル・ラベルの中の文字
        read_mock(folder)
        passed(pre(folder, BUILTIN + "computer", click(ref)))


def test_fields_not_for_tool_are_denied(folder) -> None:
    permit(folder)
    read_mock(folder)
    # 担当者が入れる欄
    assert "ツールが入れる欄とされていません" in denied(pre(folder, BUILTIN + "form_input", {"ref": "ref_235", "value": True}))
    # 種類が合わない欄
    assert "種類" in denied(pre(folder, BUILTIN + "form_input", {"ref": "ref_838", "value": True}))
    # 制度データにない欄
    post(folder, BUILTIN + "read_page", {},
         'form [ref_1]\n label [ref_2]\n  checkbox "on" [ref_3] type="checkbox"\n  generic "えるぼし加点：認定を受けている" [ref_4]')
    denied(pre(folder, BUILTIN + "form_input", {"ref": "ref_3", "value": True}))


def test_unreadable_fields_are_denied(folder) -> None:
    """名前の読めない欄（ラベルのない欄、名前の空の選択欄）には入れない（E1 の記録）。"""
    permit(folder)
    replay(folder, 4)
    assert "名前の読めない" in denied(pre(folder, BUILTIN + "form_input", {"ref": "ref_25", "value": True}))
    assert "名前の読めない" in denied(replay(folder, 7))  # 業種の選択欄
    # ラベルの外にある見出し（generic）だけでは名前にしない
    post(folder, BUILTIN + "read_page", {},
         'form [ref_1]\n generic "賃上げ加点を申請する" [ref_2]\n checkbox "on" [ref_3] type="checkbox"')
    denied(pre(folder, BUILTIN + "form_input", {"ref": "ref_3", "value": True}))


# ---- パスワードと、文字の欄 ----

def test_password_hidden_and_file_fields_are_denied(folder) -> None:
    permit(folder)
    read_mock(folder, "mock_login.txt")
    reason = denied(pre(folder, BUILTIN + "form_input", {"ref": "ref_12", "value": "x"}))
    assert "パスワード" in reason
    denied(pre(folder, BUILTIN + "form_input", {"ref": "ref_10", "value": "x"}))  # パスワードのラベル
    denied(pre(folder, BUILTIN + "computer", click("ref_12")))
    passed(pre(folder, BUILTIN + "form_input", {"ref": "ref_9", "value": "info@example.com"}))
    replay(folder, 4)
    denied(pre(folder, BUILTIN + "form_input", {"ref": "ref_29", "value": "x"}))
    denied(pre(folder, BUILTIN + "form_input", {"ref": "ref_4", "value": "x"}))  # 隠れた欄
    # 名前が「パスワード」の文字の欄（種類が text でも）
    post(folder, BUILTIN + "read_page", {}, 'label [ref_1]\n generic "パスワード" [ref_2]\n textbox [ref_3] type="text"')
    denied(pre(folder, BUILTIN + "form_input", {"ref": "ref_3", "value": "x"}))


def test_text_fields_pass(folder) -> None:
    """文字の欄は、控えにある番号なら通す（名前の空のラベルの欄、表の中の欄も）。クリックでは入れない。"""
    permit(folder)
    read_mock(folder)
    for ref in ("ref_58", "ref_91", "ref_151", "ref_526", "ref_183"):
        passed(pre(folder, BUILTIN + "form_input", {"ref": ref, "value": "x"}))
    assert "form_input" in denied(pre(folder, BUILTIN + "computer", click("ref_58")))


# ---- 添付するのは、決まった写しだけ ----

def test_upload_only_copies_in_attach_folder(folder, tmp_path) -> None:
    permit(folder)
    post(folder, CHROME + "read_page", {"tabId": 5}, [{"type": "text", "text": read_record("mock_shinsei.txt")}])
    stage = folder / "案件" / "2026_省力化（一般型）第8回" / "1_申請"
    copy = stage / "添付する書類" / "見積書の写し.pdf"
    passed(pre(folder, CHROME + "file_upload", {"paths": [str(copy)], "ref": "ref_694", "tabId": 5}))
    # 相対の場所は cwd から解く
    passed(pre(folder, CHROME + "file_upload",
               {"paths": ["案件/2026_省力化（一般型）第8回/1_申請/添付する書類/見積書の写し.pdf"], "ref": "ref_739", "tabId": 5}))
    # 効果報告の形（段階の下にもう1段ある。DESIGN 4.5）
    yearly = folder / "案件" / "2026_省力化（一般型）第8回" / "4_効果報告" / "1年目" / "添付する書類" / "賃金台帳の写し.pdf"
    yearly.parent.mkdir(parents=True)
    yearly.write_bytes(b"x")
    # 入力シートは、1年目の下の申請書にある（なければ段階の申請書を見る）
    write_sheet(yearly.parent.parent, {"賃金台帳": "賃金台帳の写し.pdf"})
    passed(pre(folder, CHROME + "file_upload", {"paths": [str(yearly)], "ref": "ref_694", "tabId": 5}))
    case = folder / "案件" / "2026_省力化（一般型）第8回"
    odd = [case / "添付する書類" / "a.pdf",                                  # 段階がない
           case / "1_申請" / "申請書" / "添付する書類" / "a.pdf",              # 申請書の下
           case / "1_申請" / "古い" / "下" / "添付する書類" / "a.pdf",         # 深すぎる
           case / "申請" / "添付する書類" / "a.pdf"]                           # 段階の名前の形でない
    for path in odd:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    outside = tmp_path / "外" / "見積書.pdf"
    outside.parent.mkdir()
    outside.write_bytes(b"x")
    link = stage / "添付する書類" / "外へのリンク.pdf"
    os.symlink(outside, link)
    (stage / "申請書").mkdir(exist_ok=True)
    (stage / "申請書" / "入力シート.xlsx").write_bytes(b"x")
    for paths in (
        [str(folder / "原本" / "見積書.pdf")],
        [str(folder / "見積書の写し.txt")],
        [str(stage / "申請書" / "入力シート.xlsx")],
        [str(stage / "添付する書類" / ".." / ".." / ".." / ".." / "原本" / "見積書.pdf")],
        [str(stage / "添付する書類" / "ない.pdf")],
        [str(stage / "添付する書類")],
        [str(link)],
        [str(outside)],
        [str(copy), str(folder / "原本" / "見積書.pdf")],
        [],
    ) + tuple([str(p)] for p in odd):
        reason = denied(pre(folder, CHROME + "file_upload", {"paths": paths, "ref": "ref_694", "tabId": 5}))
        assert "添付" in reason, paths
    # 添付の欄でない部品には使わない
    denied(pre(folder, CHROME + "file_upload", {"paths": [str(copy)], "ref": "ref_58", "tabId": 5}))


def test_upload_only_copies_named_in_the_input_sheet(folder) -> None:
    """添付するのは、入力シートの添付の欄の値に当たる写しだけ（DESIGN 5章・14章、TASKS B29）。

    当たるのは、値が写しの場所か名前、拡張子を除いた名前が同じ（原本を PDF にした写し）、書類の台帳の元の原本、のどれか。
    """
    permit(folder)
    post(folder, CHROME + "read_page", {"tabId": 5}, [{"type": "text", "text": read_record("mock_shinsei.txt")}])
    stage = folder / "案件" / CASE / "1_申請"
    attach = stage / "添付する書類"

    def upload(path: Path):
        return pre(folder, CHROME + "file_upload", {"paths": [str(path)], "ref": "ref_694", "tabId": 5})

    other = attach / "登記の写し.pdf"
    other.write_bytes(b"%PDF-1.4 other")
    assert "入力シートの添付の欄" in denied(upload(other))
    # 原本の場所を書いた値：拡張子だけ違う写し（JPEG の原本を PDF にした写し）は当たる
    photo = attach / "2026-10-23_納税証明書（その2）.pdf"
    photo.write_bytes(b"%PDF-1.4 tax")
    write_sheet(stage, {"見積書": "原本/決算・税/2026-10-23_納税証明書（その2）.jpg"})
    passed(upload(photo))
    assert "入力シートの添付の欄" in denied(upload(attach / "見積書の写し.pdf"))
    # 書類の台帳で、写しの元の原本の場所を書いた値（名前を変えた写し）
    ledger = {"写し": [{"場所": f"案件/{CASE}/1_申請/添付する書類/登記の写し.pdf",
                       "元の原本": [{"場所": "原本/登記・名簿/2026-10-22_履歴事項全部証明書.pdf"}]}]}
    (folder / "記録" / "書類の台帳.json").write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    write_sheet(stage, {"見積書": "原本/登記・名簿/2026-10-22_履歴事項全部証明書.pdf"})
    passed(upload(other))
    # 「該当なし」と空の値は、何にも当たらない
    write_sheet(stage, {"見積書": "該当なし"})
    assert "入力シートの添付の欄" in denied(upload(other))
    # 担当者が入れる欄とされた添付の値は使わない
    scheme = json.loads(json.dumps(SCHEME))
    for field in scheme["申請画面"]["画面"][0]["欄"]:
        if field["名前"] == "見積書":
            field["担当者が入れる"] = True
    blob = input_sheet.build(scheme)
    (stage / "申請書" / input_sheet.FILE_NAME).write_bytes(blob)
    assert "入力シート" in denied(upload(other))
    # 入力シートがない・読めないときは添付しない
    (stage / "申請書" / input_sheet.FILE_NAME).write_bytes(b"x")
    assert "読めない" in denied(upload(other))
    (stage / "申請書" / input_sheet.FILE_NAME).unlink()
    assert "入力シート" in denied(upload(other))


# ---- 選ぶ欄の4つの語（DESIGN 14章「画面入力の守りの細部」、TASKS B29） ----

WORD_SCHEME = {
    "申請画面": {
        "流れ": {"値": "試し", "出典": [], "根拠の文": "", "状態": "確認済み"},
        "画面": [{
            "順番": 1, "名前": "確認事項入力",
            "欄": [
                {"名前": "決算期の確認", "種類": "ラジオ", "担当者が入れる": False},
                {"名前": "業種の確認", "種類": "選択", "担当者が入れる": False},
                {"名前": "申請内容の確認", "種類": "ラジオ", "担当者が入れる": True},
                {"名前": "加点の確認", "種類": "チェック", "担当者が入れる": False},
            ],
            "押してよいボタン": ["次へ"],
        }],
    }
}
WORD_PAGE = (
    'form [ref_1]\n'
    ' label [ref_2]\n  radio "はい" [ref_3] type="radio"\n  generic "決算期の確認：はい" [ref_4]\n'
    ' label [ref_5]\n  radio "はい" [ref_6] type="radio"\n  generic "申請内容の確認：はい" [ref_7]\n'
    ' label [ref_8]\n  checkbox "on" [ref_9] type="checkbox"\n  generic "加点の確認：該当する" [ref_10]\n'
    ' label [ref_11]\n  generic "業種の確認" [ref_12]\n  combobox "--選択してください--" [ref_13]\n'
    ' label [ref_14]\n  radio "はい" [ref_15] type="radio"\n  generic "誓約の有無：はい" [ref_16]\n'
    '\nTab Context:\n- Executed on tabId: tab-1\n'
)


@pytest.fixture
def word_folder(tmp_path) -> Path:
    company = tmp_path / "語の会社"
    (company / ".hojokin").mkdir(parents=True)
    (company / "記録" / "制度データ").mkdir(parents=True)
    (company / "記録" / "制度データ" / "持続化_第20回.json").write_text(json.dumps(WORD_SCHEME, ensure_ascii=False),
                                                               encoding="utf-8")
    write_sheet(company / "案件" / "2026_持続化（通常枠）第20回" / "1_申請", {}, WORD_SCHEME)
    permit(company)
    return company


@pytest.mark.parametrize("prefix", [BUILTIN, CHROME])
def test_choice_fields_with_the_four_words(word_folder, prefix) -> None:
    """4つの語で拒むのはチェック欄だけ。ラジオボタンと選択欄は、入力シートでツールの欄とされ、制度データの欄の名前に
    当たれば、4つの語を含んでいても通す（持続化の「決算期の確認」など）。"""
    folder = word_folder
    tab = {"tabId": "tab-1"} if prefix == CHROME else {}
    read = {"tabId": "tab-1", "filter": "all"} if prefix == CHROME else {"filter": "all"}

    def fill(ref, value=True):
        return pre(folder, prefix + "form_input", {"ref": ref, "value": value, **tab})

    post(folder, prefix + "read_page", read, WORD_PAGE)
    passed(fill("ref_3"))                       # ラジオボタン「決算期の確認：はい」
    passed(fill("ref_13", "食料品製造業"))        # 選択欄「業種の確認」
    for ref in ("ref_3", "ref_4"):              # 欄・ラベルの中の文字のクリック
        post(folder, prefix + "read_page", read, WORD_PAGE)
        passed(pre(folder, prefix + "computer", click(ref, **tab)))
    post(folder, prefix + "read_page", read, WORD_PAGE)
    # チェック欄は、制度データでツールの欄とされていても、4つの語を含めば拒む
    reason = denied(fill("ref_9"))
    assert "「確認」" in reason and "担当者" in reason
    # 担当者が入れるラジオボタンと、制度データにないラジオボタンは拒む
    assert "ツールが入れる欄とされていません" in denied(fill("ref_6"))
    assert "ツールが入れる欄とされていません" in denied(fill("ref_15"))


def test_choice_with_words_needs_the_input_sheet(word_folder) -> None:
    """4つの語を含むラジオボタン・選択欄は、入力シートでもツールの欄とされているときだけ通す。"""
    folder = word_folder
    stage = folder / "案件" / "2026_持続化（通常枠）第20回" / "1_申請"
    # 入力シートを作った後に制度データが変わり、入力シートでは担当者が入れる欄とされている
    person = json.loads(json.dumps(WORD_SCHEME))
    person["申請画面"]["画面"][0]["欄"][0]["担当者が入れる"] = True
    write_sheet(stage, {}, person)
    post(folder, BUILTIN + "read_page", {"filter": "all"}, WORD_PAGE)
    assert "入力シート" in denied(pre(folder, BUILTIN + "form_input", {"ref": "ref_3", "value": True}))
    passed(pre(folder, BUILTIN + "form_input", {"ref": "ref_13", "value": "食料品製造業"}))
    # 入力シートがないときも、4つの語を含む選ぶ欄には入れない（含まない欄は、今までどおり制度データで見る）
    (stage / "申請書" / input_sheet.FILE_NAME).unlink()
    assert "入力シート" in denied(pre(folder, BUILTIN + "form_input", {"ref": "ref_13", "value": "食料品製造業"}))


def test_file_fields_are_not_clicked_or_typed(folder) -> None:
    """内蔵ブラウザでは添付できない（実験 E1）。添付の欄へのクリックと入力は拒み、担当者に頼むよう伝える。"""
    permit(folder)
    replay(folder, 4)
    assert "担当者" in denied(replay(folder, 59))
    assert "担当者" in denied(replay(folder, 63))


# ---- 記録した呼び出しを順に流す（実験 E1） ----

def test_e1_builtin_flow_with_permission(folder) -> None:
    permit(folder)
    results = {}
    for row in (1, 2, 3, 4, 5, 7, 9, 11, 15, 16, 17, 18, 19, 20):
        results[row] = replay(folder, row)
    for row in (1, 3, 5, 9, 11, 15, 16, 18):
        passed(results[row])
    denied(results[7])   # 名前の空の選択欄
    denied(results[20])  # ダブルクリック
    # 画面2：送信するは押さず、宣誓の欄は入れず、加点の欄は入れる
    denied(pre(folder, BUILTIN + "computer", click("ref_16")))
    denied(pre(folder, BUILTIN + "form_input", {"ref": "ref_11", "value": True}))
    passed(pre(folder, BUILTIN + "form_input", {"ref": "ref_9", "value": True}))
    passed(pre(folder, BUILTIN + "computer", click("ref_15")))


def test_e1_builtin_flow_without_permission(folder) -> None:
    for row in (1, 3, 4):
        passed(replay(folder, row))
    for row in (5, 9, 11, 16):
        assert "/hojokin:nyuryoku" in denied(replay(folder, row))


def test_e1_click_without_reading_new_page_is_denied(folder) -> None:
    """次へを押した後、画面2を読まずに画面1の番号で押すことはできない（番号は画面ごとに振り直される）。"""
    permit(folder)
    for row in (4, 16, 17):
        replay(folder, row)
    denied(pre(folder, BUILTIN + "computer", click("ref_30")))


def test_e1_chrome_flow(folder) -> None:
    permit(folder)
    passed(replay(folder, 40))
    replay(folder, 41)
    # E1 では会社のフォルダの直下のファイルを添付した。守りは、添付する書類の写しのほかは拒む
    assert "添付する書類" in denied(replay(folder, 42))
    copy = folder / "案件" / "2026_省力化（一般型）第8回" / "1_申請" / "添付する書類" / "見積書の写し.pdf"
    passed(pre(folder, CHROME + "file_upload", {"paths": [str(copy)], "ref": "ref_27", "tabId": 881448174}))
    passed(replay(folder, 46))  # 一時保存
    replay(folder, 47)
    denied(pre(folder, CHROME + "computer", click("ref_32", tabId=881448174)))  # 控えを捨てた


def test_e1_batch(folder) -> None:
    permit(folder)
    for row in (52, 53, 54, 55):
        replay(folder, row)
    denied(replay(folder, 56))  # 入力とダブルクリック
    passed(replay(folder, 57))  # 入力だけ
    replay(folder, 58)
    passed(replay(folder, 61))  # 画面の写し
    passed(replay(folder, 64))
    replay(folder, 65)          # 一部だけ読んだ結果で、控えが置き換わる
    denied(pre(folder, BUILTIN + "form_input", {"ref": "ref_6", "value": "x"}))


# ---- hooks.json から run.sh を通す（/usr/bin/python3） ----

def test_through_run_sh(folder, tmp_path) -> None:
    plugin = hr.copy_plugin(tmp_path / "plugin")
    home = tmp_path / "home"
    data = tmp_path / "plugin-data"
    home.mkdir()
    data.mkdir()
    path = hr.make_bin(tmp_path / "bin", "本物", tmp_path / "python-ran")

    def run(event: str, payload: dict) -> list:
        outputs = []
        commands = hr.hook_commands(event, payload.get("tool_name", ""))
        assert commands, (event, payload.get("tool_name"))
        for command in commands:
            r = hr.run(command, {**base(folder), "hook_event_name": event, **payload},
                       plugin=plugin, folder=folder, path=path, home=home, data=data)
            assert r.returncode == 0 and r.stderr == b"", r
            outputs.append(json.loads(r.stdout.decode("utf-8")) if r.stdout.strip() else None)
        return outputs

    page = [{"type": "text", "text": read_record("mock_shinsei.txt")}]
    # 許可の前：読むのは通り、クリックは拒む
    assert run("PreToolUse", {"tool_name": BUILTIN + "read_page", "tool_input": {}}) == [None]
    run("PostToolUse", {"tool_name": BUILTIN + "read_page", "tool_input": {}, "tool_response": page})
    (out,) = run("PreToolUse", {"tool_name": BUILTIN + "computer", "tool_input": click("ref_7")})
    assert "/hojokin:nyuryoku" in denied(out)
    # 許可の後
    assert run("UserPromptSubmit", {"prompt": "/hojokin:nyuryoku"}) == [None]
    (out,) = run("PreToolUse", {"tool_name": BUILTIN + "computer", "tool_input": click("ref_954")})
    assert "「提出」" in denied(out)
    (out,) = run("PreToolUse", {"tool_name": BUILTIN + "form_input", "tool_input": {"ref": "ref_29", "value": True}})
    assert "「宣誓」" in denied(out)
    assert run("PreToolUse", {"tool_name": BUILTIN + "form_input", "tool_input": {"ref": "ref_230", "value": True}}) == [None]
    assert run("PreToolUse", {"tool_name": BUILTIN + "computer", "tool_input": click("ref_7")}) == [None]
    run("PostToolUse", {"tool_name": BUILTIN + "computer", "tool_input": click("ref_7"), "tool_response": "ok"})
    (out,) = run("PreToolUse", {"tool_name": BUILTIN + "computer", "tool_input": click("ref_8")})
    assert "読み直" in denied(out)
    (out,) = run("PreToolUse", {"tool_name": "mcp__computer-use__left_click", "tool_input": {"coordinate": [1, 1]}})
    assert "computer use" in denied(out)
    (out,) = run("PreToolUse", {"tool_name": CHROME + "javascript_tool", "tool_input": {"text": "1"}})
    denied(out)
    # 添付：入力シートの添付の欄の写しは通り、ほかの写しは拒む（守りが lib/input_sheet.py を /usr/bin/python3 で読む。B29）
    run("PostToolUse", {"tool_name": CHROME + "read_page", "tool_input": {"tabId": 5}, "tool_response": page})
    copy = folder / "案件" / CASE / "1_申請" / "添付する書類" / "見積書の写し.pdf"
    upload = {"paths": [str(copy)], "ref": "ref_694", "tabId": 5}
    assert run("PreToolUse", {"tool_name": CHROME + "file_upload", "tool_input": upload}) == [None]
    other = copy.with_name("ほかの写し.pdf")
    other.write_bytes(b"%PDF-1.4 other")
    (out,) = run("PreToolUse", {"tool_name": CHROME + "file_upload", "tool_input": {**upload, "paths": [str(other)]}})
    assert "入力シートの添付の欄" in denied(out)
    # 許可と控えは .hojokin/一時/ の下だけに書き、プラグインのフォルダには書かない
    state = folder / ".hojokin" / "一時" / "画面入力" / SESSION
    assert sorted(p.name for p in state.iterdir()) == ["控え.json", "許可.json"]
    assert not list(plugin.rglob("__pycache__"))
    assert (tmp_path / "python-ran").exists()
