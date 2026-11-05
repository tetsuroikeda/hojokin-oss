---
type: regex
target:
  source: file
  path: 記録/会社の記録.json
pattern: '"種類": "(質問|社長の発言)"'
match: not_contains
---

社長に聞いていないのに、出典を「質問」「社長の発言」にした事実がないか（書類から取り込んだものは、出典を原本にする）。
