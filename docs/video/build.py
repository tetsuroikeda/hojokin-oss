"""デモ動画を組み立てる（台詞の声 → 時刻表 → BGM → 映像 → 音を重ねた mp4）。

使い方（リポの根で）：
  uv run --with numpy python docs/video/build.py <デモの会社のフォルダ>

- デモの会社のフォルダは、保存した状態「1件目を終えた」を戻したもの（evals/_lib/fukugen.py）。
  その中の実物の出力（補助金の候補.docx・概要と流れ.docx・計画書・根拠対照表・財務モデル・今の状態.html）を画像にして使う。
- 実際の対話の文は docs/video/対話/ に置き、素材.json の引用がその中にそのままあるかを確かめる（作り話を入れないため）。
- 出来たものは docs/video/out/（Git の外）。最後の mp4 は out/hojokin_demo.mp4。
- 映像を撮るのは render.mjs（puppeteer-core で、この Mac の Google Chrome を動かす）。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = HERE / "out"
ASSETS = OUT / "assets"
VOICE = OUT / "voice"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# 場面ごとの、絵の動きに要る最短の長さ（秒）。台詞が短くても、絵が見終わるまで次へ行かない
MIN_DUR = {"wall": 5.6, "title": 12.5, "p1": 13.5, "p2": 16.5, "p3": 14.5, "pm": 14.0,
           "p4": 16.0, "p5": 14.0, "learn": 13.5, "safe": 8.5, "end": 6.0}
VOICE_LEAD = {"wall": 1.2, "title": 0.9}  # 台詞を場面の頭から何秒遅らせるか（ほかは 0.3 秒）


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def duration(path: Path) -> float:
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(out)


def make_voices(lines: dict) -> dict:
    VOICE.mkdir(parents=True, exist_ok=True)
    durs = {}
    for s in lines["scenes"]:
        f = VOICE / f"{s['id']}.aiff"
        run(["say", "-v", lines["voice"], "-r", str(lines["rate"]), "-o", str(f), s["text"]])
        durs[s["id"]] = duration(f)
    return durs


def split_caption(sentence: str, limit: int = 44) -> list:
    # 字幕が1行に収まるよう、長い文を「、」の所で切る
    if len(sentence) <= limit:
        return [sentence]
    pieces = [p + "、" for p in sentence.split("、")]
    pieces[-1] = pieces[-1][:-1]
    out, cur = [], ""
    for p in pieces:
        if cur and len(cur) + len(p) > limit:
            out.append(cur)
            cur = ""
        cur += p
    out.append(cur)
    return out


def make_timeline(lines: dict, durs: dict):
    t = 0.0
    timeline, captions = [], []
    for s in lines["scenes"]:
        sid = s["id"]
        lead = VOICE_LEAD.get(sid, 0.3)
        dur = max(MIN_DUR.get(sid, 6.0), lead + durs[sid] + s["pad"])
        timeline.append({"id": sid, "start": round(t, 3), "dur": round(dur, 3), "voiceAt": round(t + lead, 3), "voiceDur": round(durs[sid], 3)})
        # 字幕：文（。）ごとに、文字の数に比べて時間を割る
        parts = []
        for sentence in [p + "。" for p in s["text"].split("。") if p.strip()]:
            parts += split_caption(sentence)
        total_len = sum(len(p) for p in parts)
        ct = t + lead
        for p in parts:
            d = durs[sid] * len(p) / total_len
            captions.append({"start": round(ct, 3), "end": round(ct + d + 0.15, 3), "text": p})
            ct += d
        t += dur
    return timeline, captions, round(t, 3)


def check_quotes(material: dict) -> None:
    # 素材.json の引用が、実際の対話の記録にそのままあるかを確かめる
    for key in ("pm", "shorui", "learn"):
        src = (HERE / material[key]["source"]).read_text(encoding="utf-8")
        flat = re.sub(r"\s+", "", src.replace("**", ""))
        if key == "pm":
            quotes = material[key]["lines"]
        elif key == "shorui":
            quotes = [f[-1] for f in material[key]["fubi"]] + [material[key]["summary"]]
        else:
            quotes = [s[1] for s in material[key]["second"]]
        for q in quotes:
            if re.sub(r"\s+", "", q.replace("**", "")) not in flat:
                sys.exit(f"引用が対話の記録にありません（{key}）：{q}")


def render_assets(company: Path) -> None:
    pdf = ASSETS / "pdf"
    pdf.mkdir(parents=True, exist_ok=True)
    case1 = company / "案件" / "2026_省力化（一般型）第9回"
    sources = {
        "kouho.docx": company / "補助金の候補.docx",
        "gaiyou.docx": case1 / "概要と流れ.docx",
        "keikaku.docx": case1 / "1_申請" / "申請書" / "その1・2.docx",
        "konkyo.xlsx": case1 / "1_申請" / "申請書" / "根拠対照表.xlsx",
        "zaimu.xlsx": company / "財務モデル.xlsx",
    }
    for name, src in sources.items():
        shutil.copy(src, pdf / name)
    run(["soffice", "--headless", "--convert-to", "pdf", *[n for n in sources]], cwd=pdf, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for name in sources:
        stem = name.split(".")[0]
        run(["pdftoppm", "-r", "110", "-png", "-f", "1", "-l", "3", f"{stem}.pdf", str(ASSETS / stem)], cwd=pdf)
    # pdftoppm はページの数で名前の桁を変えるので、-1 と -01 をそろえる
    for p in ASSETS.glob("*-0?.png"):
        p.rename(p.with_name(p.name.replace("-0", "-")))
    run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1600,2400",
         f"--screenshot={ASSETS / 'status_html.png'}", (company / "今の状態.html").as_uri()], stderr=subprocess.DEVNULL)
    shutil.copy(ROOT / "testdata" / "計画書" / "材料" / "5_差し戻し" / "差し戻し_5_機械の名称と型番.png", ASSETS / "sashimodoshi.png")


def company_data(company: Path) -> dict:
    rec = json.loads((company / "記録" / "会社の記録.json").read_text(encoding="utf-8"))["項目"]
    qs = json.loads((company / "記録" / "質問の記録.json").read_text(encoding="utf-8"))["質問"]
    rules = [r["内容"] for r in rec if r["種類"] == "書き方の決まり"]
    return {
        "facts": sum(1 for r in rec if r["種類"] == "事実"),
        "ruleCount": len(rules),
        "questions": [q["問い"] for q in qs][:9],
    }


def write_data(timeline, captions, total, material, cdata) -> None:
    learn = dict(material["learn"])
    learn.update({"facts": cdata["facts"], "ruleCount": cdata["ruleCount"], "questions": cdata["questions"]})
    data = {
        "timeline": timeline, "captions": captions, "total": total,
        "facts": material["facts"],
        "pm": {"user": material["pm"]["user"], "lines": material["pm"]["lines"]},
        "shorui": {k: material["shorui"][k] for k in ("inputs", "tree", "fubi", "summary")},
        "learn": learn,
    }
    (OUT / "data.js").write_text("window.VIDEO_DATA = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")


def mix_audio(timeline, total) -> Path:
    # 台詞を時刻どおりに置き、BGM を台詞の下で沈める（sidechaincompress）
    inputs, filters, labels = [], [], []
    for i, s in enumerate(timeline):
        inputs += ["-i", str(VOICE / f"{s['id']}.aiff")]
        ms = int(s["voiceAt"] * 1000)
        filters.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo,adelay={ms}|{ms}[v{i}]")
        labels.append(f"[v{i}]")
    n = len(timeline)
    inputs += ["-i", str(OUT / "bgm.wav")]
    filters.append(f"{''.join(labels)}amix=inputs={n}:normalize=0,apad=whole_dur={total}[voice]")
    filters.append("[voice]asplit=2[vk][vm]")
    filters.append(f"[{n}:a]volume=0.32[bgm]")
    filters.append("[bgm][vk]sidechaincompress=threshold=0.02:ratio=8:attack=30:release=600[duck]")
    filters.append("[vm]volume=1.6[vv]")
    filters.append(f"[duck][vv]amix=inputs=2:normalize=0,atrim=0:{total},loudnorm=I=-16:TP=-1.5[out]")
    out = OUT / "audio.m4a"
    run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters), "-map", "[out]", "-c:a", "aac", "-b:a", "192k", str(out)])
    return out


def main() -> None:
    company = Path(sys.argv[1]).resolve()
    skip_render = "--no-video" in sys.argv
    lines = json.loads((HERE / "台詞.json").read_text(encoding="utf-8"))
    material = json.loads((HERE / "素材.json").read_text(encoding="utf-8"))
    check_quotes(material)
    OUT.mkdir(exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    render_assets(company)
    # --keep-voice：out/voice/ の声（録り直した人の声など）をそのまま使い、長さだけ測る
    if "--keep-voice" in sys.argv:
        durs = {s["id"]: duration(VOICE / f"{s['id']}.aiff") for s in lines["scenes"]}
    else:
        durs = make_voices(lines)
    timeline, captions, total = make_timeline(lines, durs)
    write_data(timeline, captions, total, material, company_data(company))
    print(f"全体 {total:.1f} 秒")
    for s in timeline:
        print(f"  {s['id']:6s} {s['start']:6.1f} 〜 {s['start'] + s['dur']:6.1f}")
    run([sys.executable, str(HERE / "make_bgm.py"), str(OUT / "bgm.wav"), str(total), str(timeline[1]["start"])])
    audio = mix_audio(timeline, total)
    if skip_render:
        return
    silent = OUT / "video_silent.mp4"
    # --keep-video：撮った映像があれば撮り直さず、音だけ重ね直す（台詞と絵の時刻を変えていないとき）
    if not ("--keep-video" in sys.argv and silent.exists()):
        run(["node", str(HERE / "render.mjs"), str(HERE / "video.html"), str(silent), str(total)])
    final = OUT / "hojokin_demo.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), "-i", str(audio), "-c:v", "copy", "-c:a", "copy", "-shortest", str(final)])
    print(f"できました：{final}")


if __name__ == "__main__":
    main()
