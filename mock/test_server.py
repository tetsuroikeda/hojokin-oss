"""模擬の申請画面（D11a の1画面版、D11b の12画面版、D11c の持続化の13画面）の自己テスト。

`uv run pytest mock/test_server.py` で流す。

tests/ の外に置いているので、開発用の Stop hook の速いテストには入らない。
"""

from __future__ import annotations

import json
import re
import sys
import threading
from collections import Counter
import urllib.error
import urllib.request
import uuid
from html.parser import HTMLParser
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import calc  # noqa: E402
import calc_jizokuka  # noqa: E402
import screen  # noqa: E402
import screen_jizokuka as sj  # noqa: E402
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
        self.steps, self.current_steps, self.in_step = [], [], False
        self.h1, self.in_h1 = "", False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "li":
            self.in_step = True
            self.steps.append("")
            if a.get("aria-current") == "step":
                self.current_steps.append(len(self.steps) - 1)
        elif tag == "h1":
            self.in_h1 = True
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
        elif tag == "li":
            self.in_step = False
        elif tag == "h1":
            self.in_h1 = False

    def handle_data(self, data):
        if self.in_step:
            self.steps[-1] += data
        if self.in_h1:
            self.h1 += data
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


# ---- 12画面版（D11b） ----

# 画面ごとのボタン（マニュアルの各画面の絵）。上と下に置くボタンは、ここでは1回ずつ書く
NAV = ["戻る", "次へ"]
NAV_SAVE = ["戻る", "一時保存", "次へ"]
EXPECTED_BUTTONS = {
    1: NAV, 2: NAV_SAVE + ["認証コード発行"], 3: NAV_SAVE, 4: NAV_SAVE, 5: NAV_SAVE, 6: NAV_SAVE,
    7: NAV_SAVE + ["計算"], 8: NAV_SAVE + ["計算"], 9: NAV_SAVE, 10: NAV, 11: NAV + ["基本情報画面へ"],
    12: ["修正"] * 11 + ["提出"],
}
# 押さないボタンの語（DESIGN 5章）。「提出」のほかのボタンの名前には入れない
STOP_WORDS = ("提出", "送信", "申請する", "確定", "完了")


