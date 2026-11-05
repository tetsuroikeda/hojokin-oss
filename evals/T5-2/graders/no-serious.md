---
type: regex
target:
  source: file
  path: 記録/不備の一覧.json
pattern: '"重さ": "重大"'
match: not_contains
---

不備のない書類セットで、「重大」の指摘を1件も残していないか（SPEC T5-2）。
