"""デモ動画の BGM を、コードだけで作る（音源のファイルを使わない）。

使い方：
  uv run --with numpy python docs/video/make_bgm.py <出力.wav> <全体の秒数> <冒頭の場面が終わる秒>

- 冒頭（社長の道と5つの壁）：マリンバだけの疎らな旋律（Bm – G）。少し迷っている空気。
- 題名から：D – A – Bm – G の明るい進行。マリンバのアルペジオ、柔らかいピアノの和音、ウッドベース風の撥音、
  シェイカーと軽いキック・指を鳴らす音で、前に進む感じを出す。8小節ごとに少しずつ厚くする。
- 最後の8秒：音を減らして、D の和音で閉じる。
"""

from __future__ import annotations

import sys
import wave

import numpy as np

RATE = 44100
BPM = 96
BEAT = 60.0 / BPM
BAR = BEAT * 4


def hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def add(buf: np.ndarray, start: float, sig: np.ndarray, gain: float = 1.0) -> None:
    i = int(start * RATE)
    if i >= len(buf) or i < 0:
        return
    j = min(len(buf), i + len(sig))
    buf[i:j] += sig[: j - i] * gain


def marimba(f: float, dur: float = 0.9) -> np.ndarray:
    # 基音と、木の板らしい高い倍音（約4倍）を速く減衰させる
    n = int(dur * RATE)
    t = np.arange(n) / RATE
    sig = np.sin(2 * np.pi * f * t) * np.exp(-t * 5.5)
    sig += 0.35 * np.sin(2 * np.pi * f * 3.93 * t) * np.exp(-t * 22)
    sig += 0.12 * np.sin(2 * np.pi * f * 9.2 * t) * np.exp(-t * 40)
    sig *= np.minimum(1, t / 0.002)
    return sig


def piano(freqs, dur: float) -> np.ndarray:
    # 柔らかいピアノ風の和音（倍音を少し、ゆっくり減衰）
    n = int(dur * RATE)
    t = np.arange(n) / RATE
    sig = np.zeros(n)
    for f in freqs:
        for k, g in ((1, 1.0), (2, 0.35), (3, 0.12), (4, 0.05)):
            sig += g * np.sin(2 * np.pi * f * k * t) * np.exp(-t * (1.2 + k * 0.8))
    sig *= np.minimum(1, t / 0.01)
    fade = np.clip((dur - t) / 0.3, 0, 1)
    return sig * fade / len(freqs)


def upright(f: float, dur: float) -> np.ndarray:
    n = int(dur * RATE)
    t = np.arange(n) / RATE
    sig = np.sin(2 * np.pi * f * t) + 0.4 * np.sin(4 * np.pi * f * t) * np.exp(-t * 8)
    return sig * np.exp(-t * 3.0) * np.minimum(1, t / 0.008)


def kick() -> np.ndarray:
    n = int(0.3 * RATE)
    t = np.arange(n) / RATE
    f = 50 + 70 * np.exp(-t * 35)
    return np.sin(2 * np.pi * np.cumsum(f) / RATE) * np.exp(-t * 12)


def shaker(rng) -> np.ndarray:
    n = int(0.07 * RATE)
    t = np.arange(n) / RATE
    noise = np.diff(rng.uniform(-1, 1, n + 1))
    return noise * np.exp(-t * 55) * np.minimum(1, t / 0.01)


def snap(rng) -> np.ndarray:
    n = int(0.12 * RATE)
    t = np.arange(n) / RATE
    noise = np.diff(rng.uniform(-1, 1, n + 1))
    tone = np.sin(2 * np.pi * 1800 * t)
    return (noise * 0.8 + tone * 0.2) * np.exp(-t * 45)


def build(total: float, intro_end: float) -> np.ndarray:
    rng = np.random.default_rng(11)
    buf = np.zeros(int((total + 3) * RATE))

    # --- 冒頭：マリンバの疎らな旋律（Bm – G を行き来） ---
    motif = [(0, 71), (0.75, 74), (1.5, 78), (2.5, 76), (4, 67), (4.75, 71), (5.5, 74), (6.5, 73)]
    t0 = 0.3
    while t0 < intro_end - 1.0:
        for off, m in motif:
            st = t0 + off * BEAT
            if st < intro_end - 0.3:
                add(buf, st, marimba(hz(m), 1.2), 0.45)
        add(buf, t0, piano([hz(59), hz(62), hz(66)], BAR * 1.9), 0.25)
        add(buf, t0 + BAR * 2, piano([hz(55), hz(59), hz(62)], BAR * 1.9), 0.25)
        t0 += BAR * 4

    # --- 本編：D – A – Bm – G ---
    chords = [(50, [62, 66, 69, 74]), (45, [61, 64, 69, 73]), (47, [62, 66, 71, 74]), (43, [62, 67, 71, 74])]
    arp = [0, 2, 1, 3, 2, 1, 3, 2]
    outro = total - 8.0
    start = intro_end
    bar = 0
    while start < outro:
        root, tones = chords[bar % 4]
        level = min(3, bar // 8)  # 8小節ごとに厚く
        add(buf, start, piano([hz(m) for m in tones[:3]], BAR + 0.2), 0.32)
        for b in range(4):
            bt = start + b * BEAT
            if bt >= outro:
                break
            if b in (0, 2):
                add(buf, bt, kick(), 0.5)
            if b in (1, 3) and level >= 1:
                add(buf, bt, snap(rng), 0.16)
            for s in range(4):
                add(buf, bt + s * BEAT / 4, shaker(rng), 0.05 if s % 2 else 0.08)
            add(buf, bt, upright(hz(root - 12 if b != 2 else root - 5), BEAT * 0.95), 0.32)
        for s in range(8):
            st = start + s * BEAT / 2
            if st >= outro:
                break
            m = tones[arp[s]] + (12 if level >= 2 and s in (3, 7) else 0)
            add(buf, st, marimba(hz(m), 0.6), 0.2)
        start += BAR
        bar += 1

    # --- 終わり：D の和音で閉じる ---
    add(buf, outro, piano([hz(m) for m in (50, 57, 62, 66, 69)], 8.5), 0.5)
    for i, m in enumerate([62, 66, 69, 74, 78, 81]):
        add(buf, outro + 0.3 + i * BEAT / 2, marimba(hz(m), 2.0), 0.3)

    # 小さな部屋の響き
    out = buf.copy()
    for delay, g in ((0.053, 0.22), (0.089, 0.16), (0.137, 0.1), (0.211, 0.06)):
        d = int(delay * RATE)
        out[d:] += buf[:-d] * g
    out = out[: int(total * RATE)]
    n = len(out)
    fade = np.ones(n)
    fi, fo = int(0.4 * RATE), int(2.5 * RATE)
    fade[:fi] = np.linspace(0, 1, fi)
    fade[-fo:] = np.linspace(1, 0, fo)
    out *= fade
    out /= np.max(np.abs(out)) + 1e-9
    return out * 0.85


def write_wav(path: str, sig: np.ndarray) -> None:
    data = (sig * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(np.column_stack([data, data]).ravel().tobytes())


def main() -> None:
    out, total, intro_end = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    write_wav(out, build(total, intro_end))


if __name__ == "__main__":
    main()
