"""模擬の申請画面（D11a）の自己テスト。`uv run pytest mock/test_server.py` で流す。

tests/ の外に置いているので、開発用の Stop hook の速いテストには入らない。
"""

from __future__ import annotations

import json
import re
import sys
import threading
import urllib.error
import urllib.request
import uuid
from html.parser import HTMLParser
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import calc  # noqa: E402
import screen  # noqa: E402
import server  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SAMPLE_PDF = REPO / "testdata" / "デモの会社" / "書類" / "履歴事項全部証明書.pdf"
SECRET = "pw-should-never-be-recorded-7319"


class FormParser(HTMLParser):
    """欄とボタンと、それを囲むラベルの文字を集める。"""

    def __init__(self):
        super().__init__()
        self.controls, self.buttons, self.label_stack = [], [], []
        self.button = None
        self.title, self.in_title = "", False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "label":
            self.label_stack.append({"text": "", "controls": []})
        elif tag in ("input", "select", "textarea"):
            control = {"tag": tag, **a, "label": None}
            self.controls.append(control)
            if self.label_stack:
                self.label_stack[-1]["controls"].append(control)
        elif tag == "button":
            self.button = {**a, "text": ""}
        elif tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == "label" and self.label_stack:
            label = self.label_stack.pop()
            for control in label["controls"]:
                control["label"] = label["text"].strip()
        elif tag == "button" and self.button is not None:
            self.buttons.append(self.button)
            self.button = None
        elif tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.label_stack:
            self.label_stack[-1]["text"] += data
        if self.button is not None:
            self.button["text"] += data
        if self.in_title:
            self.title += data


def parse(html_text: str) -> FormParser:
    parser = FormParser()
    # 選択肢の文字はラベルの名前に入れないので、select の中を先に消してから読む
    parser.feed(re.sub(r"(<select[^>]*>).*?(</select>)", r"\1\2", html_text, flags=re.S))
    return parser


def has_word(text: str) -> bool:
    return any(w in text for w in screen.PERSON_WORDS)


@pytest.fixture()
def running(tmp_path):
    srv = server.make_server(0, tmp_path / "記録", reset=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", tmp_path / "記録"
    srv.shutdown()
    srv.server_close()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request(url, data=None, headers=None, cookie=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    if cookie:
        req.add_header("Cookie", cookie)
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req) as res:
            return res.status, dict(res.headers), res.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers), err.read().decode("utf-8")


def login(base):
    body = f"account_id=tanto%40example.test&password={SECRET}&button=login".encode()
    status, headers, _ = request(base + "/login", body, {"Content-Type": "application/x-www-form-urlencoded"})
    assert status == 303 and headers["Location"] == "/shinsei"
    return headers["Set-Cookie"].split(";")[0]


