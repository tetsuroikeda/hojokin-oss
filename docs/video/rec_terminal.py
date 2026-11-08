"""本物の Claude Code（対話モード）を疑似端末で動かし、画面に出たバイト列と時刻を記録する。

使い方：
  python3 rec_terminal.py <会社のフォルダ> <プラグインのフォルダ> <出力.json> <社長の発言>
  python3 rec_terminal.py --clean <そのままの記録.json> <出力.json>   （隠す処理だけをやり直す）

- 記録は {"cols", "rows", "trust_at", "events": [[秒, base64のバイト列], ...]}。video.html が xterm.js で描き直す（画面録画の代わり。作者の画面を録らない）。
- 「このフォルダを信頼するか」を聞かれたら Enter を送る（会社のフォルダは架空のデモの会社）。
- 社長の発言を送った後、画面が10秒静かになったら終える（作業中は回る印が描き直し続けるので、静かになるのは答え終わったとき）。
- 「Do you want to proceed?」などの確認の画面が出たら、待たずにすぐ終える（記録に stopped_at_prompt を残し、終了コード 3）。
- 作者のアカウントの表示（契約の名前・使用量の注意・agents の数）は、同じ幅の空白に置き換えてから書く。
  置き換える前の記録は <出力>_そのまま.json に置く（リポの外に出力するときだけ使う。リポには入れない）。
"""

from __future__ import annotations

import base64
import fcntl
import json
import os
import pty
import re
import select
import signal
import struct
import sys
import termios
import time
import unicodedata

COLS, ROWS = 104, 30
LIMIT = 240   # 秒。これを過ぎたら打ち切る
QUIET = 10    # 秒。発言を送った後、これだけ画面が静かなら答え終わりとみなす

# 中身を調べられないコマンドは、会社のフォルダの守り（blockReadsOutsideWorkingDirectories）の下で確認の画面を出す。
# 撮影では答える人がいないので、先に断っておく（Claude は Read などほかの道具で読む）
DENY = ["Bash(python3 -c:*)", "Bash(python -c:*)", "Bash(node -e:*)", "Bash(perl -e:*)", "Bash(ruby -e:*)", "Bash(osascript:*)"]
# 作者の全体の設定（~/.claude/CLAUDE.md）の1行と同じ。撮影では全体の設定を読まないので、ここで渡す
LANG_PROMPT = "返事は必ず日本語で書く。"
PROMPT_MARKS = ("Do you want to proceed", "Do you want to make this edit", "Do you want to create", "Esc to cancel")

# 画面に出さない表示（見える文字の上で探す）
HIDE = [
    r"· Claude (?:Ultra|Max|Pro|Team|Enterprise)",
    r"(?:· )?←\s*(?:for|\d+)\s*agents?",
    r"\d+ agents?\b",
    r"[^\r\n]{0,40}weekly limit[^\r\n]*",
    r"You've used \d+%[^\r\n]*",
    r"resets [A-Z][a-z]{2} \d+ at[^\r\n]*",
    r"/usage-credits[^\r\n]*",
]
# 置き換えた後に残っていてはいけない文字（安全網）
MUST_NOT = ["Ultra", " agents", "weekly limit", "usage-credits", "/Users/", "@"]
ESC = re.compile(r"\x1b\[[0-9;?<>=]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Z0-9]|\x1b[=>78DEHMc]")


def _width(ch: str) -> int:
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def visible(text: str):
    """制御の印を除いた見える文字と、その元の位置（-1 は印から足した区切り）を返す"""
    vis, where = [], []
    i = 0
    for m in ESC.finditer(text):
        for j in range(i, m.start()):
            vis.append(text[j]); where.append(j)
        seq = m.group()
        if seq.endswith("C") and seq.startswith("\x1b["):
            n = int(seq[2:-1] or 1) if seq[2:-1].isdigit() else 1
            vis += [" "] * n; where += [-1] * n
        elif seq.endswith("G") and seq.startswith("\x1b["):
            # 同じ行の中で列へ飛ぶ印は、語の間の空白に使われる
            vis.append(" "); where.append(-1)
        elif seq[-1] in "ABDEFHfd" and seq.startswith("\x1b["):
            vis.append("\n"); where.append(-1)
        i = m.end()
    for j in range(i, len(text)):
        vis.append(text[j]); where.append(j)
    return "".join(vis), where


