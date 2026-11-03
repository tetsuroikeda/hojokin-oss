"""実験 E1 の試しの申請画面を、手元のサーバーで出す（ブラウザの道具は、手元のファイルの画面では動かないため）。

使い方：python3 experiments/E1/serve.py [ポート]（既定は 8765）。localhost だけで受ける。
送られた欄の値・添付したファイルの名前・押したボタンを ~/.hojokin-e1/server.jsonl に書く。
「次へ」で画面2、「戻る」で画面1に移る。「提出する」「送信する」が押されたら、記録に submit と残す。
"""

import cgi
import json
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PAGE_DIR = Path(__file__).resolve().parent / "page"
LOG_DIR = Path.home() / ".hojokin-e1"
LOG_FILE = LOG_DIR / "server.jsonl"


def write_log(record: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


class Handler(BaseHTTPRequestHandler):
    def _send_page(self, name: str, note: str = "") -> None:
        body = (PAGE_DIR / name).read_text(encoding="utf-8")
        if note:
            body = body.replace("<h1>", f'<p class="banner">{note}</p><h1>', 1)
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send_page("index.html")
        elif self.path == "/page2.html":
            self._send_page("page2.html")
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers["Content-Type"]},
        )
        fields = {}
        files = {}
        for key in form.keys():
            item = form[key]
            if isinstance(item, list):
                item = item[0]
            if item.filename:
                files[key] = item.filename
            else:
                fields[key] = item.value
        button = fields.get("button", "")
        write_log({
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "page": fields.get("page"),
            "button": button,
            "fields": {k: v for k, v in fields.items() if k != "password"},
            "password_entered": bool(fields.get("password")),
            "files": files,
        })
        if button == "next":
            self._send_page("page2.html", "画面1を一時保存しました。")
        elif button == "back":
            self._send_page("index.html", "画面2から戻りました。")
        elif button == "submit":
            self._send_page("index.html", "【記録】提出のボタンが押されました（試しなので、何も送っていません）。")
        else:
            self._send_page("page2.html" if fields.get("page") == "2" else "index.html", "一時保存しました。")

    def log_message(self, fmt: str, *args) -> None:
        pass


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
