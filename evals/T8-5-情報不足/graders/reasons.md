---
type: regex
target:
  source: file
  path: 記録/質問の記録.json
pattern: '"理由": ""'
match: not_contains
---

T0-11：すべての質問に理由が添えられている。