def clean_events(events: list) -> list:
    """アカウントの表示を、同じ幅の空白に置き換える（チャンクをまたいでも探せるよう、全体をつないで探す）"""
    chunks = [base64.b64decode(e[1]) for e in events]
    text = b"".join(chunks).decode("utf-8", "surrogateescape")
    # バイトの位置 → 文字の位置
    starts, pos = [], 0
    for ch in text:
        starts.append(pos)
        pos += len(ch.encode("utf-8", "surrogateescape"))
    byte_to_char = {}
    for ci, b in enumerate(starts):
        byte_to_char[b] = ci
    bounds, acc = [], 0
    for c in chunks:
        acc += len(c)
        # 文字の途中で切れていたら、次の文字の頭まで進める
        b = acc
        while b not in byte_to_char and b < pos:
            b += 1
        bounds.append(byte_to_char.get(b, len(text)))
    out = list(text)
    vis, where = visible(text)
    for pat in HIDE:
        for m in re.finditer(pat, vis):
            for k in range(m.start(), m.end()):
                j = where[k]
                if j >= 0 and out[j] not in ("\r", "\n"):
                    out[j] = " " * _width(text[j])
    new, prev = [], 0
    for e, b in zip(events, bounds):
        piece = "".join(out[prev:b]).encode("utf-8", "surrogateescape")
        new.append([e[0], base64.b64encode(piece).decode()])
        prev = b
    return new


def check_clean(events: list) -> list:
    text = b"".join(base64.b64decode(e[1]) for e in events).decode("utf-8", "ignore")
    vis = visible(text)[0]
    return [w for w in MUST_NOT if w in vis]


def write_clean(rec: dict, out: str) -> None:
    rec = dict(rec, events=clean_events(rec["events"]))
    left = check_clean(rec["events"])
    json.dump(rec, open(out, "w"))
    if left:
        print(f"注意：隠しきれていない表示があります：{left}")


def record(folder: str, plugin: str, out: str, prompt: str) -> int:
    settings = json.dumps({"permissions": {"blockReadsExemptPaths": [plugin], "deny": DENY}})
    # 作者の全体の設定（個人の hook など）は読まない（--setting-sources project。テストと同じ）
    cmd = ["claude", "--plugin-dir", plugin, "--settings", settings, "--setting-sources", "project",
           "--permission-mode", "acceptEdits", "--allowedTools", "Bash Read Glob Grep Skill",
           "--append-system-prompt", LANG_PROMPT]
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
    typed_at = 0.0
    last_out = time.time()
    stopped_at_prompt = False
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
            if not trusted and not typed_prompt and ("trust" in text.lower() or "信頼" in text):
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
                typed_at = time.time()
                seen = b""
            elif typed_prompt and any(m in text for m in PROMPT_MARKS):
                # 確認の画面で止まった。答える人がいないので、待たずに終える
                stopped_at_prompt = True
                break
        if typed_prompt and now - typed_at > 5 and now - last_out > QUIET:
            break
        if now - start > LIMIT:
            break
    os.kill(pid, signal.SIGTERM)
    took = round(time.time() - start, 1)
    # trust_at：信頼の確かめに答えた時刻。動画ではこの後から見せる
    rec = {"cols": COLS, "rows": ROWS, "trust_at": trust_at, "events": events}
    if stopped_at_prompt:
        rec["stopped_at_prompt"] = True
    raw = re.sub(r"\.json$", "", out) + "_そのまま.json"
    json.dump(rec, open(raw, "w"))
    write_clean(rec, out)
    print(f"記録 {len(events)} 件、{took} 秒" + ("（確認の画面で止まりました）" if stopped_at_prompt else ""))
    if not typed_prompt:
        print("社長の発言を送れませんでした")
        return 2
    return 3 if stopped_at_prompt else 0


def main() -> int:
    if sys.argv[1] == "--clean":
        write_clean(json.load(open(sys.argv[2])), sys.argv[3])
        return 0
    folder, plugin, out, prompt = sys.argv[1:5]
    return record(folder, plugin, out, prompt)


if __name__ == "__main__":
    sys.exit(main())
