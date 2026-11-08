"""デモ動画を組み立てる（台詞の声 → 時刻表 → BGM → 映像 → 音を重ねた mp4）。

使い方（リポの根で）：
  uv run --with numpy python docs/video/build.py <デモの会社のフォルダ> <材料のフォルダ> [--provider vertex]

- デモの会社のフォルダは、申請書を書き終えた段階の会社のフォルダ（架空の株式会社みずなら精工）。
  その中の実物の出力（補助金の候補.docx・計画書・根拠対照表・財務モデル）と、審査役の結果・質問の記録を使う。
- 材料のフォルダ（リポの外）には、別の段階で作った実物を置く（README の「作り方」）：
  概要と流れ.docx、採択のお知らせの画像（saitaku_tsuuchi.png）、
  学習の場面の数を取る会社の記録（会社の記録_練習.json）、入力シート.xlsx、
  模擬の申請画面に保存された値の画面（nyuryoku_screen.png。あれば）。
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
MIN_DUR = {"road": 11.0, "title": 6.5, "s1": 15.6, "s2": 11.5, "s3": 11.0, "s4": 16.0, "shinsa": 8.5,
           "nyuryoku": 11.0, "s5": 11.0, "pm": 16.0, "learn": 8.5, "start": 6.5, "built": 7.0, "end": 6.0}
MAX_TOTAL = 179.5   # 提出の条件は3分以内。超えたら止める
VOICE_LEAD = {"road": 0.4, "title": 0.6, "built": 0.2}  # 台詞を場面の頭から何秒遅らせるか（ほかは 0.3 秒）
# 計画書は、文字と図表の多いページを何枚もめくって見せる（提出用の PDF の何ページ目から何ページ目か）
PLAN_PAGES = (3, 12)
CLIP_FPS = 15   # 録画から切り出した画面を、1秒に何コマの画像にするか
ZAIMU_MAX_PAGES = 10


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
    for key in [k for k in ("pm", "shorui", "learn", "how", "saitaku", "nyuryoku", "gaiyou", "calls") if k in material]:
        src = (HERE / material[key]["source"]).read_text(encoding="utf-8")
        if src.lstrip().startswith("{"):
            src = terminal_text(HERE / material[key]["source"])
        flat = re.sub(r"\s+", "", src.replace("**", ""))
        if key == "calls":
            # 呼び出しの行は「- 道具　中身」の1行がそのままあるか
            lines = {ln.strip() for ln in src.splitlines()}
            for scene, calls in material[key].items():
                for c in calls if isinstance(calls, list) else []:
                    if f"- {c[0]}　{c[1]}" not in lines:
                        sys.exit(f"呼び出しの行が記録にありません（{scene}）：{c}")
            continue
        if key == "gaiyou":
            # 表の行は、頭の列からそのまま続いているか（| 区切りで照らす）
            for row in material[key]["docs"] + material[key]["sched"] + [material[key]["sched_head"]]:
                cells = "|" + "|".join(re.sub(r"\s+", "", c.replace("**", "")) for c in row) + "|"
                if cells not in flat:
                    sys.exit(f"表の行が応答にありません（gaiyou）：{row}")
            continue
        if key == "pm":
            quotes = [c[2] for c in material[key]["callouts"]]
        elif key == "shorui":
            quotes = [q for f in material[key]["fubi"] for q in f[2:]] + [material[key]["summary"]]
        elif key == "learn":
            quotes = [s[2] for s in material[key]["second"]]
        elif key == "saitaku":
            quotes = [q[1] for q in material[key]["quotes"]]
        elif key == "nyuryoku":
            quotes = [material[key]["quote"][1]]
        else:
            quotes = [material[key]["quote"]]
        for q in quotes:
            if re.sub(r"\s+", "", q.replace("**", "")) not in flat:
                sys.exit(f"引用が対話の記録にありません（{key}）：{q}")


GAIYOU_HEAD = "申請から効果報告までの流れと期限"


def render_assets(company: Path, extra: Path, material: dict) -> dict:
    # 実物を画像にし、ページ数・シートの大きさなど、画面に添える数を返す
    pdf = ASSETS / "pdf"
    pdf.mkdir(parents=True, exist_ok=True)
    for old in ASSETS.glob("*.png"):
        old.unlink()
    case1 = company / "案件" / "2026_省力化（一般型）第9回"
    # 写す元と、画像にするページ（最初・最後。文字のときは、その文字があるページ。None は最後のページ）。
    # 概要と流れは、書体の置き換わりでページ割りが動くので、見出しの文字でページを探す
    # 補助金の候補は、STEP 1 の画面を撮ったセッションで作ったもの（材料のフォルダにあれば）を使う
    kouho = extra / "補助金の候補_探す.docx"
    sources = {
        "kouho.docx": (kouho if kouho.exists() else company / "補助金の候補.docx", 1, 2),
        "gaiyou.docx": (extra / "概要と流れ.docx", GAIYOU_HEAD, None),
        "sono3.xlsx": (case1 / "1_申請" / "申請書" / "その3.xlsx", 1, 1),
        "zaimu.xlsx": (company / "財務モデル.xlsx", 1, ZAIMU_MAX_PAGES),
    }
    for name, (src, _f, _l) in sources.items():
        shutil.copy(src, pdf / name)
    run(["soffice", "--headless", "--convert-to", "pdf", *[n for n in sources]], cwd=pdf, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # 計画書は、会社のフォルダにある提出用の PDF（製品が作ったもの）をそのまま使う
    shutil.copy(case1 / "1_申請" / "添付する書類" / "その1・2.pdf", pdf / "keikaku.pdf")
    sources["keikaku.pdf"] = (None, *PLAN_PAGES)
    info = {}
    for name, (_src, first, last) in sources.items():
        stem = name.split(".")[0]
        total = pdf_pages(pdf / f"{stem}.pdf")
        if isinstance(first, str):
            first, info["gaiyouY"] = find_page(pdf / f"{stem}.pdf", first)
            last = first
        last = min(last, total)
        info[f"{stem}Pages"] = total
        run(["pdftoppm", "-r", "110", "-png", "-f", str(first), "-l", str(last), f"{stem}.pdf", str(ASSETS / f"{stem}_p")], cwd=pdf)
        # pdftoppm はページの数で名前の桁を変えるので、元の文書の何ページ目かによらず 1 から番号を振り直す
        made = sorted(ASSETS.glob(f"{stem}_p-*.png"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))
        for i, p in enumerate(made, 1):
            p.rename(ASSETS / f"{stem}-{i}.png")
        info[f"{stem}Shown"] = len(made)
    info["planFirst"] = PLAN_PAGES[0]
    info["zaimuSheets"] = sheet_sizes(company / "財務モデル.xlsx")
    # 別の段階の画像（採択のお知らせ、模擬の申請画面に保存された値の画面）
    for n in ("saitaku_tsuuchi.png", "nyuryoku_screen.png"):
        if (extra / n).exists():
            shutil.copy(extra / n, ASSETS / n)
        else:
            print(f"注意：材料のフォルダに {n} がありません（その画面は空のまま撮ります）")
    info["nyuryokuScreen"] = (ASSETS / "nyuryoku_screen.png").exists()
    # 実際の画面（デスクトップアプリの録画から、会話の列だけを切り出してつないだもの）を、1コマずつの画像にする。
    # sagasu：STEP 1（選択肢で聞く・調べる・候補の一覧）、shirabe：STEP 2 の入口（公募要領を読んで、要件・義務をページつきの表に）
    info["clipFps"] = CLIP_FPS
    for name in ("sagasu", "shirabe", "nyuryoku"):
        info[f"{name}Frames"] = 0
        clip = extra / f"{name}_clip.mp4"
        if not clip.exists():
            continue
        frames = ASSETS / name
        shutil.rmtree(frames, ignore_errors=True)
        frames.mkdir(parents=True)
        run(["ffmpeg", "-v", "error", "-i", str(clip), "-vf", f"fps={CLIP_FPS}", "-q:v", "3", str(frames / "f_%04d.jpg")])
        info[f"{name}Frames"] = len(list(frames.glob("f_*.jpg")))
    # 入力シート（製品の yoshiki.py sheet が作ったもの）の値の行。画面を撮れなかったときは、これを見せる
    info["nyuryokuSheet"] = nyuryoku_sheet(extra / "入力シート.xlsx") if (extra / "入力シート.xlsx").exists() else []
    return info


def pdf_pages(pdf: Path) -> int:
    return int(re.search(r"Pages:\s+(\d+)", subprocess.check_output(["pdfinfo", str(pdf)], text=True)).group(1))


def sheet_sizes(xlsx: Path) -> list:
    # Excel のシートの名前と行の数（workbook.xml の順と、各シートの dimension から読む）
    import zipfile
    with zipfile.ZipFile(xlsx) as z:
        names = re.findall(r'<sheet [^>]*name="([^"]+)"', z.read("xl/workbook.xml").decode("utf-8"))
        out = []
        for i, n in enumerate(names, 1):
            m = re.search(r'<dimension ref="[A-Z]+\d+:[A-Z]+(\d+)"', z.read(f"xl/worksheets/sheet{i}.xml").decode("utf-8"))
            out.append([n, int(m.group(1)) if m else 0])
    return out


def sheet_rows(xlsx: Path) -> list:
    # Excel の最初のシートの値を、行ごとの文字の並びで読む（共有文字列・その場の文字・数）
    import zipfile
    import xml.etree.ElementTree as ET
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(xlsx) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
        rows = []
        for row in ET.fromstring(z.read("xl/worksheets/sheet1.xml")).iter(f"{{{ns['m']}}}row"):
            cells = {}
            for c in row.findall("m:c", ns):
                col = re.match(r"[A-Z]+", c.get("r")).group(0)
                v = c.find("m:v", ns)
                if c.get("t") == "s" and v is not None:
                    cells[col] = shared[int(v.text)]
                elif c.get("t") == "inlineStr":
                    cells[col] = "".join(t.text or "" for t in c.iter(f"{{{ns['m']}}}t"))
                elif v is not None:
                    cells[col] = v.text
            rows.append(cells)
    return rows


def nyuryoku_sheet(xlsx: Path, limit: int = 14) -> list:
    # 入力シートの「画面・欄・値」のうち、ツールが値を入れた行（頭から limit 行）
    rows = sheet_rows(xlsx)
    head = next(i for i, r in enumerate(rows) if r.get("C") == "欄")
    out = [[r.get("B", ""), r.get("C", ""), r.get("G", "")] for r in rows[head + 1:] if r.get("G")]
    return out[:limit]


def find_page(pdf: Path, text: str):
    # 空白を除いた文字で、そのページを探す。見出しのページの中の高さ（上からの割合）も返す
    for n in range(1, pdf_pages(pdf) + 1):
        body = subprocess.check_output(["pdftotext", "-f", str(n), "-l", str(n), str(pdf), "-"], text=True)
        if re.sub(r"\s+", "", text) in re.sub(r"\s+", "", body):
            box = subprocess.check_output(["pdftotext", "-f", str(n), "-l", str(n), "-bbox", str(pdf), "-"], text=True)
            h = float(re.search(r'<page width="[\d.]+" height="([\d.]+)"', box).group(1))
            m = re.search(r'<word xMin="[\d.]+" yMin="([\d.]+)"[^>]*>' + re.escape(text[:6]), box)
            return n, round(float(m.group(1)) / h, 4) if m else 0.0
    sys.exit(f"{pdf.name} に「{text}」のページがありません")


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


def write_data(timeline, captions, total, material, cdata, info) -> None:
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
        "nyuryoku": [material["nyuryoku"]["quote"][0], bold(material["nyuryoku"]["quote"][1])] if material.get("nyuryoku") else None,
        "zaimuSim": {k: material["zaimu_sim"][k] for k in ("change", "rows")},
        "saitaku": [[label, bold(q)] for label, q in material["saitaku"]["quotes"]],
        "shinsa": cdata["shinsa"],
        "gaiyou": {"docs": material["gaiyou"]["docs"], "schedHead": material["gaiyou"]["sched_head"],
                   "sched": [[bold(c) for c in r] for r in material["gaiyou"]["sched"]]},
        "calls": {k: v for k, v in material["calls"].items() if isinstance(v, list)},
        "assets": info,
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
    info = render_assets(company, extra, material)
    # --keep-voice：out/voice/ の声（作り直した声・録った人の声など）をそのまま使い、長さだけ測る
    # --provider gemini|vertex|say：声を作る先（既定は 台詞.json の voice.provider）
    if "--keep-voice" not in sys.argv:
        provider = sys.argv[sys.argv.index("--provider") + 1] if "--provider" in sys.argv else lines["voice"]["provider"]
        make_voices(provider)
    durs = {s["id"]: duration(VOICE / f"{s['id']}.wav") for s in lines["scenes"]}
    timeline, captions, total = make_timeline(lines, durs)
    write_data(timeline, captions, total, material, company_data(company, extra), info)
    print(f"全体 {total:.1f} 秒")
    for s in timeline:
        print(f"  {s['id']:6s} {s['start']:6.1f} 〜 {s['start'] + s['dur']:6.1f}")
    if total > MAX_TOTAL:
        sys.exit(f"3分を超えます（{total:.1f} 秒）。台詞か MIN_DUR を短くしてください")
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
