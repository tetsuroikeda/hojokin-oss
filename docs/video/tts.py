"""台詞を声にする（Gemini の音声合成、または macOS の say）。

使い方：python3 tts.py <台詞.json> <出力フォルダ> [--only id,id] [--provider gemini|vertex|say]

- Gemini は本文だけを送る（演出の指示文やタグを付けると、それも読み上げることがあるため）。声の性格は声の名前で選ぶ。
- 鍵は環境変数 GEMINI_API_KEY か、HOJOKIN_TTS_ENV（既定 ~/Projects/movie-remotion/.env.local）から実行時に読む。リポには置かない。
- 返りは WAV のことも、生の PCM（audio/L16;rate=24000）のこともあるので、両方を受ける。
- 頭と終わりの無音を切り、-16 LUFS にそろえて <id>.wav に書く。
- 1秒あたりの文字の数が、ほかの場面から大きく外れたら（2回読み・途中で切れた兆し）、作り直す。
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path


def load_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    env = Path(os.environ.get("HOJOKIN_TTS_ENV", str(Path.home() / "Projects/movie-remotion/.env.local")))
    for line in env.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*GEMINI_API_KEY\s*=\s*(.*)\s*$", line)
        if m:
            return m.group(1).strip().strip("'\"")
    sys.exit("GEMINI_API_KEY が見つかりません")


def gemini(text: str, model: str, voice: str, key: str, raw: Path) -> Path:
    body = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(body).encode("utf-8"),
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as res:
        data = json.loads(res.read())
    parts = data["candidates"][0]["content"]["parts"]
    inline = next(p["inlineData"] for p in parts if "inlineData" in p)
    audio = base64.b64decode(inline["data"])
    mime = inline.get("mimeType", "")
    if audio[:4] == b"RIFF":
        raw.write_bytes(audio)
        return raw
    rate = re.search(r"rate=(\d+)", mime)
    pcm = raw.with_suffix(".pcm")
    pcm.write_bytes(audio)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", rate.group(1) if rate else "24000",
                    "-ac", "1", "-i", str(pcm), str(raw)], check=True)
    pcm.unlink()
    return raw


def vertex(text: str, model: str, voice: str, raw: Path) -> Path:
    # Vertex AI 経由。gcloud でログインしてあること（gcloud auth login）。プロジェクトは HOJOKIN_TTS_PROJECT で渡す
    project = os.environ["HOJOKIN_TTS_PROJECT"]
    token = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
    body = {
        "contents": [{"role": "user", "parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    req = urllib.request.Request(
        f"https://aiplatform.googleapis.com/v1/projects/{project}/locations/global/publishers/google/models/{model}:generateContent",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "x-goog-user-project": project, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as res:
        data = json.loads(res.read())
    inline = next(p["inlineData"] for p in data["candidates"][0]["content"]["parts"] if "inlineData" in p)
    audio = base64.b64decode(inline["data"])
    if audio[:4] == b"RIFF":
        raw.write_bytes(audio)
        return raw
    rate = re.search(r"rate=(\d+)", inline.get("mimeType", ""))
    pcm = raw.with_suffix(".pcm")
    pcm.write_bytes(audio)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", rate.group(1) if rate else "24000",
                    "-ac", "1", "-i", str(pcm), str(raw)], check=True)
    pcm.unlink()
    return raw


def say(text: str, voice: str, rate: int, raw: Path) -> Path:
    out = raw.with_suffix(".aiff")
    subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", str(out), text], check=True)
    return out


def finish(src: Path, dst: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af",
                    "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,"
                    "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse,"
                    "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-ac", "1", str(dst)], check=True)


def duration(path: Path) -> float:
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]))


def main() -> None:
    lines = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    args = sys.argv[3:]
    only = args[args.index("--only") + 1].split(",") if "--only" in args else None
    v = lines["voice"]
    provider = args[args.index("--provider") + 1] if "--provider" in args else v["provider"]
    key = load_key() if provider == "gemini" else ""
    speeds = {}
    for s in lines["scenes"]:
        if only and s["id"] not in only:
            continue
        speech = s.get("speech", s["text"])
        for attempt in range(3):
            raw = out / f".{s['id']}.raw.wav"
            if provider == "gemini":
                src = gemini(speech, v["model"], v["name"], key, raw)
            elif provider == "vertex":
                src = vertex(speech, v["model"], v["name"], raw)
            else:
                src = say(speech, v["say_voice"], v["say_rate"], raw)
            dst = out / f"{s['id']}.wav"
            finish(src, dst)
            src.unlink()
            sec = duration(dst)
            cps = len(re.sub(r"[、。・「」？\s]", "", speech)) / sec
            # 日本語の語りは 1秒に6〜10字ほど。外れたら読み違いの兆しとして作り直す
            if 5.0 <= cps <= 11.5 or provider == "say":
                break
            print(f"  {s['id']}: 1秒 {cps:.1f} 字で外れたので作り直す（{attempt + 1}回目）")
        speeds[s["id"]] = round(sec, 2)
        print(f"{s['id']:6s} {sec:5.1f} 秒  1秒 {cps:.1f} 字")
    print("合計", round(sum(speeds.values()), 1))


if __name__ == "__main__":
    main()
