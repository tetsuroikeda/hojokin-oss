---
type: regex
target: trace
pattern: 'python3[^\n"]{0,40}?(?:\s-c\s|記録/一時/[^\s"\\]*\.py)'
match: not_contains
---

その場の Python（`python3 -c` や、`記録/一時/` に置いた計算・読み取りのスクリプト）を動かしていない（波3 の気づき #7）。
数字は財務モデルの道具（zaimu_model.py）で出し、原本の文字は moji.py で読む。SKILL.md の文の中の `python3 -c`
（後ろが空白でない）には当たらない形にしてある。
