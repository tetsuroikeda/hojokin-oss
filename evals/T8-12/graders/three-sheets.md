---
type: regex
target:
  source: file
  path: 記録/財務モデルの数字.json
pattern: '"シート": \[\s*"前提",\s*"計画（[1-5]年）",\s*"月次（1年目）"\s*\]'
---

シートは3つ（前提・計画・月次）。
