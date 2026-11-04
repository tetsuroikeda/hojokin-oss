"""持続化の模擬画面（D11c）を出す動き。server.py の Store と Handler を、持続化の画面の定義で使う。

    python3 mock/server.py --subsidy jizokuka [--port 8780] [--record-dir mock/記録_持続化] [--reset]
    python3 mock/server_jizokuka.py [--port 8780] [--reset]   （上と同じ）

流れ（申請システム操作手引き 第19回 公募申請・商工会議所地区）
- /login（p.5）→ /junshu 遵守事項（p.6）→ /mypage マイページ（p.7）→「公募・交付申請を開始する」
  → 保存した入力がなければ /shinsei/1 誓約事項、あれば /saikai 申請内容確認（再開。p.52）
- /shinsei/1〜/shinsei/13：申請の13画面（screen_jizokuka.SECTIONS）。画面の下に「戻る」「次へ」。
  「次へ」でその画面の入力を一時保存する（p.12）。画面7（賃金引上げ特例）は、特例か賃金引上げ加点を選んだときだけ通る。
- 文字数の上限を超えた欄があると、入力は保存するが、次の画面へは移さない（本物は上限まで）。
- 必須の欄が空でも、次の画面へ移す（本物は進めない。p.12）。空の欄は記録の missing_required に残す。
- 記録の形は省力化と同じ（操作記録.jsonl・入力値.json・添付/）。既定の置き場は mock/記録_持続化/。
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import calc_jizokuka  # noqa: E402
import screen_jizokuka as sj  # noqa: E402
import server  # noqa: E402
from server import esc, parse_multipart, render_button, render_field, show_value  # noqa: E402

DEFAULT_RECORD_DIR = Path(__file__).resolve().parent / "記録_持続化"

SCREEN_NOTICES = {
    "next": "前の画面で「次へ」を押しました。その画面の入力と添付を一時保存し、記録に残しました。",
    "next_error": "「次へ」を押しましたが、文字数の上限を超えた欄か、添付できないファイルがあったので、この画面のままです。"
                  "ほかの入力と添付は保存しました。",
    "back": "次の画面で「戻る」を押しました。その画面の入力は保存していません（押したことは記録に残しました）。",
    "back_first": "「戻る」を押しました。前の画面はないので、この画面のままです。保存はしていません。",
    "start": "誓約事項の画面で「申請を開始する」を押しました。誓約事項のチェックを保存し、記録に残しました。",
    "to_confirm": "宣誓・同意の画面で「最終確認画面へ」を押しました。宣誓・同意のチェックを保存し、記録に残しました。",
    "calc_expense": "「自動計算」を押しました。入力を保存し、(1)〜(7)と資金調達方法の合計を計算しました。",
    "calc_error": "「自動計算」を押しました。入力は保存しましたが、文字数の上限を超えた欄か、添付できないファイルがあります。",
    "gbiz_refresh": "「Gビズから最新情報を取得する」を押しました。模擬なので GビズID からは取り直さず、記録だけ残しました。"
                    "この画面の入力は保存していません。",
    "fix": "申請内容確認の「修正」で、この画面へ移りました。直したら「次へ」で保存します。",
    "resume": "「申請を再開する」で、入力の終わっていない画面へ移りました。",
    "unknown": "この画面にないボタンです。押したことを記録に残しましたが、保存はしていません。",
}

PAGE_NOTICES = {
    "agree_start": "遵守事項の画面で「上記に同意して利用を開始する」を押しました。記録に残しました。",
    "junshu_unknown": "この画面にないボタンです。押したことを記録に残しました。",
}

EXTRA_CSS = """
.sysbar{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:6px;background:#fff;border:1px solid #ccd;border-radius:6px;padding:6px 12px;margin:8px 0;font-size:.9rem}
.sysbar a{margin-left:14px}
h1.title{text-align:center}
.count,.filename{flex-basis:100%;padding-left:16.6rem;font-size:.8rem;color:#555}
.navbar{display:flex;justify-content:space-between;align-items:center;gap:12px;margin:16px 0}
.center{display:flex;justify-content:center;gap:12px;margin:16px 0}
details.howto{font-size:.85rem;margin:0 0 8px;text-align:center}
details.howto p{text-align:left}
section h2{margin-top:.6rem}
.status td:first-child{width:14rem}
"""

# 上限のある欄の「入力済」の字数を、打つたびに出し直す（記録には関わらない）
COUNT_JS = """
(function(){
  document.addEventListener('input', function(e){
    var t = e.target; if(!t.dataset || !t.dataset.limit) return;
    var c = document.getElementById('count_' + t.name);
    if(c){ c.textContent = '入力済：' + t.value.length + ' ／ 最大：' + Number(t.dataset.limit).toLocaleString(); }
  }, true);
})();
"""

HOWTO = ("<details class=\"howto\"><summary>操作時の注意事項および一時保存方法について</summary>"
         "<p>（模擬の説明です）各画面の「次へ」を押すと、その画面の入力が一時保存されます。一時保存した内容は、提出するまでは"
         "直せます。提出した後は直せません。入力の途中で止めたときは、マイページの「公募・交付申請を開始する」から"
         "「申請を再開する」で続けます。</p></details>")


class JizokukaStore(server.Store):
    """持続化の記録。省力化と同じ形で、次へで保存し、文字数の上限・添付の大きさも見る。"""

    saving_buttons = sj.SAVING_BUTTONS

    def __init__(self, record_dir: Path, reset: bool = False):
        super().__init__(record_dir, reset, start_url="/junshu", defs=sj)

    def load_extra(self, saved: dict) -> dict:
        return {"junshu_agreed": bool(saved.get("junshu_agreed", False))}

    def extra_state(self) -> dict:
        return {"junshu_agreed": bool(self.state.get("junshu_agreed", False))}

    def notice(self, button: str, screen_no: int, valid: bool, errors: list) -> str:
        if not valid:
            return SCREEN_NOTICES["unknown"]
        if button == "next" and errors:
            return SCREEN_NOTICES["next_error"]
        if button == "calc_expense" and errors:
            return SCREEN_NOTICES["calc_error"]
        if button == "back" and sj.target_screen(screen_no, "back", self.state["values"]) == screen_no:
            return SCREEN_NOTICES["back_first"]
        if button.startswith(sj.FIX_PREFIX):
            return SCREEN_NOTICES["fix"]
        return SCREEN_NOTICES.get(button, "")

    def extra_errors(self, button: str, screen_no, submitted: dict) -> list:
        if screen_no is None:
            return []
        return [f"{field['label']}：{n:,}字で、上限の{field['limit']:,}字を超えています"
                for field, n in sj.over_limit(sj.screen_fields(screen_no), submitted)]

    def extra_log(self, button: str, screen_no, submitted: dict, saving: bool) -> dict:
        if screen_no is None:
            return {}
        values = {**self.state["values"], **submitted}
        over = [{"field": field["id"], "length": n, "limit": field["limit"]}
                for field, n in sj.over_limit(sj.screen_fields(screen_no), submitted)]
        return {"missing_required": sj.missing_required(screen_no, values, self.state["files"]), "over_limit": over}

    def upload_problem(self, field: dict, filename: str, data: bytes) -> str:
        problem = super().upload_problem(field, filename, data)
        if not problem and len(data) > sj.MAX_FILE_BYTES:
            problem = "1つのファイルは10MBまでです（1つの欄に添付できるのは1つのファイルだけです）"
        return problem

    def log_page_button(self, page: str, button: str, fields: dict = None, **extra) -> None:
        """申請の13画面の外の画面（遵守事項・マイページ・再開）のボタンを記録する。"""
        entry = {"event": "button", "page": page, "button": button, "button_label": sj.button_label(button),
                 "saved": False, "fields": fields or {}, "submit_pressed": self.state["submit_pressed"]}
        entry.update(extra)
        self.log(entry)

    def set_junshu(self, agreed: bool) -> None:
        with self.lock:
            self.state["junshu_agreed"] = agreed
            self.write_state()


def page(title: str, body: str) -> bytes:
    return server.page(title, f"<style>{EXTRA_CSS}</style>{body}<script>{COUNT_JS}</script>")


def render_header(links: bool = True) -> str:
    nav = "<span><a href=\"/mypage\">マイページ</a><a href=\"/logout\">ログアウト</a></span>" if links else ""
    return f"<div class=\"sysbar\"><span>{esc(sj.SYSTEM_NAME)}（模擬）</span>{nav}</div>"


def render_notices(message: str = "", errors=()) -> str:
    out = f"<p class=\"notice\" role=\"status\">（模擬）{esc(message)}</p>" if message else ""
    for err in errors:
        out += f"<p class=\"error\" role=\"alert\">（模擬）{esc(err)}</p>"
    return out


def render_junshu(message: str = "") -> bytes:
    value, label, _page = sj.JUNSHU_BUTTON
    body = (render_header(links=False) + "<h1 class=\"title\">申請システム利用にあたっての遵守事項</h1>"
            + render_notices(message)
            + "<form method=\"post\" action=\"/junshu\" enctype=\"multipart/form-data\"><section>"
            + "<p class=\"note\">（模擬の遵守事項です。本物の文ではありません。）本物には、申請システムを使うときの決まり"
              "（通知を電子で受け取ること、してはいけない行為、申請の情報の扱いなど）が書かれています。"
              "担当者が最後まで読み、同意するときに自分でチェックを入れます。</p>"
            + render_field(sj.JUNSHU_FIELD, {}, {}, {})
            + f"<div class=\"center\">{render_button(value, label)}</div></section></form>")
    return page("遵守事項（持続化）", body)


def status_rows(state: dict) -> str:
    status = "提出済み" if state["submit_pressed"] else ("下書き" if state.get("saved_at") else "未作成")
    rows = [("申請ステータス", status), ("依頼先確認ステータス", "未依頼（模擬では変わりません）")]
    return "".join(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in rows)


def render_mypage(state: dict, message: str = "") -> bytes:
    value, label, _page = sj.MYPAGE_BUTTON
    body = (render_header() + "<h1 class=\"title\">マイページ（模擬）</h1>" + render_notices(message)
            + "<section><h2>お知らせ</h2><p class=\"note\">（模擬）お知らせはありません。</p></section>"
            + "<form method=\"post\" action=\"/mypage\" enctype=\"multipart/form-data\"><section><h2>公募交付申請</h2>"
            + f"<div class=\"center\">{render_button(value, label)}</div>"
            + f"<table class=\"status\">{status_rows(state)}</table></section></form>")
    return page("マイページ（持続化）", body)


def render_summary(state: dict, fix_buttons: bool = False) -> str:
    """保存した内容を、入力の画面（画面2〜11）ごとに出す。fix_buttons なら、画面ごとに「修正」を置く。"""
    parts = []
    for k in sj.FIX_SCREENS:
        s = sj.SECTIONS[k - 1]
        rows = []
        for field in sj.screen_fields(k):
            if field["kind"] == "file":
                attached = state["files"].get(field["id"])
                if attached:
                    rows.append((field["label"], attached["filename"]))
                continue
            value = state["values"].get(field["id"])
            if value not in ("", False, [], None):
                rows.append((field["label"], show_value(value)))
        body = "".join(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td></tr>" for a, b in rows) \
            or "<tr><td colspan=\"2\">（保存した入力はありません）</td></tr>"
        fix = render_button(f"{sj.FIX_PREFIX}{k}", sj.FIX_LABEL) if fix_buttons else ""
        parts.append(f"<h3>{esc(s['no'])} {esc(s['title'])} {fix}</h3><table class=\"summary\">{body}</table>")
    return "".join(parts)


def render_saikai(state: dict) -> bytes:
    buttons = "".join(render_button(v, label) for v, label, _page in sj.SAIKAI_BUTTONS)
    body = (render_header() + "<h1 class=\"title\">申請内容確認</h1>"
            + "<p class=\"note\">内容を直すときや、入力の途中の画面があるときは、いちばん下の「申請を再開する」を押します。</p>"
            + "<form method=\"post\" action=\"/saikai\" enctype=\"multipart/form-data\"><section>"
            + render_summary(state) + f"</section><div class=\"center\">{buttons}</div></form>")
    return page("申請内容確認（再開・持続化）", body)


def render_group(g: dict, buttons: dict, values: dict, files: dict, computed: dict) -> str:
    before = [b for b in buttons.get(g["title"], []) if b[0] in sj.BUTTONS_BEFORE_FIELDS]
    after = [b for b in buttons.get(g["title"], []) if b[0] not in sj.BUTTONS_BEFORE_FIELDS]
    inner = [f"<h2>{esc(g['title'])}</h2>"]
    if g["note"]:
        inner.append(f"<p class=\"note\">{esc(g['note'])}</p>")
    if before:
        inner.append("<div class=\"nav\">" + "".join(render_button(v, label) for v, label in before) + "</div>")
    inner.extend(render_field(field, values, files, computed) for field in g["fields"])
    if after:
        inner.append("<div class=\"nav\">" + "".join(render_button(v, label) for v, label in after) + "</div>")
    return "<section>" + "".join(inner) + "</section>"


def render_screen(state: dict, n: int, message: str = "", errors=()) -> bytes:
    """n 番目（1〜13）の画面。"""
    s = sj.SECTIONS[n - 1]
    values, files = state["values"], state["files"]
    computed = calc_jizokuka.compute(values)
    parts = [render_header(), f"<h1 class=\"title\">{esc(s['title'])}</h1>",
             f"<p class=\"sub\">{esc(s['no'])}（手引きの流れ {esc(s['step'])}、p.{esc(s['pages'])}）／{esc(sj.SCREENS_NAME)}</p>",
             HOWTO]
    if s.get("only_when") and not sj.wage_screen_applies(values):
        parts.append("<p class=\"note\">この画面は、賃金引上げ特例か賃金引上げ加点を希望したときだけ出ます。今の入力では当たらないので、"
                     "「次へ」「戻る」では飛ばします（模擬なので、URL を開けば出ます）。</p>")
    parts.append(render_notices(message, errors))
    if state.get("saved_at"):
        parts.append(f"<p class=\"note\">最後に保存した時刻：{esc(state['saved_at'])}</p>")
    parts.append(f"<form method=\"post\" action=\"{sj.screen_url(n)}\" enctype=\"multipart/form-data\">")
    buttons = {}
    for v, label, _page, where in s.get("buttons", []):
        buttons.setdefault(where, []).append((v, label))
    if n == sj.SCREEN_COUNT:
        parts.append("<section><p class=\"note\">一時保存した内容です。直すときは、画面ごとの「修正」でその画面へ移ります。"
                     "「提出」は担当者が押すボタンです（模擬なので、押してもどこにも送りません）。</p>"
                     + render_summary(state, fix_buttons=True) + "</section>")
    parts.extend(render_group(g, buttons, values, files, computed) for g in s["groups"])
    labels = {v: label for v, label, _page in sj.NAV_BUTTONS}
    center = "".join(render_button(v, label) for v, label in buttons.get("", []))
    if s["nav"] == sj.NAV:
        parts.append(f"<div class=\"navbar\">{render_button('back', labels['back'])}{center}"
                     f"{render_button('next', labels['next'])}</div>")
    else:
        nav = "".join(render_button(v, labels[v]) for v in s["nav"])
        parts.append(f"<div class=\"center\">{nav}{center}</div>")
    parts.append("</form>")
    return page(f"{s['title']}（持続化）", "".join(parts))


class JizokukaHandler(server.Handler):
    defs = sj

    def extra_field(self, name: str) -> dict:
        return {sj.JUNSHU_FIELD["id"]: sj.JUNSHU_FIELD}.get(name, {})

    def take_notice(self, token: str) -> dict:
        notice = self.sessions.get(token) or {}
        self.sessions[token] = None  # 知らせは1回だけ出す
        return notice

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/login"):
            super().do_GET()
            return
        if path == "/logout":
            self.logout()
            return
        token = self.session_token()
        if not token:
            self.redirect("/login")
            return
        n = self.screen_number(path)
        state = self.store.state
        if path == "/junshu":
            self.send(200, render_junshu(self.take_notice(token).get("message", "")))
        elif path == "/mypage":
            self.send(200, render_mypage(state, self.take_notice(token).get("message", "")))
        elif path == "/saikai":
            self.send(200, render_saikai(state))
        elif path == "/shinsei":
            self.redirect(sj.screen_url(1))
        elif n:
            notice = self.take_notice(token)
            self.send(200, render_screen(state, n, notice.get("message", ""), notice.get("errors", ())))
        else:
            self.send(404, page("見つかりません", "<p>この模擬画面にはないページです。</p>"))

    def logout(self) -> None:
        token = self.session_token()
        self.store.log({"event": "logout", "page": "logout"})
        self.sessions.pop(token, None)
        self.redirect("/login", {"Set-Cookie": f"{server.COOKIE}=; Max-Age=0; Path=/"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/login", "/log"):
            super().do_POST()
            return
        try:
            body = self.read_body()
        except ValueError as err:
            self.send(413, page("大きすぎます", f"<p>{esc(err)}</p>"))
            return
        token = self.session_token()
        if not token:
            self.redirect("/login")
            return
        n = self.screen_number(path)
        if n:
            self.post_screen(n, body)
            return
        form, _uploads = parse_multipart(self.headers.get("Content-Type", ""), body)
        button = (form.get("button") or [""])[0]
        state = self.store.state
        if path == "/junshu":
            agreed = bool(form.get(sj.JUNSHU_FIELD["id"]))
            self.store.log_page_button("junshu", button, {sj.JUNSHU_FIELD["id"]: agreed})
            if button == sj.JUNSHU_BUTTON[0]:
                self.store.set_junshu(agreed)
                self.sessions[token] = {"message": PAGE_NOTICES["agree_start"]}
                self.redirect("/mypage")
            else:
                self.sessions[token] = {"message": PAGE_NOTICES["junshu_unknown"]}
                self.redirect("/junshu")
        elif path == "/mypage":
            target = "/mypage"
            if button == sj.MYPAGE_BUTTON[0]:
                target = "/saikai" if state.get("saved_at") else sj.screen_url(1)
            self.store.log_page_button("mypage", button, target=target)
            self.redirect(target)
        elif path == "/saikai":
            target = "/saikai"
            if button == "resume":
                target = sj.screen_url(sj.resume_screen(state["values"], state["files"]))
                self.sessions[token] = {"message": SCREEN_NOTICES["resume"]}
            elif button == "back":
                target = "/mypage"
            self.store.log_page_button("saikai", button, target=target)
            self.redirect(target)
        else:
            self.send(404, page("見つかりません", "<p>この模擬画面にはないページです。</p>"))

    def post_screen(self, n: int, body: bytes) -> None:
        """申請の画面のボタン。記録してから、次に出す画面へ移す（知らせはその画面に出す）。"""
        token = self.session_token()
        form, uploads = parse_multipart(self.headers.get("Content-Type", ""), body)
        button = (form.get("button") or [""])[0]
        result = self.store.handle_button(button, form, uploads, screen_no=n)
        if button == "submit":
            self.send(200, server.render_submitted(self.store.state, sj.screen_url(sj.SCREEN_COUNT)))
            return
        # その画面にないボタンと、上限を超えた欄・添付できないファイルがあったときは、同じ画面のまま
        ok = result["valid"] and not result["errors"]
        target = sj.target_screen(n, button, self.store.state["values"]) if ok else n
        self.sessions[token] = {"message": result["message"], "errors": result["errors"]}
        self.redirect(sj.screen_url(target))


def make_server(port: int, record_dir: Path = None, reset: bool = False,
                host: str = "127.0.0.1") -> server.ThreadingHTTPServer:
    if host not in server.LOCAL_HOSTS:
        raise ValueError("模擬画面は、このパソコンの中（127.0.0.1）だけで出します")
    store = JizokukaStore(record_dir or DEFAULT_RECORD_DIR, reset)
    handler = type("JizokukaMockHandler", (JizokukaHandler,), {"store": store, "sessions": {}, "start_url": "/junshu"})
    return server.ThreadingHTTPServer((host, port), handler)


if __name__ == "__main__":
    sys.exit(server.main(["--subsidy", "jizokuka", *sys.argv[1:]]))
