"""本物の Claude Code（対話モード）を疑似端末で動かし、画面に出たバイト列と時刻を記録する。

使い方：python3 rec_terminal.py <会社のフォルダ> <プラグインのフォルダ> <出力.json> <社長の発言>

- 記録は {"cols", "rows", "events": [[秒, base64のバイト列], ...]}。video.html が xterm.js で描き直す（画面録画の代わり。作者の画面を録らない）。
- 「このフォルダを信頼するか」を聞かれたら Enter を送る（会社のフォルダは架空のデモの会社）。
- 応答が終わって画面が8秒静かになったら終える。
"""

from __future__ import annotations

import base64
import fcntl
import json
import os
import pty
import select
import signal
import struct
import sys
import termios
import time

COLS, ROWS = 104, 30


def main() -> None:
    folder, plugin, out, prompt = sys.argv[1:5]
    settings = json.dumps({"permissions": {"blockReadsExemptPaths": [plugin]}})
    # 作者の全体の設定（個人の hook など）は読まない（--setting-sources project。テストと同じ）
    cmd = ["claude", "--plugin-dir", plugin, "--settings", settings, "--setting-sources", "project",
           "--permission-mode", "acceptEdits", "--allowedTools", "Bash Read Glob Grep Skill"]
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(folder)
        # 今のセッションから引き継ぐ印（子のセッション扱い・メールなど）は外す
        for k in list(os.environ):
            if k in ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT") or k.startswith(("CLAUDE_CODE_CHILD", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION",
                     "CLAUDE_CODE_HOST_SESSION", "CLAUDE_CODE_MESSAGING", "CLAUDE_CODE_SIMPLE", "CLAUDE_CODE_DISABLE_TERMINAL_TITLE",
                     "CLAUDE_CODE_EMIT", "CLAUDE_CODE_TERMINAL_MCP", "CLAUDE_CODE_USER_EMAIL", "CLAUDE_CODE_STARTUP")):
                del os.environ[k]
        os.environ.update({"TERM": "xterm-256color", "COLUMNS": str(COLS), "LINES": str(ROWS), "FORCE_COLOR": "1"})
        os.execvp(cmd[0], cmd)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
    start = time.time()
    events = []
    seen = b""
    trusted = False
    trust_at = 0.0
    typed_prompt = False
    last_out = time.time()
    answered = False
    while True:
        r, _, _ = select.select([fd], [], [], 0.2)
        now = time.time()
        if r:
            try:
                data = os.read(fd, 65536)
            except OSError:
                break
            if not data:
                break
            events.append([round(now - start, 3), base64.b64encode(data).decode()])
            seen = (seen + data)[-20000:]
            last_out = now
            text = seen.decode("utf-8", "ignore")
            if not trusted and ("trust" in text.lower() or "信頼" in text):
                # 初めの選択は「No, exit」なので、下の「Yes, I trust this folder」へ動かしてから決める
                time.sleep(0.8)
                os.write(fd, b"\x1b[B")
                time.sleep(0.4)
                os.write(fd, b"\r")
                trusted = True
                trust_at = round(time.time() - start, 3)
            # 入力の欄が出て画面が落ち着いたら、社長の発言を1文字ずつ打って送る
            if not typed_prompt and "❯" in text and "accept" in text:
                time.sleep(1.5)
                for ch in prompt:
                    os.write(fd, ch.encode("utf-8"))
                    time.sleep(0.06)
                time.sleep(0.5)
                os.write(fd, b"\r")
                typed_prompt = True
                seen = b""
            if typed_prompt and ("様式4" in text or "締切" in text):
                answered = True
        if answered and now - last_out > 10:
            break
        if now - start > 420:
            break
    os.kill(pid, signal.SIGTERM)
    # trust_at：信頼の確かめに答えた時刻。動画ではこの後から見せる
    json.dump({"cols": COLS, "rows": ROWS, "trust_at": trust_at, "events": events}, open(out, "w"))
    print(f"記録 {len(events)} 件、{round(time.time() - start, 1)} 秒")


if __name__ == "__main__":
    main()
