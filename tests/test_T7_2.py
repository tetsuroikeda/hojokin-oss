"""T7-2 確かめられないとき（SPEC F7。TASKS B28）。

SPEC：通信を止めて開く。公式サイトの応答が決めた時間を超える状態でも開く。
合格ライン：どちらも「確かめられなかった」と伝え、他の処理は止まらない。

- 開いたときの公式サイトの確かめ（hooks/kaitei_hooks.py）を、資料の一覧（`記録/資料の本文/<案件>/資料の一覧.json`）の URL で動かす。
  - 通信できない：つながらない場所（手元の閉じたポート）と、名前を引けない場所（.invalid）。
  - 時間切れ：手元に、応答を遅らせる HTTP のサーバーを立てる。決めた時間（全部で TOTAL_SECONDS 秒）で切り上げ、待ち続けない。
- 開いたときの hook（hooks.json のコマンド。run.sh → main.py）を、会社のフォルダで動かす。確かめられなくても、
  期限と作業・共通の決まりなど、ほかの処理が渡す情報はそのまま出る（他の処理は止まらない）。
- 確かめ終えたとき：サイトの更新日が取った日より後なら「更新されたかもしれない」と知らせ、そうでなければ見つからなかったと知らせる。
  確かめ終えた結果は、その日のうちは控えを使う（問い合わせ直さない）。確かめられなかったときは控えない。
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import hook_runner as hr
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS = REPO_ROOT / "hooks"
CASE = "2026_省力化（一般型）第9回"
NOT_CHECKED = "確かめられませんでした"


def kaitei_hooks():
    if str(HOOKS) not in sys.path:
        sys.path.insert(0, str(HOOKS))
    import kaitei_hooks as k  # noqa: E402

    return k


class Handler(BaseHTTPRequestHandler):
    delay = 0.0
    modified = "Tue, 01 Sep 2026 00:00:00 GMT"

    def do_HEAD(self):  # noqa: N802
        time.sleep(self.delay)
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Last-Modified", self.modified)
        self.end_headers()

    def log_message(self, *args):  # 出力を出さない
        pass


@pytest.fixture
def server():
    started = []

    def start(delay: float = 0.0, modified: str = Handler.modified) -> str:
        handler = type("H", (Handler,), {"delay": delay, "modified": modified})
        srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        started.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}/application_guidelines.pdf"

    yield start
    for srv in started:
        srv.shutdown()
        srv.server_close()


def closed_port_url() -> str:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/application_guidelines.pdf"


def make_company(tmp_path: Path, urls, got="2026-11-05") -> Path:
    folder = tmp_path / "会社"
    (folder / ".hojokin").mkdir(parents=True)
    (folder / ".hojokin" / "設定.json").write_text(json.dumps({"今日の日付": "2026-11-05"}), encoding="utf-8")
    root = folder / "記録" / "資料の本文" / CASE
    root.mkdir(parents=True)
    docs = [{"id": f"要領{i}", "名前": "公募要領", "公募回": "第8回", "URL": u, "取得日": got, "ハッシュ": "0" * 64}
            for i, u in enumerate(urls)]
    listed = {"案件": CASE, "制度": {"名前": "テスト用 補助金"}, "資料": docs, "前の回の資料": [
        {"id": "前", "名前": "公募要領", "公募回": "第7回", "URL": "http://127.0.0.1:9/old.pdf", "取得日": got}]}
    (root / "資料の一覧.json").write_text(json.dumps(listed, ensure_ascii=False), encoding="utf-8")
    return folder


@pytest.fixture(autouse=True)
def enable(monkeypatch):
    monkeypatch.setenv("HOJOKIN_SITE_CHECK", "1")


def test_no_network_says_not_checked(tmp_path) -> None:
    """通信できない（閉じたポート、名前を引けない場所）：「確かめられなかった」と伝える。控えは残さない。"""
    k = kaitei_hooks()
    folder = make_company(tmp_path, [closed_port_url(), "http://hojokin-test.invalid/guide.pdf"])
    start = time.monotonic()
    text = k.check_text(folder)
    assert time.monotonic() - start < k.TOTAL_SECONDS + 1.5
    assert NOT_CHECKED in text and "通信できません" in text
    assert not (folder / k.CACHE_REL).exists()


def test_slow_site_is_cut_off_and_says_not_checked(tmp_path, server) -> None:
    """公式サイトの応答が決めた時間を超える：待ち続けずに切り上げ、「確かめられなかった」と伝える。"""
    k = kaitei_hooks()
    folder = make_company(tmp_path, [server(delay=6.0)])
    start = time.monotonic()
    text = k.check_text(folder, total=1.0)
    elapsed = time.monotonic() - start
    assert elapsed < 2.5, elapsed
    assert NOT_CHECKED in text and "時間内に応答がありませんでした" in text
    assert not (folder / k.CACHE_REL).exists()


def test_updated_document_is_told(tmp_path, server) -> None:
    k = kaitei_hooks()
    folder = make_company(tmp_path, [server(modified="Fri, 20 Nov 2026 01:00:00 GMT")])
    text = k.check_text(folder)
    assert "更新されたかもしれない資料があります" in text and "2026-11-20" in text
    assert NOT_CHECKED not in text


def test_unchanged_is_told_and_remembered_for_the_day(tmp_path, server) -> None:
    k = kaitei_hooks()
    url = server()
    folder = make_company(tmp_path, [url])
    text = k.check_text(folder)
    assert "見つかりませんでした" in text and "確かめました（1件）" in text
    assert (folder / k.CACHE_REL).is_file()
    calls = []
    assert k.check_text(folder, fetch=lambda u, t: calls.append(u) or ("変わっていない", None)) == text
    assert calls == []  # 同じ日は控えを使う


def test_previous_round_documents_are_not_checked(tmp_path) -> None:
    k = kaitei_hooks()
    folder = make_company(tmp_path, ["https://example.invalid/a.pdf"])
    assert [d["id"] for _c, d in k.documents(folder)] == ["要領0"]


def test_switch_off_does_nothing(tmp_path, monkeypatch) -> None:
    k = kaitei_hooks()
    monkeypatch.setenv("HOJOKIN_SITE_CHECK", "0")
    folder = make_company(tmp_path, [closed_port_url()])
    assert k.check_text(folder) is None


@pytest.mark.parametrize("kind", ["通信できない", "時間切れ"])
def test_session_start_hook_continues_other_work(tmp_path, server, kind) -> None:
    """開いたときの hook（hooks.json のコマンド）：確かめられなくても、ほかの処理が渡す情報（期限と作業・共通の決まり）は出る。"""
    url = closed_port_url() if kind == "通信できない" else server(delay=8.0)
    folder = make_company(tmp_path, [url])
    home = tmp_path / "home"
    data = tmp_path / "data"
    home.mkdir()
    data.mkdir()
    (command,) = hr.hook_commands("SessionStart")
    payload = {"session_id": "t7-2", "transcript_path": str(home / "t.jsonl"), "cwd": str(folder),
               "hook_event_name": "SessionStart", "source": "startup"}
    start = time.monotonic()
    r = hr.run(command, payload, plugin=REPO_ROOT, folder=folder, path="/usr/bin:/bin", home=home, data=data,
               extra_env={"HOJOKIN_SITE_CHECK": "1"}, timeout=60)
    elapsed = time.monotonic() - start
    assert r.returncode == 0, r
    out = json.loads(r.stdout.decode("utf-8"))
    context = out["hookSpecificOutput"]["additionalContext"]
    assert NOT_CHECKED in context
    assert "公式サイトの改訂の確かめ" in context
    assert "期限と作業" in context  # ほかの処理（M3 の期限と作業・共通の決まり）は止まらない
    assert elapsed < 25, elapsed