def multipart(fields: dict, files: dict = None):
    """ブラウザと同じく、日本語のファイル名を UTF-8 のまま入れた multipart を作る。"""
    boundary = uuid.uuid4().hex
    out = b""
    for name, values in fields.items():
        for value in values if isinstance(values, list) else [values]:
            out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n").encode()
            out += value.encode("utf-8") + b"\r\n"
    for name, (filename, data) in (files or {}).items():
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
                "Content-Type: application/octet-stream\r\n\r\n").encode("utf-8") + data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return out, {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def read_log(record_dir: Path, with_start: bool = False) -> list:
    log = [json.loads(x) for x in (record_dir / server.LOG_FILE).read_text(encoding="utf-8").splitlines()]
    return log if with_start else [x for x in log if x["event"] != "server_start"]


# ---- 画面の定義 ----

def test_field_ids_are_unique():
    ids = [f["id"] for f in screen.all_fields()] + [f["id"] for f in screen.LOGIN_FIELDS]
    assert len(ids) == len(set(ids))


def test_person_and_tool_names():
    """担当者が入れる欄の名前には4語のどれかがあり、ツールが入れる欄の名前には4語がない（DESIGN 5章）。"""
    for field in screen.all_fields():
        if field["kind"] not in ("checkbox", "checkboxes", "radio", "select"):
            continue
        names = [field["label"]]
        if field["kind"] == "radio":
            names = [f"{field['label']}：{opt}" for opt in field["options"]]
        if field["kind"] == "checkboxes":
            names = field["options"]
        for name in names:
            if field["who"] == "person":
                assert has_word(name), name
            else:
                assert not has_word(name), name


def test_all_four_words_are_used():
    labels = " ".join(f["label"] for f in screen.all_fields() if f["who"] == "person")
    for word in screen.PERSON_WORDS:
        assert word in labels, word


def test_sections_follow_manual_order():
    assert [s["no"] for s in screen.SECTIONS] == list("❶❷❸❹❺❻❼❽❾❿⓫⓬")
    titles = [s["title"] for s in screen.SECTIONS]
    assert titles == ["宣誓・手引き", "基本情報", "要件", "加点項目", "事業計画名及び作成者情報", "最低賃金及び特例希望",
                      "事業計画数値", "経費明細｜資金調達内訳", "書類添付", "アンケート", "メールアドレス認証", "確認"]


# ---- 画面 ----

def test_login_page_has_password_and_banner(running):
    base, _ = running
    status, _, text = request(base + "/login")
    page = parse(text)
    assert status == 200
    assert "模擬画面" in page.title and server.BANNER in text
    assert [c for c in page.controls if c.get("type") == "password" and c["label"] == "パスワード"]
    assert [b for b in page.buttons if b["text"] == "ログイン"]


def test_shinsei_needs_login(running):
    base, _ = running
    status, headers, _ = request(base + "/shinsei")
    assert status == 303 and headers["Location"] == "/login"


def test_shinsei_has_required_parts(running):
    """D11a の行の「必ず置く」もの。チェック欄・ラジオボタン・選択欄は囲むラベルで名前が付く。"""
    base, _ = running
    cookie = login(base)
    status, _, text = request(base + "/shinsei", cookie=cookie)
    page = parse(text)
    assert status == 200 and "模擬画面" in page.title and server.BANNER in text
    assert "maxlength" not in text

    button_texts = [b["text"] for b in page.buttons]
    for label in ("戻る", "一時保存", "次へ", "計算", "認証コード発行", "提出"):
        assert label in button_texts, label
    assert button_texts.count("提出") == 1

    for control in page.controls:
        if control["tag"] == "select" or control.get("type") in ("checkbox", "radio"):
            assert control["label"], f"囲むラベルがない：{control.get('name')}"
    by_name = {}
    for control in page.controls:
        by_name.setdefault(control.get("name"), []).append(control)
    checkbox_labels = [c["label"] for c in page.controls if c.get("type") == "checkbox"]
    assert any("宣誓" in x for x in checkbox_labels)
    assert any("同意" in x for x in checkbox_labels)
    assert any("誓約" in x for x in checkbox_labels)
    assert any("確認" in x for x in checkbox_labels)
    assert any(x.startswith("省力化ナビ加点") for x in checkbox_labels)
    assert [c["label"] for c in by_name["other_subsidy"]] == ["国の他の助成制度との重複：はい", "国の他の助成制度との重複：いいえ"]
    assert by_name["org_type"][0]["label"] == "組織形態"
    files = [c for c in page.controls if c.get("type") == "file"]
    assert len(files) == len([f for f in screen.all_fields() if f["kind"] == "file"])
    assert all(c["label"] for c in files)


# ---- 記録 ----

def test_save_records_values_files_and_button(running):
    base, record_dir = running
    cookie = login(base)
    body, headers = multipart(
        {"button": "save", "biz_name": "株式会社やまぶき惣菜", "employees": "15", "kasan_navi": "on",
         "other_subsidy": "いいえ", "survey_issues": ["設備投資計画", "IT化・DX"],
         "org_type": "1-1.中小企業者（組合関連以外）"},
        {"doc_registry": ("履歴事項全部証明書.pdf", SAMPLE_PDF.read_bytes())})
    status, _, text = request(base + "/shinsei", body, headers, cookie)
    assert status == 200
    assert "添付済み：履歴事項全部証明書.pdf" in text
    assert 'value="株式会社やまぶき惣菜"' in text

    state = json.loads((record_dir / server.STATE_FILE).read_text(encoding="utf-8"))
    assert state["fields"]["biz_name"]["value"] == "株式会社やまぶき惣菜"
    assert state["fields"]["kasan_navi"]["value"] is True
    assert state["fields"]["oath_1"]["value"] is False
    assert state["fields"]["survey_issues"]["value"] == ["設備投資計画", "IT化・DX"]
    assert state["files"]["doc_registry"]["filename"] == "履歴事項全部証明書.pdf"
    saved = record_dir / state["files"]["doc_registry"]["path"]
    assert saved.read_bytes() == SAMPLE_PDF.read_bytes()
    assert state["submit_pressed"] is False

    entry = read_log(record_dir)[-1]
    assert entry["button"] == "save" and entry["button_label"] == "一時保存" and entry["saved"] is True
    assert entry["fields"]["not_same_corp"] is False  # チェックしていない欄も False で残る
    assert entry["uploads"][0]["accepted"] is True


def test_textarea_newlines_become_lf(running):
    """ブラウザは複数行の欄の改行を CRLF で送る。記録は入力シートと同じ LF にそろえる。"""
    base, record_dir = running
    cookie = login(base)
    request(base + "/shinsei", *multipart({"button": "save", "plan_summary": "一行目\r\n二行目"}), cookie)
    state = json.loads((record_dir / server.STATE_FILE).read_text(encoding="utf-8"))
    assert state["fields"]["plan_summary"]["value"] == "一行目\n二行目"


def test_state_tells_tables_apart(running):
    """❽ 8-3 の2つの表は、項目名が同じ欄があるので、表の名前も残す。"""
    base, record_dir = running
    cookie = login(base)
    request(base + "/shinsei", *multipart({"button": "save", "fund_all_own_amount": "100", "fund_d_own_amount": "50"}),
            cookie)
    fields = json.loads((record_dir / server.STATE_FILE).read_text(encoding="utf-8"))["fields"]
    a, d = fields["fund_all_own_amount"], fields["fund_d_own_amount"]
    assert a["label"] == d["label"] and a["section"] == d["section"]
    assert a["table"] == "事業全体に要する経費調達一覧" and d["table"] == "補助金申請額（D）の経費内訳"
    assert fields["biz_name"]["group"] == "2-1. 事業者情報"


def test_server_start_marks_a_run(tmp_path):
    record_dir = tmp_path / "記録"
    store = server.Store(record_dir, reset=True)
    store.handle_button("submit", {}, [])
    server.Store(record_dir)
    starts = [x for x in read_log(record_dir, with_start=True) if x["event"] == "server_start"]
    assert [x["submit_pressed_before"] for x in starts] == [False, True]


def test_link_click_is_recorded(running):
    base, record_dir = running
    request(base + "/log", json.dumps({"event": "click", "link": "#s2", "label": "修正", "page": "/shinsei"}).encode())
    entry = read_log(record_dir)[-1]
    assert entry["link"] == "#s2" and entry["link_label"] == "修正"


def test_back_does_not_save(running):
    base, record_dir = running
    cookie = login(base)
    request(base + "/shinsei", *multipart({"button": "save", "biz_name": "保存する名前"}), cookie)
    request(base + "/shinsei", *multipart({"button": "back", "biz_name": "保存しない名前"}), cookie)
    state = json.loads((record_dir / server.STATE_FILE).read_text(encoding="utf-8"))
    assert state["fields"]["biz_name"]["value"] == "保存する名前"
    entry = read_log(record_dir)[-1]
    assert entry["button"] == "back" and entry["saved"] is False and entry["fields"]["biz_name"] == "保存しない名前"


def test_wrong_file_type_is_rejected(running):
    base, record_dir = running
    cookie = login(base)
    body, headers = multipart({"button": "save"}, {"doc_officers": ("役員名簿.pdf", b"%PDF-1.4")})
    _, _, text = request(base + "/shinsei", body, headers, cookie)
    assert "添付できませんでした" in text
    state = json.loads((record_dir / server.STATE_FILE).read_text(encoding="utf-8"))
    assert "doc_officers" not in state["files"]
    assert read_log(record_dir)[-1]["uploads"][0]["accepted"] is False


def test_submit_is_recorded(running):
    base, record_dir = running
    cookie = login(base)
    _, _, text = request(base + "/shinsei", *multipart({"button": "submit"}), cookie)
    assert "どこにも送っていません" in text
    state = json.loads((record_dir / server.STATE_FILE).read_text(encoding="utf-8"))
    assert state["submit_pressed"] is True and len(state["submit_times"]) == 1
    entry = read_log(record_dir)[-1]
    assert entry["button"] == "submit" and entry["button_label"] == "提出" and entry["submit_pressed"] is True


def test_password_value_is_never_recorded(running):
    base, record_dir = running
    login(base)
    request(base + "/log", json.dumps({"event": "change", "name": "password", "type": "password",
                                      "value": SECRET, "entered": True}).encode())
    request(base + "/log", json.dumps({"event": "change", "name": "oath_1", "type": "checkbox",
                                      "value": "on", "checked": True, "page": "/shinsei"}).encode())
    log = read_log(record_dir)
    assert log[0]["event"] == "login" and log[0]["password_entered"] is True
    assert log[1] == {**log[1], "field": "password", "entered": True} and "value" not in log[1]
    assert log[2]["label"].startswith("宣誓事項1") and log[2]["checked"] is True
    for path in record_dir.rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text(encoding="utf-8", errors="ignore")


def test_state_survives_restart(tmp_path):
    record_dir = tmp_path / "記録"
    store = server.Store(record_dir, reset=True)
    store.handle_button("save", {"biz_name": ["再起動の後も残る"], "kasan_bcp": ["on"]}, [])
    again = server.Store(record_dir)
    assert again.state["values"]["biz_name"] == "再起動の後も残る"
    assert again.state["values"]["kasan_bcp"] is True


def test_non_local_host_is_refused(tmp_path):
    with pytest.raises(ValueError):
        server.make_server(0, tmp_path / "記録", host="0.0.0.0")


# ---- 計算（マニュアル p.17 の例の数字で確かめる） ----

def test_plan_calculation_matches_manual_example():
    values = {"plan_sales_y0": "100000000", "plan_cogs_y0": "60000000", "plan_sga_y0": "30000000",
              "plan_personnel_y0": "18000000", "plan_dep_existing_y0": "3000000",
              "plan_officers_y0": "2", "plan_employees_y0": "8",
              "plan_sales_y1": "104000000", "plan_cogs_y1": "62000000", "plan_sga_y1": "31000000",
              "plan_personnel_y1": "18500000", "plan_dep_existing_y1": "3100000", "plan_dep_new_y1": "1000000",
              "plan_officers_y1": "2", "plan_employees_y1": "8"}
    out = calc.compute(values)
    assert out["plan_value_added_y0"] == "31,000,000"
    assert out["plan_value_added_y1"] == "33,600,000"
    assert out["plan_productivity_y0"] == "3,100,000.00"
    assert out["plan_productivity_target_y1"] == "3,224,000.00"
    assert out["plan_va_growth_y1"] == "8.39"


def test_subsidy_amount_rate():
    values = {"expense_machine_b": "22500000"}
    assert calc.compute(values)["subsidy_amount"] == "11,250,000"
    assert calc.compute({**values, "small_business": True})["subsidy_amount"] == "15,000,000"