@pytest.fixture()
def running_screens(tmp_path):
    srv = server.make_server(0, tmp_path / "記録", reset=True, screens=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", tmp_path / "記録"
    srv.shutdown()
    srv.server_close()


def login_screens(base):
    body = "account_id=tanto%40example.test&password=x&button=login".encode()
    status, headers, _ = request(base + "/login", body, {"Content-Type": "application/x-www-form-urlencoded"})
    assert status == 303 and headers["Location"] == "/shinsei/1"
    return headers["Set-Cookie"].split(";")[0]


def post_screen(base, n, cookie, fields, files=None):
    return request(f"{base}/shinsei/{n}", *multipart(fields, files), cookie)


def read_state(record_dir):
    return json.loads((record_dir / server.STATE_FILE).read_text(encoding="utf-8"))


def test_screens_split_all_fields_in_manual_order():
    """12画面に、すべての欄が1回ずつ、画面の順に入っている。"""
    assert screen.SCREEN_COUNT == 12
    ids = [f["id"] for n in range(1, 13) for f in screen.screen_fields(n)]
    assert ids == [f["id"] for f in screen.all_fields()]
    for n in range(1, 13):
        section = screen.SECTIONS[n - 1]
        assert all(f["section"] == f"{section['no']} {section['title']}" for f in screen.screen_fields(n))


def test_screen_buttons_follow_manual():
    """❶・❿・⓫ に一時保存がなく、⓬ は修正と提出だけ。提出は ⓬ にしかない。"""
    for n, labels in EXPECTED_BUTTONS.items():
        assert [label for _v, label, _p, _w in screen.screen_buttons(n)] == labels, n
    for n in range(1, 13):
        for value, label, _p, _w in screen.screen_buttons(n):
            if value != "submit":
                assert not any(w in label for w in STOP_WORDS), label
            assert screen.button_label(value) == label


def test_default_login_still_goes_to_one_page(running):
    """--screens を付けないときは、D11a のとおりログインの後に1画面版へ入る。"""
    base, _ = running
    login(base)  # Location が /shinsei であることを確かめる


def test_screens_login_goes_to_first_screen(running_screens):
    base, record_dir = running_screens
    cookie = login_screens(base)
    status, headers, _ = request(base + "/", cookie=cookie)
    assert status == 303 and headers["Location"] == "/shinsei/1"
    start = read_log(record_dir, with_start=True)[0]
    assert start["event"] == "server_start" and start["start_url"] == "/shinsei/1"


def test_each_screen_has_its_fields_and_buttons(running_screens):
    """どの画面も、その画面の欄と、マニュアルのとおりのボタンだけを出す。"""
    base, _ = running_screens
    cookie = login_screens(base)
    for n in range(1, 13):
        section = screen.SECTIONS[n - 1]
        status, _, text = request(f"{base}/shinsei/{n}", cookie=cookie)
        page = parse(text)
        assert status == 200
        assert "模擬画面" in page.title and section["title"] in page.title and server.BANNER in text
        assert page.h1 == f"{section['no']} {section['title']}"
        assert "maxlength" not in text
        # 進み具合は12個で、今の画面にだけ印がある（リンクにはしない）
        assert page.steps == [f"{s['no']} {s['title']}" for s in screen.SECTIONS]
        assert page.current_steps == [n - 1]
        steps_html = re.search(r'<ol class="steps">(.*?)</ol>', text, flags=re.S).group(1)
        assert "<a " not in steps_html and "<button" not in steps_html
        # 欄は、その画面の欄だけ
        names = {c.get("name") for c in page.controls}
        assert names == {f["id"] for f in screen.screen_fields(n)}, n
        for control in page.controls:
            if control["tag"] == "select" or control.get("type") in ("checkbox", "radio", "file"):
                assert control["label"], f"囲むラベルがない：{control.get('name')}"
        # ボタン：上と下のボタンは2回ずつ、ほかは1回ずつ
        nav_labels = {label for v, label, _p in screen.NAV_BUTTONS if v in section["nav"]}
        expected = Counter({label: (2 if label in nav_labels else 1) for label in EXPECTED_BUTTONS[n]})
        if n == 12:
            expected = Counter({"修正": 11, "提出": 1})
        assert Counter(b["text"] for b in page.buttons) == expected, n
        assert ("提出" in [b["text"] for b in page.buttons]) == (n == 12)


def test_person_fields_on_screens_keep_the_words(running_screens):
    """担当者が入れる欄は、画面に出たときも、囲むラベルの名前に4語のどれかが入る（DESIGN 5章）。"""
    base, _ = running_screens
    cookie = login_screens(base)
    person = {f["id"] for f in screen.all_fields() if f["who"] == "person"}
    seen = set()
    for n in range(1, 13):
        page = parse(request(f"{base}/shinsei/{n}", cookie=cookie)[2])
        for control in page.controls:
            if control.get("type") in ("checkbox", "radio") or control["tag"] == "select":
                if control.get("name") in person:
                    seen.add(control["name"])
                    assert has_word(control["label"]), control["label"]
                else:
                    assert not has_word(control["label"]), control["label"]
    assert seen == person


def test_next_saves_only_that_screen_and_moves_on(running_screens):
    """次へは、その画面の欄だけを保存して次の画面へ移る。ほかの画面の値は消さない。"""
    base, record_dir = running_screens
    cookie = login_screens(base)
    status, headers, _ = post_screen(base, 2, cookie, {"button": "save", "biz_name": "株式会社やまぶき惣菜",
                                                       "employees": "15"})
    assert status == 303 and headers["Location"] == "/shinsei/2"
    status, headers, _ = post_screen(base, 3, cookie, {"button": "next", "small_business": "on",
                                                       "other_subsidy": "いいえ"})
    assert status == 303 and headers["Location"] == "/shinsei/4"
    fields = read_state(record_dir)["fields"]
    assert fields["biz_name"]["value"] == "株式会社やまぶき惣菜" and fields["employees"]["value"] == "15"
    assert fields["small_business"]["value"] is True and fields["other_subsidy"]["value"] == "いいえ"
    assert fields["oath_1"]["value"] is False and fields["not_same_corp"]["value"] is False
    entry = read_log(record_dir)[-1]
    assert entry["page"] == "shinsei/3" and entry["screen"] == "❸ 要件"
    assert entry["button"] == "next" and entry["button_label"] == "次へ" and entry["saved"] is True
    # 記録の fields は、1画面版と同じく、すべての欄の値
    assert set(entry["fields"]) == set(server.empty_values())
    assert entry["fields"]["biz_name"] == "株式会社やまぶき惣菜" and entry["fields"]["small_business"] is True
    # 知らせは、移った先の画面に1回だけ出る
    text = request(base + "/shinsei/4", cookie=cookie)[2]
    assert "前の画面で「次へ」を押しました" in text
    assert "前の画面で「次へ」を押しました" not in request(base + "/shinsei/4", cookie=cookie)[2]
    # 保存した値は、ほかの画面にも、1画面版にも出る
    assert 'value="株式会社やまぶき惣菜"' in request(base + "/shinsei/2", cookie=cookie)[2]
    assert 'value="株式会社やまぶき惣菜"' in request(base + "/shinsei", cookie=cookie)[2]


def test_back_does_not_save_and_moves_back(running_screens):
    base, record_dir = running_screens
    cookie = login_screens(base)
    status, headers, _ = post_screen(base, 3, cookie, {"button": "back", "small_business": "on"})
    assert status == 303 and headers["Location"] == "/shinsei/2"
    assert not (record_dir / server.STATE_FILE).exists() or read_state(record_dir)["fields"]["small_business"]["value"] is False
    entry = read_log(record_dir)[-1]
    assert entry["button"] == "back" and entry["saved"] is False and entry["fields"]["small_business"] is True
    # ❶ より前の画面はないので、❶ のまま
    status, headers, _ = post_screen(base, 1, cookie, {"button": "back"})
    assert status == 303 and headers["Location"] == "/shinsei/1"
    assert "マイページ" in request(base + "/shinsei/1", cookie=cookie)[2]


def test_fix_goto_and_last_next_move_between_screens(running_screens):
    base, record_dir = running_screens
    cookie = login_screens(base)
    for k in range(1, 12):
        status, headers, _ = post_screen(base, 12, cookie, {"button": f"fix_{k}"})
        assert status == 303 and headers["Location"] == f"/shinsei/{k}"
    assert read_log(record_dir)[-1]["button_label"] == "修正"
    status, headers, _ = post_screen(base, 11, cookie, {"button": "goto_2"})
    assert status == 303 and headers["Location"] == "/shinsei/2"
    status, headers, _ = post_screen(base, 11, cookie, {"button": "next", "auth_code": "123456"})
    assert status == 303 and headers["Location"] == "/shinsei/12"
    assert read_state(record_dir)["fields"]["auth_code"]["value"] == "123456"


def test_button_not_on_the_screen_is_recorded_only(running_screens):
    """その画面にないボタン（❸ に送られた「計算」など）は、記録だけして保存しない。"""
    base, record_dir = running_screens
    cookie = login_screens(base)
    status, headers, _ = post_screen(base, 3, cookie, {"button": "calc_plan", "small_business": "on"})
    assert status == 303 and headers["Location"] == "/shinsei/3"
    entry = read_log(record_dir)[-1]
    assert entry["button"] == "calc_plan" and entry["saved"] is False
    assert "この画面にないボタンです" in request(base + "/shinsei/3", cookie=cookie)[2]
    status, headers, _ = post_screen(base, 1, cookie, {"button": "save", "oath_1": "on"})
    assert headers["Location"] == "/shinsei/1"
    assert read_log(record_dir)[-1]["saved"] is False  # ❶ には一時保存がない


def test_attach_on_document_screen(running_screens):
    base, record_dir = running_screens
    cookie = login_screens(base)
    status, headers, _ = post_screen(base, 9, cookie, {"button": "next"},
                                     {"doc_registry": ("履歴事項全部証明書.pdf", SAMPLE_PDF.read_bytes())})
    assert status == 303 and headers["Location"] == "/shinsei/10"
    state = read_state(record_dir)
    assert state["files"]["doc_registry"]["filename"] == "履歴事項全部証明書.pdf"
    assert (record_dir / state["files"]["doc_registry"]["path"]).read_bytes() == SAMPLE_PDF.read_bytes()
    assert "添付済み：履歴事項全部証明書.pdf" in request(base + "/shinsei/9", cookie=cookie)[2]
    # 形式の合わないファイルがあると、次へを押しても ❾ のまま
    status, headers, _ = post_screen(base, 9, cookie, {"button": "next"}, {"doc_officers": ("役員名簿.pdf", b"%PDF-1.4")})
    assert status == 303 and headers["Location"] == "/shinsei/9"
    text = request(base + "/shinsei/9", cookie=cookie)[2]
    assert "添付できませんでした" in text and "この画面のままです" in text
    assert "doc_officers" not in read_state(record_dir)["files"]
    # ほかの画面に送られた添付は受け取らない
    post_screen(base, 3, cookie, {"button": "save"}, {"doc_tax": ("納税証明書.pdf", b"%PDF-1.4")})
    assert "doc_tax" not in read_state(record_dir)["files"]


def test_auth_code_screen(running_screens):
    base, _ = running_screens
    cookie = login_screens(base)
    status, headers, _ = post_screen(base, 2, cookie, {"button": "issue_code", "staff_email": "tanto@example.test"})
    assert status == 303 and headers["Location"] == "/shinsei/2"
    assert "模擬の認証コードは" in request(base + "/shinsei/2", cookie=cookie)[2]
    text = request(base + "/shinsei/11", cookie=cookie)[2]
    assert "tanto@example.test" in text and "発行した認証コードは" in text


def test_confirm_screen_and_submit(running_screens):
    base, record_dir = running_screens
    cookie = login_screens(base)
    post_screen(base, 2, cookie, {"button": "save", "biz_name": "株式会社やまぶき惣菜"})
    page = parse(request(base + "/shinsei/12", cookie=cookie)[2])
    assert [b["value"] for b in page.buttons if b["text"] == "修正"] == [f"fix_{k}" for k in range(1, 12)]
    assert "株式会社やまぶき惣菜" in request(base + "/shinsei/12", cookie=cookie)[2]
    assert read_state(record_dir)["submit_pressed"] is False
    status, _, text = post_screen(base, 12, cookie, {"button": "submit"})
    assert status == 200 and "どこにも送っていません" in text and 'href="/shinsei/12"' in text
    state = read_state(record_dir)
    assert state["submit_pressed"] is True and len(state["submit_times"]) == 1
    entry = read_log(record_dir)[-1]
    assert entry["page"] == "shinsei/12" and entry["screen"] == "⓬ 確認"
    assert entry["button_label"] == "提出" and entry["submit_pressed"] is True


def test_screen_pages_need_login_and_exist(running_screens):
    base, _ = running_screens
    status, headers, _ = request(base + "/shinsei/1")
    assert status == 303 and headers["Location"] == "/login"
    status, headers, _ = request(base + "/shinsei/1", *multipart({"button": "next"}))
    assert status == 303 and headers["Location"] == "/login"
    cookie = login_screens(base)
    for path in ("/shinsei/0", "/shinsei/13", "/shinsei/x"):
        assert request(base + path, cookie=cookie)[0] == 404


def test_client_events_on_screen_pages(running_screens):
    base, record_dir = running_screens
    request(base + "/log", json.dumps({"event": "change", "name": "kasan_navi", "type": "checkbox", "value": "on",
                                      "checked": True, "page": "/shinsei/4"}).encode())
    request(base + "/log", json.dumps({"event": "click", "button": "fix_3", "label": "修正",
                                      "page": "/shinsei/12"}).encode())
    change, click = read_log(record_dir)[-2:]
    assert change["page"] == "shinsei/4" and change["label"].startswith("省力化ナビ加点") and change["checked"] is True
    assert click["page"] == "shinsei/12" and click["button"] == "fix_3" and click["button_label"] == "修正"


def test_screen_list_names_every_screen_and_field():
    text = screen.markdown_screens()
    for n, s in enumerate(screen.SECTIONS, start=1):
        assert f"### {s['no']} {s['title']}（`/shinsei/{n}`、マニュアル p.{s['pages']}）" in text
    for field in screen.all_fields():
        assert field["id"] in text or field.get("grid") and f"{field['grid']}_<行>_<列>" in text


def test_readme_has_the_current_screen_list():
    """README の「画面ごとの欄とボタンの一覧」は、`python3 mock/screen.py` の今の出力と同じ。"""
    readme = (Path(__file__).resolve().parent / "README.md").read_text(encoding="utf-8")
    assert screen.markdown_screens() in readme


# ---- 持続化の13画面（D11c） ----

JIZOKUKA_TITLES = ["誓約事項", "申請情報入力", "基本情報入力", "応募者概要入力（様式２）", "確認事項入力（様式２）",
                   "希望する特例及び加点項目（様式２）", "賃金引上げ特例・賃金引上げ加点（様式７）", "経営計画入力（様式２）",
                   "補助事業計画入力（様式２）", "経費明細表・資金調達方法（様式３）", "様式添付", "宣誓・同意", "申請内容確認"]
# 手引き p.9 の「申請情報入力の流れ」の番号（画面7は 6 の続き、画面13は 12 と 13）
JIZOKUKA_STEPS = ["1", "2", "3", "4", "5", "6", "6", "7", "8", "9", "10", "11", "12・13"]
JIZOKUKA_NAV = ["戻る", "次へ"]
JIZOKUKA_BUTTONS = {
    1: ["申請を開始する"], 2: JIZOKUKA_NAV, 3: JIZOKUKA_NAV + ["Gビズから最新情報を取得する"], 4: JIZOKUKA_NAV,
    5: JIZOKUKA_NAV, 6: JIZOKUKA_NAV, 7: JIZOKUKA_NAV, 8: JIZOKUKA_NAV, 9: JIZOKUKA_NAV,
    10: JIZOKUKA_NAV + ["自動計算"], 11: JIZOKUKA_NAV, 12: ["戻る", "最終確認画面へ"], 13: ["修正"] * 10 + ["提出"],
}
SCREEN2_FULL = {"invoice_tokurei": "希望しない", "wage_tokurei": "希望しない", "end_date": "2028-03-31",
                "income": "②収入金無し", "support_org_type": "商工会議所", "support_org_name": "架空商工会議所",
                "member": "いいえ"}


@pytest.fixture()
def running_jizokuka(tmp_path):
    srv = server.make_server(0, tmp_path / "記録", reset=True, subsidy="jizokuka")
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", tmp_path / "記録"
    srv.shutdown()
    srv.server_close()


def login_jizokuka(base):
    body = f"account_id=tanto%40example.test&password={SECRET}&button=login".encode()
    status, headers, _ = request(base + "/login", body, {"Content-Type": "application/x-www-form-urlencoded"})
    assert status == 303 and headers["Location"] == "/junshu"
    return headers["Set-Cookie"].split(";")[0]


def post_page(base, path, cookie, fields, files=None):
    return request(base + path, *multipart(fields, files), cookie)


def choice_names(field: dict) -> list:
    """守りが見る名前（ラジオボタンは「問い：値」）。"""
    if field["kind"] == "radio":
        return [f"{field['label']}：{opt}" for opt in field["options"]]
    if field["kind"] == "checkboxes":
        return field["options"]
    return [field["label"]]


def test_jizokuka_screens_follow_tebiki_flow():
    """13画面が、手引き p.9 の流れの順に並ぶ。欄の id は1つずつで、画面の段の名前が付く。"""
    assert sj.SCREEN_COUNT == 13
    assert [s["title"] for s in sj.SECTIONS] == JIZOKUKA_TITLES
    assert [s["step"] for s in sj.SECTIONS] == JIZOKUKA_STEPS
    assert [s["no"] for s in sj.SECTIONS] == [f"画面{n}" for n in range(1, 14)]
    ids = [x["id"] for x in sj.all_fields()] + [x["id"] for x in sj.LOGIN_FIELDS] + [sj.JUNSHU_FIELD["id"]]
    assert len(ids) == len(set(ids))
    assert [x["id"] for n in range(1, 14) for x in sj.screen_fields(n)] == [x["id"] for x in sj.all_fields()]
    for n, s in enumerate(sj.SECTIONS, start=1):
        assert all(x["section"] == f"画面{n} {s['title']}" for x in sj.screen_fields(n))


def test_jizokuka_person_and_tool_names():
    """選ぶ欄の名前と4語（DESIGN 5章）。本物の項目名が4語の決まりに合わない欄は、一覧に挙げたものだけ。"""
    tool_with, person_without = set(), set()
    for field in sj.all_fields():
        if field["kind"] not in ("checkbox", "checkboxes", "radio", "select"):
            continue
        words = [has_word(name) for name in choice_names(field)]
        if field["who"] == "person" and not all(words):
            person_without.add(field["id"])
        if field["who"] == "tool" and any(words):
            tool_with.add(field["id"])
    assert tool_with == sj.TOOL_FIELDS_WITH_WORDS
    assert person_without == sj.PERSON_FIELDS_WITHOUT_WORDS
    person_labels = " ".join(x["label"] for x in sj.all_fields() if x["who"] == "person")
    for word in sj.PERSON_WORDS:
        assert word in person_labels, word
    # 確認・誓約・同意（宣誓を含む）のチェック欄は、どれも担当者が入れる欄（SPEC 2.3）
    for field in sj.all_fields() + [sj.JUNSHU_FIELD]:
        if field["kind"] == "checkbox" and has_word(field["label"]):
            assert field["who"] == "person", field["id"]


def test_jizokuka_limits_follow_tebiki():
    """文字数の上限：経営計画・補助事業計画の文の欄は4,000字、事業名は30文字（手引き p.41–42）。ほかの欄には付けない。"""
    limited = {x["id"]: x["limit"] for x in sj.all_fields() if x.get("limit")}
    assert limited["project_name"] == 30
    long_texts = [x for n in (8, 9) for x in sj.screen_fields(n) if x["kind"] == "textarea"]
    assert long_texts and all(limited[x["id"]] == 4000 for x in long_texts)
    assert set(limited) == {x["id"] for x in long_texts} | {"project_name"}


def test_jizokuka_screen_buttons_follow_tebiki():
    """画面ごとのボタン。提出は画面13にしかなく、ほかのボタンの名前に押さないボタンの語を入れない。"""
    for n, labels in JIZOKUKA_BUTTONS.items():
        assert [label for _v, label, _p, _w in sj.screen_buttons(n)] == labels, n
    for _v, label, _p, _w in sj.all_buttons():
        if label != "提出":
            assert not any(w in label for w in STOP_WORDS), label
        assert sj.button_label(_v) == label
    assert [v for v, label, _p, _w in sj.all_buttons() if label == "提出"] == ["submit"]
    assert {"submit", "start", "to_confirm", "agree_start", "login"} == sj.PERSON_BUTTONS


def test_jizokuka_each_screen_has_its_fields_and_buttons(running_jizokuka):
    base, _ = running_jizokuka
    cookie = login_jizokuka(base)
    for n, s in enumerate(sj.SECTIONS, start=1):
        status, _, text = request(f"{base}/shinsei/{n}", cookie=cookie)
        page = parse(text)
        assert status == 200
        assert "模擬画面" in page.title and s["title"] in page.title and server.BANNER in text
        assert page.h1 == s["title"]
        assert {c.get("name") for c in page.controls} == {x["id"] for x in sj.screen_fields(n)}, n
        for control in page.controls:
            if control["tag"] == "select" or control.get("type") in ("checkbox", "radio", "file"):
                assert control["label"], f"囲むラベルがない：{control.get('name')}"
        assert Counter(b["text"] for b in page.buttons) == Counter(JIZOKUKA_BUTTONS[n]), n
        assert ("提出" in [b["text"] for b in page.buttons]) == (n == 13)
        # 上限のある欄にだけ maxlength を付け、値は上限と同じ
        limited = {x["id"]: str(x["limit"]) for x in sj.screen_fields(n) if x.get("limit")}
        assert {c["name"]: c.get("maxlength") for c in page.controls if c.get("maxlength")} == limited, n
        for control in page.controls:
            if control.get("type") == "file":
                assert control["accept"] == sj.ACCEPT
        # マイページとログアウトへのリンク（手引き p.7、p.53）
        assert 'href="/mypage"' in text and 'href="/logout"' in text


def test_jizokuka_radio_and_checkbox_labels(running_jizokuka):
    """ラジオボタンは「問い：値」、担当者の欄の名前は、画面に出たときも定義のとおり。"""
    base, _ = running_jizokuka
    cookie = login_jizokuka(base)
    page = parse(request(base + "/shinsei/4", cookie=cookie)[2])
    by_name = {}
    for control in page.controls:
        by_name.setdefault(control.get("name"), []).append(control)
    assert [c["label"] for c in by_name["settled"]] == ["決算期の確認：はい", "決算期の確認：いいえ"]
    assert by_name["site_pref"][0]["label"] == "事業実施場所の住所（都道府県）"
    page = parse(request(base + "/shinsei/13", cookie=cookie)[2])
    labels = {c["name"]: c["label"] for c in page.controls}
    assert labels["final_no_error"] == "入れた内容に誤りはない" and not has_word(labels["final_no_error"])
    assert has_word(labels["final_reviewed"])


def test_jizokuka_login_junshu_mypage_and_start(running_jizokuka):
    """ログイン → 遵守事項 → マイページ → 誓約事項 → 申請情報入力（手引き p.5–7、p.10）。"""
    base, record_dir = running_jizokuka
    for path in ("/shinsei/1", "/junshu", "/mypage", "/saikai"):
        status, headers, _ = request(base + path)
        assert status == 303 and headers["Location"] == "/login", path
    cookie = login_jizokuka(base)
    page = parse(request(base + "/junshu", cookie=cookie)[2])
    assert [c["label"] for c in page.controls if c.get("type") == "checkbox"] == ["遵守事項に同意する"]
    assert [b["text"] for b in page.buttons] == ["上記に同意して利用を開始する"]
    status, headers, _ = post_page(base, "/junshu", cookie, {"button": "agree_start", "junshu_agree": "on"})
    assert status == 303 and headers["Location"] == "/mypage"
    assert read_state(record_dir)["junshu_agreed"] is True
    entry = read_log(record_dir)[-1]
    assert entry["page"] == "junshu" and entry["button_label"] == "上記に同意して利用を開始する"
    assert entry["fields"] == {"junshu_agree": True}
    text = request(base + "/mypage", cookie=cookie)[2]
    assert "未作成" in text and [b["text"] for b in parse(text).buttons] == ["公募・交付申請を開始する"]
    # 保存した入力がないときは、誓約事項の画面へ
    status, headers, _ = post_page(base, "/mypage", cookie, {"button": "open_application"})
    assert status == 303 and headers["Location"] == "/shinsei/1"
    status, headers, _ = post_page(base, "/shinsei/1", cookie, {"button": "start", "pledge_agree": "on"})
    assert status == 303 and headers["Location"] == "/shinsei/2"
    assert read_state(record_dir)["fields"]["pledge_agree"]["value"] is True
    assert read_state(record_dir)["fields"]["pledge_agree"]["who"] == "person"
    assert "「申請を開始する」を押しました" in request(base + "/shinsei/2", cookie=cookie)[2]


def test_jizokuka_resume_from_mypage(running_jizokuka):
    """保存した入力があるときは、再開の申請内容確認へ。「申請を再開する」で、入力の終わっていない画面へ（p.52）。"""
    base, record_dir = running_jizokuka
    cookie = login_jizokuka(base)
    status, headers, _ = post_page(base, "/shinsei/2", cookie, {"button": "next", **SCREEN2_FULL})
    assert status == 303 and headers["Location"] == "/shinsei/3"
    assert "下書き" in request(base + "/mypage", cookie=cookie)[2]
    status, headers, _ = post_page(base, "/mypage", cookie, {"button": "open_application"})
    assert headers["Location"] == "/saikai"
    page = parse(request(base + "/saikai", cookie=cookie)[2])
    assert [b["text"] for b in page.buttons] == ["申請を再開する", "戻る"]
    status, headers, _ = post_page(base, "/saikai", cookie, {"button": "resume"})
    assert status == 303 and headers["Location"] == "/shinsei/3"
    status, headers, _ = post_page(base, "/saikai", cookie, {"button": "back"})
    assert headers["Location"] == "/mypage"
    assert read_log(record_dir)[-1]["page"] == "saikai"


def test_jizokuka_next_saves_and_records_missing_required(running_jizokuka):
    """次へは、その画面の欄を保存して次の画面へ移る。必須の空の欄は止めずに、記録に残す。"""
    base, record_dir = running_jizokuka
    cookie = login_jizokuka(base)
    status, headers, _ = post_page(base, "/shinsei/2", cookie, {"button": "next", "invoice_tokurei": "希望しない"})
    assert status == 303 and headers["Location"] == "/shinsei/3"
    entry = read_log(record_dir)[-1]
    assert entry["screen"] == "画面2 申請情報入力" and entry["saved"] is True
    assert "wage_tokurei" in entry["missing_required"] and "invoice_tokurei" not in entry["missing_required"]
    assert entry["over_limit"] == []
    assert set(entry["fields"]) == set(server.empty_values(sj))
    fields = read_state(record_dir)["fields"]
    assert fields["invoice_tokurei"]["value"] == "希望しない" and fields["invoice_tokurei"]["who"] == "tool"
    # 戻るは保存しない
    status, headers, _ = post_page(base, "/shinsei/3", cookie, {"button": "back", "hq_zip": "1000000"})
    assert headers["Location"] == "/shinsei/2"
    assert read_state(record_dir)["fields"]["hq_zip"]["value"] == ""


def test_jizokuka_wage_screen_only_when_chosen(running_jizokuka):
    """画面7（賃金引上げ特例）は、特例か賃金引上げ加点を選んだときだけ通る（手引き p.35）。"""
    base, _ = running_jizokuka
    cookie = login_jizokuka(base)
    post_page(base, "/shinsei/2", cookie, {"button": "next", **SCREEN2_FULL})
    assert post_page(base, "/shinsei/6", cookie, {"button": "next"})[1]["Location"] == "/shinsei/8"
    assert post_page(base, "/shinsei/8", cookie, {"button": "back"})[1]["Location"] == "/shinsei/6"
    assert "今の入力では当たらない" in request(base + "/shinsei/7", cookie=cookie)[2]
    post_page(base, "/shinsei/2", cookie, {"button": "next", **SCREEN2_FULL, "wage_tokurei": sj.WAGE_OPTIONS[1]})
    assert post_page(base, "/shinsei/6", cookie, {"button": "next"})[1]["Location"] == "/shinsei/7"
    assert post_page(base, "/shinsei/7", cookie, {"button": "next"})[1]["Location"] == "/shinsei/8"
    assert post_page(base, "/shinsei/8", cookie, {"button": "back"})[1]["Location"] == "/shinsei/7"
    # 特例を希望しなくても、政策加点で「1.賃金引上げ加点」を選べば通る
    post_page(base, "/shinsei/2", cookie, {"button": "next", **SCREEN2_FULL})
    assert post_page(base, "/shinsei/6", cookie, {"button": "next", "kasan_policy": sj.KASAN_WAGE})[1]["Location"] \
        == "/shinsei/7"


def test_jizokuka_limit_keeps_the_screen(running_jizokuka):
    """上限を超えた欄があると、入力は保存して同じ画面のまま。改行は LF にそろえて数える。"""
    base, record_dir = running_jizokuka
    cookie = login_jizokuka(base)
    status, headers, _ = post_page(base, "/shinsei/9", cookie, {"button": "next", "project_name": "あ" * 31})
    assert status == 303 and headers["Location"] == "/shinsei/9"
    assert read_state(record_dir)["fields"]["project_name"]["value"] == "あ" * 31
    assert read_state(record_dir)["fields"]["project_name"]["limit"] == 30
    entry = read_log(record_dir)[-1]
    assert entry["over_limit"] == [{"field": "project_name", "length": 31, "limit": 30}]
    text = request(base + "/shinsei/9", cookie=cookie)[2]
    assert "31字で、上限の30字を超えています" in text and "この画面のままです" in text
    status, headers, _ = post_page(base, "/shinsei/9", cookie, {"button": "next", "project_name": "あ" * 30,
                                                                "sales_2_1": "い\r\n" * 2000})
    assert headers["Location"] == "/shinsei/10"  # 4,000字ちょうどは通る（CRLF のままなら6,000字）
    status, headers, _ = post_page(base, "/shinsei/8", cookie, {"button": "next", "plan_1_1": "う" * 4001})
    assert headers["Location"] == "/shinsei/8"
    assert "入力済：4001 ／ 最大：4,000" in request(base + "/shinsei/8", cookie=cookie)[2]


def test_jizokuka_attach_rules(running_jizokuka):
    """添付：形式（手引き p.55）と大きさ（10MB。p.65）。手引きが決めたファイルの名前を画面に出す。"""
    base, record_dir = running_jizokuka
    cookie = login_jizokuka(base)
    status, headers, _ = post_page(base, "/shinsei/4", cookie, {"button": "next"},
                                   {"doc_bs": ("貸借対照表（株式会社やまぶき惣菜）.pdf", SAMPLE_PDF.read_bytes())})
    assert headers["Location"] == "/shinsei/5"
    state = read_state(record_dir)
    assert state["files"]["doc_bs"]["filename"] == "貸借対照表（株式会社やまぶき惣菜）.pdf"
    assert (record_dir / state["files"]["doc_bs"]["path"]).read_bytes() == SAMPLE_PDF.read_bytes()
    text = request(base + "/shinsei/4", cookie=cookie)[2]
    assert "添付済み：貸借対照表（株式会社やまぶき惣菜）.pdf" in text and "ファイルの名前：貸借対照表（事業者名）" in text
    post_page(base, "/shinsei/4", cookie, {"button": "next"}, {"doc_pl": ("損益計算書.HEIC", b"heic")})
    assert "doc_pl" in read_state(record_dir)["files"]
    status, headers, _ = post_page(base, "/shinsei/4", cookie, {"button": "next"}, {"doc_registry": ("登記.txt", b"x")})
    assert headers["Location"] == "/shinsei/4" and "doc_registry" not in read_state(record_dir)["files"]
    big = b"0" * (sj.MAX_FILE_BYTES + 1)
    status, headers, _ = post_page(base, "/shinsei/4", cookie, {"button": "next"}, {"doc_sales_ledger": ("売上台帳.pdf", big)})
    assert headers["Location"] == "/shinsei/4" and "doc_sales_ledger" not in read_state(record_dir)["files"]
    assert "10MBまで" in read_log(record_dir)[-1]["uploads"][0]["reason"]


def test_jizokuka_expense_calculation_matches_tebiki_example():
    """手引き p.46 の例（②広報費 100000×3）と、ウェブサイト関連費・赤字事業者の補助率。"""
    out = calc_jizokuka.compute({"exp1_category": "②広報費", "exp1_amount": "300000"})
    assert out["exp_sum_a"] == "300,000" and out["subsidy_b_max"] == "200,000"
    assert out["exp_sum_c"] == "0" and out["exp_sub_d"] == "0"
    assert out["exp_total_e"] == "300,000" and out["exp_total_f"] == "200,000" and out["exp_diff_g"] == "100,000"
    assert out["web_check"] == "はい" and out["fund_subsidy_amount"] == "200,000"
    values = {"exp1_category": "①機械装置等費", "exp1_amount": "900000",
              "exp2_category": sj.WEB_CATEGORY, "exp2_amount": "150000"}
    out = calc_jizokuka.compute(values)
    assert (out["exp_sum_a"], out["exp_sum_c"], out["exp_sub_d"], out["exp_total_f"]) == \
        ("900,000", "150,000", "100,000", "700,000")
    assert out["web_check"] == "はい"
    out = calc_jizokuka.compute({**values, "exp2_amount": "1200000"})
    assert out["exp_sub_d"] == "500,000" and out["web_check"] == "いいえ"  # 50万円まで。(f)の1/4を超える
    out = calc_jizokuka.compute({**values, "wage_tokurei": sj.WAGE_DEFICIT})
    assert out["subsidy_b_max"] == "675,000" and out["exp_sub_d"] == "112,500"
    out = calc_jizokuka.compute({**values, "subsidy_b": "500000", "fund_own_amount": "350000", "fund_loan_amount": "0"})
    assert out["exp_total_f"] == "600,000" and out["fund_total_amount"] == "950,000"


def test_jizokuka_calc_and_gbiz_buttons(running_jizokuka):
    base, record_dir = running_jizokuka
    cookie = login_jizokuka(base)
    status, headers, _ = post_page(base, "/shinsei/10", cookie, {"button": "calc_expense", "exp1_category": "②広報費",
                                                                 "exp1_amount": "300000", "tax_type": "税抜"})
    assert status == 303 and headers["Location"] == "/shinsei/10"
    text = request(base + "/shinsei/10", cookie=cookie)[2]
    assert "「自動計算」を押しました" in text and "200,000" in text
    assert read_state(record_dir)["fields"]["exp1_amount"]["value"] == "300000"
    # 「Gビズから最新情報を取得する」は記録だけ（欄の上に置く）
    status, headers, _ = post_page(base, "/shinsei/3", cookie, {"button": "gbiz_refresh", "hq_zip": "1000000"})
    assert headers["Location"] == "/shinsei/3"
    assert read_log(record_dir)[-1]["saved"] is False
    assert read_state(record_dir)["fields"]["hq_zip"]["value"] == ""
    text = request(base + "/shinsei/3", cookie=cookie)[2]
    assert text.index("Gビズから最新情報を取得する</button>") < text.index('name="hq_zip"')


def test_jizokuka_oath_confirm_and_submit(running_jizokuka):
    """宣誓・同意 → 申請内容確認（修正・提出）。提出は押されたと記録するだけ（手引き p.50–51）。"""
    base, record_dir = running_jizokuka
    cookie = login_jizokuka(base)
    status, headers, _ = post_page(base, "/shinsei/12", cookie, {
        "button": "to_confirm", "oath_pledge": "on", "oath_consent": "on", "oath_all": "on", "oath_esys": "on"})
    assert status == 303 and headers["Location"] == "/shinsei/13"
    fields = read_state(record_dir)["fields"]
    assert all(fields[k]["value"] is True and fields[k]["who"] == "person"
               for k in ("oath_pledge", "oath_consent", "oath_all", "oath_esys"))
    page = parse(request(base + "/shinsei/13", cookie=cookie)[2])
    assert [b["value"] for b in page.buttons if b["text"] == "修正"] == [f"fix_{k}" for k in range(2, 12)]
    for k in range(2, 12):
        assert post_page(base, "/shinsei/13", cookie, {"button": f"fix_{k}"})[1]["Location"] == f"/shinsei/{k}"
    assert read_state(record_dir)["submit_pressed"] is False
    status, _, text = post_page(base, "/shinsei/13", cookie, {"button": "submit", "final_reviewed": "on"})
    assert status == 200 and "どこにも送っていません" in text and 'href="/shinsei/13"' in text
    state = read_state(record_dir)
    assert state["submit_pressed"] is True and len(state["submit_times"]) == 1
    entry = read_log(record_dir)[-1]
    assert entry["screen"] == "画面13 申請内容確認" and entry["button_label"] == "提出"
    assert entry["fields"]["final_reviewed"] is True and entry["fields"]["final_no_error"] is False
    assert "提出済み" in request(base + "/mypage", cookie=cookie)[2]


def test_jizokuka_button_not_on_screen_and_paths(running_jizokuka):
    base, record_dir = running_jizokuka
    cookie = login_jizokuka(base)
    status, headers, _ = post_page(base, "/shinsei/2", cookie, {"button": "submit"})
    assert status == 200 and read_state(record_dir)["submit_pressed"] is True  # どの画面に送られても記録する
    status, headers, _ = post_page(base, "/shinsei/1", cookie, {"button": "next", "pledge_agree": "on"})
    assert headers["Location"] == "/shinsei/1" and read_log(record_dir)[-1]["saved"] is False
    assert "この画面にないボタンです" in request(base + "/shinsei/1", cookie=cookie)[2]
    assert request(base + "/shinsei", cookie=cookie)[1]["Location"] == "/shinsei/1"
    for path in ("/shinsei/0", "/shinsei/14", "/nothing"):
        assert request(base + path, cookie=cookie)[0] == 404


def test_jizokuka_client_events_logout_and_password(running_jizokuka):
    base, record_dir = running_jizokuka
    cookie = login_jizokuka(base)
    request(base + "/log", json.dumps({"event": "change", "name": "junshu_agree", "type": "checkbox", "value": "on",
                                      "checked": True, "page": "/junshu"}).encode())
    request(base + "/log", json.dumps({"event": "change", "name": "password", "type": "password",
                                      "value": SECRET, "entered": True, "page": "/login"}).encode())
    request(base + "/log", json.dumps({"event": "click", "link": "/logout", "label": "ログアウト",
                                      "page": "/shinsei/3"}).encode())
    change, password, click = read_log(record_dir)[-3:]
    assert change["label"] == "遵守事項に同意する" and change["checked"] is True
    assert password["entered"] is True and "value" not in password
    assert click["link"] == "/logout"
    status, headers, _ = request(base + "/logout", cookie=cookie)
    assert status == 303 and headers["Location"] == "/login"
    assert read_log(record_dir)[-1]["event"] == "logout"
    assert request(base + "/mypage", cookie=cookie)[1]["Location"] == "/login"
    for path in record_dir.rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text(encoding="utf-8", errors="ignore")


def test_jizokuka_default_record_dir_is_separate():
    """持続化の記録の既定の置き場は、省力化（mock/記録）と別。--reset で省力化の記録を消さない。"""
    import server_jizokuka
    assert server_jizokuka.DEFAULT_RECORD_DIR != server.DEFAULT_RECORD_DIR
    assert server_jizokuka.DEFAULT_RECORD_DIR.parent == server.DEFAULT_RECORD_DIR.parent
    ignored = (Path(__file__).resolve().parent / ".gitignore").read_text(encoding="utf-8")
    assert f"{server_jizokuka.DEFAULT_RECORD_DIR.name}/" in ignored.splitlines()


def test_readme_has_the_jizokuka_screen_list():
    """README の持続化の一覧は、`python3 mock/screen_jizokuka.py` の今の出力と同じ。"""
    readme = (Path(__file__).resolve().parent / "README.md").read_text(encoding="utf-8")
    assert sj.markdown_screens() in readme
