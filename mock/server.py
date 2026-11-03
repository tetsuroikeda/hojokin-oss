"""模擬の申請画面を手元で出すサーバー（D11a）。Python の標準のライブラリだけで動く。

    python3 mock/server.py [--port 8780] [--record-dir mock/記録] [--reset]

- http://127.0.0.1:8780/ を開くと、ログインの画面が出る（模擬なので、どの値でも入れる）。
- ログインの後は、申請の画面（❶〜⓬を縦に並べた1画面）が出る。
- 入れた値・添付したファイル・押したボタンを、記録のフォルダに残す。
  - 操作記録.jsonl：1つの操作を1行（ボタン、ログイン、欄の変更、クリック）
  - 入力値.json：一時保存した値と添付の今の状態
  - 添付/<欄の id>/：添付したファイルそのもの
- パスワードの値は、どこにも記録しない（入ったかどうかだけを残す）。
- 「提出」を押しても、どこにも送らない。押したことを記録して、模擬の画面を出す。
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import secrets
import shutil
import sys
import threading
from datetime import datetime
from email import policy
from email.parser import BytesParser
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import calc  # noqa: E402
import screen  # noqa: E402

# 実験 E1 の試しのサーバー（experiments/E1/serve.py）が 8765 を使うので、重ならない番号にする
DEFAULT_PORT = 8780
DEFAULT_RECORD_DIR = Path(__file__).resolve().parent / "記録"
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
MAX_BODY = 50 * 1024 * 1024
LOG_FILE = "操作記録.jsonl"
STATE_FILE = "入力値.json"
FILES_DIR = "添付"
COOKIE = "mock_session"

# 値を保存するボタン。「戻る」は保存しない。「提出」は記録だけ
SAVING_BUTTONS = {"save", "next", "calc_plan", "calc_expense", "issue_code"}

NOTICES = {
    "save": "「一時保存」を押しました。入力と添付を保存し、記録に残しました。",
    "next": "「次へ」を押しました。入力と添付を保存し、記録に残しました。D11a は1画面だけなので、次の画面はありません。",
    "back": "「戻る」を押しました。記録に残しました。前の画面はなく、この操作では保存していません。",
    "calc_plan": "「計算」（事業計画数値）を押しました。入力を保存し、計算した値を出しました。",
    "calc_expense": "「計算」（経費明細）を押しました。入力を保存し、計算した値を出しました。",
}


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def esc(text) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def fix_header_text(text: str) -> str:
    """ブラウザが UTF-8 のまま送ったヘッダーの文字（ファイル名など）を読み直す。"""
    try:
        return text.encode("utf-8", "surrogateescape").decode("utf-8")
    except UnicodeError:
        return text


def parse_multipart(content_type: str, body: bytes):
    """multipart/form-data を読む。戻り値は（欄の名前 → 値の並び, [(欄の名前, ファイル名, 中身)]）。"""
    head = b"Content-Type: " + content_type.encode("latin-1") + b"\r\nMIME-Version: 1.0\r\n\r\n"
    message = BytesParser(policy=policy.HTTP).parsebytes(head + body)
    fields, files = {}, []
    if not message.is_multipart():
        return fields, files
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        name = fix_header_text(str(name))
        data = part.get_payload(decode=True) or b""
        filename = part.get_param("filename", header="content-disposition")
        if filename is not None:
            filename = fix_header_text(str(filename))
            if filename:
                files.append((name, filename, data))
            continue
        # charset のない部分は us-ascii とみなされるので、バイト列から UTF-8 で読む
        fields.setdefault(name, []).append(data.decode("utf-8", errors="replace"))
    return fields, files


def safe_filename(name: str) -> str:
    name = name.replace("\\", "/").split("/")[-1]
    name = "".join(c for c in name if c >= " " and c not in '<>:"|?*').strip(" .")
    return name[:150] or "添付"


def accepted(filename: str, accept: str) -> bool:
    return any(filename.lower().endswith(ext) for ext in accept.split(","))


def empty_values() -> dict:
    values = {}
    for field in screen.all_fields():
        if field["kind"] == "checkbox":
            values[field["id"]] = False
        elif field["kind"] == "checkboxes":
            values[field["id"]] = []
        elif field["kind"] != "file":
            values[field["id"]] = ""
    return values


def values_from_form(form: dict) -> dict:
    """送られた欄から、すべての欄の値を作る。チェックしていない欄は送られないので False で埋める。"""
    values = {}
    for field in screen.all_fields():
        got = form.get(field["id"], [])
        if field["kind"] == "checkbox":
            values[field["id"]] = bool(got)
        elif field["kind"] == "checkboxes":
            values[field["id"]] = [v for v in got if v in field["options"]]
        elif field["kind"] != "file":
            # ブラウザは複数行の欄の改行を CRLF にして送るので、入力シートと同じ LF にそろえる
            values[field["id"]] = (got[0] if got else "").replace("\r\n", "\n")
    return values


class Store:
    """記録のフォルダ。書き込みは1つずつ行う。"""

    def __init__(self, record_dir: Path, reset: bool = False):
        self.dir = record_dir
        self.lock = threading.Lock()
        if reset and self.dir.exists():
            shutil.rmtree(self.dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state = self._load()
        # 回の区切り。前の回の「提出」は、--reset を付けない限り入力値.json に残る
        self.log({"event": "server_start", "reset": reset, "submit_pressed_before": self.state["submit_pressed"]})

    def _load(self) -> dict:
        path = self.dir / STATE_FILE
        state = {"values": empty_values(), "files": {}, "submit_pressed": False, "submit_times": [],
                 "auth_code": "", "saved_at": ""}
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            state["values"].update({k: v["value"] for k, v in saved.get("fields", {}).items()
                                    if k in state["values"]})
            for key in ("files", "submit_pressed", "submit_times", "auth_code", "saved_at"):
                state[key] = saved.get(key, state[key])
        return state

    def log(self, entry: dict) -> None:
        with self.lock:
            with (self.dir / LOG_FILE).open("a", encoding="utf-8") as fp:
                fp.write(json.dumps({"time": now(), **entry}, ensure_ascii=False) + "\n")

    def write_state(self) -> None:
        fields = {}
        for field in screen.all_fields():
            if field["kind"] == "file":
                continue
            fields[field["id"]] = {"section": field["section"], "group": field["group"], "label": field["label"],
                                   "kind": field["kind"], "who": field["who"],
                                   "value": self.state["values"].get(field["id"])}
            if field.get("table"):
                fields[field["id"]]["table"] = field["table"]
        data = {
            "screen": screen.SCREEN_NAME,
            "note": "模擬画面の記録です。実在の申請システムとは関係ありません。",
            "saved_at": self.state["saved_at"],
            "submit_pressed": self.state["submit_pressed"],
            "submit_times": self.state["submit_times"],
            "auth_code": self.state["auth_code"],
            "fields": fields,
            "files": self.state["files"],
        }
        path = self.dir / STATE_FILE
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def save_upload(self, field: dict, filename: str, data: bytes) -> dict:
        info = {"field": field["id"], "label": field["label"], "filename": filename, "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest()}
        if not accepted(filename, field["accept"]):
            return {**info, "accepted": False,
                    "reason": f"この欄に添付できるのは {screen.ACCEPT_NAMES[field['accept']]} だけです"}
        folder = self.dir / FILES_DIR / field["id"]
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        path = folder / safe_filename(filename)
        path.write_bytes(data)
        self.state["files"][field["id"]] = {
            "label": field["label"], "filename": filename, "size": len(data), "sha256": info["sha256"],
            "path": str(path.relative_to(self.dir)), "attached_at": now()}
        return {**info, "accepted": True}

    def handle_button(self, button: str, form: dict, uploads: list) -> dict:
        """申請の画面のボタン1回分を処理し、記録する。戻り値は画面に出す知らせ。"""
        fields = screen.field_map()
        submitted = values_from_form(form)
        upload_results = []
        message, errors = NOTICES.get(button, ""), []
        with self.lock:
            saving = button in SAVING_BUTTONS
            if saving:
                self.state["values"] = submitted
                self.state["saved_at"] = now()
                for name, filename, data in uploads:
                    field = fields.get(name)
                    if not field or field["kind"] != "file":
                        continue
                    result = self.save_upload(field, filename, data)
                    upload_results.append(result)
                    if not result["accepted"]:
                        errors.append(f"{field['label']}：{result['reason']}（{filename}）")
            else:
                upload_results = [{"field": n, "filename": fn, "size": len(d), "accepted": False,
                                   "reason": "保存しないボタンなので受け取っていません"} for n, fn, d in uploads]
            if button == "issue_code":
                self.state["auth_code"] = f"{secrets.randbelow(10**6):06d}"
                message = (f"「認証コード発行」を押しました。模擬の認証コードは {self.state['auth_code']} です"
                           "（本物ではメールで届きます）。入力も保存しました。")
            if button == "submit":
                self.state["submit_pressed"] = True
                self.state["submit_times"].append(now())
            if saving or button in ("issue_code", "submit"):
                self.write_state()
        self.log({"event": "button", "page": "shinsei", "button": button, "button_label": screen.button_label(button),
                  "saved": saving, "fields": submitted, "uploads": upload_results, "files": self.state["files"],
                  "submit_pressed": self.state["submit_pressed"]})
        return {"message": message, "errors": errors}


CSS = """
body{margin:0;font-family:-apple-system,"Hiragino Sans","Noto Sans JP",sans-serif;background:#f4f4f2;color:#222;line-height:1.6}
.mock-banner{position:sticky;top:0;z-index:10;background:#fff3b0;border-bottom:4px dashed #a33;color:#5a1010;font-weight:bold;padding:8px 16px;text-align:center}
main{max-width:980px;margin:0 auto;padding:16px}
h1{font-size:1.4rem;margin:.5rem 0}
h2{font-size:1.15rem;border-left:6px solid #567;padding-left:8px;margin:2rem 0 .5rem}
h3{font-size:1rem;margin:1.2rem 0 .3rem;color:#345}
section{background:#fff;border:1px solid #ccd;border-radius:6px;padding:8px 16px 16px;margin:16px 0}
.progress{font-size:.85rem;color:#555;background:#fff;border:1px solid #ccd;padding:6px 10px;border-radius:6px}
.nav{display:flex;gap:12px;justify-content:center;margin:16px 0}
button{font-size:1rem;padding:6px 18px;border:1px solid #567;background:#fff;border-radius:4px;cursor:pointer}
button.save{background:#456;color:#fff}
button.submit{background:#8a2b2b;color:#fff;border-color:#8a2b2b;padding:8px 32px}
.row{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;margin:6px 0}
.row label{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px}
.row .name{display:inline-block;min-width:16rem;font-size:.92rem}
.row.check .name{min-width:0}
input[type=text],input[type=password],select,textarea{font-size:1rem;padding:4px 6px;border:1px solid #999;border-radius:3px;max-width:100%}
input[type=text]{width:18rem}
textarea{width:36rem;height:5rem}
fieldset{border:1px solid #ccd;border-radius:4px;margin:6px 0}
.req{font-size:.75rem;color:#a33;border:1px solid #a33;border-radius:3px;padding:0 4px}
.unit,.fmt{font-size:.85rem;color:#555}
.note{font-size:.85rem;color:#555;margin:.2rem 0}
.display{color:#555}
.attached{flex-basis:100%;font-size:.85rem;color:#1d5c2e;padding-left:16.6rem}
.picked{font-size:.85rem;color:#345}
.notice{background:#e8f4ea;border:1px solid #6a6;padding:8px 12px;border-radius:4px}
.error{background:#fbeaea;border:1px solid #c66;padding:8px 12px;border-radius:4px}
.scroll{overflow-x:auto}
table{border-collapse:collapse;font-size:.85rem;margin:6px 0}
th,td{border:1px solid #bbc;padding:3px 6px;vertical-align:middle}
th{background:#eef0f4;text-align:left}
td input[type=text]{width:8.5rem;text-align:right}
td textarea{width:18rem;height:3rem}
td.calc{background:#f2f2f2;text-align:right;min-width:7rem}
.summary td:first-child{width:22rem}
"""

# 欄の変更とボタンのクリックも記録する（一時保存しなかった操作も残すため）。パスワードの値は送らない
JS = """
(function(){
  function send(data){
    data.page = location.pathname;
    try{ navigator.sendBeacon('/log', JSON.stringify(data)); }catch(e){}
  }
  document.addEventListener('change', function(e){
    var t = e.target; if(!t.name) return;
    var d = {event:'change', name:t.name, type:t.type};
    if(t.type === 'password'){ d.entered = t.value.length > 0; }
    else if(t.type === 'checkbox' || t.type === 'radio'){ d.value = t.value; d.checked = t.checked; }
    else if(t.type === 'file'){
      d.files = Array.prototype.map.call(t.files, function(x){ return x.name; });
      var picked = document.getElementById('picked_' + t.name);
      if(picked){ picked.textContent = d.files.length ? '選んだファイル：' + d.files.join('、') + '（一時保存で添付されます）' : ''; }
    }
    else { d.value = t.value; }
    send(d);
  }, true);
  document.addEventListener('click', function(e){
    if(!e.target.closest) return;
    var b = e.target.closest('button');
    if(b){ send({event:'click', button:b.value, label:b.textContent.trim()}); return; }
    var a = e.target.closest('a');
    if(a){ send({event:'click', link:a.getAttribute('href'), label:a.textContent.trim()}); }
  }, true);
})();
"""

BANNER = "模擬画面（実在のシステムではありません）。架空の練習用の画面で、入れた内容はこのパソコンの中にだけ記録されます。"


def page(title: str, body: str) -> bytes:
    return ("<!doctype html><html lang=\"ja\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>【模擬画面】{esc(title)}</title><style>{CSS}</style></head><body>"
            f"<div class=\"mock-banner\" role=\"note\">{esc(BANNER)}</div><main>{body}</main>"
            f"<script>{JS}</script></body></html>").encode("utf-8")


def render_login(message: str = "") -> bytes:
    rows = []
    for field in screen.LOGIN_FIELDS:
        kind = "password" if field["kind"] == "password" else "text"
        rows.append(f"<div class=\"row\"><label><span class=\"name\">{esc(field['label'])}</span>"
                    f"<input type=\"{kind}\" name=\"{field['id']}\" id=\"f_{field['id']}\" autocomplete=\"off\"></label></div>")
    value, label, _page = screen.LOGIN_BUTTON
    body = (f"<h1>ログイン（模擬）</h1>"
            + (f"<p class=\"notice\">{esc(message)}</p>" if message else "")
            + "<p class=\"note\">本物のログインではありません。模擬なので、どの値でも（空でも）ログインできます。"
              "ログインは担当者が自分で行います。パスワードの値は記録しません。</p>"
            + "<form method=\"post\" action=\"/login\"><section>" + "".join(rows)
            + f"<div class=\"nav\"><button type=\"submit\" name=\"button\" value=\"{value}\" class=\"save\">{esc(label)}</button></div>"
            + "</section></form>")
    return page("ログイン", body)


def required_mark(field: dict) -> str:
    return "<span class=\"req\">必須</span>" if field.get("required") else ""


def render_field(field: dict, values: dict, files: dict, computed: dict) -> str:
    fid, label, kind = field["id"], field["label"], field["kind"]
    value = values.get(fid, "")
    unit = f"<span class=\"unit\">{esc(field['unit'])}</span>" if field.get("unit") else ""
    if kind == "display":
        shown = computed.get(fid, field.get("value", "")) if field.get("calc") else field.get("value", "")
        return (f"<div class=\"row\"><span class=\"name\">{esc(label)}</span>"
                f"<span class=\"display\" id=\"f_{fid}\">{esc(shown)}</span>{unit}</div>")
    if kind == "grid":
        return render_grid(field, values, computed)
    if kind in ("text", "number"):
        extra = " inputmode=\"numeric\"" if kind == "number" else ""
        if field.get("placeholder"):
            extra += f" placeholder=\"{esc(field['placeholder'])}\""
        return (f"<div class=\"row\"><label><span class=\"name\">{esc(label)}</span>"
                f"<input type=\"text\" name=\"{fid}\" id=\"f_{fid}\" value=\"{esc(value)}\"{extra}></label>"
                f"{unit}{required_mark(field)}</div>")
    if kind == "textarea":
        ph = f" placeholder=\"{esc(field['placeholder'])}\"" if field.get("placeholder") else ""
        return (f"<div class=\"row\"><label><span class=\"name\">{esc(label)}</span>"
                f"<textarea name=\"{fid}\" id=\"f_{fid}\"{ph}>{esc(value)}</textarea></label>{required_mark(field)}</div>")
    if kind == "select":
        options = ["<option value=\"\">--選択してください--</option>"]
        for opt in field["options"]:
            selected = " selected" if value == opt else ""
            options.append(f"<option value=\"{esc(opt)}\"{selected}>{esc(opt)}</option>")
        return (f"<div class=\"row\"><label><span class=\"name\">{esc(label)}</span>"
                f"<select name=\"{fid}\" id=\"f_{fid}\">{''.join(options)}</select></label>{unit}{required_mark(field)}</div>")
    if kind == "checkbox":
        checked = " checked" if value is True else ""
        return (f"<div class=\"row check\"><label><input type=\"checkbox\" name=\"{fid}\" id=\"f_{fid}\" value=\"on\"{checked}>"
                f"<span class=\"name\">{esc(label)}</span></label>{required_mark(field)}</div>")
    if kind == "checkboxes":
        boxes = []
        for i, opt in enumerate(field["options"]):
            checked = " checked" if opt in (value or []) else ""
            boxes.append(f"<div class=\"row check\"><label><input type=\"checkbox\" name=\"{fid}\" id=\"f_{fid}_{i}\" "
                         f"value=\"{esc(opt)}\"{checked}><span class=\"name\">{esc(opt)}</span></label></div>")
        return f"<fieldset><legend>{esc(label)}</legend>{''.join(boxes)}</fieldset>"
    if kind == "radio":
        radios = []
        for i, opt in enumerate(field["options"]):
            checked = " checked" if value == opt else ""
            radios.append(f"<div class=\"row check\"><label><input type=\"radio\" name=\"{fid}\" id=\"f_{fid}_{i}\" "
                          f"value=\"{esc(opt)}\"{checked}><span class=\"name\">{esc(label)}：{esc(opt)}</span></label></div>")
        return f"<fieldset><legend>{esc(label)}{required_mark(field)}</legend>{''.join(radios)}</fieldset>"
    if kind == "file":
        attached = files.get(fid)
        shown = (f"<div class=\"attached\" id=\"attached_{fid}\">添付済み：{esc(attached['filename'])}"
                 f"（{attached['size']:,}バイト）</div>") if attached else ""
        return (f"<div class=\"row\"><label><span class=\"name\">{esc(label)}</span>"
                f"<input type=\"file\" name=\"{fid}\" id=\"f_{fid}\" accept=\"{esc(field['accept'])}\"></label>"
                f"<span class=\"fmt\">対応形式：{esc(screen.ACCEPT_NAMES[field['accept']])}</span>{required_mark(field)}"
                f"<span class=\"picked\" id=\"picked_{fid}\"></span>{shown}</div>")
    raise ValueError(f"知らない種類の欄です：{kind}")


def render_grid(g: dict, values: dict, computed: dict) -> str:
    head = "".join(f"<th>{esc(label)}</th>" for _key, label, _kind in g["cols"])
    rows = []
    for row in g["rows"]:
        cells = []
        for col, col_label, kind in g["cols"]:
            mode = row.get("cells", {}).get(col, "in")
            cid = f"{g['id']}_{row['key']}_{col}"
            name = f"{row['label']}（{col_label}）"
            if mode == "none":
                cells.append("<td class=\"calc\">—</td>")
            elif mode == "calc":
                cells.append(f"<td class=\"calc\" id=\"f_{cid}\">{esc(computed.get(cid, ''))}</td>")
            elif kind == "textarea":
                cells.append(f"<td><textarea name=\"{cid}\" id=\"f_{cid}\" aria-label=\"{esc(name)}\">"
                             f"{esc(values.get(cid, ''))}</textarea></td>")
            else:
                numeric = " inputmode=\"numeric\"" if kind == "number" else ""
                cells.append(f"<td><input type=\"text\" name=\"{cid}\" id=\"f_{cid}\" aria-label=\"{esc(name)}\" "
                             f"value=\"{esc(values.get(cid, ''))}\"{numeric}></td>")
        rows.append(f"<tr><th>{esc(row['label'])}</th>{''.join(cells)}</tr>")
    return (f"<p class=\"note\">{esc(g['label'])}</p><div class=\"scroll\"><table>"
            f"<tr><th></th>{head}</tr>{''.join(rows)}</table></div>")


def render_button(value: str, label: str) -> str:
    cls = {"save": "save", "submit": "submit"}.get(value, "")
    return f"<button type=\"submit\" name=\"button\" value=\"{value}\" class=\"{cls}\">{esc(label)}</button>"


def render_nav() -> str:
    return "<div class=\"nav\">" + "".join(render_button(v, label) for v, label, _p in screen.NAV_BUTTONS) + "</div>"


def show_value(value) -> str:
    if value is True:
        return "チェックあり"
    if isinstance(value, list):
        return "、".join(value)
    return str(value)


def render_summary(state: dict) -> str:
    """⓬ 確認：保存した内容を段ごとに出す。"""
    parts = []
    for s in screen.SECTIONS[:-1]:
        rows = []
        for field in screen.section_fields(s):
            if field["kind"] == "file":
                attached = state["files"].get(field["id"])
                if attached:
                    rows.append((field["label"], attached["filename"]))
                continue
            value = state["values"].get(field["id"])
            if value not in ("", False, [], None):
                rows.append((field["label"], show_value(value)))
        body = "".join(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in rows) \
            or "<tr><td colspan=\"2\">（保存した入力はありません）</td></tr>"
        parts.append(f"<h3>{s['no']} {esc(s['title'])} <a href=\"#{s['key']}\">修正</a></h3>"
                     f"<table class=\"summary\">{body}</table>")
    return "".join(parts)


def render_shinsei(state: dict, message: str = "", errors=()) -> bytes:
    values, files = state["values"], state["files"]
    computed = calc.compute(values)
    progress = " → ".join(f"{s['no']} {s['title']}" for s in screen.SECTIONS)
    parts = [f"<h1>{esc(screen.SCREEN_NAME)}</h1>",
             f"<p class=\"progress\">進み具合（模擬・1画面版）：{esc(progress)}</p>"]
    if message:
        parts.append(f"<p class=\"notice\" role=\"status\">（模擬）{esc(message)}</p>")
    for err in errors:
        parts.append(f"<p class=\"error\" role=\"alert\">（模擬）添付できませんでした。{esc(err)}</p>")
    if state.get("saved_at"):
        parts.append(f"<p class=\"note\">最後に保存した時刻：{esc(state['saved_at'])}</p>")
    parts.append("<form method=\"post\" action=\"/shinsei\" enctype=\"multipart/form-data\">")
    parts.append(render_nav())
    for s in screen.SECTIONS:
        buttons = {where: (v, label) for v, label, _p, where in s.get("buttons", [])}
        inner = []
        for g in s["groups"]:
            inner.append(f"<h3>{esc(g['title'])}</h3>")
            if g["note"]:
                inner.append(f"<p class=\"note\">{esc(g['note'])}</p>")
            inner.extend(render_field(field, values, files, computed) for field in g["fields"])
            if g["title"] in buttons:
                inner.append("<div class=\"nav\">" + render_button(*buttons[g["title"]]) + "</div>")
        if s["key"] == "s12":
            inner.append("<p class=\"note\">一時保存した内容です。直すときは「修正」でその段へ移ります。"
                         "「提出」は担当者が押すボタンです（模擬なので、押してもどこにも送りません）。</p>")
            inner.append(render_summary(state))
        for href, label in s.get("links", []):
            inner.append(f"<p><a href=\"{esc(href)}\">{esc(label)}</a></p>")
        if "" in buttons:
            inner.append("<div class=\"nav\">" + render_button(*buttons[""]) + "</div>")
        parts.append(f"<section id=\"{s['key']}\"><h2>{s['no']} {esc(s['title'])}</h2>{''.join(inner)}</section>")
    parts.append(render_nav())
    parts.append("</form>")
    return page("申請の画面（省力化・一般型）", "".join(parts))


def render_submitted(state: dict) -> bytes:
    body = ("<h1>（模擬）「提出」が押されました</h1>"
            "<section><p>これは模擬画面です。どこにも送っていません。</p>"
            f"<p>「提出」が押されたことを記録に残しました（{esc(state['submit_times'][-1])}）。</p>"
            "<p><a href=\"/shinsei\">申請の画面へ戻る</a></p></section>")
    return page("提出が押されました", body)


class Handler(BaseHTTPRequestHandler):
    store: Store = None
    sessions: set = set()

    def log_message(self, format, *args) -> None:  # noqa: A002
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), format % args))

    def send(self, status: int, body: bytes = b"", headers: dict = None) -> None:
        self.send_response(status)
        if body:
            self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def redirect(self, location: str, headers: dict = None) -> None:
        self.send(303, b"", {"Location": location, **(headers or {})})

    def logged_in(self) -> bool:
        jar = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return COOKIE in jar and jar[COOKIE].value in self.sessions

    def read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("送られたデータが大きすぎます")
        return self.rfile.read(length)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            self.redirect("/shinsei" if self.logged_in() else "/login")
        elif path == "/login":
            self.send(200, render_login())
        elif path == "/shinsei":
            if not self.logged_in():
                self.redirect("/login")
            else:
                self.send(200, render_shinsei(self.store.state))
        else:
            self.send(404, page("見つかりません", "<p>この模擬画面にはないページです。</p>"))

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            body = self.read_body()
        except ValueError as err:
            self.send(413, page("大きすぎます", f"<p>{esc(err)}</p>"))
            return
        if path == "/login":
            form = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
            self.store.log({"event": "login", "page": "login", "button": "login", "button_label": "ログイン",
                            "account_id": form.get("account_id", [""])[0],
                            "password_entered": bool(form.get("password", [""])[0])})
            token = secrets.token_hex(16)
            self.sessions.add(token)
            self.redirect("/shinsei", {"Set-Cookie": f"{COOKIE}={token}; HttpOnly; SameSite=Lax; Path=/"})
        elif path == "/shinsei":
            if not self.logged_in():
                self.redirect("/login")
                return
            form, uploads = parse_multipart(self.headers.get("Content-Type", ""), body)
            button = (form.get("button") or [""])[0]
            result = self.store.handle_button(button, form, uploads)
            if button == "submit":
                self.send(200, render_submitted(self.store.state))
            else:
                self.send(200, render_shinsei(self.store.state, result["message"], result["errors"]))
        elif path == "/log":
            self.log_client_event(body)
            self.send(204)
        else:
            self.send(404, page("見つかりません", "<p>この模擬画面にはないページです。</p>"))

    def log_client_event(self, body: bytes) -> None:
        """画面の中の欄の変更とクリックを記録する。パスワードの値は残さない。"""
        try:
            data = json.loads(body.decode("utf-8"))
        except ValueError:
            return
        if not isinstance(data, dict):
            return
        entry = {"event": str(data.get("event", ""))[:20], "page": str(data.get("page", ""))[:50].strip("/")}
        if entry["event"] == "click" and data.get("link") is not None:
            entry["link"] = str(data.get("link", ""))[:200]
            entry["link_label"] = str(data.get("label", ""))[:50]
        elif entry["event"] == "click":
            entry["button"] = str(data.get("button", ""))[:50]
            entry["button_label"] = str(data.get("label", ""))[:50]
        else:
            name, kind = str(data.get("name", ""))[:100], str(data.get("type", ""))[:20]
            field = screen.field_map().get(name) or {f["id"]: f for f in screen.LOGIN_FIELDS}.get(name, {})
            entry.update({"field": name, "label": field.get("label", ""), "type": kind})
            if kind == "password" or name == "password":
                entry["entered"] = bool(data.get("entered"))
            elif kind == "file":
                entry["files"] = [str(x)[:200] for x in data.get("files", [])][:10]
            else:
                entry["value"] = str(data.get("value", ""))[:2000]
                if kind in ("checkbox", "radio"):
                    entry["checked"] = bool(data.get("checked"))
        self.store.log(entry)


def make_server(port: int, record_dir: Path, reset: bool = False, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    if host not in LOCAL_HOSTS:
        raise ValueError("模擬画面は、このパソコンの中（127.0.0.1）だけで出します")
    handler = type("MockHandler", (Handler,), {"store": Store(record_dir, reset), "sessions": set()})
    return ThreadingHTTPServer((host, port), handler)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="模擬の申請画面（省力化・一般型 第8回、D11a）を手元で出す")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"ポート（既定 {DEFAULT_PORT}）")
    parser.add_argument("--host", default="127.0.0.1", help="受ける所（127.0.0.1・localhost・::1 だけ）")
    parser.add_argument("--record-dir", type=Path, default=DEFAULT_RECORD_DIR, help="記録のフォルダ（既定 mock/記録）")
    parser.add_argument("--reset", action="store_true", help="始める前に記録のフォルダを空にする")
    args = parser.parse_args(argv)
    try:
        server = make_server(args.port, args.record_dir, args.reset, args.host)
    except (OSError, ValueError) as err:
        sys.stderr.write(f"模擬画面のサーバーを始められません：{err}\n")
        return 1
    print(f"模擬の申請画面： http://{args.host}:{args.port}/", flush=True)
    print(f"記録のフォルダ： {args.record_dir}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
