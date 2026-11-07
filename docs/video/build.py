"""デモ動画を組み立てる（台詞の声 → 時刻表 → BGM → 映像 → 音を重ねた mp4）。

使い方（リポの根で）：
  uv run --with numpy python docs/video/build.py <デモの会社のフォルダ> <材料のフォルダ> [--provider vertex]

- デモの会社のフォルダは、申請書を書き終えた段階の会社のフォルダ（架空の株式会社みずなら精工）。
  その中の実物の出力（補助金の候補.docx・計画書・根拠対照表・財務モデル）と、審査役の結果・質問の記録を使う。
- 材料のフォルダ（リポの外）には、別の段階で作った実物を置く（README の「作り方」）：
  概要と流れ.docx、指摘の前後の画像（fix_*.png）、採択のお知らせの画像（saitaku_tsuuchi.png）、
  学習の場面の数を取る会社の記録（会社の記録_練習.json）。
- 実際の対話の文は docs/video/対話/ に置き、素材.json の引用がその中にそのままあるかを確かめる（作り話を入れないため）。
- 出来たものは docs/video/out/（Git の外）。最後の mp4 は out/hojokin_demo.mp4。
- 映像を撮るのは render.mjs（puppeteer-core で、この Mac の Google Chrome を動かす）。
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
ASSETS = OUT / "assets"
VOICE = OUT / "voice"

# 場面ごとの、絵の動きに要る最短の長さ（秒）。台詞が短くても、絵が見終わるまで次へ行かない
MIN_DUR = {"road": 15.0, "title": 6.5, "s1": 11.5, "s2": 11.5, "s3": 12.5, "s4": 13.0, "fix": 13.0, "s5": 11.0,
           "pm": 18.0, "how": 11.0, "learn": 11.0, "start": 9.5, "built": 14.0, "end": 6.0}
VOICE_LEAD = {"road": 0.4, "title": 0.6}  # 台詞を場面の頭から何秒遅らせるか（ほかは 0.3 秒）


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def duration(path: Path) -> float:
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(out)


def make_voices(provider: str) -> None:
    # 声は tts.py が out/voice/<場面>.wav に作る（Gemini・Vertex・say）
    run([sys.executable, str(HERE / "tts.py"), str(HERE / "台詞.json"), str(VOICE), "--provider", provider])


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


def terminal_text(path: Path) -> str:
    # 端末の記録から、画面に出た文字だけを取り出す（色や位置の制御の印を除く）
    rec = json.loads(path.read_text(encoding="utf-8"))
    raw = b"".join(base64.b64decode(e[1]) for e in rec["events"]).decode("utf-8", "ignore")
    return re.sub(r"\x1b\[[0-9;?<>=]*[a-zA-Z~]|\x1b\][^\x07]*\x07|\x1b[()][A-Z0-9]|\x1b[=>]", "", raw)


def check_quotes(material: dict) -> None:
    # 素材.json の引用が、実際の対話の記録にそのままあるかを確かめる
    for key in ("pm", "shorui", "learn", "how", "saitaku"):
        src = (HERE / material[key]["source"]).read_text(encoding="utf-8")
        if src.lstrip().startswith("{"):
            src = terminal_text(HERE / material[key]["source"])
        flat = re.sub(r"\s+", "", src.replace("**", ""))
        if key == "pm":
            quotes = [c[2] for c in material[key]["callouts"]]
        elif key == "shorui":
            quotes = [q for f in material[key]["fubi"] for q in f[2:]] + [material[key]["summary"]]
        elif key == "learn":
            quotes = [s[2] for s in material[key]["second"]]
        elif key == "saitaku":
            quotes = [q[1] for q in material[key]["quotes"]]
        else:
            quotes = [material[key]["quote"]]
        for q in quotes:
            if re.sub(r"\s+", "", q.replace("**", "")) not in flat:
                sys.exit(f"引用が対話の記録にありません（{key}）：{q}")


def render_assets(company: Path, extra: Path, material: dict) -> None:
    pdf = ASSETS / "pdf"
    pdf.mkdir(parents=True, exist_ok=True)
    case1 = company / "案件" / "2026_省力化（一般型）第9回"
    # 写す元と、画像にするページ（最初・最後）
    sources = {
        "kouho.docx": (company / "補助金の候補.docx", 1, 2),
        "gaiyou.docx": (extra / "概要と流れ.docx", 5, 5),
        "keikaku.docx": (case1 / "1_申請" / "申請書" / "その1・2.docx", 1, 3),
        "konkyo.xlsx": (case1 / "1_申請" / "申請書" / "根拠対照表.xlsx", 1, 1),
        "zaimu.xlsx": (company / "財務モデル.xlsx", 1, 1),
    }
    for name, (src, _f, _l) in sources.items():
        shutil.copy(src, pdf / name)
    run(["soffice", "--headless", "--convert-to", "pdf", *[n for n in sources]], cwd=pdf, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for name, (_src, first, last) in sources.items():
        stem = name.split(".")[0]
        run(["pdftoppm", "-r", "110", "-png", "-f", str(first), "-l", str(last), f"{stem}.pdf", str(ASSETS / stem)], cwd=pdf)
    # pdftoppm はページの数で名前の桁を変えるので、-1 と -01 をそろえる
    for p in ASSETS.glob("*-0?.png"):
        p.rename(p.with_name(p.name.replace("-0", "-")))
    # 別の段階で作った画像（指摘の前後、採択のお知らせ）
    names = [n for pair in material["fix"]["pairs"] for n in pair[3:5]] + ["saitaku_tsuuchi.png"]
    for n in names:
        shutil.copy(extra / n, ASSETS / n)


def short_question(q: str, limit: int = 22) -> str:
    # 学習の場面の吹き出しは1行なので、問いの頭の1文だけを短く出す
    q = re.sub(r"^加点の確かめ（\d/\d）：", "", q.split("（理由：")[0])
    m = re.search(r"[？。]", q)
    q = q[: m.end()] if m else q
    return q if len(q) <= limit else q[: limit - 1] + "…"


def company_data(company: Path, extra: Path) -> dict:
    # 覚えた事実と書き方の決まりの数は、説明の練習で決まりを1つ覚えた後の会社の記録から取る（なければ会社のフォルダ）
    rec_path = extra / "会社の記録_練習.json"
    if not rec_path.exists():
        rec_path = company / "記録" / "会社の記録.json"
    rec = json.loads(rec_path.read_text(encoding="utf-8"))["項目"]
    qs = json.loads((company / "記録" / "質問の記録.json").read_text(encoding="utf-8"))["質問"]
    rules = [r["内容"] for r in rec if r["種類"] == "書き方の決まり"]
    # 選択肢の画面の代わりの断り書き（*( で始まるもの）は問いではないので除く
    questions = [short_question(q["問い"]) for q in qs if not q["問い"].startswith(("*(", "("))][:9]
    # 審査役：1回目の要修正の数と、初めて完成になった確かめが何回目か
    reviews = sorted((company / "記録" / "審査役の結果").glob("確かめ-*.json"))
    first_fix = sum(1 for s in json.loads(reviews[0].read_text(encoding="utf-8"))["結果"]["指摘"] if s.get("重さ") == "要修正")
    done = json.loads((company / "記録" / "完成の記録.json").read_text(encoding="utf-8"))["記録"][0]["確かめの番号"]
    done_round = [p.stem for p in reviews].index(done) + 1
    return {
        "facts": sum(1 for r in rec if r["種類"] == "事実"),
        "ruleCount": len(rules),
        "rules": rules,
        "questions": questions,
        "shinsa": {"firstFix": first_fix, "doneRound": done_round},
    }


def write_data(timeline, captions, total, material, cdata) -> None:
    learn = dict(material["learn"])
    learn.update({"facts": cdata["facts"], "ruleCount": cdata["ruleCount"], "rules": cdata["rules"], "questions": cdata["questions"]})
    # ** で囲んだ所は太字にする
    bold = lambda s: re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    data = {
        "timeline": timeline, "captions": captions, "total": total,
        "pm": {"callouts": [c[:2] for c in material["pm"]["callouts"]]},
        "term": json.loads((HERE / material["pm"]["source"]).read_text(encoding="utf-8")),
        "how": {"items": material["how"]["items"], "quote": material["how"]["quote"]},
        "built": material["built"],
        "shorui": {k: material["shorui"][k] for k in ("inputs", "tree", "fubi", "summary")},
        "learn": learn,
        "fix": material["fix"]["pairs"],
        "saitaku": [[label, bold(q)] for label, q in material["saitaku"]["quotes"]],
        "shinsa": cdata["shinsa"],
    }
    (OUT / "data.js").write_text("window.VIDEO_DATA = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")


def mix_audio(timeline, total) -> Path:
    # 台詞を時刻どおりに置き、BGM を台詞の下で沈める（sidechaincompress）
    inputs, filters, labels = [], [], []
    for i, s in enumerate(timeline):
        inputs += ["-i", str(VOICE / f"{s['id']}.wav")]
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
    extra = Path(sys.argv[2]).resolve()
    skip_render = "--no-video" in sys.argv
    lines = json.loads((HERE / "台詞.json").read_text(encoding="utf-8"))
    material = json.loads((HERE / "素材.json").read_text(encoding="utf-8"))
    check_quotes(material)
    OUT.mkdir(exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    render_assets(company, extra, material)
    # --keep-voice：out/voice/ の声（作り直した声・録った人の声など）をそのまま使い、長さだけ測る
    # --provider gemini|vertex|say：声を作る先（既定は 台詞.json の voice.provider）
    if "--keep-voice" not in sys.argv:
        provider = sys.argv[sys.argv.index("--provider") + 1] if "--provider" in sys.argv else lines["voice"]["provider"]
        make_voices(provider)
    durs = {s["id"]: duration(VOICE / f"{s['id']}.wav") for s in lines["scenes"]}
    timeline, captions, total = make_timeline(lines, durs)
    write_data(timeline, captions, total, material, company_data(company, extra))
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
