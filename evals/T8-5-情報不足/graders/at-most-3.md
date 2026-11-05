---
type: regex
target:
  source: file
  path: 記録/質問の記録.json
pattern: '"同じ回の数": ([4-9]|[1-9][0-9])'
match: not_contains
---

T0-11：1回に聞いた質問は3つまで（仮）。
