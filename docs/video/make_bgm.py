"""デモ動画の BGM を、コードだけで作る（音源のファイルを使わない）。

使い方：
  uv run --with numpy python docs/video/make_bgm.py <出力.wav> <全体の秒数> <壁の場面が終わる秒>

- 冒頭（壁の場面）は、短調の低い持続音と、時計のような刻みで「困っている」空気を作る。
- 壁が終わる所で、長調の進行（F – G – Em – Am）に切り替え、キック・スネア・ハイハット・ベース・アルペジオで前に進む感じを出す。
- 最後の8秒は、音を減らして終わりの和音で閉じる。
"""

from __future__ import annotations

import sys
import wave

import numpy as np

RATE = 44100
BPM = 104
BEAT = 60.0 / BPM
BAR = BEAT * 4


def note_freq(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def envelope(n: int, attack: float, release: float) -> np.ndarray:
    # 立ち上がりと減衰だけの簡単な包絡線
    t = np.arange(n) / RATE
    env = np.minimum(1.0, t / max(attack, 1e-4))
    env *= np.exp(-t / max(release, 1e-4))
    return env


def add(buf: np.ndarray, start: float, sig: np.ndarray, gain: float = 1.0) -> None:
    i = int(start * RATE)
    if i >= len(buf):
        return
    j = min(len(buf), i + len(sig))
    buf[i:j] += sig[: j - i] * gain


def pad(freqs, dur: float) -> np.ndarray:
    # やわらかい持続音（少しずらした鋸波を重ね、ゆっくり出入りさせる）
    n = int(dur * RATE)
    t = np.arange(n) / RATE
    sig = np.zeros(n)
    for f in freqs:
        for detune in (-0.12, 0.0, 0.12):
            ph = 2 * np.pi * f * (1 + detune / 100) * t
            sig += np.sin(ph) * 0.6 + np.sin(2 * ph) * 0.15
    fade = np.minimum(1.0, np.minimum(t / 0.6, (dur - t) / 0.6))
    return sig * np.clip(fade, 0, 1) / (len(freqs) * 3)


def pluck(f: float, dur: float) -> np.ndarray:
    n = int(dur * RATE)
    t = np.arange(n) / RATE
    sig = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(4 * np.pi * f * t) + 0.12 * np.sin(6 * np.pi * f * t)
    return sig * envelope(n, 0.004, 0.22)


def bass(f: float, dur: float) -> np.ndarray:
    n = int(dur * RATE)
    t = np.arange(n) / RATE
    sig = np.sin(2 * np.pi * f * t) + 0.3 * np.sign(np.sin(2 * np.pi * f * t)) * 0.3
    return sig * envelope(n, 0.01, 0.35)


def kick() -> np.ndarray:
    n = int(0.35 * RATE)
    t = np.arange(n) / RATE
    f = 45 + 110 * np.exp(-t * 28)
    ph = 2 * np.pi * np.cumsum(f) / RATE
    return np.sin(ph) * np.exp(-t * 9)


def snare(rng) -> np.ndarray:
    n = int(0.22 * RATE)
    t = np.arange(n) / RATE
    noise = rng.uniform(-1, 1, n)
    tone = np.sin(2 * np.pi * 190 * t)
    return (noise * 0.7 + tone * 0.3) * np.exp(-t * 18)


def hat(rng, open_: bool = False) -> np.ndarray:
    n = int((0.12 if open_ else 0.04) * RATE)
    t = np.arange(n) / RATE
    noise = rng.uniform(-1, 1, n)
    # 高い所だけ残す（差分で低い音を削る）
    noise = np.diff(noise, prepend=0)
    return noise * np.exp(-t * (20 if open_ else 70))


def tick() -> np.ndarray:
    n = int(0.03 * RATE)
    t = np.arange(n) / RATE
    return np.sin(2 * np.pi * 2400 * t) * np.exp(-t * 160)


def build(total: float, wall_end: float) -> np.ndarray:
    rng = np.random.default_rng(7)
    buf = np.zeros(int((total + 2) * RATE))

    # --- 壁の場面：短調の持続音と刻み ---
    add(buf, 0, pad([note_freq(m) for m in (45, 52, 57, 60)], wall_end + 0.4), 0.55)
    t = 0.0
    k = 0
    while t < wall_end - 0.05:
        add(buf, t, tick(), 0.25 if k % 2 == 0 else 0.15)
        # 壁が近づくにつれて刻みを速める
        step = BEAT / 2 if t < wall_end * 0.6 else BEAT / 4
        t += step
        k += 1
    # 壁が崩れる所の低い一撃
    add(buf, max(0.0, wall_end - 0.05), kick(), 0.9)

    # --- 本編：長調の進行 ---
    # F – G – Em – Am（各1小節）
    chords = [
        (53, [65, 69, 72, 76]),
        (55, [67, 71, 74, 77]),
        (52, [64, 67, 71, 74]),
        (57, [69, 72, 76, 79]),
    ]
    outro_start = total - 8.0
    start = wall_end
    bar = 0
    while start < outro_start:
        root, tones = chords[bar % 4]
        section = bar // 8  # 8小節ごとに少しずつ厚くする
        add(buf, start, pad([note_freq(m - 12) for m in tones], BAR + 0.3), 0.35)
        for b in range(4):
            bt = start + b * BEAT
            if bt >= outro_start:
                break
            add(buf, bt, kick(), 0.55 if b in (0, 2) else 0.0)
            if b in (1, 3):
                add(buf, bt, snare(rng), 0.22)
            add(buf, bt, hat(rng), 0.08)
            add(buf, bt + BEAT / 2, hat(rng, open_=(b == 3)), 0.06)
            add(buf, bt, bass(note_freq(root - 12), BEAT * 0.9), 0.32)
            if b == 2:
                add(buf, bt + BEAT / 2, bass(note_freq(root - 12 + 7), BEAT * 0.4), 0.2)
        # アルペジオ（16分。2小節目以降の区切りから入れる）
        if bar >= 2:
            pattern = [0, 1, 2, 3, 2, 1, 2, 3]
            for s in range(8):
                st = start + s * BEAT / 2
                if st >= outro_start:
                    break
                m = tones[pattern[s]] + (12 if section % 2 == 1 and s % 4 == 3 else 0)
                add(buf, st, pluck(note_freq(m), 0.4), 0.12)
        start += BAR
        bar += 1

    # --- 終わり：音を減らして和音で閉じる ---
    add(buf, outro_start, pad([note_freq(m) for m in (53, 60, 65, 69, 72)], 8.5), 0.5)
    for i, m in enumerate([65, 69, 72, 77, 81]):
        add(buf, outro_start + 0.4 + i * BEAT / 2, pluck(note_freq(m), 1.6), 0.14)

    # 簡単な残響（ずらして重ねる）
    out = buf.copy()
    for delay, g in ((0.071, 0.25), (0.113, 0.18), (0.173, 0.12), (0.241, 0.08)):
        d = int(delay * RATE)
        out[d:] += buf[:-d] * g

    out = out[: int(total * RATE)]
    # 全体のフェードと音量の正規化
    n = len(out)
    fade = np.ones(n)
    fi = int(0.3 * RATE)
    fo = int(2.5 * RATE)
    fade[:fi] = np.linspace(0, 1, fi)
    fade[-fo:] = np.linspace(1, 0, fo)
    out *= fade
    out /= np.max(np.abs(out)) + 1e-9
    return out * 0.85


def write_wav(path: str, sig: np.ndarray) -> None:
    data = (sig * 32767).astype(np.int16)
    stereo = np.column_stack([data, data]).ravel()
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(stereo.tobytes())


def main() -> None:
    out, total, wall_end = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    write_wav(out, build(total, wall_end))


if __name__ == "__main__":
    main()
