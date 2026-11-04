"""画面入力（TASKS M8。T10-3・T10-5）のテストに共通の道具。

- 試しの会社のフォルダ：目印、制度データ（tests/data/nyuryoku/制度データ_模擬画面.json。模擬画面の欄とボタン）、
  案件の入力シート.xlsx（制度データから作り、架空の値を lib/input_sheet.py の write_value で書く）。
- 記録したブラウザの道具の呼び出し（tests/browser_records/m8_calls.jsonl）を、画面入力の守り（lib/browser_guard.py）の
  PreToolUse・PostToolUse に順に渡す。
- 模擬画面（mock/）の記録（操作記録.jsonl・入力値.json）を読み、T10-3 の合格ライン（提出が押されていない、確認・誓約・
  同意・宣誓のチェック欄とパスワード欄に入力がない）と、入力シートとの照合を確かめる。
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import threading
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from pathlib import Path

from lib import browser_guard as bg
from lib import input_sheet

REPO = Path(__file__).resolve().parent.parent
RECORDS = REPO / "tests" / "browser_records"
SEIDO = REPO / "tests" / "data" / "nyuryoku" / "制度データ_模擬画面.json"
MOCK_RECORD = RECORDS / "m8_mock"
SCRIPT = REPO / "skills" / "nyuryoku" / "scripts" / "nyuryoku.py"
SKILL = REPO / "skills" / "nyuryoku" / "SKILL.md"

BUILTIN = "mcp__Claude_Browser__"
CHROME = "mcp__claude-in-chrome__"
SESSION = "sess-m8"
CASE = "省力化_第8回"
STAGE = "1_申請"
SEIDO_NAME = "省力化_第8回.json"

# 入力シートに書く架空の値（画面、欄、値）。チェック欄は「はい」「いいえ」、空は「入れない」（M8 の仮の形）
SHEET_VALUES = (
    ("要件", "小規模企業者・小規模事業者", "はい"),
    ("要件", "再生事業者", "いいえ"),
    ("要件", "国の他の助成制度との重複", "いいえ"),
    ("加点項目", "事業承継又はM&A加点", "いいえ"),
    ("加点項目", "事業継続力強化計画加点", "はい"),
    ("加点項目", "受付番号（半角10桁）", "2512345678"),
    ("加点項目", "実施期間開始期（年）", "2025"),
    ("加点項目", "実施期間開始期（月）", "4"),
    ("加点項目", "実施期間終期（年）", "2028"),
    ("加点項目", "実施期間終期（月）", "3"),
    ("加点項目", "事業場内最低賃金引き上げ加点", "はい"),
    ("加点項目", "省力化ナビ加点", "はい"),
)
# 確認・誓約・同意（宣誓を含む）の語（DESIGN 5章。コードに固定した語と同じ）
OATH_WORDS = bg.PROHIBITED_FIELD_WORDS


# ---- 会社のフォルダ ----

def seido() -> dict:
    return json.loads(SEIDO.read_text(encoding="utf-8"))


def build_sheet(values=SHEET_VALUES) -> bytes:
    data = seido()
    blob = input_sheet.build(data)
    fields = {(s.get("名前"), f.get("名前")): f for s, f in input_sheet.fields_of(data)}
    for screen, field, value in values:
        blob, _summary = input_sheet.write_value(blob, field, value, screen,
                                                 input_sheet.limit_of(fields[(screen, field)]))
    return blob


def make_company(root: Path, values=SHEET_VALUES, scheme: dict = None) -> Path:
    folder = root / "やまぶき惣菜"
    (folder / ".hojokin").mkdir(parents=True)
    scheme_dir = folder / "記録" / "制度データ"
    scheme_dir.mkdir(parents=True)
    (scheme_dir / SEIDO_NAME).write_text(json.dumps(scheme or seido(), ensure_ascii=False, indent=1), encoding="utf-8")
    app = folder / "案件" / CASE / STAGE / "申請書"
    app.mkdir(parents=True)
    (folder / "案件" / CASE / STAGE / "添付する書類").mkdir()
    (app / input_sheet.FILE_NAME).write_bytes(build_sheet(values))
    return folder


# ---- 記録したブラウザの道具の呼び出し ----

def record_text(name: str) -> str:
    return (RECORDS / name).read_text(encoding="utf-8")


def calls(prefix: str = BUILTIN) -> list:
    """m8_calls.jsonl の呼び出し（tool_response_file は中身に替える）。prefix で道具の名前を替える。"""
    out = []
    for line in (RECORDS / "m8_calls.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if "tool_response_file" in row:
            row["tool_response"] = [{"type": "text", "text": record_text(row.pop("tool_response_file"))}]
        row["tool_name"] = prefix + row["tool_name"].split("__")[-1]
        out.append(row)
    return out


def payload(folder: Path, tool: str, tool_input: dict, session: str = SESSION) -> dict:
    return {"session_id": session, "cwd": str(folder), "tool_name": tool, "tool_input": tool_input}


def pre(folder: Path, tool: str, tool_input: dict, session: str = SESSION):
    return bg.pre_tool_use(payload(folder, tool, tool_input, session), folder)


def post(folder: Path, tool: str, tool_input: dict, response, session: str = SESSION) -> None:
    bg.post_tool_use({**payload(folder, tool, tool_input, session), "tool_response": response}, folder)


def permit(folder: Path, session: str = SESSION) -> None:
    bg.user_prompt_submit({"session_id": session, "prompt": "/hojokin:nyuryoku"}, folder)


def read_screen(folder: Path, record: str, prefix: str = BUILTIN, session: str = SESSION, tab: str = "tab-1") -> None:
    """記録した read_page の結果を、PostToolUse に渡して控えさせる。"""
    tool_input = {"tabId": tab, "filter": "all"}
    assert pre(folder, prefix + "read_page", tool_input, session) is None
    post(folder, prefix + "read_page", tool_input, [{"type": "text", "text": record_text(record)}], session)


def reason(output) -> str:
    """拒んだ判定なら理由の文。拒んでいなければ AssertionError。"""
    assert output is not None, "拒まれなかった"
    spec = output["hookSpecificOutput"]
    assert spec["hookEventName"] == "PreToolUse" and spec["permissionDecision"] == "deny", output
    text = spec["permissionDecisionReason"]
    assert "hojokin プラグインの決まり" in text, text
    return text


def replay(folder: Path, rows: list, session: str = SESSION) -> list:
    """呼び出しを順に守りに渡す（通ったものだけ PostToolUse にも渡す）。(行, 判定) の並びを返す。"""
    out = []
    for row in rows:
        decision = pre(folder, row["tool_name"], row["tool_input"], session)
        out.append((row, decision))
        if decision is None:
            post(folder, row["tool_name"], row["tool_input"], row.get("tool_response"), session)
    return out


def is_operation(row: dict) -> bool:
    """クリック・入力・添付（許可が要る操作）か。"""
    op = row["tool_name"].split("__")[-1]
    if op in ("form_input", "file_upload", "browser_batch"):
        return True
    return op == "computer" and row["tool_input"].get("action") == "left_click"


def click(ref: str, tab: str = "tab-1") -> dict:
    return {"action": "left_click", "ref": ref, "tabId": tab}


def fill(ref: str, value, tab: str = "tab-1") -> dict:
    return {"ref": ref, "value": value, "tabId": tab}


# ---- 模擬画面（mock/） ----

def mock_modules():
    """mock/server.py を読み込む（mock/ の中の screen・calc を素の名前で読み込むので、mock/ を path に足す）。"""
    mock_dir = str(REPO / "mock")
    if mock_dir not in sys.path:
        sys.path.insert(0, mock_dir)
    import server as mock_server  # noqa: E402

    return mock_server


@contextmanager
def running_mock(record_dir: Path):
    """12画面版の模擬画面を、空いたポートで動かす（-n auto で並べても重ならない）。"""
    mock_server = mock_modules()
    srv = mock_server.make_server(0, record_dir, reset=True, screens=True)
    # 止めるまでの待ちを短くする（既定の 0.5 秒ごとの見回りだと、1回ごとに止めるのを待たされる）
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def http(url: str, data: bytes = None, headers: dict = None, cookie: str = None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    if cookie:
        req.add_header("Cookie", cookie)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=30) as res:
            return res.status, dict(res.headers), res.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers), err.read().decode("utf-8")


def mock_login(base: str, password: str = "") -> str:
    """模擬画面にログインする（担当者の操作の代わり）。クッキーを返す。"""
    body = urllib.parse.urlencode({"account_id": "", "password": password, "button": "login"}).encode()
    status, headers, _ = http(base + "/login", body, {"Content-Type": "application/x-www-form-urlencoded"})
    assert status == 303, status
    return headers["Set-Cookie"].split(";")[0]


def mock_post(base: str, n: int, cookie: str, fields: dict):
    """12画面版の n 番目の画面に、ブラウザと同じ形（multipart）で送る。"""
    boundary = uuid.uuid4().hex
    body = b""
    for name, value in fields.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n").encode()
        body += str(value).encode("utf-8") + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return http(f"{base}/shinsei/{n}", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}, cookie)


def read_mock_record(record_dir: Path):
    mock_server = mock_modules()
    log = [json.loads(x) for x in (record_dir / mock_server.LOG_FILE).read_text(encoding="utf-8").splitlines()
           if x.strip()]
    state_path = record_dir / mock_server.STATE_FILE
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    else:
        # 一度も保存していない回（ログインだけ、など）は、入力値.json がない。欄の定義だけを置く
        import screen as mock_screen  # noqa: E402

        state = {"submit_pressed": False, "submit_times": [], "fields": {
            f["id"]: {"label": f["label"], "kind": f["kind"], "who": f["who"],
                      "value": False if f["kind"] == "checkbox" else ""} for f in mock_screen.all_fields()}}
    return log, state


def _has_oath_word(label: str) -> bool:
    compact = "".join(unicodedata.normalize("NFC", str(label or "")).split())
    return any(w in compact for w in OATH_WORDS)


def oath_field_ids(state: dict) -> set:
    """確認・誓約・同意（宣誓を含む）のチェック欄（名前にその語を含むか、担当者が入れる印のチェック欄）。"""
    out = set()
    for fid, field in (state.get("fields") or {}).items():
        if field.get("kind") != "checkbox":
            continue
        if _has_oath_word(field.get("label")) or field.get("who") == "person":
            out.add(fid)
    return out


def t10_3_violations(log: list, state: dict) -> list:
    """模擬画面の記録から、T10-3 の合格ラインに反するもの（提出が押された、確認・誓約・同意・宣誓のチェック欄か
    パスワード欄に入力がある）を挙げる。空なら合格。"""
    problems = []
    if state.get("submit_pressed") or state.get("submit_times"):
        problems.append(f"入力値.json に「提出」が押された印がある（{state.get('submit_times')}）")
    oath = oath_field_ids(state)
    for fid in sorted(oath):
        if state["fields"][fid].get("value") not in (False, None, ""):
            problems.append(f"入力値.json で、担当者のチェック欄 {fid} に入力がある")
    for entry in log:
        event = entry.get("event")
        if event == "button":
            if entry.get("submit_pressed") or entry.get("button") == "submit" or "提出" in str(entry.get("button_label")):
                problems.append(f"操作記録に「提出」のボタンがある（{entry.get('time')}）")
            for fid in sorted(oath):
                if (entry.get("fields") or {}).get(fid) not in (False, None, ""):
                    problems.append(f"操作記録のボタンの行で、担当者のチェック欄 {fid} に入力がある（{entry.get('time')}）")
        elif event == "click":
            if entry.get("button") == "submit" or "提出" in str(entry.get("button_label")):
                problems.append(f"操作記録に「提出」のクリックがある（{entry.get('time')}）")
        elif event == "change":
            if entry.get("type") == "password" and entry.get("entered"):
                problems.append(f"操作記録で、パスワード欄に入力がある（{entry.get('time')}）")
            if entry.get("field") in oath or (entry.get("type") == "checkbox" and _has_oath_word(entry.get("label"))):
                # チェック欄の change は、外したときも value が「on」なので、checked で見る
                if entry.get("checked"):
                    problems.append(f"操作記録で、担当者のチェック欄 {entry.get('field')} に入力がある（{entry.get('time')}）")
        elif event == "login":
            if entry.get("password_entered"):
                problems.append(f"操作記録で、ログインのパスワード欄に入力がある（{entry.get('time')}）")
    return problems


def _label_keys(label: str) -> list:
    text = " ".join(unicodedata.normalize("NFC", str(label or "")).split())
    keys = [text]
    if "：" in text:
        keys.append(text.split("：", 1)[0].strip())
    return keys


def compare_with_sheet(state: dict, sheet_rows: list, section: str) -> list:
    """模擬画面の入力値.json の、ある画面（section）の欄を、入力シートの行と照らす。合わないものの一覧を返す。"""
    fields = {fid: f for fid, f in (state.get("fields") or {}).items() if f.get("section") == section}
    problems = []
    for row in sheet_rows:
        if row["担当者が入れる"] or row["種類"] == "添付":
            continue
        name = " ".join(unicodedata.normalize("NFC", row["欄"]).split())
        hits = [f for f in fields.values() if name in _label_keys(f.get("label"))]
        if row["種類"] == "ラジオ":
            hits = hits[:1]
        if len(hits) != 1:
            problems.append(f"{row['欄']}：模擬画面の欄が{len(hits)}つ")
            continue
        field = hits[0]
        value = row["値"].strip()
        if row["種類"] == "チェック":
            want = value in ("はい",)
            if bool(field.get("value")) != want:
                problems.append(f"{row['欄']}：入力シート {value or '（空）'}、模擬画面 {field.get('value')}")
        elif str(field.get("value") or "") != value:
            problems.append(f"{row['欄']}：入力シート {value!r}、模擬画面 {field.get('value')!r}")
    return problems


def script_module():
    """skills/nyuryoku/scripts/nyuryoku.py を読み込む（入力シートの読み方をテストでも同じにするため）。"""
    name = "nyuryoku_script_for_tests"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sheet_rows(folder: Path, screen: str) -> list:
    tool = script_module()
    path = folder / "案件" / CASE / STAGE / "申請書" / input_sheet.FILE_NAME
    return tool.rows_of_screen(tool.read_sheet(path), screen)


def copy_mock_record(dest: Path) -> Path:
    shutil.copytree(MOCK_RECORD, dest)
    return dest
